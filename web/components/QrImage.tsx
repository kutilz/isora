"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

/** Render any string as a QR code image. */
export default function QrImage({
  value,
  size = 240,
  alt = "QR code",
}: {
  value: string;
  size?: number;
  alt?: string;
}) {
  const [dataUrl, setDataUrl] = useState("");

  useEffect(() => {
    if (!value) {
      setDataUrl("");
      return;
    }
    QRCode.toDataURL(value, {
      width: size,
      margin: 2,
      errorCorrectionLevel: "M",
      color: { dark: "#141414", light: "#FFFFFF" },
    })
      .then(setDataUrl)
      .catch(() => setDataUrl(""));
  }, [value, size]);

  if (!dataUrl) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={dataUrl} alt={alt} width={size} height={size} style={{ display: "block" }} />;
}
