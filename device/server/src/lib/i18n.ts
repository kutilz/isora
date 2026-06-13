/**
 * Minimal i18n. Bahasa Indonesia (`id`) is the default; English (`en`)
 * is loaded only if the user toggles it from A11yBar.
 *
 * Strings live in `i18n/id.json` / `i18n/en.json`. Components call
 * `t("dotted.key.path", { name: "x" })` — missing keys return the key
 * itself so they're visible during development.
 */

import id from "../i18n/id.json";
import en from "../i18n/en.json";

type Dict = Record<string, unknown>;

const DICTS: Record<string, Dict> = { id, en };
const LS_KEY = "auralai.lang";
let _lang: "id" | "en" = "id";

try {
  const saved = localStorage.getItem(LS_KEY);
  if (saved === "id" || saved === "en") _lang = saved;
} catch {
  /* ignore */
}

function lookup(dict: Dict, path: string): unknown {
  let cur: unknown = dict;
  for (const seg of path.split(".")) {
    if (cur && typeof cur === "object" && seg in (cur as Dict)) {
      cur = (cur as Dict)[seg];
    } else {
      return undefined;
    }
  }
  return cur;
}

function interp(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_m, k) =>
    k in vars ? String(vars[k]) : `{${k}}`,
  );
}

export function t(
  key: string,
  vars?: Record<string, string | number>,
): string {
  // Prefer current lang; fall back to ID if English key missing.
  let v = lookup(DICTS[_lang], key);
  if (v == null && _lang !== "id") v = lookup(DICTS.id, key);
  if (typeof v !== "string") return key;
  return interp(v, vars);
}

export function getLang(): "id" | "en" {
  return _lang;
}

export function setLang(lang: "id" | "en") {
  _lang = lang;
  try {
    localStorage.setItem(LS_KEY, lang);
  } catch {
    /* ignore */
  }
  document.documentElement.lang = lang;
  // Re-render hook: dispatch a custom event so root components can
  // useState-bump if they care. Most UI updates on next state change
  // (e.g. polling tick) anyway.
  window.dispatchEvent(new CustomEvent("auralai:langchange"));
}

// Set <html lang> on import so server rendering and SR see correct lang.
try {
  document.documentElement.lang = _lang;
} catch {
  /* ignore */
}
