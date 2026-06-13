import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice } from "@/lib/device";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Periodic device status push (mode, wifi, battery, online…). High-level only —
 * the camera feed never goes through the cloud. Auth via device headers.
 * Body: { status: {...} }
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

  const admin = createAdminClient();
  const { data, error } = await admin
    .from("devices")
    .update({ status, last_seen: new Date().toISOString() })
    .eq("id", auth.deviceId)
    .select("owner_user_id")
    .maybeSingle();
  if (error) return NextResponse.json({ error: "heartbeat failed" }, { status: 500 });

  return NextResponse.json({ ok: true, paired: !!data?.owner_user_id });
}
