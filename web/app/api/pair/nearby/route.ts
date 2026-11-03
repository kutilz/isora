import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { networkHash } from "@/lib/net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** A device must have phoned home this recently to count as "here right now". */
const FRESH_MS = 3 * 60 * 1000;

/**
 * Zero-typing pairing for the common case: the phone and the device are on the
 * same WiFi, so they reach the relay from the same public IP (see lib/net.ts).
 *
 *   GET  → unclaimed devices currently visible on the caller's network
 *   POST → claim one of them  (body: { device_id })
 *
 * Safety: only devices that nobody owns yet are ever listed, and the claim
 * re-checks the network at the moment of the write. Because carrier-grade NAT
 * can share one public IPv4 between households, GET reports `ambiguous: true`
 * when more than one candidate is visible — the app then refuses the one-tap
 * path and sends the user to the QR or the spoken code, which prove possession.
 */
async function candidates(req: Request) {
  const net = networkHash(req);
  if (!net) return { net: "", rows: [] as { id: string; name: string | null; last_seen: string | null }[] };

  try {
    const admin = createAdminClient();
    const { data } = await admin
      .from("devices")
      .select("id, name, fw_version, last_seen")
      .is("owner_user_id", null)
      .eq("net_hash", net)
      .gte("last_seen", new Date(Date.now() - FRESH_MS).toISOString())
      .order("last_seen", { ascending: false })
      .limit(5);
    return { net, rows: data ?? [] };
  } catch {
    // Relay not fully configured (or the column is missing because schema.sql
    // hasn't been re-run). Report "cannot tell" so the app offers QR/code
    // instead of spinning on a search that will never resolve.
    return { net: "", rows: [] };
  }
}

export async function GET(req: Request) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const { net, rows } = await candidates(req);
  return NextResponse.json({
    // "" means we could not work out the caller's network at all — the app
    // should then present QR/code without claiming the LAN path is broken.
    supported: !!net,
    devices: rows,
    ambiguous: rows.length > 1,
  });
}

export async function POST(req: Request) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  const deviceId = String(body.device_id || "").trim();
  if (!deviceId) return NextResponse.json({ error: "device_id required" }, { status: 400 });

  const { net, rows } = await candidates(req);
  if (!net) {
    return NextResponse.json(
      { error: "jaringanmu tidak bisa dikenali — pakai QR atau kode suara" },
      { status: 400 }
    );
  }
  if (rows.length > 1) {
    return NextResponse.json(
      { error: "ada lebih dari satu perangkat baru di jaringan ini — pakai QR atau kode suara" },
      { status: 409 }
    );
  }
  if (!rows.some((d) => d.id === deviceId)) {
    return NextResponse.json(
      { error: "perangkat tidak terlihat di jaringan ini lagi" },
      { status: 404 }
    );
  }

  // Re-assert both conditions in the write itself, so a device claimed a moment
  // ago by someone else can't be taken over by a stale list.
  const admin = createAdminClient();
  const { data, error } = await admin
    .from("devices")
    .update({ owner_user_id: user.id })
    .eq("id", deviceId)
    .is("owner_user_id", null)
    .eq("net_hash", net)
    .select("id, name, pubkey, fw_version")
    .maybeSingle();
  if (error) return NextResponse.json({ error: "gagal menautkan perangkat" }, { status: 500 });
  if (!data) return NextResponse.json({ error: "perangkat sudah dihubungkan di ponsel lain" }, { status: 409 });

  return NextResponse.json({ ok: true, device: data });
}
