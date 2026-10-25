const { readStats, databaseFiles } = require("./stats.cjs");
const { readPostgresStats } = require("./postgres.cjs");

const statsNames = new Set([
  ...Object.keys(databaseFiles), "searxng", "it-tools", "stirling-pdf", "wg-easy",
  "synapse", "element", "authelia", "snapotter",
]);

function count(value) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error("Invalid aggregate");
  return value.toLocaleString("en-US");
}

async function text(url, headers = {}) {
  const response = await fetch(url, { headers, redirect: "error", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error("Upstream request failed");
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > 2 * 1024 * 1024) throw new Error("Upstream response too large");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function json(url, headers) {
  return JSON.parse(await text(url, headers));
}

function metricValues(body, name) {
  if (!new RegExp(`^# TYPE ${name} (?:counter|gauge)$`, "m").test(body)) {
    throw new Error("Missing metric family");
  }
  return [...body.matchAll(new RegExp(`^${name}(?:\\{[^\\n]*\\})? ([^\\s]+)$`, "gm"))].map((match) => {
    const value = Number(match[1]);
    if (!Number.isFinite(value) || value < 0) throw new Error("Invalid metric");
    return value;
  });
}

function toolCatalog(bundle) {
  const registrations = new Map([...bundle.matchAll(
    /([A-Za-z_$][\w$]*)=[A-Za-z_$][\w$]*\(\{name:[^{}]{1,400}?,path:"(\/[a-z0-9-]+)",description:/g,
  )].map((match) => [match[1], match[2]]));
  const groups = [...bundle.matchAll(/\{name:"([^"]+)",components:\[([\w$,]+)\]\}/g)];
  if (groups.length < 2 || registrations.size < 2) throw new Error("Unrecognized tool catalog");
  const paths = new Set();
  const categories = new Set();
  for (const group of groups) {
    if (categories.has(group[1])) throw new Error("Duplicate category");
    categories.add(group[1]);
    for (const id of group[2].split(",")) {
      const path = registrations.get(id);
      if (!path || paths.has(path)) throw new Error("Incomplete tool catalog");
      paths.add(path);
    }
  }
  if (paths.size !== registrations.size) throw new Error("Uncategorized tools");
  return { tools: count(paths.size), categories: count(categories.size) };
}

function pdfCatalog(document) {
  const allowed = new Set(["General", "Misc", "Security", "Convert", "Analysis", "Filter",
    "Forms", "Auto Form Detection", "DocParse", "AI Tools"]);
  const categories = new Set();
  let actions = 0;
  function hasFile(schema, seen = new Set()) {
    if (!schema || typeof schema !== "object" || seen.has(schema)) return false;
    seen.add(schema);
    if (schema.$ref) {
      if (!schema.$ref.startsWith("#/components/schemas/")) throw new Error("External schema reference");
      return hasFile(document.components?.schemas?.[schema.$ref.slice(21)], seen);
    }
    return schema.format === "binary" || hasFile(schema.items, seen)
      || Object.values(schema.properties || {}).some((property) => hasFile(property, seen))
      || [...schema.allOf || [], ...schema.anyOf || [], ...schema.oneOf || []]
        .some((property) => hasFile(property, seen));
  }
  if (!document.openapi || !document.paths) throw new Error("Missing API catalog");
  for (const [path, operations] of Object.entries(document.paths)) {
    const operation = operations.post;
    const tags = (operation?.tags || []).filter((tag) => allowed.has(tag));
    if (!path.startsWith("/api/v1/") || !tags.length) continue;
    if (!hasFile(operation.requestBody?.content?.["multipart/form-data"]?.schema)) continue;
    actions++;
    tags.forEach((tag) => categories.add(tag));
  }
  if (!actions || !categories.size) throw new Error("Missing PDF actions");
  return { actions: count(actions), categories: count(categories.size) };
}

function peerStats(body) {
  const config = JSON.parse(body);
  if (!config.clients || typeof config.clients !== "object" || Array.isArray(config.clients)) {
    throw new Error("Invalid peer configuration");
  }
  const peers = Object.values(config.clients);
  if (!peers.every((peer) => peer && typeof peer.enabled === "boolean")) throw new Error("Invalid peer");
  return { peers: count(peers.length), enabled: count(peers.filter((peer) => peer.enabled).length) };
}

async function applicationStats(name, { readContainerFile }) {
  if (Object.hasOwn(databaseFiles, name)) {
    const result = readStats(name);
    if (name === "convertx") {
      const source = await readContainerFile("convertx", "/app/dist/src/converters/main.js");
      const registry = /const properties = \{([\s\S]*?)\n\};/.exec(source)?.[1];
      const converters = registry?.match(/^\s{4}[A-Za-z][A-Za-z0-9]*: \{\s+properties:/gm);
      if (!converters?.length) throw new Error("Missing converter registry");
      return { converters: count(converters.length), ...result };
    }
    return result;
  }
  switch (name) {
    case "wg-easy":
      return peerStats(await readContainerFile(name, "/etc/wireguard/wg0.json"));
    case "synapse":
    case "element":
      return readPostgresStats("synapse");
    case "authelia":
      return readPostgresStats(name);
    case "snapotter": {
      const result = await json("http://snapotter:8089/stats");
      if (Object.keys(result).sort().join(",") !== "completed,failed,queued,running"
          || !Object.values(result).every((value) => typeof value === "string" && /^[\d,]+$/.test(value))) {
        throw new Error("Invalid job aggregates");
      }
      return result;
    }
    case "it-tools": {
      const html = await text("http://it-tools/");
      const asset = /<script[^>]+src="(\/assets\/index-[A-Za-z0-9_-]+\.js)"/.exec(html)?.[1];
      if (!asset) throw new Error("Missing tool catalog asset");
      return toolCatalog(await text(`http://it-tools${asset}`));
    }
    case "stirling-pdf":
      return pdfCatalog(await json("http://stirling-pdf:8080/v1/api-docs"));
    case "searxng": {
      const password = process.env.SEARXNG_METRICS_PASSWORD;
      if (!password) throw new Error("Metrics credential missing");
      const [config, metrics] = await Promise.all([
        json("http://searxng:8080/config"),
        text("http://searxng:8080/metrics", { Authorization: `Basic ${Buffer.from(`widget:${password}`).toString("base64")}` }),
      ]);
      if (!Array.isArray(config.engines)
          || !config.engines.every((engine) => typeof engine.enabled === "boolean" && Array.isArray(engine.categories))) {
        throw new Error("Invalid engine configuration");
      }
      const requests = metricValues(metrics, "searxng_engines_request_count_total");
      const latency = metricValues(metrics, "searxng_engines_response_time_total_seconds");
      return {
        engines: count(config.engines.filter((engine) => engine.enabled).length),
        calls: count(requests.reduce((sum, value) => sum + value, 0)),
        latency: latency.length ? `${Math.round(latency.reduce((sum, value) => sum + value, 0) / latency.length * 1000)}ms` : "No samples",
      };
    }
    default:
      throw new Error("Unsupported statistics source");
  }
}

module.exports = { applicationStats, count, metricValues, pdfCatalog, peerStats, statsNames, toolCatalog };
