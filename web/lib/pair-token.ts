import crypto from "node:crypto";

/**
 * Signed, short-lived claim token for camera-QR pairing — no DB row needed.
 *
 * The logged-in browser asks for a token (bound to its user id), renders it as a
 * QR, and the device camera scans it. The device posts the token to /api/pair/scan
 * (authenticated as itself); the server verifies the signature + expiry and links
 * the device to the user. Token lifetime is short so a glimpsed QR can't be reused.
 */

const TTL_MS = 3 * 60 * 1000; // 3 minutes

function secret(): string {
  const s = process.env.PAIR_SIGNING_SECRET || process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!s) throw new Error("pair signing secret missing");
  return s;
}

function b64url(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromB64url(s: string): Buffer {
  return Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

export function signClaimToken(userId: string): string {
  const payload = b64url(Buffer.from(JSON.stringify({ uid: userId, exp: Date.now() + TTL_MS })));
  const sig = b64url(crypto.createHmac("sha256", secret()).update(payload).digest());
  return `${payload}.${sig}`;
}

export function verifyClaimToken(token: string): { uid: string } | null {
  const parts = String(token || "").split(".");
  if (parts.length !== 2) return null;
  const [payload, sig] = parts;
  const expected = b64url(crypto.createHmac("sha256", secret()).update(payload).digest());
  try {
    if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
  } catch {
    return null;
  }
  try {
    const data = JSON.parse(fromB64url(payload).toString("utf8"));
    if (!data.uid || typeof data.exp !== "number" || Date.now() > data.exp) return null;
    return { uid: String(data.uid) };
  } catch {
    return null;
  }
}
