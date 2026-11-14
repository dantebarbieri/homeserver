const CACHE = "chasex-shell-v5";
const assets = new Map([
  ["index.html", "text/html"], ["styles.css", "text/css"], ["favicon.svg", "image/svg+xml"],
  ["manifest.webmanifest", "application/manifest+json"],
  ...["app.mjs", "board.mjs", "model.mjs", "metric-model.mjs", "metrics.mjs",
    "live-data.mjs", "linux-snapshot.mjs", "mobile-ui.mjs", "pwa.mjs", "services.mjs", "service-model.mjs"].map(name => [name, "javascript"]),
  ...["icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"].map(name => [name, "image/png"]),
].map(([name, type]) => [new URL(name, self.location.href).href, type]));
const home = new URL("./", self.location.href).href;
const index = new URL("index.html", self.location.href).href;

async function cacheable(response, type) {
  if (!response.ok || response.redirected || ["opaque", "opaqueredirect"].includes(response.type) ||
      !(response.headers.get("Content-Type") ?? "").includes(type)) return false;
  if (type !== "text/html") return true;
  const html = await response.clone().text();
  return html.includes('<meta name="atlas-data"') && html.includes('id="board-view"');
}

self.addEventListener("install", event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  await Promise.all([...assets].map(async ([url, type]) => {
    const response = await fetch(url, { credentials: "same-origin", cache: "reload" });
    if (!await cacheable(response, type)) throw new Error(`ChasEx offline asset unavailable: ${new URL(url).pathname}`);
    await cache.put(url, response);
  }));
  await self.skipWaiting();
})()));

self.addEventListener("activate", event => event.waitUntil((async () => {
  await Promise.all((await caches.keys()).filter(key => key.startsWith("chasex-shell-") && key !== CACHE)
    .map(key => caches.delete(key)));
  await self.clients.claim();
})()));

self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  url.search = "";
  url.hash = "";
  const key = url.href === home ? index : url.href;
  // Only public application files belong here, never telemetry or SSO responses.
  if (!assets.has(key)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    let response;
    try {
      response = await fetch(request);
    } catch (error) {
      const saved = await cache.match(key);
      if (saved) return saved;
      throw error;
    }
    if (await cacheable(response, assets.get(key))) {
      try {
        await cache.put(key, response.clone());
      } catch (error) {
        console.warn("ChasEx offline cache write failed", error);
      }
    }
    return response;
  })());
});
