/* Service worker: makes the app installable and keeps the last-seen data available offline.
   Bump VERSION to drop old caches after a change to the caching rules. */
const VERSION = "v2";
const STATIC = `static-${VERSION}`;
const PAGES = `pages-${VERSION}`;
const DATA = `data-${VERSION}`;

// Where the app is mounted: "" at a domain root, "/lottery-timesfm/app" on GitHub Pages.
const BASE = new URL(self.registration.scope).pathname.replace(/\/$/, "");

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => ![STATIC, PAGES, DATA].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    const hit = (await cache.match(request)) || (fallbackUrl && (await cache.match(fallbackUrl)));
    if (hit) return hit;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith(`${BASE}/`)) return;
  const path = url.pathname.slice(BASE.length);

  if (path.startsWith("/_next/static/") || path.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request, STATIC)); // content-hashed, never changes
  } else if (path.startsWith("/api/") || path.startsWith("/data/")) {
    event.respondWith(networkFirst(request, DATA)); // fresh when online, last-seen when not
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, PAGES, `${BASE}/powerball/`));
  } else {
    event.respondWith(networkFirst(request, PAGES));
  }
});
