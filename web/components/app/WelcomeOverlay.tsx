"use client";

import { useEffect, useRef } from "react";
import Logo from "@/components/Logo";
import type { AckState } from "@/lib/useCommandAck";

/**
 * The moment first-time setup is saved.
 *
 * It replaces a green "Pengaturan terkirim ke perangkat." that sat there doing
 * nothing: the settings had been queued, the screen looked identical to the one
 * before it, and there was no sign of what to do next. This says the setup is
 * over, shows whether the device has actually taken the settings, and then
 * hands the person to the device screen — by itself when the device confirms,
 * or on one tap that is always available so nobody is ever made to wait.
 */
export default function WelcomeOverlay({
  name,
  ack,
  onContinue,
}: {
  name: string;
  ack: AckState;
  onContinue: () => void;
}) {
  const button = useRef<HTMLButtonElement>(null);

  // Move focus into the dialog so a screen reader lands here rather than
  // continuing to read the form that is now behind it.
  useEffect(() => {
    button.current?.focus();
  }, []);

  // Auto-continue once the device confirms — but not instantly: the status line
  // is a live region and needs a beat to be announced before the screen changes.
  useEffect(() => {
    if (ack !== "applied") return;
    const t = setTimeout(onContinue, 2_500);
    return () => clearTimeout(t);
  }, [ack, onContinue]);

  const status =
    ack === "applied"
      ? "Pengaturan sudah diterima perangkat."
      : ack === "slow"
        ? "Tersimpan. Perangkat belum mengambilnya — nanti masuk sendiri begitu perangkat online."
        : "Mengirim pengaturan ke perangkat…";

  return (
    <div className="welcome" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className="welcome__card">
        <span className="welcome__ring">
          <Logo size={84} />
        </span>
        <p className="welcome__eyebrow">Selamat datang di</p>
        <h2 id="welcome-title">I-Sora</h2>
        <p className="welcome__name">{name} siap menemanimu.</p>
        <p className="welcome__status" role="status">
          {status}
        </p>
        <button ref={button} className="btn btn--primary btn--lg" onClick={onContinue}>
          {ack === "applied" ? "Mulai pakai" : "Lanjut"}
        </button>
      </div>
    </div>
  );
}
