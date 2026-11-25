import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import {MAP_FILES} from "./atlas.mjs";

async function worker(fetch, cachedMaps = []) {
  const handlers = {}, puts = [], messages = [];
  const cached = {body: "public static shell"};
  const stores = new Map([
    ["attacks-shell-v20", new Map(["/", "/globe.mjs", "/globe-draw.mjs", "/geo-vendor.mjs"].map(path => [path, cached]))],
    ["attacks-maps-v1", new Map(cachedMaps.map(path => [path, cached]))],
  ]);
  const open = async name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const data = stores.get(name);
    return {
      put: async (path, response) => { puts.push([path, response]); data.set(path, response); },
      match: async path => data.get(path),
      keys: async () => [...data.keys()].map(path => ({url: new URL(path, "https://attacks.test").href})),
      delete: async request => data.delete(new URL(request.url).pathname),
    };
  };
  const context = {
    URL, Set, Promise, Error, console, fetch,
    self: {location: {origin: "https://attacks.test"}, addEventListener: (name, handler) => { handlers[name] = handler; },
      skipWaiting: async () => {},
      clients: {claim: async () => {}, matchAll: async () => [{postMessage: value => messages.push(value)}]}},
    caches: {open, match: async (path, {cacheName}) => stores.get(cacheName)?.get(path),
      keys: async () => [...stores.keys()], delete: async name => stores.delete(name)},
  };
  const source = await readFile(new URL("./sw.js", import.meta.url), "utf8");
  // Runs as a classic script: an import statement would fail here, as in the browser.
  const maps = vm.runInNewContext(`${source}\n;MAP_FILES`, context);
  async function request(path, method = "GET") {
    let response;
    const waits = [];
    handlers.fetch({request: {url: new URL(path, "https://attacks.test").href, method},
      respondWith: value => { response = value; }, waitUntil: value => waits.push(value)});
    const result = await response;
    await Promise.all(waits);
    return result;
  }
  async function install() {
    let result;
    handlers.install({waitUntil: promise => { result = promise; }});
    await result;
  }
  return {request, puts, cached, messages, install, maps};
}

test("service worker registers as a classic script whose map list matches the atlas", async () => {
  const sw = await worker(async () => {});
  assert.deepEqual({...sw.maps}, {...MAP_FILES});
  // Module worker scripts are fetched without cookies, so Authelia redirects them.
  const pwa = await readFile(new URL("./pwa.mjs", import.meta.url), "utf8");
  assert.match(pwa, /serviceWorker\.register\("\/sw\.js"/);
  assert.doesNotMatch(pwa, /type:\s*"module"/);
});

test("service worker never handles API data, health responses, other origins or writes", async () => {
  let fetches = 0;
  const sw = await worker(async () => { fetches++; });
  for (const path of ["/api/events?ip=8.8.8.8", "/api/stats", "/api/status", "/healthz", "https://other.test/"])
    assert.equal(await sw.request(path), undefined);
  assert.equal(await sw.request("/", "POST"), undefined);
  assert.equal(fetches, 0);
  assert.equal(sw.puts.length, 0);
});

test("offline shell fallback never replaces an authentication response or caches a redirect", async () => {
  const unauthorized = {ok: false, status: 401};
  const denied = await worker(async () => unauthorized);
  assert.equal(await denied.request("/"), unauthorized);
  assert.equal(denied.puts.length, 0);
  const redirect = {ok: true, redirected: true, type: "basic"};
  const redirected = await worker(async () => redirect);
  assert.equal(await redirected.request("/"), redirect);
  assert.equal(redirected.puts.length, 0);
  const offline = await worker(async () => { throw new TypeError("Network unavailable"); });
  assert.equal(await offline.request("/"), offline.cached);
  for (const path of ["/globe.mjs", "/globe-draw.mjs", "/geo-vendor.mjs"])
    assert.equal(await offline.request(path), offline.cached);
  const asset = {ok: true, redirected: false, type: "basic", headers: new Map([["X-Attacks-Asset", "1"]])};
  asset.clone = () => asset;
  const online = await worker(async () => asset);
  assert.equal(await online.request("/styles.css"), asset);
  assert.equal(online.puts.length, 1);
});

test("only overview borders are precached; detailed maps fetch once and then work offline", async () => {
  const fetched = [], asset = {ok: true, redirected: false, type: "basic", headers: new Map([["X-Attacks-Asset", "1"]])};
  asset.clone = () => asset;
  const sw = await worker(async request => { fetched.push(typeof request === "string" ? request : new URL(request.url).pathname); return asset; });
  await sw.install();
  assert.deepEqual(fetched.filter(path => path.startsWith("/world-")), [MAP_FILES["110m"]]);
  assert.equal(await sw.request(MAP_FILES["10m"]), asset);
  assert.equal(await sw.request(MAP_FILES["10m"]), asset);
  assert.equal(fetched.filter(path => path === MAP_FILES["10m"]).length, 1);
  const offline = await worker(async () => { throw new Error("Offline"); }, [MAP_FILES["110m"]]);
  assert.equal(await offline.request(MAP_FILES["110m"]), offline.cached);
  await assert.rejects(offline.request(MAP_FILES["10m"]), /Offline/);
});
