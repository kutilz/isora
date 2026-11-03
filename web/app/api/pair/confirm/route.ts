import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice } from "@/lib/device";
import { networkHash } from "@/lib/net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * The device half of button pairing: "the person holding me just pressed the
 * button — link me to whoever is waiting."
 *
 * Which waiting session the press belongs to is decided in two tiers:
 *
 *   1. Sessions opened from the device's own network (same `net_hash`). This is
 *      the normal case and it is unambiguous even while other households are
 *      pairing at the same moment.
 *   2. If none match — the phone is on mobile data, or we cannot hash either
 *      side's network — any session waiting anywhere, but ONLY if exactly one
 *      is. Two strangers pressing within the same three-minute window is rare,
 *      and refusing is the safe answer when it happens.
 *
 * Returns a machine-readable `reason` so the device can speak the right line.
 * Never 4xx for the ordinary "nobody is waiting" case: that is an answer, not a
 * failure, and the device should say so rather than retry.
 */
export async function POST(req: Request) {
  const auth = await authDevice(req);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  const admin = createAdminClient();

  const { data: device } = await admin
    .from("devices")
    .select("id, owner_user_id")
    .eq("id", auth.deviceId)
    .maybeSingle();
  if (!device) return NextResponse.json({ error: "unknown device" }, { status: 404 });
  if (device.owner_user_id) {
    return NextResponse.json({ ok: false, reason: "already_paired" });
  }

  const nowIso = new Date().toISOString();
  const { data: waiting } = await admin
    .from("pairing_sessions")
    .select("id, user_id, net_hash")
    .is("device_id", null)
    .gt("expires_at", nowIso)
    .order("created_at", { ascending: false })
    .limit(20);

  const all = waiting ?? [];
  if (all.length === 0) return NextResponse.json({ ok: false, reason: "no_session" });

  // The device's *current* network, taken from this very request — not from the
  // stored heartbeat, which may be minutes old and from a different WiFi.
  const net = networkHash(req);
  const sameNet = net ? all.filter((s) => s.net_hash === net) : [];
  const pool = sameNet.length > 0 ? sameNet : all;

  if (pool.length > 1) return NextResponse.json({ ok: false, reason: "ambiguous" });
  const session = pool[0];

  // Claim the device first, re-asserting "still unowned" in the write itself so
  // two presses racing cannot both succeed.
  const { data: claimed } = await admin
    .from("devices")
    .update({ owner_user_id: session.user_id })
    .eq("id", auth.deviceId)
    .is("owner_user_id", null)
    .select("id")
    .maybeSingle();
  if (!claimed) return NextResponse.json({ ok: false, reason: "already_paired" });

  // Then close the session — likewise only if it is still open, so a session
  // that just took a different device is not overwritten.
  const { data: closed } = await admin
    .from("pairing_sessions")
    .update({ device_id: auth.deviceId })
    .eq("id", session.id)
    .is("device_id", null)
    .select("id")
    .maybeSingle();
  if (!closed) {
    // Lost the race: give the device back rather than leaving it owned by
    // someone whose screen never confirmed it.
    await admin
      .from("devices")
      .update({ owner_user_id: null })
      .eq("id", auth.deviceId)
      .eq("owner_user_id", session.user_id);
    return NextResponse.json({ ok: false, reason: "no_session" });
  }

  return NextResponse.json({ ok: true, paired: true });
}
