import { useEffect, useState } from "preact/hooks";

/**
 * Asset + chime detection — handoff §8.5.
 *
 * On any page load, fetch both manifests once. Components consult the
 * cached lists to decide:
 *   - Whether to render an <img> from /assets/X.jpg or fall back to a
 *     SVG mockup.
 *   - Whether the "Putar chime" button should be active or hidden.
 *
 * Network failure or missing endpoints fall back to empty lists, so a
 * fresh device with no assets/ folder still renders the full mockup
 * experience.
 */

export interface Manifests {
  chimes: string[]; // bare filenames, e.g. ["boot.wav", "obstacle.wav"]
  assets: string[]; // bare filenames, e.g. ["glasses_front.jpg"]
}

let _cache: Manifests | null = null;
let _inflight: Promise<Manifests> | null = null;

export async function loadManifests(): Promise<Manifests> {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  _inflight = Promise.all([
    fetch("/audio/chimes/manifest.json")
      .then((r) => (r.ok ? r.json() : { chimes: [] }))
      .catch(() => ({ chimes: [] })),
    fetch("/assets/manifest.json")
      .then((r) => (r.ok ? r.json() : { assets: [] }))
      .catch(() => ({ assets: [] })),
  ]).then(([c, a]) => {
    _cache = {
      chimes: Array.isArray(c.chimes) ? c.chimes : [],
      assets: Array.isArray(a.assets) ? a.assets : [],
    };
    return _cache;
  });
  return _inflight;
}

export function useManifests(): Manifests {
  const [m, setM] = useState<Manifests>(_cache || { chimes: [], assets: [] });
  useEffect(() => {
    let alive = true;
    loadManifests().then((v) => {
      if (alive) setM(v);
    });
    return () => {
      alive = false;
    };
  }, []);
  return m;
}

export function hasChime(m: Manifests, id: string): boolean {
  return m.chimes.includes(`${id}.wav`);
}

export function hasAsset(m: Manifests, name: string): boolean {
  return m.assets.includes(name);
}
