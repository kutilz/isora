import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice } from "@/lib/device";
import { networkHash } from "@/lib/net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Periodic device status push (mode, wifi, battery, online…). High-level only —
 * the camera feed never goes through the cloud. Auth via device headers.
 * Body: { status: {...} }
 *
 * Also records a keyed hash of the network the device phones home from, so the
 * app can tell whether the user's phone is on the same WiFi (see lib/net.ts).
 * The raw IP is never stored.
 */
export async function POST(req: Request) {
  const auth = await authDevice(req);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any = {};
  try {
    body = await req.json();
  } catch {
    /* tolerate empty body — still updates last_seen */
  }
  const status = body && typeof body.status === "object" && body.status ? body.status : {};

  const patch: Record<string, unknown> = {
    status,
    last_seen: new Date().toISOString(),
  };
  const net = networkHash(req);
  if (net) patch.net_hash = net;

  const admin = createAdminClient();
  const { data, error } = await admin
    .from("devices")
    .update(patch)
    .eq("id", auth.deviceId)
    .select("owner_user_id")
    .maybeSingle();
  if (error) return NextResponse.json({ error: "heartbeat failed" }, { status: 500 });

  return NextResponse.json({ ok: true, paired: !!data?.owner_user_id });
}
