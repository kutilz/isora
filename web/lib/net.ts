import crypto from "node:crypto";

/**
 * "Same WiFi?" detection for the relay.
 *
 * A browser served over HTTPS cannot talk to the device's plain-HTTP LAN
 * address at all (mixed content is blocked), and it has no way to scan the
 * local network. So the hub answers the question indirectly: a device and a
 * phone that reach us from the *same public IP* are behind the same router.
 *
 * We never store the IP itself — only a keyed hash — so the relay keeps no log
 * of where anyone's device lives. Equality is all the feature needs.
 *
 * Caveat worth knowing: carrier-grade NAT can put unrelated households behind
 * one public IPv4. That is why an automatic claim is only offered when exactly
 * ONE unclaimed device is visible (see /api/pair/nearby) — anything ambiguous
 * falls back to the QR or the spoken code.
 */

/** Best-effort public IP of the caller, as seen by the edge. "" if unknown. */
export function clientIp(req: Request): string {
  const xff = req.headers.get("x-forwarded-for") || "";
  // Vercel appends; the left-most entry is the original client.
  const first = xff.split(",")[0]?.trim();
  const ip = first || req.headers.get("x-real-ip")?.trim() || "";
  if (!ip) return "";
  // Strip an IPv4-mapped IPv6 prefix so both stacks agree on the same string.
  return ip.startsWith("::ffff:") ? ip.slice(7) : ip;
}

/**
 * Keyed hash of the caller's network. Returns "" when the IP is unknown or no
 * signing secret is configured — callers must treat "" as "cannot tell".
 */
export function networkHash(req: Request): string {
  const ip = clientIp(req);
  if (!ip) return "";
  const key = process.env.PAIR_SIGNING_SECRET || process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) return "";
  return crypto.createHmac("sha256", key).update(`net:${ip}`).digest("hex");
}

/** Constant-time equality for two network hashes; "" never matches. */
export function sameNetwork(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b || a.length !== b.length) return false;
  try {
    return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
  } catch {
    return false;
  }
}
