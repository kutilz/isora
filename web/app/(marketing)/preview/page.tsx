"use client";

import { useRef, useState } from "react";

type Sample = { file: string; label: string; desc: string };

const SPEECH: Sample[] = [
  { file: "isora_siap_digunakan", label: "I-Sora siap digunakan", desc: "Sapaan saat perangkat siap." },
  { file: "baik_sudah_paham", label: "Baik, sudah paham", desc: "Konfirmasi setelah tombol ditekan lama." },
];

const CHIMES: Sample[] = [
  { file: "obj_person_left", label: "Orang — kiri", desc: "Ada orang di sebelah kiri." },
  { file: "obj_person_center", label: "Orang — tengah", desc: "Ada orang tepat di depan." },
  { file: "obj_person_right", label: "Orang — kanan", desc: "Ada orang di sebelah kanan." },
  { file: "obj_bottle_center", label: "Botol — tengah", desc: "Ada botol di depan." },
  { file: "obj_chair_left", label: "Kursi — kiri", desc: "Ada kursi di sebelah kiri." },
  { file: "obj_car_right", label: "Mobil — kanan", desc: "Ada mobil di sebelah kanan." },
];

function AudioCard({ s, playing, onPlay }: { s: Sample; playing: boolean; onPlay: (f: string) => void }) {
  return (
    <div className="card audio-card">
      <span className="label">{s.label}</span>
      <span className="desc">{s.desc}</span>
      <button
        className={playing ? "btn btn--primary" : "btn"}
        onClick={() => onPlay(s.file)}
        aria-label={`Putar suara: ${s.label}`}
      >
        {playing ? "▶ Memutar…" : "► Putar"}
      </button>
    </div>
  );
}

export default function PreviewPage() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [current, setCurrent] = useState<string | null>(null);

  const play = (file: string) => {
    const el = audioRef.current;
    if (!el) return;
    el.src = `/audio/${file}.wav`;
    el.currentTime = 0;
    setCurrent(file);
    el.play().catch(() => setCurrent(null));
  };

  return (
    <div className="container section">
      <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Coba suara I-Sora</h1>
      <p className="sub">
        Dengarkan contoh suara yang akan kamu dengar dari perangkat — chime objek
        dan sapaan — supaya kamu terbiasa sebelum mulai memakainya.
      </p>

      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} onEnded={() => setCurrent(null)} hidden />

      <h2 style={{ marginTop: "var(--s-8)" }}>Sapaan & konfirmasi</h2>
      <div className="audio-grid" style={{ marginTop: "var(--s-4)" }}>
        {SPEECH.map((s) => (
          <AudioCard key={s.file} s={s} playing={current === s.file} onPlay={play} />
        ))}
      </div>

      <h2 style={{ marginTop: "var(--s-10)" }}>Chime objek (offline)</h2>
      <p className="sub">
        Chime ini berbunyi sepenuhnya tanpa internet. Posisi (kiri / tengah / kanan)
        membantumu tahu arah objek.
      </p>
      <div className="audio-grid" style={{ marginTop: "var(--s-4)" }}>
        {CHIMES.map((s) => (
          <AudioCard key={s.file} s={s} playing={current === s.file} onPlay={play} />
        ))}
      </div>
    </div>
  );
}
