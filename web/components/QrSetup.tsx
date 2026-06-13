"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

/**
 * Renders a QR code that deep-links to the pairing page with the code prefilled,
 * e.g. https://isora.vercel.app/pair?code=A3F7C1 — a pendamping can scan it to skip typing.
 */
export default function QrSetup({ code, size = 180 }: { code: string; size?: number }) {
  const [dataUrl, setDataUrl] = useState<string>("");

  useEffect(() => {
    if (!code) {
      setDataUrl("");
      return;
    }
    const base = process.env.NEXT_PUBLIC_SITE_URL || (typeof window !== "undefined" ? window.location.origin : "");
    const url = `${base}/pair?code=${encodeURIComponent(code)}`;
    QRCode.toDataURL(url, { width: size, margin: 1, color: { dark: "#141414", light: "#FFFFFF" } })
      .then(setDataUrl)
      .catch(() => setDataUrl(""));
  }, [code, size]);

  if (!code || !dataUrl) return null;

  return (
    <figure style={{ margin: 0, textAlign: "center" }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={dataUrl} alt={`QR code untuk kode pairing ${code}`} width={size} height={size} />
      <figcaption style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)", marginTop: 8 }}>
        Pindai untuk membuka halaman ini dengan kode terisi
      </figcaption>
    </figure>
  );
}
