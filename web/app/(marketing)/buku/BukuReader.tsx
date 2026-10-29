"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BUKU, BUKU_AUDIO, formatTime, spokenMinutes, type Block, type Chapter } from "@/lib/buku";

const MARKERS = BUKU_AUDIO.markers;
const DURATION = BUKU_AUDIO.duration;
const RATES = [1, 1.25, 1.5, 1.75, 0.85];
const POS_KEY = "isora-buku-pos";
const FIRST_GUIDE = BUKU.chapters.find((c) => c.num === BUKU.parts[1].from)!;

function markerIndexAt(t: number): number {
  let i = 0;
  while (i + 1 < MARKERS.length && MARKERS[i + 1].start <= t + 0.05) i++;
  return i;
}

function startOf(id: string): number {
  return MARKERS.find((m) => m.id === id)?.start ?? 0;
}

function lengthOf(id: string): number {
  const i = MARKERS.findIndex((m) => m.id === id);
  const end = i + 1 < MARKERS.length ? MARKERS[i + 1].start : DURATION;
  return end - (MARKERS[i]?.start ?? 0);
}

function readPos(): number {
  try {
    const v = Number(localStorage.getItem(POS_KEY));
    return Number.isFinite(v) ? v : 0;
  } catch {
    return 0;
  }
}

function writePos(t: number) {
  try {
    localStorage.setItem(POS_KEY, t.toFixed(1));
  } catch {
    /* private mode — resuming is a convenience only */
  }
}

export default function BukuReader() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastSaved = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [started, setStarted] = useState(false);
  const [time, setTime] = useState(0);
  const [rate, setRate] = useState(1);
  const [resumeAt, setResumeAt] = useState(0);
  const [failed, setFailed] = useState(false);

  const idx = markerIndexAt(time);
  const current = MARKERS[idx];

  useEffect(() => {
    const t = readPos();
    if (t > 20 && t < DURATION - 15) setResumeAt(t);
  }, []);

  const seekAndPlay = useCallback((t: number) => {
    const el = audioRef.current;
    if (!el) return;
    setFailed(false);
    setStarted(true);
    // play() must run inside the tap (iOS); the seek can follow once metadata is in.
    el.play().catch(() => setPlaying(false));
    if (el.readyState >= 1) el.currentTime = t;
    else el.addEventListener("loadedmetadata", () => (el.currentTime = t), { once: true });
    setTime(t);
  }, []);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) {
      setStarted(true);
      el.play().catch(() => setPlaying(false));
    } else el.pause();
  }, []);

  const jump = useCallback(
    (delta: number) => {
      const el = audioRef.current;
      const t = el ? el.currentTime : time;
      const i = markerIndexAt(t);
      // "Previous" restarts the chapter first, like any audiobook player.
      const target = delta < 0 && t - MARKERS[i].start > 4 ? i : i + delta;
      seekAndPlay(MARKERS[Math.max(0, Math.min(MARKERS.length - 1, target))].start);
    },
    [seekAndPlay, time]
  );

  const cycleRate = () => {
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
    setRate(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
  };

  // Lock-screen / earphone controls: chapter skip + 10 s nudges.
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    const set = (a: MediaSessionAction, h: MediaSessionActionHandler | null) => {
      try {
        ms.setActionHandler(a, h);
      } catch {
        /* action unsupported on this browser */
      }
    };
    set("previoustrack", () => jump(-1));
    set("nexttrack", () => jump(1));
    set("seekbackward", () => audioRef.current && (audioRef.current.currentTime -= 10));
    set("seekforward", () => audioRef.current && (audioRef.current.currentTime += 10));
    return () => {
      (["previoustrack", "nexttrack", "seekbackward", "seekforward"] as const).forEach((a) => set(a, null));
    };
  }, [jump]);

  useEffect(() => {
    if (!started || !("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: current.title,
      artist: "Tim I-SORA",
      album: "Manual Book I-SORA",
      artwork: [{ src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" }],
    });
  }, [current.title, started]);

  const onTime = () => {
    const t = audioRef.current?.currentTime ?? 0;
    setTime(t);
    if (Math.abs(t - lastSaved.current) > 5) {
      lastSaved.current = t;
      writePos(t);
    }
  };

  return (
    <div className="buku">
      <audio
        ref={audioRef}
        src={BUKU_AUDIO.src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={onTime}
        onEnded={() => writePos(0)}
        onError={() => {
          setFailed(true);
          setPlaying(false);
        }}
      />

      <header className="container buku-hero">
        <p className="buku-eyebrow">Buku panduan pengguna · versi audio &amp; digital</p>
        <h1>{BUKU.title}</h1>
        <p className="lead">{BUKU.subtitle}</p>
        <p className="buku-hint">
          Tombol <strong>Dengarkan</strong> memutar rekaman suara buku ini ({spokenMinutes(DURATION)}). Bila memakai pembaca
          layar, semua teks di bawah juga bisa dibaca langsung.
        </p>
        <div className="cta-row">
          {resumeAt > 0 && !started ? (
            <button className="btn btn--primary btn--lg" onClick={() => seekAndPlay(resumeAt)}>
              ▶ Lanjutkan: {MARKERS[markerIndexAt(resumeAt)].title}
            </button>
          ) : (
            <button className="btn btn--primary btn--lg" onClick={() => seekAndPlay(0)}>
              ▶ Dengarkan dari awal
            </button>
          )}
          <button className="btn btn--lg" onClick={() => seekAndPlay(startOf(FIRST_GUIDE.id))}>
            ▶ Langsung ke panduan pemakaian
          </button>
        </div>
        <div className="notice notice--warn buku-important" role="note">
          PENTING: I-SORA adalah alat bantu tambahan, bukan pengganti tongkat putih, keterampilan orientasi mobilitas,
          maupun pendamping.
        </div>
      </header>

      <nav className="container buku-toc" aria-label="Daftar isi">
        <h2>Daftar isi</h2>
        {BUKU.parts.map((part) => (
          <div key={part.id}>
            <h3>{part.title}</h3>
            <ol>
              {BUKU.chapters
                .filter((c) => c.num >= part.from && c.num <= part.to)
                .map((c) => (
                  <li key={c.id} value={c.num}>
                    <a href={`#${c.id}`}>{c.title}</a>
                  </li>
                ))}
            </ol>
          </div>
        ))}
        <p>
          <a href={BUKU_AUDIO.src.split("?")[0]} download="Manual Book I-SORA (buku audio).mp3">
            Unduh buku audio (MP3) untuk didengar tanpa internet
          </a>
        </p>
      </nav>

      <div className="container buku-body">
        {BUKU.parts.map((part) => (
          <section key={part.id} aria-labelledby={`bagian-${part.id}`}>
            <h2 id={`bagian-${part.id}`} className="buku-part">
              {part.title}
            </h2>
            {BUKU.chapters
              .filter((c) => c.num >= part.from && c.num <= part.to)
              .map((c) => (
                <ChapterView
                  key={c.id}
                  ch={c}
                  active={started && current.id === c.id}
                  playing={playing}
                  onListen={() =>
                    started && current.id === c.id ? toggle() : seekAndPlay(startOf(c.id))
                  }
                />
              ))}
          </section>
        ))}
        <p className="buku-closing">Melihat dunia adalah hak setiap orang.</p>
      </div>

      <div className="buku-player" role="region" aria-label="Pemutar buku audio">
        <div className="container buku-player__inner">
          <input
            type="range"
            className="buku-player__seek"
            min={0}
            max={Math.floor(DURATION)}
            step={1}
            value={Math.floor(time)}
            onChange={(e) => {
              const t = Number(e.target.value);
              setTime(t);
              if (audioRef.current) audioRef.current.currentTime = t;
            }}
            aria-label="Posisi buku audio"
            aria-valuetext={`${current.title}, menit ${Math.floor(time / 60)} dari ${Math.round(DURATION / 60)}`}
          />
          <div className="buku-player__row">
            <div className="buku-player__now">
              <span className="buku-player__title">{failed ? "Audio gagal dimuat" : current.title}</span>
              <span className="buku-player__time">
                {failed ? "Periksa koneksi, lalu coba lagi" : `${formatTime(time)} / ${formatTime(DURATION)}`}
              </span>
            </div>
            <div className="buku-player__ctrl">
              <button className="btn" onClick={() => jump(-1)} aria-label="Bab sebelumnya">
                ⏮
              </button>
              <button
                className="btn btn--primary buku-player__play"
                onClick={toggle}
                aria-label={playing ? "Jeda" : "Putar"}
              >
                {playing ? "❚❚" : "▶"}
              </button>
              <button className="btn" onClick={() => jump(1)} aria-label="Bab berikutnya">
                ⏭
              </button>
              <button className="btn buku-player__rate" onClick={cycleRate} aria-label={`Kecepatan ${rate} kali`}>
                {rate}×
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChapterView({
  ch,
  active,
  playing,
  onListen,
}: {
  ch: Chapter;
  active: boolean;
  playing: boolean;
  onListen: () => void;
}) {
  const len = spokenMinutes(lengthOf(ch.id));
  return (
    <article id={ch.id} className={active ? "buku-ch buku-ch--active" : "buku-ch"} aria-labelledby={`${ch.id}-judul`}>
      <p className="buku-ch__num" aria-hidden="true">
        Bab {ch.num}
      </p>
      <h3 id={`${ch.id}-judul`}>
        <span className="sr-only">Bab {ch.num}. </span>
        {ch.title}
      </h3>
      <button
        className={active ? "btn btn--primary buku-ch__listen" : "btn buku-ch__listen"}
        onClick={onListen}
        aria-label={
          active && playing ? `Jeda bab ${ch.num}` : `Dengarkan bab ${ch.num}, ${ch.title}, sekitar ${len}`
        }
      >
        {active && playing ? "❚❚ Jeda" : `▶ Dengarkan bab ini · ${len}`}
      </button>
      {ch.blocks.map((b, i) => (
        <BlockView key={i} b={b} />
      ))}
    </article>
  );
}

function BlockView({ b }: { b: Block }) {
  if ("p" in b) return <p>{b.p}</p>;
  if ("h" in b) return <h4>{b.h}</h4>;
  if ("note" in b)
    return (
      <p className="notice notice--info" role="note">
        {b.note}
      </p>
    );
  if ("ul" in b)
    return (
      <ul>
        {b.ul.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
    );
  if ("ol" in b)
    return (
      <ol className="buku-steps">
        {b.ol.map(([t, d]) => (
          <li key={t}>
            <strong>{t}.</strong> {d}
          </li>
        ))}
      </ol>
    );
  if ("dl" in b)
    return (
      <dl className="buku-dl">
        {b.dl.map(([t, d]) => (
          <div key={t}>
            <dt>{t}</dt>
            <dd>{d}</dd>
          </div>
        ))}
      </dl>
    );
  if ("table" in b)
    return (
      <div className="buku-table" role="region" aria-label="Tabel" tabIndex={0}>
        <table>
          <thead>
            <tr>
              {b.table.head.map((h) => (
                <th key={h} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {b.table.rows.map((r) => (
              <tr key={r[0]}>
                <th scope="row">{r[0]}</th>
                {r.slice(1).map((c, i) => (
                  <td key={i}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  const c = BUKU.contact;
  return (
    <ul className="buku-contact">
      <li>
        Email: <a href={`mailto:${c.email}`}>{c.email}</a>
      </li>
      <li>
        Instagram: <a href={`https://instagram.com/${c.instagram}`}>@{c.instagram}</a>
      </li>
      <li>
        YouTube: <a href={`https://youtube.com/@${c.youtube}`}>@{c.youtube}</a>
      </li>
    </ul>
  );
}
