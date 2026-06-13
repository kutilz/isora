import { useEffect, useState, useRef } from "preact/hooks";
import { apiGet } from "./api";

/**
 * usePolling — fetches `path` every `intervalMs`. Pauses when the tab
 * loses focus to save battery + device CPU. Returns the latest payload
 * plus a simple `online` flag derived from fetch success/failure.
 *
 * Used by /status (1000 ms), /snapshot (500 ms — but for snapshot we
 * pull as raw bytes; see useSnapshotUrl), /history (5000 ms).
 */
export function usePolling<T>(path: string, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [online, setOnline] = useState<boolean>(true);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    let timer: number | undefined;
    let visible = !document.hidden;

    const tick = async () => {
      if (!aliveRef.current) return;
      if (visible) {
        try {
          const j = await apiGet<T>(path);
          if (aliveRef.current) {
            setData(j);
            setOnline(true);
          }
        } catch {
          if (aliveRef.current) setOnline(false);
        }
      }
      if (aliveRef.current) {
        timer = window.setTimeout(tick, intervalMs);
      }
    };

    const onVis = () => {
      visible = !document.hidden;
    };
    document.addEventListener("visibilitychange", onVis);

    tick();
    return () => {
      aliveRef.current = false;
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [path, intervalMs]);

  return { data, online };
}

/**
 * useSnapshotUrl — returns a URL that updates every `intervalMs` with a
 * cache-busted querystring so the <img> reloads. Cheaper than fetching
 * the bytes through JS and creating object URLs.
 */
export function useSnapshotUrl(intervalMs: number = 500) {
  const [url, setUrl] = useState<string>(`/snapshot?t=${Date.now()}`);
  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) setUrl(`/snapshot?t=${Date.now()}`);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return url;
}
