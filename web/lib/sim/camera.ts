"use client";

/**
 * Opening the phone's camera, and saying in plain Indonesian why it did not open.
 *
 * Browsers report camera failures as bare DOMException names, and the reason a
 * phone refuses is usually something the person can fix (a denied permission,
 * an app holding the camera, a link opened inside WhatsApp), so each one gets
 * its own sentence instead of the browser's English.
 */

const BACK_CAMERA: MediaStreamConstraints = {
  video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
  audio: false,
};
const ANY_CAMERA: MediaStreamConstraints = { video: true, audio: false };

/** A failure whose message is already written for the person holding the phone. */
class CameraProblem extends Error {}

/** Android WebView and the browsers built into chat and social apps. */
function inAppBrowser(): boolean {
  return /FBAN|FBAV|Instagram|WhatsApp|Line\/|TikTok|musical_ly|; wv\)/i.test(navigator.userAgent);
}

export async function openCamera(): Promise<MediaStream> {
  if (!window.isSecureContext) {
    throw new CameraProblem(
      "Browser mematikan kamera di alamat http://. Buka lewat https://isora-smartglasses.vercel.app/simulasi."
    );
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new CameraProblem(
      inAppBrowser()
        ? "Browser di dalam aplikasi ini tidak bisa membuka kamera. Buka halaman ini lewat Chrome atau Safari."
        : "Browser ini tidak mendukung akses kamera. Buka halaman ini lewat Chrome atau Safari."
    );
  }
  try {
    return await navigator.mediaDevices.getUserMedia(BACK_CAMERA);
  } catch (e) {
    // A refusal stays a refusal. Anything else can be this phone not liking the
    // requested camera or resolution, so ask once more for whatever it has.
    if (e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError")) throw e;
    return navigator.mediaDevices.getUserMedia(ANY_CAMERA);
  }
}

export function cameraErrorMessage(e: unknown): string {
  if (e instanceof CameraProblem) return e.message;
  switch (e instanceof DOMException ? e.name : "") {
    case "NotAllowedError":
    case "SecurityError":
      return inAppBrowser()
        ? "Browser di dalam aplikasi ini memblokir kamera. Buka halaman ini lewat Chrome atau Safari."
        : "Akses kamera ditolak. Izinkan kamera untuk situs ini di pengaturan browser, lalu coba lagi.";
    case "NotReadableError":
    case "AbortError":
      return "Kamera sedang dipakai aplikasi lain. Tutup aplikasi itu, lalu coba lagi.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "Tidak ada kamera yang bisa dipakai di perangkat ini.";
    default:
      return "Kamera tidak bisa dibuka. Muat ulang halaman, lalu coba lagi.";
  }
}
