import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { networkHash } from "@/lib/net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** How long the phone waits for a button press before the session goes stale. */
const TTL_MS = 3 * 60 * 1000;

/**
 * The browser half of button pairing.
 *
 *   POST → open a session and start waiting  → { session_id, expires_at }
 *   GET ?id=… → has the device confirmed yet? → { status, device? }
 *
 * The device half is /api/pair/confirm: the person presses the ACTION button on
 * the hardware they are holding, which is a far stronger claim to it than "we
 * share a public IP" — and unlike the spoken code it needs no typing, no reading
 * and no sighted help, which is the whole point for the people I-Sora is for.
 */
export async function POST(req: Request) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const expiresAt = new Date(Date.now() + TTL_MS).toISOString();
  const admin = createAdminClient();

  // One live session per user: reopening the screen must not leave an older
  // session waiting, or a single press could land on the wrong one.
  await admin
    .from("pairing_sessions")
    .delete()
    .eq("user_id", user.id)
    .is("device_id", null);

  const { data, error } = await admin
    .from("pairing_sessions")
    .insert({
      user_id: user.id,
      // May be "" when we cannot work out the caller's network; confirm then
      // falls back to "the only session waiting anywhere", see that route.
      net_hash: networkHash(req) || null,
      expires_at: expiresAt,
    })
    .select("id, expires_at")
    .maybeSingle();

  if (error || !data) {
    return NextResponse.json({ error: "gagal memulai sesi" }, { status: 500 });
  }
  return NextResponse.json({ session_id: data.id, expires_at: data.expires_at });
}

export async function GET(req: Request) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const id = new URL(req.url).searchParams.get("id") || "";
  if (!id) return NextResponse.json({ error: "id required" }, { status: 400 });

  const admin = createAdminClient();
  const { data: row } = await admin
    .from("pairing_sessions")
    .select("id, device_id, expires_at")
    // Scoped to the caller, so one user can never poll another's session.
    .eq("id", id)
    .eq("user_id", user.id)
    .maybeSingle();

  if (!row) return NextResponse.json({ status: "gone" });
  if (!row.device_id) {
    if (new Date(row.expires_at).getTime() < Date.now()) {
      return NextResponse.json({ status: "expired" });
    }
    return NextResponse.json({ status: "waiting" });
  }

  const { data: device } = await admin
    .from("devices")
    .select("id, name, pubkey, fw_version")
    .eq("id", row.device_id)
    .maybeSingle();

  return NextResponse.json({ status: "paired", device });
}
