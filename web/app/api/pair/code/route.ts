import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice, generatePairingCode } from "@/lib/device";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TTL_MS = 10 * 60 * 1000; // 10 minutes
const MAX_PER_MINUTE = 5;

/** Device requests a fresh pairing code to speak aloud. Auth via device headers. */
export async function POST(req: Request) {
  const auth = await authDevice(req);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  const admin = createAdminClient();

  // Simple rate-limit: cap codes minted per device per minute.
  const since = new Date(Date.now() - 60_000).toISOString();
  const { count } = await admin
    .from("pairing_codes")
    .select("code", { count: "exact", head: true })
    .eq("device_id", auth.deviceId)
    .gte("created_at", since);
  if ((count ?? 0) >= MAX_PER_MINUTE) {
    return NextResponse.json({ error: "rate limited" }, { status: 429 });
  }

  // Invalidate previous unused codes so only the latest spoken one works.
  await admin.from("pairing_codes").update({ used: true }).eq("device_id", auth.deviceId).eq("used", false);

  // Generate a unique code (retry on the rare collision).
  let code = "";
  const expiresAt = new Date(Date.now() + TTL_MS).toISOString();
  for (let attempt = 0; attempt < 5; attempt++) {
    code = generatePairingCode(6);
    const { error } = await admin
      .from("pairing_codes")
      .insert({ code, device_id: auth.deviceId, expires_at: expiresAt });
    if (!error) {
      return NextResponse.json({ code, expires_at: expiresAt });
    }
  }
  return NextResponse.json({ error: "could not allocate code" }, { status: 500 });
}
