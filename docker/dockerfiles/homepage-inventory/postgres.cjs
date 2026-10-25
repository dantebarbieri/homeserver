const http = require("node:http");
const { Client } = require("pg");

const sources = {
  synapse: { host: "synapse_postgres", database: "synapse", fields: ["users", "rooms", "active"] },
  authelia: { host: "authelia_postgres", database: "authelia", fields: ["successful", "failed", "totp", "passkeys"] },
  snapotter: { host: "127.0.0.1", database: "snapotter", fields: ["queued", "running", "completed", "failed"] },
};

function aggregates(row, fields) {
  if (!row || Object.keys(row).sort().join(",") !== [...fields].sort().join(",")) {
    throw new Error("Invalid aggregate columns");
  }
  return Object.fromEntries(fields.map((field) => {
    const raw = row[field];
    if (!/^\d+$/.test(String(raw))) throw new Error("Invalid aggregate count");
    const value = Number(raw);
    if (!Number.isSafeInteger(value) || value < 0) throw new Error("Invalid aggregate count");
    return [field, value.toLocaleString("en-US")];
  }));
}

async function readPostgresStats(name, ClientClass = Client) {
  if (!Object.hasOwn(sources, name) || !process.env.WIDGET_DB_PASSWORD) throw new Error("Missing database configuration");
  const source = sources[name];
  const client = new ClientClass({
    host: source.host, database: source.database, user: "homepage_widget",
    password: process.env.WIDGET_DB_PASSWORD,
    connectionTimeoutMillis: 3000, statement_timeout: 2000, query_timeout: 3000,
    application_name: "homepage-widget",
  });
  try {
    await client.connect();
    await client.query("BEGIN READ ONLY");
    const { rows } = await client.query("SELECT * FROM homepage_widget.stats");
    if (rows.length !== 1) throw new Error("Invalid aggregate row count");
    return aggregates(rows[0], source.fields);
  } finally {
    await client.end();
  }
}

function createPostgresServer({ read = () => readPostgresStats("snapotter"), logError = console.error } = {}) {
  let cache;
  let pending;
  return http.createServer(async (request, response) => {
    const send = (status, body) => {
      response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      response.end(JSON.stringify(body));
    };
    if (!["/stats", "/healthz"].includes(request.url)) return send(404, { error: "Not found" });
    if (request.method !== "GET") {
      response.setHeader("Allow", "GET");
      return send(405, { error: "Method not allowed" });
    }
    try {
      if (!cache || Date.now() - cache.at >= 10000) {
        pending ||= Promise.resolve().then(read).then((value) => { cache = { at: Date.now(), value }; })
          .finally(() => { pending = undefined; });
        await pending;
      }
      send(200, request.url === "/healthz" ? { status: "ok" } : cache.value);
    } catch {
      logError("SnapOtter aggregate view unavailable");
      send(502, { error: "SnapOtter aggregate view unavailable" });
    }
  });
}

if (require.main === module) createPostgresServer().listen(8089, "0.0.0.0");
module.exports = { aggregates, createPostgresServer, readPostgresStats };
