import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice } from "@/lib/device";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Device confirms it applied a command. We DELETE the row so any E2E ciphertext
 * (e.g. API keys) does not linger in the relay. Auth via device headers.
 * Body: { command_id }
 */
export async function POST(req: Request) {
  const auth = await authDevice(req);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  const commandId = String(body.command_id || "").trim();
  if (!commandId) return NextResponse.json({ error: "command_id required" }, { status: 400 });

  const admin = createAdminClient();
  const { error } = await admin
    .from("commands")
    .delete()
    .eq("id", commandId)
    .eq("device_id", auth.deviceId);
  if (error) return NextResponse.json({ error: "ack failed" }, { status: 500 });

  return NextResponse.json({ ok: true });
}
