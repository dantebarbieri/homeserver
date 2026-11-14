import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("./sw.js", import.meta.url), "utf8");
const types = { html: "text/html", css: "text/css", svg: "image/svg+xml",
  mjs: "text/javascript", png: "image/png", webmanifest: "application/manifest+json" };

function worker() {
  const handlers = new Map(), stores = new Map();
  let fetcher = async request => {
    const url = new URL(typeof request === "string" ? request : request.url);
    const name = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    return new Response(await readFile(new URL(`./${name}`, import.meta.url)),
      { headers: { "Content-Type": types[name.split(".").at(-1)] } });
  };
  const caches = {
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return {
        async put(key, response) { store.set(key, response); },
        async match(key) { return store.get(key)?.clone(); },
      };
    },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
  };
  const self = { location: new URL("https://chasex.example/sw.js"), skipWaiting: async () => {},
    clients: { claim: async () => {} }, addEventListener: (name, handler) => handlers.set(name, handler) };
  vm.runInNewContext(source, { self, URL, caches, fetch: (...args) => fetcher(...args), console });
  return {
    stores,
    set fetch(value) { fetcher = value; },
    async lifecycle(name) {
      let work;
      handlers.get(name)({ waitUntil(value) { work = value; } });
      await work;
    },
    async request(path, method = "GET") {
      let work;
      handlers.get("fetch")({ request: new Request(new URL(path, self.location), { method }),
        respondWith(value) { work = value; } });
      return work;
    },
  };
}

test("the installed shell opens offline but private APIs, SSO and other origins never enter its cache", async () => {
  const sw = worker();
  await sw.lifecycle("install");
  const entries = [...sw.stores.values()][0];
  assert.ok(entries.size > 10);
  for (const path of ["/api/snapshot", "/api/history?ids=cpu&seconds=120", "/metrics", "/healthz",
    "/logout", "https://auth.example/login", "/unlisted.json"]) {
    assert.equal(await sw.request(path), undefined, path);
    assert.equal(entries.has(new URL(path, "https://chasex.example").href), false);
  }
  assert.equal(await sw.request("/app.mjs", "POST"), undefined);
  sw.fetch = async () => { throw new TypeError("Offline"); };
  const response = await sw.request("/?phone=1");
  assert.match(await response.text(), /<h1>.*<span class="brand-name">ChasEx<\/span><\/h1>/);
  assert.match(await (await sw.request("/app.mjs")).text(), /setupPwa/);
});

test("authentication errors and redirected or same-origin login HTML never replace the cached application", async () => {
  const sw = worker();
  await sw.lifecycle("install");
  for (const variant of ["unauthorized", "redirect", "login"]) {
    sw.fetch = async () => {
      const response = new Response("<html>Private login form</html>",
        { status: variant === "unauthorized" ? 401 : 200, headers: { "Content-Type": "text/html" } });
      if (variant === "redirect") Object.defineProperty(response, "redirected", { value: true });
      return response;
    };
    const response = await sw.request("/");
    assert.equal(response.status, variant === "unauthorized" ? 401 : 200);
  }
  sw.fetch = async () => { throw new TypeError("Offline"); };
  const html = await (await sw.request("/")).text();
  assert.match(html, /<h1>.*<span class="brand-name">ChasEx<\/span><\/h1>/);
  assert.doesNotMatch(html, /Private login form/);
});

test("installation rejects intercepted assets and activation only removes old ChasEx caches", async () => {
  const rejected = worker();
  rejected.fetch = async () => new Response("<html>Sign in</html>", { headers: { "Content-Type": "text/html" } });
  await assert.rejects(rejected.lifecycle("install"), /offline asset unavailable/);
  const sw = worker();
  await sw.lifecycle("install");
  const [current] = sw.stores.keys();
  sw.stores.set("chasex-shell-old", new Map());
  sw.stores.set("unrelated-app", new Map());
  await sw.lifecycle("activate");
  assert.ok(!sw.stores.has("chasex-shell-old"));
  assert.ok(sw.stores.has("unrelated-app"));
  assert.ok(sw.stores.has(current));
});

test("install metadata supplies real correctly sized Apple, standard and maskable PNG icons", async () => {
  const manifest = JSON.parse(await readFile(new URL("./manifest.webmanifest", import.meta.url), "utf8"));
  const html = await readFile(new URL("./index.html", import.meta.url), "utf8");
  assert.equal(manifest.name, "ChasEx");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.scope, manifest.start_url);
  assert.match(html, /rel="manifest"[^>]+crossorigin="use-credentials"/);
  assert.match(html, /rel="apple-touch-icon" sizes="180x180" href="\.\/apple-touch-icon.png"/);
  const images = [...manifest.icons, { src: "./apple-touch-icon.png", sizes: "180x180" }];
  for (const icon of images) {
    const bytes = await readFile(new URL(icon.src, import.meta.url));
    assert.equal(bytes.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
    assert.equal(`${bytes.readUInt32BE(16)}x${bytes.readUInt32BE(20)}`, icon.sizes);
  }
  assert.ok(manifest.icons.some(icon => icon.purpose === "maskable"));
  assert.ok(manifest.icons.some(icon => icon.sizes === "192x192" && icon.purpose === "any"));
  assert.ok(manifest.icons.some(icon => icon.sizes === "512x512" && icon.purpose === "any"));
});
