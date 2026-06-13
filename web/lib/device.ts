import crypto from "node:crypto";
import { createAdminClient } from "@/lib/supabase/admin";

/** sha256 hex of the device secret — only the hash is ever stored server-side. */
export function hashSecret(secret: string): string {
  return crypto.createHash("sha256").update(secret, "utf8").digest("hex");
}

/** Constant-time compare of two hex strings of equal length. */
export function safeEqualHex(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  try {
    return crypto.timingSafeEqual(Buffer.from(a, "hex"), Buffer.from(b, "hex"));
  } catch {
    return false;
  }
}

/**
 * TTS-friendly pairing code: hex chars only ([0-9A-F]) so the device can spell it
 * with the existing Indonesian syllable map (utils/identity._SPELL_ID).
 */
export function generatePairingCode(len = 6): string {
  const alphabet = "0123456789ABCDEF";
  const bytes = crypto.randomBytes(len);
  let out = "";
  for (let i = 0; i < len; i++) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

export type DeviceAuth =
  | { ok: true; deviceId: string }
  | { ok: false; status: number; error: string };

/**
 * Authenticate a device-facing request. Expects:
 *   X-Device-Id:     the cloud device id
 *   X-Device-Secret: the device secret (compared against stored sha256 hash)
 */
export async function authDevice(req: Request): Promise<DeviceAuth> {
  const deviceId = req.headers.get("x-device-id")?.trim();
  const secret = req.headers.get("x-device-secret")?.trim();
  if (!deviceId || !secret) {
    return { ok: false, status: 401, error: "missing device credentials" };
  }
  const admin = createAdminClient();
  const { data, error } = await admin
    .from("devices")
    .select("id, secret_hash")
    .eq("id", deviceId)
    .maybeSingle();
  if (error || !data) {
    return { ok: false, status: 401, error: "unknown device" };
  }
  if (!safeEqualHex(hashSecret(secret), data.secret_hash)) {
    return { ok: false, status: 401, error: "bad device secret" };
  }
  return { ok: true, deviceId };
}
