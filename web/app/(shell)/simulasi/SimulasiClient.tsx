"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import LoadingGuide from "./LoadingGuide";
import AppBar from "@/components/app/AppBar";
import Notice from "@/components/Notice";
import { SettingsField, SettingsGroup, SettingsItem } from "@/components/app/Settings";
import { INFERENCE_INTERVAL_MS, NAV_OBJECTS, caption } from "@/lib/sim/constants";
import { decide, type AnnounceState, type Detection } from "@/lib/sim/announce";
import { cameraErrorMessage, openCamera } from "@/lib/sim/camera";
import { detectFrame, loadDetector, type CocoModel } from "@/lib/sim/detector";
import { PresenceTracker, spokenNominal } from "@/lib/sim/money";
import { detectMoney, loadMoneyModel, scanBand, type MoneyModel } from "@/lib/sim/money-detector";
import { qrisPhrase, scanQr } from "@/lib/sim/qris";
import { SimAudio, type AudioMode } from "@/lib/sim/audio";
import { DescribeError, describeScene, forgetStoredKey } from "@/lib/sim/describe";
import { positionFromBbox, type Tier } from "@/lib/sim/vision";

type Mode = "penjelajah" | "qris" | "rupiah";
type ModelState = "none" | "loading" | "ready" | "failed";
type Status = "idle" | "starting" | "running" | "error";
type LogKind = "nav" | "near" | "system" | "ai" | "qris";
type LogItem = { id: number; at: string; text: string; kind: LogKind };

const LOG_MAX = 40;
/** The permission prompt has no deadline, so past this we offer a retry beside it. */
const SLOW_START_MS = 15_000;
const PLAY_WAIT_MS = 5_000;

const MODE_NAME: Record<Mode, string> = { penjelajah: "Mode penjelajah", qris: "Mode QRIS", rupiah: "Mode rupiah" };

/** Fit the overlay canvas to how the browser actually crops the video (cover). */
function coverTransform(video: HTMLVideoElement, canvas: HTMLCanvasElement) {
  const vw = video.videoWidth || 1;
  const vh = video.videoHeight || 1;
  const scale = Math.max(canvas.width / vw, canvas.height / vh);
  return { scale, dx: (canvas.width - vw * scale) / 2, dy: (canvas.height - vh * scale) / 2 };
}

export default function SimulasiClient() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const workRef = useRef<HTMLCanvasElement | null>(null); // offscreen, for QR pixels
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<SimAudio | null>(null);
  const rafRef = useRef<number | null>(null);
  const wakeRef = useRef<{ release: () => Promise<void> } | null>(null);
  // The frame loop re-enters through this ref, never through a captured
  // closure: `tick` is rebuilt whenever debug drawing changes, and a running
  // loop must pick that up instead of running the version it started with.
  const tickRef = useRef<() => void>(() => {});

  // Loop-owned state — refs, not React state, so the frame loop never restarts.
  const announceState = useRef<AnnounceState>({});
  const prevTiers = useRef<Map<string, Tier>>(new Map());
  const lastInference = useRef(0);
  const detectionsRef = useRef<Detection[]>([]);
  const forceRef = useRef(false);
  const modeRef = useRef<Mode>("penjelajah");
  const lastQr = useRef<{ value: string; at: number }>({ value: "", at: 0 });
  const busyRef = useRef(false);
  const runningRef = useRef(false);
  const logId = useRef(0);
  const modelRef = useRef<CocoModel | null>(null);
  const moneyRef = useRef<MoneyModel | null>(null);
  const moneyTracker = useRef(new PresenceTracker());
  const greetedRef = useRef(false);
  // Bumped by every start and stop, so a camera that answers late is closed
  // instead of taking over from whatever the person has done since.
  const attemptRef = useRef(0);

  const [status, setStatus] = useState<Status>("idle");
  const [mode, setMode] = useState<Mode>("penjelajah");
  const [audioMode, setAudioMode] = useState<AudioMode>("both");
  const [log, setLog] = useState<LogItem[]>([]);
  const [err, setErr] = useState("");
  const [slowStart, setSlowStart] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);
  const [modelState, setModelState] = useState<ModelState>("none");
  const [moneyState, setMoneyState] = useState<ModelState>("none");
  const [debug, setDebug] = useState(false);
  const [stats, setStats] = useState({ ms: 0, count: 0 });
  const [detections, setDetections] = useState<Detection[]>([]);
  const [describing, setDescribing] = useState(false);

  // The button arrives in the prerendered HTML, before it can do anything. On a
  // slow connection a tap in that gap is lost without a trace.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
    forgetStoredKey();
  }, []);

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  const say = useCallback((text: string, kind: LogKind) => {
    const at = new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setLog((prev) => [{ id: logId.current++, at, text, kind }, ...prev].slice(0, LOG_MAX));
  }, []);

  // ─── camera + loop ────────────────────────────────────────────────────────

  const stop = useCallback(() => {
    attemptRef.current++;
    runningRef.current = false;
    greetedRef.current = false;
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    audioRef.current?.silence();
    wakeRef.current?.release().catch(() => {});
    wakeRef.current = null;
    announceState.current = {};
    prevTiers.current.clear();
    moneyTracker.current.reset();
    detectionsRef.current = [];
    setDetections([]);
    setSlowStart(false);
    setNeedsTap(false);
    setStatus("idle");
  }, []);

  useEffect(() => () => stop(), [stop]);

  const drawOverlay = useCallback(() => {
    const video = videoRef.current;
    const canvas = overlayRef.current;
    if (!video || !canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (canvas.width !== rect.width || canvas.height !== rect.height) {
      canvas.width = Math.round(rect.width);
      canvas.height = Math.round(rect.height);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // The 3×3 grid the position names come from — worth seeing while learning.
    ctx.strokeStyle = "rgba(255,255,255,.18)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 3; i++) {
      ctx.beginPath();
      ctx.moveTo((canvas.width / 3) * i, 0);
      ctx.lineTo((canvas.width / 3) * i, canvas.height);
      ctx.moveTo(0, (canvas.height / 3) * i);
      ctx.lineTo(canvas.width, (canvas.height / 3) * i);
      ctx.stroke();
    }

    const { scale, dx, dy } = coverTransform(video, canvas);

    // Rupiah only reads the band that fits the model, so dim the rest of the picture.
    if (modeRef.current === "rupiah") {
      const band = scanBand(video.videoWidth, video.videoHeight);
      const top = band.y * scale + dy;
      const height = band.h * scale;
      ctx.fillStyle = "rgba(11,14,42,.55)";
      ctx.fillRect(0, 0, canvas.width, Math.max(top, 0));
      ctx.fillRect(0, top + height, canvas.width, canvas.height - top - height);
    }

    ctx.font = "600 13px system-ui, sans-serif";
    for (const d of detectionsRef.current) {
      const x = d.bbox.x * scale + dx;
      const y = d.bbox.y * scale + dy;
      const w = d.bbox.w * scale;
      const h = d.bbox.h * scale;
      const near = d.tier === "near";
      ctx.strokeStyle = near ? "#F4A23B" : "#6B9BFF";
      ctx.lineWidth = near ? 3 : 2;
      ctx.strokeRect(x, y, w, h);
      const name = NAV_OBJECTS[d.label] ?? d.label;
      const text = debug
        ? `${name} ${d.position}${modeRef.current === "rupiah" ? "" : ` ${d.tier}`} ${d.confidence.toFixed(2)}`
        : name;
      const tw = ctx.measureText(text).width + 10;
      ctx.fillStyle = near ? "#F4A23B" : "#6B9BFF";
      ctx.fillRect(x, Math.max(y - 20, 0), tw, 20);
      ctx.fillStyle = "#0B0E2A";
      ctx.fillText(text, x + 5, Math.max(y - 6, 14));
    }
  }, [debug]);

  const tick = useCallback(async () => {
    // Check before re-arming, so a stopped loop can never schedule another frame.
    if (!runningRef.current) return;
    rafRef.current = requestAnimationFrame(() => tickRef.current());
    const video = videoRef.current;
    const audio = audioRef.current;
    // A paused video still reports frames, and they would be announced as if live.
    if (!video || !audio || video.readyState < 2 || video.paused) return;

    drawOverlay();

    const now = performance.now();
    const forced = forceRef.current;
    if (!forced && now - lastInference.current < INFERENCE_INTERVAL_MS) return;
    if (busyRef.current) return;
    busyRef.current = true;
    lastInference.current = now;

    try {
      if (modeRef.current === "qris") {
        // A short press in QRIS mode re-reads the last code instead of forcing
        // a scan; clearing the flag here also stops it pinning the loop at full
        // rate for every later frame.
        if (forced) {
          forceRef.current = false;
          if (lastQr.current.value) {
            const again = qrisPhrase(lastQr.current.value);
            audio.say(again, true);
            say(again, "qris");
          } else {
            const none = "Belum ada kode yang terbaca.";
            audio.say(none, true);
            say(none, "system");
          }
        }
        const work = workRef.current;
        if (work) {
          const w = 480;
          const h = Math.round((video.videoHeight / Math.max(video.videoWidth, 1)) * w) || 360;
          work.width = w;
          work.height = h;
          work.getContext("2d", { willReadFrequently: true })?.drawImage(video, 0, 0, w, h);
          const value = await scanQr(work);
          // De-dupe: the same code stays in frame for many seconds.
          if (value && (value !== lastQr.current.value || now - lastQr.current.at > 8000)) {
            lastQr.current = { value, at: now };
            const phrase = qrisPhrase(value);
            audio.say(phrase, true);
            say(phrase, "qris");
          }
        }
        return;
      }

      if (modeRef.current === "rupiah") {
        const money = moneyRef.current;
        if (!money) {
          if (forced) {
            forceRef.current = false;
            const wait = "Deteksi objek belum siap.";
            audio.say(wait, true);
            say(wait, "system");
          }
          return;
        }
        const started = performance.now();
        const found = await detectMoney(money, video, video.videoWidth, video.videoHeight);
        const elapsed = Math.round(performance.now() - started);
        if (!runningRef.current || modeRef.current !== "rupiah") return;

        const dets: Detection[] = found.map((m) => ({
          label: `Rp${m.value.toLocaleString("id-ID")}`,
          confidence: m.confidence,
          position: positionFromBbox(m.bbox.x, m.bbox.y, m.bbox.w, m.bbox.h, video.videoWidth, video.videoHeight),
          tier: "far",
          is_danger: false,
          areaRatio: Math.round(((m.bbox.w * m.bbox.h) / (video.videoWidth * video.videoHeight)) * 10000) / 10000,
          bbox: m.bbox,
        }));
        detectionsRef.current = dets;
        setDetections(dets);
        setStats({ ms: elapsed, count: dets.length });

        const seconds = now / 1000;
        const tracker = moneyTracker.current;
        tracker.update(new Set(found.map((m) => m.value)), seconds);
        const arrived = tracker.take(seconds);
        // A short press re-reads what is in view; several notes, largest first.
        const toSay = forced ? tracker.present : arrived;
        if (forced) {
          forceRef.current = false;
          if (toSay.length === 0) {
            const none = "Belum ada uang yang terbaca.";
            audio.say(none, true);
            say(none, "system");
          }
        }
        [...toSay]
          .sort((a, b) => b - a)
          .forEach((value, i) => {
            const phrase = spokenNominal(value);
            audio.say(phrase, forced && i === 0);
            say(phrase, "qris");
          });
        return;
      }

      const model = modelRef.current;
      if (!model) {
        if (forced) {
          forceRef.current = false;
          const wait = "Deteksi objek belum siap.";
          audio.say(wait, true);
          say(wait, "system");
        }
        return;
      }
      const started = performance.now();
      const dets = await detectFrame(
        model,
        video,
        video.videoWidth,
        video.videoHeight,
        prevTiers.current
      );
      const elapsed = Math.round(performance.now() - started);

      detectionsRef.current = dets;
      setDetections(dets);
      setStats({ ms: elapsed, count: dets.length });

      if (!runningRef.current) return;

      const { announcements, state } = decide(announceState.current, dets, now / 1000, forced);
      announceState.current = state;
      if (forced) forceRef.current = false;

      if (announcements.length === 0 && forced) {
        const phrase = "Tidak ada objek yang dikenali.";
        audio.say(phrase, true);
        say(phrase, "system");
      }
      for (const a of announcements) {
        audio.announce(a.label, a.position, a.tier, a.is_danger);
        say(caption(a.label, a.position, a.tier), a.tier === "near" ? "near" : "nav");
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Terjadi kesalahan saat memproses frame.");
    } finally {
      busyRef.current = false;
    }
  }, [drawOverlay, say]);

  const start = useCallback(async () => {
    const attempt = ++attemptRef.current;
    setErr("");
    setSlowStart(false);
    setNeedsTap(false);
    setModelState((s) => (s === "failed" ? "none" : s));
    setMoneyState((s) => (s === "failed" ? "none" : s));
    setStatus("starting");

    // Must happen inside the tap that started us. Sound is not a condition for
    // seeing: if it cannot start, the transcript still tells the story.
    try {
      const audio = audioRef.current ?? new SimAudio();
      audioRef.current = audio;
      audio.unlock();
      audio.setMode(audioMode);
    } catch {
      /* no audio on this browser */
    }

    const slowTimer = window.setTimeout(() => {
      if (attempt === attemptRef.current) setSlowStart(true);
    }, SLOW_START_MS);

    let stream: MediaStream;
    try {
      stream = await openCamera();
    } catch (e: unknown) {
      if (attempt === attemptRef.current) {
        setErr(cameraErrorMessage(e));
        setSlowStart(false);
        setStatus("error");
      }
      return;
    } finally {
      window.clearTimeout(slowTimer);
    }
    if (attempt !== attemptRef.current) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    const video = videoRef.current;
    if (!video) {
      stream.getTracks().forEach((t) => t.stop());
      setErr("Kamera tidak bisa dibuka. Muat ulang halaman, lalu coba lagi.");
      setStatus("error");
      return;
    }
    streamRef.current = stream;
    setSlowStart(false);
    // Another app taking the camera ends the track without any other signal.
    stream.getVideoTracks()[0]?.addEventListener("ended", () => {
      if (streamRef.current !== stream) return;
      stop();
      setErr("Kamera terputus. Ketuk Mulai simulasi untuk menyalakannya lagi.");
    });

    // The camera shows as soon as it is open. Everything slower (the model
    // download, the wake lock) happens beside a live picture, never before it.
    video.muted = true;
    video.srcObject = stream;
    runningRef.current = true;
    setStatus("running");
    audioRef.current?.wake();
    rafRef.current = requestAnimationFrame(() => tickRef.current());

    (navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> } })
      .wakeLock?.request("screen")
      .then((lock) => {
        if (attempt === attemptRef.current) wakeRef.current = lock;
        else void lock.release().catch(() => {});
      })
      .catch(() => {
        /* keeping the screen on is a nicety, not a requirement */
      });

    // The tap that started us may have expired during the permission prompt,
    // and then only another tap will start the picture.
    const played = await Promise.race([
      video.play().then(
        () => true,
        () => false
      ),
      new Promise<boolean>((resolve) => window.setTimeout(() => resolve(false), PLAY_WAIT_MS)),
    ]);
    // play() clears `paused` at once, so a call still pending shows only in readyState.
    if (!played && attempt === attemptRef.current && (video.paused || video.readyState < 2)) setNeedsTap(true);
  }, [audioMode, stop]);

  const resumeVideo = useCallback(() => {
    audioRef.current?.wake();
    void videoRef.current?.play().then(
      () => setNeedsTap(false),
      () => {}
    );
  }, []);

  useEffect(() => {
    tickRef.current = () => void tick();
  }, [tick]);

  // Phones pause the picture and the audio while the page is in the background.
  useEffect(() => {
    const onVisible = () => {
      const video = videoRef.current;
      if (document.visibilityState !== "visible" || !runningRef.current || !video) return;
      audioRef.current?.wake();
      void video.play().catch(() => setNeedsTap(true));
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // The detector downloads beside a live camera, and only when this mode needs it.
  useEffect(() => {
    if (status !== "running" || mode !== "penjelajah" || modelState !== "none") return;
    setModelState("loading");
    loadDetector().then(
      (model) => {
        modelRef.current = model;
        setModelState("ready");
      },
      () => {
        setModelState("failed");
        if (runningRef.current) audioRef.current?.say("Gagal, coba lagi.", true);
      }
    );
  }, [status, mode, modelState]);

  useEffect(() => {
    if (status !== "running" || mode !== "rupiah" || moneyState !== "none") return;
    setMoneyState("loading");
    loadMoneyModel().then(
      (model) => {
        moneyRef.current = model;
        setMoneyState("ready");
      },
      () => {
        setMoneyState("failed");
        if (runningRef.current) audioRef.current?.say("Gagal, coba lagi.", true);
      }
    );
  }, [status, mode, moneyState]);

  // ─── the single physical button ───────────────────────────────────────────


  const describe = useCallback(async () => {
    const video = videoRef.current;
    const audio = audioRef.current;
    if (!video || !audio) return;
    setDescribing(true);
    audio.say("Sedang memproses.", true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20_000);
    try {
      const text = await describeScene(video, controller.signal);
      audio.say(text, true);
      say(text, "ai");
    } catch (e: unknown) {
      const msg =
        e instanceof DOMException && e.name === "AbortError"
          ? "Terlalu lama menunggu jawaban. Coba lagi."
          : e instanceof DescribeError
            ? e.message
            : "Gagal menjelaskan sekitar. Periksa internet, lalu coba lagi.";
      const outside = e instanceof DescribeError && e.code === "outside_hours";
      audio.say(outside ? "Fitur ini hanya aktif pukul dua belas lima puluh sampai lima belas tiga puluh." : "Gagal, coba lagi.", true);
      say(msg, "system");
    } finally {
      window.clearTimeout(timeout);
      setDescribing(false);
    }
  }, [say]);

  /** Read the scene out now, bypassing cooldown and cap. */
  const repeat = () => {
    if (status !== "running") return;
    navigator.vibrate?.(15);
    forceRef.current = true;
  };

  // ─── settings side-effects ────────────────────────────────────────────────

  useEffect(() => {
    audioRef.current?.setMode(audioMode);
  }, [audioMode]);

  const lastMode = useRef(mode);
  useEffect(() => {
    const switched = lastMode.current !== mode;
    lastMode.current = mode;
    if (status !== "running") return;
    // Switching modes clears what the old mode remembered.
    announceState.current = {};
    prevTiers.current.clear();
    moneyTracker.current.reset();
    detectionsRef.current = [];
    setDetections([]);
    // Only a mode switch while running cuts speech; this also runs on start,
    // where it would swallow the greeting that start() has just queued.
    if (switched) audioRef.current?.silence();
  }, [mode, status]);

  // The model this mode runs on; QRIS needs none.
  const activeModel: ModelState = mode === "penjelajah" ? modelState : mode === "rupiah" ? moneyState : "ready";

  // "Siap" is a promise that it can already speak, so a mode waits for its model.
  useEffect(() => {
    if (status !== "running" || greetedRef.current || activeModel !== "ready") return;
    greetedRef.current = true;
    const hello = "Isora siap digunakan.";
    audioRef.current?.say(hello, true);
    say(hello, "system");
  }, [status, activeModel, say]);

  const running = status === "running";
  const starting = status === "starting";
  const lastHeard = log[0]?.text;

  return (
    <>
      <AppBar
        title="Simulasi kamera"
        back="/app"
        trailing={
          <span className={`pill ${running ? "pill--ok" : "pill--off"}`}>
            {running ? MODE_NAME[mode] : "Berhenti"}
          </span>
        }
      />

      <div className="app-body">
        {err && <Notice kind="err">{err}</Notice>}
        {starting && slowStart && (
          <Notice kind="warn">
            Kamera belum menjawab. Kalau ada pertanyaan izin kamera di layar, pilih Izinkan. Kalau tidak ada, coba lagi.
          </Notice>
        )}
        {running && activeModel === "failed" && (
          <Notice kind="err">
            Kamera jalan, tapi model deteksi gagal dimuat. Butuh internet sekali di awal, setelah itu tersimpan dan
            bisa offline.{" "}
            <button
              className="btn"
              onClick={() => (mode === "rupiah" ? setMoneyState("none") : setModelState("none"))}
            >
              Muat ulang model
            </button>
          </Notice>
        )}
        <div className="sim-stage">
          {/* Never display:none: iOS will not start a video that is not on screen. */}
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            aria-hidden="true"
            onPlaying={() => setNeedsTap(false)}
          />
          <canvas ref={overlayRef} aria-hidden="true" hidden={!running} />
          <canvas ref={workRef} hidden aria-hidden="true" />
          {!running && (
            <div className="sim-stage__idle">
              <p style={{ margin: 0, fontSize: "var(--t-md)", fontWeight: 700 }}>
                {starting ? "Membuka kamera…" : "Arahkan kamera belakang ke sekitar"}
              </p>
              <p style={{ margin: "var(--s-3) 0 0", color: "#C9CEEA" }}>
                {starting
                  ? "Kalau muncul pertanyaan izin kamera, pilih Izinkan."
                  : "Pakai earphone supaya arah kiri/kanan terdengar jelas."}
              </p>
            </div>
          )}
          {running && !needsTap && mode !== "qris" && (activeModel === "loading" || activeModel === "none") && (
            <LoadingGuide mode={mode} />
          )}
          {running && !needsTap && activeModel === "ready" && (
            <div className="sim-stage__badge" aria-hidden="true">
              {mode === "rupiah" && detections.length === 0
                ? "Pegang uang kertas di bagian terang, jarak sekitar 30 cm."
                : (lastHeard ?? "Belum ada yang terdengar.")}
            </div>
          )}
          {running && needsTap && (
            <button className="sim-stage__tap" onClick={resumeVideo}>
              Ketuk untuk menyalakan kamera
            </button>
          )}
        </div>

        {!running ? (
          <button
            className="btn btn--primary btn--lg"
            onClick={start}
            disabled={!hydrated || (starting && !slowStart)}
          >
            {!hydrated ? "Memuat halaman…" : !starting ? "Mulai simulasi" : slowStart ? "Coba lagi" : "Membuka kamera…"}
          </button>
        ) : (
          <>
            <div className="sim-actions">
              <button className="sim-button" onClick={repeat} aria-label="Ulangi, sebutkan lagi yang terlihat">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v4.5h4.5" />
                </svg>
                Ulangi
              </button>
              <button
                className="sim-button sim-button--ai"
                onClick={() => {
                  navigator.vibrate?.(30);
                  void describe();
                }}
                disabled={describing}
                aria-label="Jelaskan, gambarkan sekitar dengan AI"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
                {describing ? "Memproses…" : "Jelaskan"}
              </button>
            </div>
            <button className="btn" onClick={stop}>
              Berhenti
            </button>
          </>
        )}

        <SettingsGroup
          title="Cara kerja"
          note="Logika arah, jarak, dan kapan harus bersuara diambil apa adanya dari perangkat — bukan tiruan kasar."
        >
          <SettingsField>
            <div className="field">
              <label htmlFor="sim-mode">Mode</label>
              <select
                id="sim-mode"
                className="select"
                value={mode}
                onChange={(e) => setMode(e.target.value as Mode)}
              >
                <option value="penjelajah">Penjelajah — sebut objek & arahnya</option>
                <option value="qris">QRIS — baca kode pembayaran</option>
                <option value="rupiah">Rupiah — sebut nilai uang kertas</option>
              </select>
            </div>
          </SettingsField>
          <SettingsField>
            <div className="field">
              <label htmlFor="sim-audio">Cara mendengar</label>
              <select
                id="sim-audio"
                className="select"
                value={audioMode}
                onChange={(e) => setAudioMode(e.target.value as AudioMode)}
              >
                <option value="both">Chime + bicara (default)</option>
                <option value="chime">Hanya chime (mahir)</option>
                <option value="speech">Hanya bicara (pemula)</option>
              </select>
            </div>
          </SettingsField>
        </SettingsGroup>


        <SettingsGroup title="Yang terdengar">
          {log.length === 0 ? (
            <SettingsItem label="Belum ada suara" sub="Mulai simulasi untuk melihat transkripnya." />
          ) : (
            <div style={{ padding: "var(--s-3)" }}>
              <ul className="sim-log" role="log" aria-live="off">
                {log.map((l) => (
                  <li key={l.id} data-kind={l.kind}>
                    <time>{l.at}</time>
                    <span>{l.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </SettingsGroup>

        <SettingsGroup
          title="Panel debug"
          note="Menampilkan angka yang dipakai untuk memutuskan, di kotak deteksi dan di bawah sini."
        >
          <SettingsField>
            <label style={{ display: "flex", alignItems: "center", gap: "var(--s-3)", minHeight: 32 }}>
              <input type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} />
              <span className="srow__label">Tampilkan detail teknis</span>
            </label>
          </SettingsField>
          {debug && (
            <SettingsField>
              <div className="sim-chips" style={{ marginBottom: "var(--s-3)" }}>
                <span className="sim-chip">inferensi {stats.ms} ms</span>
                <span className="sim-chip">objek {stats.count}</span>
                <span className="sim-chip">interval {INFERENCE_INTERVAL_MS} ms</span>
                <span className="sim-chip">model {activeModel}</span>
              </div>
              <pre className="sim-debug">
                {detections.length === 0
                  ? "— tidak ada objek relevan dalam frame —"
                  : detections
                      .map(
                        (d) =>
                          `${d.label.padEnd(11)} ${d.position.padEnd(12)} ${mode === "rupiah" ? "" : d.tier.padEnd(5)}` +
                          ` conf=${d.confidence.toFixed(2)} area=${d.areaRatio.toFixed(4)}` +
                          `${d.is_danger ? " DANGER" : ""}`
                      )
                      .join("\n")}
              </pre>
            </SettingsField>
          )}
        </SettingsGroup>
      </div>
    </>
  );
}
