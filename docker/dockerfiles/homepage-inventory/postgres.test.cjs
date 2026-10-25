const assert = require("node:assert/strict");
const { once } = require("node:events");
const { test } = require("node:test");
const { aggregates, createPostgresServer, readPostgresStats } = require("./postgres.cjs");

test("database aggregates accept only the expected safe count columns, not record contents", () => {
  assert.deepEqual(aggregates({ users: "1234", rooms: "2" }, ["users", "rooms"]), { users: "1,234", rooms: "2" });
  for (const value of [-1, null, "private", "1.5", "9007199254740993"]) {
    assert.throws(() => aggregates({ count: value }, ["count"]), /Invalid aggregate/);
  }
  assert.throws(() => aggregates({ count: "1", username: "private" }, ["count"]), /columns/);
});

test("PostgreSQL uses the restricted identity, read-only transaction and only the aggregate view", async (t) => {
  const previous = process.env.WIDGET_DB_PASSWORD;
  process.env.WIDGET_DB_PASSWORD = "private-test-password";
  t.after(() => {
    if (previous === undefined) delete process.env.WIDGET_DB_PASSWORD;
    else process.env.WIDGET_DB_PASSWORD = previous;
  });
  const queries = [];
  let closed = false;
  class FakeClient {
    constructor(config) {
      assert.equal(config.user, "homepage_widget");
      assert.equal(config.host, "synapse_postgres");
      assert.equal(config.database, "synapse");
      assert.equal(config.statement_timeout, 2000);
    }
    async connect() {}
    async query(sql) {
      queries.push(sql);
      return { rows: [{ users: "10", rooms: "20", active: "3" }] };
    }
    async end() { closed = true; }
  }
  assert.deepEqual(await readPostgresStats("synapse", FakeClient), { users: "10", rooms: "20", active: "3" });
  assert.deepEqual(queries, ["BEGIN READ ONLY", "SELECT * FROM homepage_widget.stats"]);
  assert.equal(closed, true);
  await assert.rejects(readPostgresStats("unknown", FakeClient), /Missing database/);
});

test("SnapOtter companion is GET-only, hides raw errors, and healthchecks actual database access", async (t) => {
  const errors = [];
  const server = createPostgresServer({
    read: () => { throw new Error("private database URL and user records"); },
    logError: (message) => errors.push(message),
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise((resolve) => { server.closeAllConnections(); server.close(resolve); }));
  const url = `http://127.0.0.1:${server.address().port}`;
  assert.equal((await fetch(`${url}/stats?sql=SELECT`)).status, 404);
  assert.equal((await fetch(`${url}/stats`, { method: "POST" })).status, 405);
  for (const path of ["/stats", "/healthz"]) {
    const response = await fetch(url + path);
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { error: "SnapOtter aggregate view unavailable" });
  }
  assert.deepEqual(errors, ["SnapOtter aggregate view unavailable", "SnapOtter aggregate view unavailable"]);
});
