// Versi digital Manual Book I-SORA — tujuan QR di buku cetak (/buku).
// Teks: content/buku.json. Audio: content/buku-audio.json + public/buku-audio/,
// keduanya dibuat oleh tools/generate_buku_audio.py dari teks yang sama.
import book from "@/content/buku.json";
import audio from "@/content/buku-audio.json";

export type Block =
  | { p: string }
  | { h: string }
  | { note: string }
  | { ul: string[] }
  | { ol: [string, string][] }
  | { dl: [string, string][] }
  | { table: { head: string[]; rows: string[][] } }
  | { contact: true };

export type Chapter = { id: string; num: number; title: string; blocks: Block[] };
export type Part = { id: string; title: string; from: number; to: number };
export type Marker = { id: string; title: string; start: number };

export const BUKU = book as unknown as {
  title: string;
  subtitle: string;
  parts: Part[];
  chapters: Chapter[];
  contact: { email: string; instagram: string; youtube: string };
};

export const BUKU_AUDIO = audio as { src: string; duration: number; markers: Marker[] };

export function formatTime(s: number): string {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}

/** "4 menit" — for a screen reader, "4:02" is read as a clock time. */
export function spokenMinutes(s: number): string {
  const m = Math.max(1, Math.round(s / 60));
  return `${m} menit`;
}
