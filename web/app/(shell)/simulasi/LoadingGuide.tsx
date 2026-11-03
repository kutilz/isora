"use client";

import { useEffect, useState } from "react";

const STEP_MS = 4500;

/** Each line describes what lib/sim actually does, so keep them true if that changes. */
const STEPS = {
  penjelajah: [
    "Kamera melihat apa yang ada di depanmu, sama seperti kamera di kacamata.",
    "Model AI di ponsel ini mengenali 12 objek, seperti orang, motor, mobil, dan kursi.",
    "Letak objek di gambar menentukan arahnya: kiri, depan, atau kanan.",
    "Makin besar objek di gambar, makin dekat jaraknya.",
    "Suara hanya muncul saat ada yang berubah, supaya tidak berisik.",
  ],
  rupiah: [
    "Kamera membaca uang kertas yang kamu pegang di bagian terang.",
    "Model AI di ponsel ini mengenali 7 pecahan, dari seribu sampai seratus ribu.",
    "Uang harus terlihat beberapa kali berturut-turut, supaya tidak salah sebut.",
    "Nilainya disebut sekali, dan tidak diulang selama uangnya masih dipegang.",
    "Tekan tombol sebentar untuk mendengar nilainya lagi.",
  ],
};

/**
 * Shown over the live camera while a mode's model downloads. The status line is
 * for screen readers too; the rotating lines are not, because a live region that
 * changes every few seconds would talk over the simulation.
 */
export default function LoadingGuide({ mode }: { mode: keyof typeof STEPS }) {
  const steps = STEPS[mode];
  const [step, setStep] = useState(0);

  useEffect(() => {
    setStep(0);
    const id = window.setInterval(() => setStep((s) => (s + 1) % steps.length), STEP_MS);
    return () => window.clearInterval(id);
  }, [steps]);

  return (
    <div className="sim-guide">
      <p className="sim-guide__status" role="status">
        Memuat model deteksi… suara menyusul setelah siap.
      </p>
      <div className="sim-guide__bar" aria-hidden="true">
        <span />
      </div>
      <p key={`${mode}-${step}`} className="sim-guide__step" aria-hidden="true">
        <b>Cara kerja {step + 1}/{steps.length}</b>
        {steps[step]}
      </p>
    </div>
  );
}
