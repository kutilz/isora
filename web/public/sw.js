/* I-Sora service worker.
 *
 * Goal: the simulator keeps working with no internet, because that is the
 * promise the device itself makes ("tetap berfungsi penuh secara offline").
 * Everything else degrades politely.
 *
 * Strategies
 *   navigation        → network-first, fall back to cache, then /offline
 *   /_next/static, /icons, /audio, /models
 *                     → cache-first (immutable build output & media)
 *   TFJS model files  → cache-first, kept in their own bucket so a page
 *                       version bump doesn't force a 6 MB re-download
 *   /api/*            → never cached (auth + live device state)
 */

const VERSION = "isora-v1";
const SHELL = `${VERSION}-shell`;
const STATIC = `${VERSION}-static`;
const MODELS = "isora-models"; // deliberately unversioned — see header

const SHELL_URLS = [
  "/offline",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon.svg",
];

// Where @tensorflow-models/coco-ssd fetches its weights from.
const MODEL_HOSTS = ["storage.googleapis.com", "tfhub.dev", "www.kaggle.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      // addAll is all-or-nothing; one missing file must not abort the install.
      .then((c) => Promise.allSettled(SHELL_URLS.map((u) => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== SHELL && k !== STATIC && k !== MODELS)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

/** Cache-first with a background refresh; `cacheName` isolates the bucket. */
async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res && (res.status === 200 || res.type === "opaque")) {
    cache.put(request, res.clone());
  }
  return res;
}

/** Network-first; on failure serve the cached copy, then the offline page. */
async function navigationHandler(request) {
  const cache = await caches.open(SHELL);
  try {
    const res = await fetch(request);
    if (res && res.ok) cache.put(request, res.clone());
    return res;
  } catch {
    const hit = await cache.match(request);
    if (hit) return hit;
    const offline = await cache.match("/offline");
    if (offline) return offline;
    return new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }

  // Live data must never come from a cache.
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) return;

  // Model weights: their own long-lived bucket.
  if (MODEL_HOSTS.includes(url.hostname)) {
    event.respondWith(cacheFirst(request, MODELS));
    return;
  }

  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(navigationHandler(request));
    return;
  }

  if (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname.startsWith("/audio/") ||
    url.pathname.startsWith("/models/")
  ) {
    event.respondWith(cacheFirst(request, STATIC));
  }
});
