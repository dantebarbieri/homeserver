/* Classic, not module: browsers fetch module service-worker scripts without cookies,
   so Authelia would redirect them and registration fails. npm run build:atlas keeps
   this copy of atlas.mjs's MAP_FILES current. */
const MAP_FILES = {"110m":"/world-110m-308dfeb0b90b.json","50m":"/world-50m-c4ac46bd8d55.json","10m":"/world-10m-d597e8ffe7d8.json"};

/* Public static assets only. Navigation authenticates; APIs never enter a cache. */
const CACHE = "attacks-shell-v9";
const MAP_CACHE = "attacks-maps-v1";
const ASSETS = ["/", "/styles.css", "/app.mjs", "/model.mjs", "/map-view.mjs", "/globe.mjs",
  "/atlas.mjs", "/geo-vendor.mjs", "/geo-vendor-LICENSE.txt", "/pwa.mjs",
  "/flags.woff2", "/flags-LICENSE.txt", "/favicon.svg", "/apple-touch-icon.png",
  "/icon-192.png", "/icon-512.png", "/manifest.webmanifest"];
const allowed = new Set(ASSETS);
const maps = new Set(Object.values(MAP_FILES));
const cacheFirst = new Set(["/flags.woff2", "/flags-LICENSE.txt", "/favicon.svg",
  "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png"]);

function cacheable(response) {
  return response.ok && !response.redirected && response.type === "basic"
    && response.headers.get("X-Attacks-Asset") === "1";
}

async function reportCacheError(error) {
  console.warn("Attacks static cache update failed:", error);
  for (const client of await self.clients.matchAll()) client.postMessage({type: "attacks-cache-error"});
}

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(ASSETS.map(async path => {
      const response = await fetch(path, {credentials: "same-origin", cache: "no-store", redirect: "error"});
      if (!cacheable(response)) throw new Error("Static asset unavailable or authentication required");
      await cache.put(path, response);
    }));
    const atlas = await caches.open(MAP_CACHE);
    const overview = MAP_FILES["110m"];
    if (!await atlas.match(overview)) {
      const response = await fetch(overview, {credentials: "same-origin", cache: "force-cache", redirect: "error"});
      if (!cacheable(response)) throw new Error("Overview map unavailable");
      await atlas.put(overview, response);
    }
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name.startsWith("attacks-shell-") && name !== CACHE) await caches.delete(name);
    const atlas = await caches.open(MAP_CACHE);
    for (const request of await atlas.keys()) if (!maps.has(new URL(request.url).pathname)) await atlas.delete(request);
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url), isMap = maps.has(url.pathname);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || (!allowed.has(url.pathname) && !isMap)) return;
  event.respondWith((async () => {
    const cacheName = isMap ? MAP_CACHE : CACHE;
    if (isMap || cacheFirst.has(url.pathname)) {
      const cached = await caches.match(url.pathname, {cacheName});
      if (cached) return cached;
    }
    let response;
    try {
      // HTML always checks authentication; only a network failure uses the offline shell.
      response = await fetch(event.request);
    } catch (error) {
      const cached = await caches.match(url.pathname, {cacheName});
      if (cached) return cached;
      throw error;
    }
    if (cacheable(response)) {
      const copy = response.clone();
      event.waitUntil(caches.open(cacheName).then(cache => cache.put(url.pathname, copy)).catch(reportCacheError));
    }
    return response;
  })());
});
