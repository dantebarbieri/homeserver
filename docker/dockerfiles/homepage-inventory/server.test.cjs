const assert = require("node:assert/strict");
const { once } = require("node:events");
const { test } = require("node:test");
const { archiveText, containerInfo, createServer, dockerRequest, imageVersion, InventoryError } = require("./server.cjs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs/promises");

const id = `sha256:${"a".repeat(64)}`;
const now = Date.parse("2026-10-25T02:00:00Z");
const container = {
  Image: id,
  Config: { Env: ["PRIVATE_SECRET=do-not-return"], Labels: { "com.docker.compose.project": "compose" } },
  State: { Running: true, Status: "running", StartedAt: "2026-10-23T00:30:00Z" },
};
const image = { Id: id, Config: { Env: ["PRIVATE_SECRET=do-not-return"], Labels: {} } };
const copy = (value) => structuredClone(value);

function tar(filename, text, type = "0") {
  const data = Buffer.from(text);
  const header = Buffer.alloc(512);
  header.write(filename, 0, 100);
  header.write(data.length.toString(8).padStart(11, "0") + "\0", 124, 12);
  header.write(type, 156, 1);
  return Buffer.concat([header, data, Buffer.alloc((512 - data.length % 512) % 512), Buffer.alloc(1024)]);
}

async function fixture(t, options = {}) {
  const calls = [];
  const errors = [];
  const server = createServer({
    now: () => now,
    requestDocker: async (url) => {
      calls.push(url);
      if (url.startsWith("/containers/")) return copy(container);
      if (url.startsWith("/images/")) return copy(image);
      if (url === "/version") return { Version: "29.9.1" };
      throw new Error("Unexpected request");
    },
    logError: (message) => errors.push(message),
    ...options,
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise((resolve) => {
    server.closeAllConnections();
    server.close(resolve);
  }));
  return { request: (url, init) => fetch(`http://127.0.0.1:${server.address().port}${url}`, init), calls, errors };
}

test("returns version and uptime rows without redundant state or unconfigured health", async (t) => {
  const { request, calls } = await fixture(t);
  const response = await request("/containers/it-tools");
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), {
    items: [{ label: "App / Build", value: "Image aaaaaaaaaaaa" }, { label: "Container Up", value: "2d 1h" }],
  });
  assert.deepEqual(calls, ["/containers/it-tools/json", `/images/${id}/json`]);
});

test("shows healthy, unhealthy, and starting only when Docker reports them", () => {
  for (const status of ["healthy", "unhealthy", "starting"]) {
    const value = copy(container);
    value.Config.Healthcheck = { Test: ["CMD", "true"] };
    value.State.Health = { Status: status, Log: [{ Output: "do-not-return" }] };
    assert.deepEqual(containerInfo(value, "1.2.3", now).items.at(-1), { label: "Health", value: status });
  }
});

test("stopped Hytale does not retain stale healthy status or claim uptime", () => {
  const value = copy(container);
  value.Config.Healthcheck = { Test: ["CMD", "true"] };
  value.State = { Running: false, Status: "exited", Health: { Status: "healthy" } };
  assert.deepEqual(containerInfo(value, "Wrapper 1.1.0", now), {
    items: [
      { label: "App / Build", value: "Wrapper 1.1.0" }, { label: "Container Up", value: "-" },
      { label: "Health", value: "Not running" },
    ],
  });
});

test("formats seconds, minutes and hours without claiming application uptime", () => {
  for (const [seconds, expected] of [[0, "0s"], [35, "35s"], [90, "1m"], [7500, "2h 5m"]]) {
    const value = copy(container);
    value.State.StartedAt = new Date(now - seconds * 1000).toISOString();
    assert.equal(containerInfo(value, "1", now).items[1].value, expected);
  }
});

test("uses explicitly verified application labels, not inherited Ubuntu versions", () => {
  const value = copy(image);
  value.Config.Labels["org.opencontainers.image.version"] = "24.04";
  for (const name of ["storyteller", "komga", "komf", "whisperasr", "satisfactory-server"]) {
    assert.equal(imageVersion(name, value), "Image aaaaaaaaaaaa");
  }
  value.Config.Labels["org.opencontainers.image.version"] = "2.11.0";
  assert.equal(imageVersion("aurral", value), "2.11.0");
  assert.equal(imageVersion("hytale-server", value), "Wrapper 2.11.0");
});

test("does not label a moving branch or latest tag as a version", () => {
  for (const version of ["latest", "main", "master"]) {
    const value = copy(image);
    value.Config.Labels["org.opencontainers.image.version"] = version;
    assert.equal(imageVersion("aurral", value), "Image aaaaaaaaaaaa");
  }
});

test("uses database and NPM application version variables from the image, not container secrets", () => {
  for (const [name, key] of [
    ["authelia_postgres", "PG_VERSION"], ["immich_postgres", "PG_VERSION"],
    ["authelia_redis", "REDIS_VERSION"], ["couchdb", "COUCHDB_VERSION"], ["nginxproxymanager", "NPM_BUILD_VERSION"],
    ["nextcloud_cron", "NEXTCLOUD_VERSION"], ["forgejo_runner_dind", "DOCKER_VERSION"],
  ]) {
    const value = copy(image);
    value.Config.Env.push(`${key}=3.5.3`);
    assert.equal(imageVersion(name, value), "3.5.3");
  }
  assert.equal(imageVersion("immich_redis", image), "Image aaaaaaaaaaaa");
  const invalid = copy(image);
  invalid.Config.Env.push("REDIS_VERSION=invalid version with whitespace");
  assert.throws(() => imageVersion("immich_redis", invalid), InventoryError);
});

test("uses an application revision only when its source matches, not an inherited runtime version", () => {
  const value = copy(image);
  value.Config.Labels = {
    "org.opencontainers.image.source": "https://github.com/dantebarbieri/mirklurk-map",
    "org.opencontainers.image.version": "1.29.8-alpine",
    "org.opencontainers.image.revision": "b".repeat(40),
  };
  assert.equal(imageVersion("mirklurk-map", value), `Build ${"b".repeat(12)}`);
  value.Config.Labels["org.opencontainers.image.source"] = "https://github.com/nginx/nginx";
  assert.equal(imageVersion("mirklurk-map", value), "Image aaaaaaaaaaaa");
  delete value.Config.Labels["org.opencontainers.image.source"];
  assert.equal(imageVersion("unknown-app", value), "Image aaaaaaaaaaaa");
});

test("reads WireGuard's release, not its unrelated package version", async (t) => {
  const calls = [];
  const { request } = await fixture(t, { requestDocker: async (url, options) => {
    calls.push(url);
    if (url.endsWith("/json")) return copy(container);
    assert.equal(options.binary, true);
    return tar("package.json", '{"version":"1.0.1","release":{"version":"14"}}');
  } });
  assert.equal((await (await request("/containers/wg-easy")).json()).items[0].value, "v14");
  assert.deepEqual(calls, ["/containers/wg-easy/json", "/containers/wg-easy/archive?path=%2Fapp%2Fpackage.json"]);
});

test("reads the installed Satisfactory Steam build, not the image's Ubuntu version", async (t) => {
  const { request } = await fixture(t, { requestDocker: async (url) => url.endsWith("/json")
    ? copy(container) : tar("appmanifest_1690800.acf", '"AppState"\n{\n "buildid" "24656085"\n}\n') });
  assert.equal((await (await request("/containers/satisfactory-server")).json()).items[0].value, "Steam build 24656085");
});

test("does not provide arbitrary Docker, file, query-string, or mutation endpoints", async (t) => {
  const { request, calls } = await fixture(t);
  for (const url of ["/images/json", "/containers/x/archive", "/containers/x?path=/etc/shadow", "/containers/x%2Fy"]) {
    assert.equal((await request(url)).status, 404);
  }
  assert.equal((await request("/containers/aurral", { method: "POST" })).status, 405);
  assert.equal(calls.length, 0);
});

test("rejects containers outside the Compose project without reading their image", async (t) => {
  const value = copy(container);
  value.Config.Labels["com.docker.compose.project"] = "unrelated-project";
  let calls = 0;
  const { request } = await fixture(t, { requestDocker: async () => { calls++; return value; } });
  assert.equal((await request("/containers/unrelated")).status, 404);
  assert.equal(calls, 1);
});

test("shares in-flight requests, caches briefly, and surfaces failures after expiry without stale data", async (t) => {
  let clock = now;
  let failed = false;
  const { request } = await fixture(t, { now: () => clock, requestDocker: async (url) => {
    if (failed) throw new InventoryError("Docker socket unavailable");
    return url.startsWith("/images/") ? copy(image) : copy(container);
  } });
  assert.deepEqual(await Promise.all([request("/containers/aurral"), request("/containers/aurral")]).then(
    (responses) => responses.map((response) => response.status),
  ), [200, 200]);
  failed = true;
  assert.equal((await request("/containers/aurral")).status, 200);
  clock += 10001;
  assert.equal((await request("/containers/aurral")).status, 502);
});

test("errors never disclose raw Docker responses, credentials, mounts, or stack traces", async (t) => {
  const { request, errors } = await fixture(t, { requestDocker: async () => { throw new Error("do-not-return secret"); } });
  const response = await request("/containers/aurral");
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: "Unexpected inventory failure" });
  assert.deepEqual(errors, ["Unexpected inventory failure"]);
});

test("healthcheck verifies socket access without returning Docker details", async (t) => {
  const { request, calls } = await fixture(t);
  assert.deepEqual(await (await request("/healthz")).json(), { status: "ok" });
  assert.deepEqual(calls, ["/version"]);
});

test("omits disabled healthchecks, including stale state from a previously enabled check", () => {
  for (const check of [undefined, { Test: [] }, { Test: ["NONE"] }]) {
    const value = copy(container);
    value.Config.Healthcheck = check;
    value.State.Health = { Status: "healthy" };
    assert.equal(containerInfo(value, "1", now).items.length, 2);
  }
  const value = copy(container);
  value.Config.Healthcheck = { Test: ["CMD", "true"] };
  assert.throws(() => containerInfo(value, "1", now), /Invalid healthcheck state/);
});

test("application metrics precede inventory and are cached separately from metadata", async (t) => {
  let queries = 0;
  const { request } = await fixture(t, { requestStats: (name) => {
    assert.equal(name, "aurral");
    queries++;
    return [{ label: "Songs", value: "123" }];
  } });
  assert.equal((await (await request("/containers/aurral")).json()).items.length, 2);
  for (let i = 0; i < 2; i++) {
    const response = await request("/stats/aurral");
    assert.equal(response.status, 200);
    assert.deepEqual((await response.json()).items[0], { label: "Songs", value: "123" });
  }
  assert.equal(queries, 1);
});

test("statistics routes are fixed, GET-only and project-scoped", async (t) => {
  let queries = 0;
  const value = copy(container);
  value.Config.Labels["com.docker.compose.project"] = "unrelated";
  const { request, calls } = await fixture(t, {
    requestStats: () => { queries++; return []; },
    requestDocker: async () => value,
  });
  for (const url of ["/stats/toString", "/stats/unknown", "/stats/aurral?sql=SELECT", "/stats/aurral/elsewhere"]) {
    assert.equal((await request(url)).status, 404);
  }
  assert.equal((await request("/stats/aurral", { method: "POST" })).status, 405);
  assert.equal((await request("/stats/aurral")).status, 404);
  assert.equal(queries, 0);
  assert.equal(calls.length, 0);
});

test("expired statistics never become fake zeros, stale success or raw database errors", async (t) => {
  let clock = now;
  let fail = false;
  const { request, errors } = await fixture(t, {
    now: () => clock,
    requestStats: () => {
      if (fail) throw new Error("/private/database: secret contents");
      return [{ label: "Logins", value: "12" }];
    },
  });
  assert.equal((await request("/stats/vaultwarden")).status, 200);
  fail = true;
  clock += 10001;
  const response = await request("/stats/vaultwarden");
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "Application statistics unavailable: vaultwarden" });
  assert.deepEqual(errors, ["Application statistics unavailable: vaultwarden"]);
});

test("rejects invalid states, future start times, and malformed version files", () => {
  assert.throws(() => containerInfo({}, "1", now), InventoryError);
  const value = copy(container);
  value.State.StartedAt = new Date(now + 1000).toISOString();
  assert.throws(() => containerInfo(value, "1", now), InventoryError);
  assert.throws(() => archiveText(Buffer.alloc(0), "package.json"), InventoryError);
  assert.throws(() => archiveText(tar("elsewhere", "{}"), "package.json"), InventoryError);
  const truncated = tar("package.json", "{}").subarray(0, 513);
  assert.throws(() => archiveText(truncated, "package.json"), InventoryError);
  const badSize = tar("package.json", "{}");
  badSize.write("99999999999", 124, 11);
  assert.throws(() => archiveText(badSize, "package.json"), InventoryError);
});

test("Docker transport is GET-only and hides invalid JSON, HTTP failures, and socket errors", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "homepage-inventory-"));
  const socket = path.join(directory, "docker.sock");
  const methods = [];
  const server = http.createServer((request, response) => {
    methods.push(request.method);
    response.statusCode = request.url === "/missing" ? 404 : 200;
    response.end(request.url === "/valid" ? '{"value":1}' : "do-not-return");
  });
  server.listen(socket);
  await once(server, "listening");
  t.after(async () => {
    await new Promise((resolve) => server.close(resolve));
    await fs.rm(directory, { recursive: true });
  });
  assert.deepEqual(await dockerRequest(socket, "/valid"), { value: 1 });
  await assert.rejects(dockerRequest(socket, "/invalid"), /invalid JSON/);
  await assert.rejects(dockerRequest(socket, "/missing"), /not found/);
  await assert.rejects(dockerRequest(path.join(directory, "absent"), "/valid"), /socket unavailable/);
  assert.deepEqual(methods, ["GET", "GET", "GET"]);
});
