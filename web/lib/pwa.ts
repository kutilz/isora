"use client";

/**
 * Tiny store for the PWA install state.
 *
 * `beforeinstallprompt` fires once, early, and on whichever page happened to
 * load first — so the event has to be stashed globally rather than owned by the
 * component that eventually renders the install button. Subscribers are plain
 * callbacks so this works without a React context provider.
 */

export type InstallState = {
  /** Chromium fired beforeinstallprompt — a real install prompt is available. */
  canPrompt: boolean;
  /** Running as an installed app (standalone display mode). */
  installed: boolean;
  /** iOS Safari: no prompt API, install is a manual Share-sheet action. */
  iosSafari: boolean;
};

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

let deferred: BeforeInstallPromptEvent | null = null;
let state: InstallState = { canPrompt: false, installed: false, iosSafari: false };
const listeners = new Set<(s: InstallState) => void>();

function emit(patch: Partial<InstallState>) {
  state = { ...state, ...patch };
  listeners.forEach((fn) => fn(state));
}

export function getInstallState(): InstallState {
  return state;
}

export function subscribeInstall(fn: (s: InstallState) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    // iOS Safari's non-standard flag for home-screen apps.
    (window.navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

function detectIosSafari(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  const iOS = /iPad|iPhone|iPod/.test(ua) || (ua.includes("Macintosh") && "ontouchend" in document);
  // Chrome/Firefox on iOS are Safari underneath but cannot install.
  return iOS && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
}

/** Called once from the root layout. Safe to call more than once. */
export function initPwa() {
  if (typeof window === "undefined") return;

  emit({ installed: isStandalone(), iosSafari: detectIosSafari() });

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // keep the mini-infobar away; we render our own button
    deferred = e as BeforeInstallPromptEvent;
    emit({ canPrompt: true });
  });

  window.addEventListener("appinstalled", () => {
    deferred = null;
    emit({ canPrompt: false, installed: true });
  });

  if ("serviceWorker" in navigator) {
    // After load so the SW registration never competes with first paint. This
    // runs from a useEffect, which is usually already past `load` — waiting
    // for the event then would never register the worker at all.
    const register = () =>
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* offline support is a bonus, never a hard requirement */
      });
    if (document.readyState === "complete") void register();
    else window.addEventListener("load", () => void register(), { once: true });
  }
}

/** Show the browser's install prompt. Returns true if the user accepted. */
export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false;
  try {
    await deferred.prompt();
    const { outcome } = await deferred.userChoice;
    deferred = null;
    emit({ canPrompt: false });
    return outcome === "accepted";
  } catch {
    return false;
  }
}
