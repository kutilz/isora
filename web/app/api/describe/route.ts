import { NextResponse } from "next/server";
import { DESCRIBE_HOURS_LABEL, describeIsOpen } from "@/lib/sim/hours";

export const runtime = "nodejs";
export const maxDuration = 30;

/**
 * "Jelaskan sekitar" for the simulator, so visitors need no API key of their own.
 *
 *   POST { image: "data:image/jpeg;base64,..." } → { text }
 *
 * SIM_OPENAI_API_KEY stays on the server. A public page can reach this route, so
 * what the key can buy is fixed here and not by the caller: this prompt, this
 * model, a low-detail image, a short answer, and only during the opening hours.
 *
 * The prompt is a condensed version of the device's pack
 * (device/utils/scene_prompt.py): same priority ladder and the same "every object
 * must carry a describing detail" rule. The device's pack is the authority.
 */

const MODEL = "gpt-4o-mini";
const MAX_IMAGE_CHARS = 400_000;
const OPENAI_TIMEOUT_MS = 18_000;
const IP_LIMIT_PER_MIN = 20;

const PROMPT = [
  "Berperanlah sebagai mata untuk pengguna tunanetra di Indonesia. Jawab dalam bahasa Indonesia lisan,",
  "maksimal dua kalimat, langsung ke isinya tanpa basa-basi.",
  "URUTAN PRIORITAS: kalau ada benda yang dipegang atau disodorkan ke kamera, sebut hanya benda itu",
  "beserta angka atau tulisan yang terbaca padanya. Kalau tidak ada, sebut bahaya atau hambatan lebih",
  "dulu, lalu orang, lalu isi ruangan.",
  "SETIAP BENDA WAJIB BERCIRI: untuk orang sebut warna dan jenis pakaian lalu barang yang dipegang;",
  "untuk benda lain sebut jenis, warna, lalu tulisan atau angka yang terbaca.",
  "Kalau satu ciri tidak pasti, turunkan ke kata yang pasti benar, jangan hapus bendanya.",
  "Sebut arah dengan kiri, depan, atau kanan. Jangan menebak yang tidak terlihat.",
  "Jangan menyapa pengguna: jangan pakai kata kamu, anda, atau akhiran -mu.",
].join(" ");

// Per server instance, so it only blunts a burst; the opening hours are the real limit.
const recent = new Map<string, number[]>();

function overLimit(ip: string, now: number): boolean {
  if (recent.size > 2000) recent.clear();
  const hits = (recent.get(ip) ?? []).filter((t) => now - t < 60_000);
  hits.push(now);
  recent.set(ip, hits);
  return hits.length > IP_LIMIT_PER_MIN;
}

function fail(code: string, message: string, status: number) {
  return NextResponse.json({ error: code, message }, { status, headers: { "Cache-Control": "no-store" } });
}

export async function POST(req: Request) {
  if (!describeIsOpen()) {
    return fail("outside_hours", `Jelaskan sekitar hanya aktif pukul ${DESCRIBE_HOURS_LABEL}.`, 403);
  }

  // Keeps other websites from spending the key through a visitor's browser.
  const origin = req.headers.get("origin");
  if (origin && new URL(origin).host !== req.headers.get("host")) {
    return fail("forbidden", "Permintaan ditolak.", 403);
  }

  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  if (overLimit(ip, Date.now())) {
    return fail("rate_limited", "Terlalu banyak permintaan. Tunggu sebentar, lalu coba lagi.", 429);
  }

  const key = process.env.SIM_OPENAI_API_KEY?.trim();
  if (!key) return fail("unavailable", "Layanan AI belum siap.", 503);

  const raw = await req.text();
  if (raw.length > MAX_IMAGE_CHARS) return fail("too_large", "Gambar terlalu besar.", 413);
  let image: unknown;
  try {
    image = (JSON.parse(raw) as { image?: unknown }).image;
  } catch {
    return fail("bad_request", "Permintaan tidak valid.", 400);
  }
  if (typeof image !== "string" || !image.startsWith("data:image/jpeg;base64,")) {
    return fail("bad_request", "Permintaan tidak valid.", 400);
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), OPENAI_TIMEOUT_MS);
  try {
    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 200,
        messages: [
          {
            role: "user",
            content: [
              { type: "text", text: PROMPT },
              { type: "image_url", image_url: { url: image, detail: "low" } },
            ],
          },
        ],
      }),
    });
    if (!res.ok) {
      // OpenAI's own message can quote part of the key, so it stays in the server log.
      console.error("describe: OpenAI answered", res.status);
      return fail("upstream", "Layanan AI sedang bermasalah. Coba lagi.", 502);
    }
    const data = (await res.json()) as { choices?: { message?: { content?: string } }[] };
    const text = data.choices?.[0]?.message?.content?.trim();
    return NextResponse.json(
      { text: text || "Tidak ada hasil yang bisa dibacakan." },
      { headers: { "Cache-Control": "no-store" } }
    );
  } catch {
    return fail("upstream", "Layanan AI sedang bermasalah. Coba lagi.", 502);
  } finally {
    clearTimeout(timer);
  }
}
