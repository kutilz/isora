"use client";

import { useEffect, useState } from "react";
import { getInstallState, promptInstall, subscribeInstall, type InstallState } from "@/lib/pwa";

/**
 * "Pasang di layar utama" card. Renders nothing once installed, or when the
 * browser can neither prompt (Chromium) nor be talked through it (iOS Safari).
 */
export default function InstallCard() {
  const [s, setS] = useState<InstallState>({ canPrompt: false, installed: false, iosSafari: false });
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setS(getInstallState());
    return subscribeInstall(setS);
  }, []);

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem("isora.pwa.dismissed") === "1");
    } catch {
      /* private mode — just show the card */
    }
  }, []);

  if (s.installed || dismissed || (!s.canPrompt && !s.iosSafari)) return null;

  const hide = () => {
    setDismissed(true);
    try {
      localStorage.setItem("isora.pwa.dismissed", "1");
    } catch {
      /* nothing to do */
    }
  };

  return (
    <div className="card install-card">
      <div>
        <strong style={{ fontSize: "var(--t-md)" }}>Pasang I-Sora di layar utama</strong>
        <p style={{ margin: "var(--s-2) 0 0", color: "var(--ink-2)" }}>
          {s.canPrompt
            ? "Buka langsung dari ikon, tanpa mengetik alamat. Simulasi kamera tetap jalan tanpa internet."
            : "Di Safari: ketuk tombol Bagikan, lalu pilih “Tambahkan ke Layar Utama”."}
        </p>
      </div>
      <div style={{ display: "flex", gap: "var(--s-2)", flexWrap: "wrap" }}>
        {s.canPrompt && (
          <button className="btn btn--primary" onClick={() => promptInstall()}>
            Pasang aplikasi
          </button>
        )}
        <button className="btn" onClick={hide}>
          Nanti saja
        </button>
      </div>
    </div>
  );
}
