/**
 * A11y preference store — high-contrast, large-type, reduced-motion.
 * Persisted to localStorage with the keys spec'd in handoff §9.
 *
 * Applied by toggling data-* attrs on <html>; matching CSS in tokens.css
 * does the rest (no per-component logic).
 */

const KEYS = {
  contrast: "auralai.a11y.contrast",
  bigType:  "auralai.a11y.bigType",
  motion:   "auralai.a11y.reduceMotion",
} as const;

export interface A11yState {
  highContrast: boolean;
  largeType: boolean;
  reduceMotion: boolean;
}

function readBool(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeBool(key: string, v: boolean) {
  try {
    if (v) localStorage.setItem(key, "1");
    else localStorage.removeItem(key);
  } catch {
    /* swallow */
  }
}

export function loadA11y(): A11yState {
  return {
    highContrast: readBool(KEYS.contrast),
    largeType:    readBool(KEYS.bigType),
    reduceMotion: readBool(KEYS.motion),
  };
}

export function applyA11y(state: A11yState) {
  const html = document.documentElement;
  if (state.highContrast) html.setAttribute("data-contrast", "high");
  else                    html.removeAttribute("data-contrast");
  if (state.largeType)    html.setAttribute("data-type", "large");
  else                    html.removeAttribute("data-type");
  if (state.reduceMotion) html.setAttribute("data-motion", "reduce");
  else                    html.removeAttribute("data-motion");
}

export function saveA11y(state: A11yState) {
  writeBool(KEYS.contrast, state.highContrast);
  writeBool(KEYS.bigType,  state.largeType);
  writeBool(KEYS.motion,   state.reduceMotion);
  applyA11y(state);
}

/** Call once at app bootstrap to restore the user's preferences. */
export function bootstrapA11y(): A11yState {
  const s = loadA11y();
  applyA11y(s);
  return s;
}
