const assert = require("node:assert/strict");
const { once } = require("node:events");
const { test } = require("node:test");
const { createServer } = require("./server.cjs");

const counts = { download: 10, nondownload: 3, read: 7, unread: 6 };
const countsResponse = { data: Object.fromEntries(Object.entries(counts).map(([key, value]) => [key, { totalCount: value }])) };
const loginResponse = { data: { login: { accessToken: "private-token" } } };
const unauthorized = { errors: [{ message: "Exception while fetching data : Unauthorized\nprivate details" }] };
const username = "widget-user";
const password = "private-password:$#";
const auth = `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
const json = (value, status = 200) => new Response(JSON.stringify(value), { status });

async function fixture(t, replies, options = {}) {
  const calls = [];
  const errors = [];
  const server = createServer({
    url: "http://suwayomi:4567",
    username,
    password,
    logError: (error) => errors.push(error),
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), ...init, body: JSON.parse(init.body) });
      assert.ok(replies.length, "Unexpected upstream request");
      const reply = replies.shift();
      if (reply instanceof Error) throw reply;
      return typeof reply === "function" ? reply(init) : json(reply);
    },
    ...options,
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise((resolve, reject) => {
    server.closeAllConnections();
    server.close((error) => error ? reject(error) : resolve());
  }));
  const url = `http://127.0.0.1:${server.address().port}`;
  const request = (path = "/stats", init = {}) => fetch(url + path, {
    headers: { Authorization: auth },
    ...init,
  });
  return { request, calls, errors };
}

test("logs in, reads only library counts and reuses the token", async (t) => {
  const { request, calls } = await fixture(t, [loginResponse, countsResponse, countsResponse]);
  for (let i = 0; i < 2; i++) {
    const response = await request();
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), counts);
  }
  assert.equal(calls.length, 3);
  assert.deepEqual(calls[0].body.variables, { input: { username, password } });
  assert.equal(calls[0].headers.Authorization, undefined);
  assert.equal(calls[1].headers.Authorization, "Bearer private-token");
  assert.match(calls[1].body.query, /inLibrary: \{equalTo: true\}/);
  assert.equal(calls[1].url, "http://suwayomi:4567/api/graphql");
  assert.equal(calls[1].redirect, "error");
});

test("rejects missing or incorrect authentication without contacting Suwayomi", async (t) => {
  const { request, calls } = await fixture(t, []);
  for (const headers of [{}, { Authorization: "Basic invalid" }]) {
    assert.equal((await request("/stats", { headers })).status, 401);
  }
  assert.equal(calls.length, 0);
});

test("does not expose a general-purpose GraphQL proxy or accept writes", async (t) => {
  const { request, calls } = await fixture(t, []);
  assert.equal((await request("/api/graphql", { method: "POST", body: "{}" })).status, 404);
  assert.equal((await request("/stats", { method: "POST", body: "{}" })).status, 405);
  assert.equal(calls.length, 0);
});

test("renews an expired token once on GraphQL Unauthorized", async (t) => {
  const { request, calls } = await fixture(t, [
    loginResponse, unauthorized, { data: { login: { accessToken: "renewed-token" } } }, countsResponse,
  ]);
  const response = await request();
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), counts);
  assert.equal(calls[3].headers.Authorization, "Bearer renewed-token");
});

test("renews an expired token once on HTTP 401", async (t) => {
  const { request } = await fixture(t, [loginResponse, () => json({}, 401), loginResponse, countsResponse]);
  assert.equal((await request()).status, 200);
});

test("stops after one rejected-token retry and never returns partial success", async (t) => {
  const { request, calls, errors } = await fixture(t, [loginResponse, unauthorized, loginResponse, unauthorized]);
  const response = await request();
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "Suwayomi authentication failed" });
  assert.equal(calls.length, 4);
  assert.deepEqual(errors, ["Suwayomi authentication failed"]);
});

test("failed login is visible, secret-free and can recover on the next request", async (t) => {
  const { request, calls, errors } = await fixture(t, [
    { errors: [{ message: `Login rejected ${password} private-token` }] },
    loginResponse, countsResponse,
  ]);
  const response = await request();
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "Suwayomi returned GraphQL errors" });
  assert.deepEqual(errors, ["Suwayomi returned GraphQL errors"]);
  assert.equal((await request()).status, 200);
  assert.equal(calls.length, 3);
});

test("concurrent requests share a single login", async (t) => {
  let release;
  const { request, calls } = await fixture(t, [
    () => new Promise((resolve) => { release = () => resolve(json(loginResponse)); }),
    countsResponse, countsResponse,
  ]);
  const first = request();
  const second = request();
  while (!release) await new Promise((resolve) => setTimeout(resolve, 5));
  release();
  assert.equal((await first).status, 200);
  assert.equal((await second).status, 200);
  assert.equal(calls.filter((call) => call.body.variables).length, 1);
});

for (const [label, reply, status] of [
  ["network failure", new Error(`Network failed ${password}`), 502],
  ["invalid JSON", () => new Response("not-json"), 502],
  ["HTTP failure", () => json({ error: password }, 503), 502],
  ["timeout", new DOMException("private-token", "TimeoutError"), 504],
  ["missing token", { data: { login: {} } }, 502],
  ["missing data", {}, 502],
]) {
  test(`reports ${label} without exposing secrets`, async (t) => {
    const { request, errors } = await fixture(t, [reply]);
    const response = await request();
    assert.equal(response.status, status);
    const body = await response.text();
    assert.doesNotMatch(body + errors.join(), /private-token|private-password/);
    assert.equal(errors.length, 1);
  });
}

for (const value of [null, "3", -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
  test(`rejects invalid count ${value}`, async (t) => {
    const { request } = await fixture(t, [loginResponse, {
      data: { ...countsResponse.data, read: { totalCount: value } },
    }]);
    assert.equal((await request()).status, 502);
  });
}

test("does not retry non-authentication GraphQL errors", async (t) => {
  const { request, calls } = await fixture(t, [loginResponse, { data: countsResponse.data, errors: [{ message: "Schema failure" }] }]);
  assert.equal((await request()).status, 502);
  assert.equal(calls.length, 2);
});

test("requires explicit configuration", () => {
  assert.throws(() => createServer({ url: "http://suwayomi:4567", username, password: "" }), /are required/);
});
