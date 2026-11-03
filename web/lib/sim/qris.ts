"use client";

/**
 * QR reading for the simulator's QRIS mode.
 *
 * Prefers the browser's own BarcodeDetector (hardware-accelerated, present on
 * Chrome for Android) and falls back to jsQR over pixel data everywhere else.
 *
 * The merchant name is pulled out of the QRIS payload the same way the device
 * does it: EMVCo TLV, tag 59. We deliberately only *read* — nothing here
 * initiates a payment.
 */

type Detector = { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> };

let native: Detector | null | undefined;

function nativeDetector(): Detector | null {
  if (native !== undefined) return native;
  const Ctor = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector })
    .BarcodeDetector;
  native = Ctor ? new Ctor({ formats: ["qr_code"] }) : null;
  return native;
}

/** Decode the first QR visible in the canvas, or "" when there is none. */
export async function scanQr(canvas: HTMLCanvasElement): Promise<string> {
  const det = nativeDetector();
  if (det) {
    try {
      const found = await det.detect(canvas);
      if (found.length) return found[0].rawValue || "";
    } catch {
      native = null; // detector unusable on this device — fall through to jsQR
    }
  }

  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return "";
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const jsQR = (await import("jsqr")).default;
  const res = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
  return res?.data ?? "";
}

/**
 * Parse EMVCo TLV and return the merchant name (tag 59) and city (tag 60).
 * QRIS payloads are plain "TTLLVALUE" triples, so this is a short loop.
 */
export function parseQris(payload: string): { merchant: string; city: string } | null {
  if (!payload || !payload.startsWith("00")) return null;
  let i = 0;
  let merchant = "";
  let city = "";
  while (i + 4 <= payload.length) {
    const tag = payload.slice(i, i + 2);
    const len = Number(payload.slice(i + 2, i + 4));
    if (!Number.isFinite(len) || len < 0) break;
    const value = payload.slice(i + 4, i + 4 + len);
    if (tag === "59") merchant = value;
    if (tag === "60") city = value;
    i += 4 + len;
  }
  if (!merchant) return null;
  return { merchant: merchant.trim(), city: city.trim() };
}

/** The sentence the device would speak for a scanned code. */
export function qrisPhrase(payload: string): string {
  const parsed = parseQris(payload);
  if (parsed) {
    return parsed.city
      ? `Kode pembayaran ${parsed.merchant}, ${parsed.city}.`
      : `Kode pembayaran ${parsed.merchant}.`;
  }
  if (/^https?:\/\//i.test(payload)) {
    const host = payload.replace(/^https?:\/\//i, "").split("/")[0];
    return `Kode berisi tautan ${host.replace(/\./g, " titik ")}.`;
  }
  return "Kode terbaca, tapi bukan kode pembayaran QRIS.";
}
