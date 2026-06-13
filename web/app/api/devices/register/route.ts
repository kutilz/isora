import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { hashSecret, safeEqualHex } from "@/lib/device";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Device bootstrap. The device proves ownership of its random id by knowing the
 * secret it generated on first boot. First call creates the row (stores the
 * secret HASH); later calls must present the same secret and may refresh pubkey/fw.
 *
 * Body: { device_id, secret, pubkey?, fw_version?, name? }
 */
export async function POST(req: Request) {
  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  const deviceId = String(body.device_id || "").trim();
  const secret = String(body.secret || "").trim();
  if (!deviceId || !secret) {
    return NextResponse.json({ error: "device_id and secret required" }, { status: 400 });
  }

  const admin = createAdminClient();
  const { data: existing } = await admin
    .from("devices")
    .select("id, secret_hash, owner_user_id")
    .eq("id", deviceId)
    .maybeSingle();

  const secretHash = hashSecret(secret);
  const patch: Record<string, unknown> = {};
  if (body.pubkey) patch.pubkey = String(body.pubkey);
  if (body.fw_version) patch.fw_version = String(body.fw_version);
  if (body.name) patch.name = String(body.name);

  if (existing) {
    if (!safeEqualHex(secretHash, existing.secret_hash)) {
      return NextResponse.json({ error: "device id already registered" }, { status: 409 });
    }
    if (Object.keys(patch).length) {
      await admin.from("devices").update(patch).eq("id", deviceId);
    }
    return NextResponse.json({ ok: true, paired: !!existing.owner_user_id });
  }

  const { error } = await admin.from("devices").insert({
    id: deviceId,
    secret_hash: secretHash,
    ...patch,
  });
  if (error) {
    return NextResponse.json({ error: "register failed" }, { status: 500 });
  }
  return NextResponse.json({ ok: true, paired: false });
}
