"use client";

/**
 * The simulator's ears-only output, standing in for the device's AudioManager.
 *
 * Two channels, same as the hardware:
 *   chime  — a short panned blip. On the device these are pre-rendered WAVs so
 *            they play instantly and offline; here they're synthesised, which
 *            gets the same property for free and costs no download.
 *   speech — the Indonesian caption in the device's own gTTS voice. Every
 *            sentence known ahead of time is a pre-rendered clip
 *            (tools/generate_sim_audio.py → voice-manifest.json); anything else
 *            (an AI answer, a merchant name) comes from /api/tts. The phone's
 *            Web Speech is the last resort only: on many phones it has no
 *            Indonesian voice and reads the words with an English accent.
 *
 * Direction is carried by stereo panning, which is why the on-device chime is
 * worth hearing on earbuds: "orang di sebelah kiri" also *sounds* left.
 */

import { POS_KEY, caption } from "./constants";
import manifest from "./voice-manifest.json";

const PRERENDERED = new Set(Object.keys(manifest));

/** File name of a sentence. Must match tools/generate_sim_audio.py:voice_key. */
export function voiceKey(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

/** Dynamic sentences kept decoded, so a re-read QRIS code replays instantly. */
const DYNAMIC_CACHE_MAX = 30;
const PREFETCH_DELAY_MS = 8000;

export type AudioMode = "both" | "chime" | "speech";

/** Pan position per grid cell, −1 (hard left) … +1 (hard right). */
const PAN: Record<string, number> = {
  left: -0.85,
  right: 0.85,
  center: 0,
  top: 0,
  bottom: 0,
  top_left: -0.7,
  bottom_left: -0.7,
  top_right: 0.7,
  bottom_right: 0.7,
};

/** A distinct base pitch per object class so chimes stay tellable apart. */
const PITCH: Record<string, number> = {
  person: 660,
  motorcycle: 392,
  car: 330,
  bicycle: 494,
  bus: 294,
  truck: 262,
  dog: 587,
  cat: 740,
  chair: 523,
  bottle: 880,
  handbag: 784,
  backpack: 698,
};

export class SimAudio {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  mode: AudioMode = "both";
  /** Indonesian Web Speech voice, used only when no gTTS clip can be had. */
  private voice: SpeechSynthesisVoice | null = null;
  private voiceHooked = false;
  /** Pending "speak after the chime" timers, so silence() can drop them. */
  private timers = new Set<number>();
  /** Decoded clips by URL (a promise, so two asks share one download). */
  private clips = new Map<string, Promise<AudioBuffer | null>>();
  /** Sentences play one after another; an urgent one resets the queue. */
  private queue: Promise<void> = Promise.resolve();
  private playing: AudioBufferSourceNode | null = null;
  /** Bumped by every barge-in, so a sentence queued before it never plays. */
  private epoch = 0;
  private prefetched = false;

  /**
   * Must run inside a user gesture — mobile browsers start audio suspended.
   * Never waits for audio: resume() can stay pending for good on a phone, and
   * the camera must not be held up by it.
   */
  unlock(): void {
    if (!this.ctx) {
      const Ctor =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new Ctor();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.5;
      this.master.connect(this.ctx.destination);
    }
    this.wake();
    this.loadVoice();
    // Chrome fills the voice list asynchronously; hook it once, not per start.
    if (!this.voiceHooked && typeof speechSynthesis !== "undefined") {
      speechSynthesis.addEventListener?.("voiceschanged", () => this.loadVoice());
      this.voiceHooked = true;
    }
    // Wait before prefetching, so the greeting and the first announcements
    // are not stuck behind 220 downloads on a slow connection.
    if (!this.prefetched) window.setTimeout(() => this.prefetchAll(), PREFETCH_DELAY_MS);
  }

  /** Ask audio to run again; iOS also suspends it across a permission prompt. */
  wake() {
    if (this.ctx && this.ctx.state !== "running") void this.ctx.resume().catch(() => {});
  }

  private loadVoice() {
    if (typeof speechSynthesis === "undefined") return;
    const voices = speechSynthesis.getVoices();
    this.voice = voices.find((v) => v.lang?.toLowerCase().startsWith("id")) ?? null;
  }

  /**
   * Pull every pre-rendered clip (~2 MB) into the service worker's /audio/
   * cache in the background, so the simulation keeps talking offline, as the
   * page promises, even for objects it has not seen yet.
   */
  private prefetchAll() {
    if (this.prefetched || typeof fetch === "undefined") return;
    this.prefetched = true;
    const keys = [...PRERENDERED];
    const worker = async () => {
      for (let k = keys.shift(); k; k = keys.shift()) {
        if (!this.ctx) return; // simulation closed
        try {
          await fetch(`/audio/sim/${k}.mp3`);
        } catch {
          return; // offline: the rest will come on demand
        }
      }
    };
    void Promise.all([worker(), worker(), worker()]);
  }

  private clip(text: string): Promise<AudioBuffer | null> {
    const key = voiceKey(text);
    const url = PRERENDERED.has(key) ? `/audio/sim/${key}.mp3` : `/api/tts?q=${encodeURIComponent(text)}`;
    const hit = this.clips.get(url);
    if (hit) return hit;
    const p = (async () => {
      const ctx = this.ctx;
      if (!ctx) return null;
      try {
        const res = await fetch(url, { signal: AbortSignal.timeout?.(10_000) });
        if (!res.ok) return null;
        return await ctx.decodeAudioData(await res.arrayBuffer());
      } catch {
        return null;
      }
    })();
    if (!PRERENDERED.has(key)) {
      // Keep the map bounded; a failed fetch is forgotten so it can be retried.
      if (this.clips.size >= DYNAMIC_CACHE_MAX + PRERENDERED.size) this.clips.clear();
      void p.then((b) => b ?? this.clips.delete(url));
    }
    this.clips.set(url, p);
    return p;
  }

  private play(buf: AudioBuffer): Promise<void> {
    const ctx = this.ctx;
    const master = this.master;
    if (!ctx || !master) return Promise.resolve();
    return new Promise((resolve) => {
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(master);
      src.onended = () => {
        if (this.playing === src) this.playing = null;
        resolve();
      };
      this.playing = src;
      src.start();
    });
  }

  private stopSpeech() {
    this.epoch++;
    this.queue = Promise.resolve();
    try {
      this.playing?.stop();
    } catch {
      /* already ended */
    }
    this.playing = null;
    if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
  }

  /** The last resort: the phone's own voice, Indonesian if it has one. */
  private webSpeech(text: string) {
    if (typeof speechSynthesis === "undefined") return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "id-ID";
    if (this.voice) u.voice = this.voice;
    u.rate = 1.05;
    u.pitch = 1;
    speechSynthesis.speak(u);
  }

  setMode(mode: AudioMode) {
    this.mode = mode;
  }

  setVolume(v: number) {
    if (this.master) this.master.gain.value = Math.min(Math.max(v, 0), 1);
  }

  /** One panned blip. `urgent` doubles it and lifts the pitch. */
  private blip(label: string, posKey: string, urgent: boolean) {
    const ctx = this.ctx;
    const master = this.master;
    if (!ctx || !master) return;

    const base = (PITCH[label] ?? 520) * (urgent ? 1.5 : 1);
    const pan = PAN[posKey] ?? 0;
    const now = ctx.currentTime;
    const beats = urgent ? [0, 0.18] : [0];

    for (const offset of beats) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const panner = ctx.createStereoPanner?.();

      osc.type = "sine";
      osc.frequency.setValueAtTime(base, now + offset);
      // A small downward sweep reads as "a thing", not as an alarm.
      osc.frequency.exponentialRampToValueAtTime(base * 0.82, now + offset + 0.13);

      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.6, now + offset + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.15);

      osc.connect(gain);
      if (panner) {
        panner.pan.value = pan;
        gain.connect(panner);
        panner.connect(master);
      } else {
        gain.connect(master); // Safari <14.1 has no StereoPanner
      }
      osc.start(now + offset);
      osc.stop(now + offset + 0.18);
    }
  }

  /** Speak one line. `urgent` barges in, like the device's CRITICAL priority. */
  say(text: string, urgent = false) {
    if (!text) return;
    if (urgent) this.stopSpeech();
    const epoch = this.epoch;
    const clip = this.clip(text); // start downloading now, not when its turn comes
    this.queue = this.queue.then(async () => {
      const buf = await clip;
      if (epoch !== this.epoch) return;
      if (buf) await this.play(buf);
      else this.webSpeech(text);
    });
  }

  /**
   * One nav announcement: chime and/or caption, depending on the audio mode.
   * Returns the caption so the caller can show it in the transcript.
   */
  announce(label: string, cell: string, tier: string, danger: boolean): string {
    const posKey = POS_KEY[cell] ?? cell;
    const text = caption(label, cell, tier);
    const urgent = danger || tier === "near";
    if (this.mode !== "speech") this.blip(label, posKey, urgent);
    if (this.mode !== "chime") {
      // Let the chime land first so the two don't overlap into mush.
      const id = window.setTimeout(() => {
        this.timers.delete(id);
        this.say(text, urgent);
      }, this.mode === "both" ? 220 : 0);
      this.timers.add(id);
    }
    return text;
  }

  /** Cancel anything still queued (mode switch, stop button). */
  silence() {
    this.timers.forEach((id) => window.clearTimeout(id));
    this.timers.clear();
    this.stopSpeech();
  }

  close() {
    this.silence();
    try {
      this.ctx?.close();
    } catch {
      /* already closed */
    }
    this.ctx = null;
    this.master = null;
  }
}
