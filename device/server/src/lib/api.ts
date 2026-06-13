/**
 * Tiny HTTP helper for the device API. Auto-injects X-Auth-Token from
 * localStorage["aural_token"], identical convention to the legacy
 * dashboard.js so a single token works across both UIs.
 *
 * Returns the parsed JSON (or null on 204/empty). Throws on non-2xx so
 * callers can `.catch()` for error UI.
 */

const TOKEN_KEY = "aural_token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(t: string): void {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* localStorage disabled — quietly skip */
  }
}

/**
 * If we don't have a token yet and we're loaded from the device itself,
 * grab one via /auth/token (localhost-only endpoint). Returns the token
 * or empty string.
 */
export async function ensureToken(): Promise<string> {
  let t = getToken();
  if (t) return t;
  try {
    const res = await fetch("/auth/token");
    if (!res.ok) return "";
    const json = await res.json();
    t = json.token || "";
    if (t) setToken(t);
  } catch {
    /* swallow */
  }
  return t;
}

export interface ApiOptions extends RequestInit {
  /** Skip auth header even on mutate calls (rarely useful). */
  noAuth?: boolean;
}

export async function api<T = unknown>(
  path: string,
  opts: ApiOptions = {},
): Promise<T> {
  const headers = new Headers(opts.headers || {});
  if (!opts.noAuth) {
    const t = getToken();
    if (t) headers.set("X-Auth-Token", t);
  }
  if (opts.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let serverMsg = res.statusText;
    try {
      const j = await res.json();
      serverMsg = j.error || j.message || serverMsg;
    } catch {
      /* ignore */
    }
    // Indonesian-friendly mapping for the codes pendamping will actually
    // see in the wizard. Keep the raw status/message in .cause for devs.
    const friendly =
      res.status === 401
        ? "Belum tersambung ke kacamata. Coba muat ulang halaman ini."
        : res.status === 403
          ? "Akses ditolak oleh kacamata. Coba muat ulang halaman ini."
          : res.status === 404
            ? "Halaman atau data tidak ditemukan di kacamata."
            : res.status >= 500
              ? "Kacamata sedang bermasalah. Coba lagi sebentar."
              : `${res.status} ${serverMsg}`;
    const err = new Error(friendly);
    (err as Error & { cause?: unknown }).cause = `${res.status} ${serverMsg}`;
    throw err;
  }
  if (res.status === 204) return null as T;
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("json")) return (await res.text()) as unknown as T;
  return (await res.json()) as T;
}

// Convenience wrappers — keep call sites short.
export const apiGet = <T = unknown>(p: string) => api<T>(p);
export const apiPost = <T = unknown>(p: string, body: unknown) =>
  api<T>(p, { method: "POST", body: JSON.stringify(body) });
