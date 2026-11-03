import { NextResponse } from "next/server";

export const runtime = "nodejs";

/**
 * Indonesian speech for the simulator's sentences that can't be rendered ahead
 * of time (an AI scene description, a QRIS merchant name). Same voice as the
 * device and as tools/generate_sim_audio.py: Google Translate's TTS, which is
 * what gTTS calls. The phone's own Web Speech often falls back to an English
 * voice, so it is only the last resort in lib/sim/audio.ts.
 *
 *   GET ?q=<text>  → audio/mpeg
 *
 * The answer depends only on the text, so the CDN may keep it for a long time.
 */

const MAX_TEXT = 600;
// Google rejects a request over ~200 characters; gTTS splits at the same size.
const CHUNK = 180;

function chunks(text: string): string[] {
  const out: string[] = [];
  let rest = text.replace(/\s+/g, " ").trim();
  while (rest.length > CHUNK) {
    const head = rest.slice(0, CHUNK);
    // Prefer ending a chunk at a sentence, then a comma, then a space.
    const cut = Math.max(head.lastIndexOf(". "), head.lastIndexOf("? "), head.lastIndexOf("! "));
    const at =
      cut > CHUNK / 3 ? cut + 1 : head.lastIndexOf(", ") > CHUNK / 3 ? head.lastIndexOf(", ") + 1 : head.lastIndexOf(" ");
    const end = at > 0 ? at : CHUNK;
    out.push(rest.slice(0, end).trim());
    rest = rest.slice(end).trim();
  }
  if (rest) out.push(rest);
  return out;
}

async function speak(part: string, signal: AbortSignal): Promise<ArrayBuffer> {
  const url =
    "https://translate.google.com/translate_tts?ie=UTF-8&tl=id&client=tw-ob&q=" + encodeURIComponent(part);
  const res = await fetch(url, {
    signal,
    headers: { "User-Agent": "Mozilla/5.0", Referer: "https://translate.google.com/" },
  });
  if (!res.ok) throw new Error(`tts ${res.status}`);
  return res.arrayBuffer();
}

export async function GET(req: Request) {
  const q = new URL(req.url).searchParams.get("q")?.trim() ?? "";
  if (!q || q.length > MAX_TEXT) {
    return NextResponse.json({ error: "q wajib diisi, maksimal 600 karakter" }, { status: 400 });
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 10_000);
  try {
    // MP3 frames concatenate cleanly, so the pieces are simply joined.
    const parts = await Promise.all(chunks(q).map((p) => speak(p, ctrl.signal)));
    const body = new Uint8Array(parts.reduce((n, p) => n + p.byteLength, 0));
    let at = 0;
    for (const p of parts) {
      body.set(new Uint8Array(p), at);
      at += p.byteLength;
    }
    return new Response(body, {
      headers: {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "public, max-age=86400, s-maxage=2592000, immutable",
      },
    });
  } catch {
    return NextResponse.json({ error: "layanan suara tidak tersedia" }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }
}
