"use client";

/**
 * "Jelaskan sekitar" — the simulator's stand-in for the device's Context mode.
 *
 * Unlike the device, which holds its own key, the simulator is opened by people
 * who have no key at all, so the frame goes to /api/describe and the shared key
 * stays on the server. The prompt lives there too.
 */

/** Grab the current frame as a JPEG data URL, downscaled to keep the call cheap. */
export function frameToJpeg(video: HTMLVideoElement, maxWidth = 768): string {
  const scale = Math.min(1, maxWidth / (video.videoWidth || maxWidth));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round((video.videoWidth || maxWidth) * scale);
  canvas.height = Math.round((video.videoHeight || maxWidth) * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.72);
}

/** A refusal from /api/describe, with a message written for the person. */
export class DescribeError extends Error {
  constructor(
    message: string,
    readonly code: string
  ) {
    super(message);
  }
}

export async function describeScene(video: HTMLVideoElement, signal: AbortSignal): Promise<string> {
  const image = frameToJpeg(video);
  if (!image) throw new DescribeError("Tidak bisa mengambil gambar dari kamera.", "no_frame");
  const res = await fetch("/api/describe", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image }),
  });
  const data = (await res.json().catch(() => ({}))) as { text?: string; error?: string; message?: string };
  if (!res.ok) throw new DescribeError(data.message || "Gagal menjelaskan sekitar.", data.error || "failed");
  return data.text || "Tidak ada hasil yang bisa dibacakan.";
}

/** Earlier versions asked for a personal key and kept it here; do not keep it any longer. */
export function forgetStoredKey() {
  try {
    localStorage.removeItem("isora.sim.key");
    localStorage.removeItem("isora.sim.provider");
  } catch {
    /* storage blocked: there is nothing to forget */
  }
}
