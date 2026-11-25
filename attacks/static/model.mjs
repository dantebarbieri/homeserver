export const TYPES = {
  endlessh: {label: "Endlessh", color: "#aab8ca"},
  ssh: {label: "Real SSH", color: "#f4f7ff"},
  authelia: {label: "Authelia", color: "#f397ad"},
  web: {label: "Web / NPM", color: "#71d5ed"},
  minecraft: {label: "Minecraft", color: "#94dfa5"},
  plex: {label: "Plex", color: "#efc477"},
  game: {label: "Other games", color: "#bc9ceb"},
  git: {label: "Git SSH", color: "#82a8ff"},
};

export const OUTCOMES = [
  ["accepted", "Login accepted"], ["failure", "Sign-in rejected"], ["incomplete", "Pre-auth disconnect"],
  ["blocked", "Blocked / banned"], ["suspected", "Suspected probe"], ["observed", "Observed"],
  ["unclassified", "Unclassified connection"],
];

// Evidence of hostile intent, lowest first. Mirrors attacks/events.py; rows from the API carry their own level.
export const SEVERITIES = [
  ["info", "Info", "Looks routine: a signed-in session or an ordinary service check."],
  ["low", "Low", "Reached a port or public endpoint; unremarkable on its own."],
  ["suspicious", "Suspicious", "Unusual or unauthenticated, but nothing was rejected or exploited."],
  ["high", "High", "A rejected login, ban, or a request matching a known exploit pattern."],
  ["critical", "Critical", "A login succeeded with a credential this dashboard does not recognize."],
];
const SEVERITY_BY_KIND = {
  endlessh_open: "low", endlessh_close: "low", ssh_failure: "high", ssh_accepted: "info", ssh_accepted_unknown: "critical",
  ssh_disconnect: "suspicious", ssh_probe: "low", ssh_ban: "high", auth_failure: "high", http_probe: "high",
  http_denied: "low", service_connection: "low", plex_client: "info", plex_reachability: "info", plex_public: "low",
  plex_probe: "suspicious", hytale_rejected: "suspicious",
};

export function severityOf(item) {
  return SEVERITIES.some(([level]) => level === item.severity) ? item.severity : SEVERITY_BY_KIND[item.kind] || "low";
}

const list = value => (value ? String(value).split(",") : []);

// Mirrors the server's event query so synthetic and just-arrived events obey the same filters.
export function matchesFilters(item, parameters) {
  const levels = SEVERITIES.map(([level]) => level);
  const types = list(parameters.type), outcomes = list(parameters.outcome);
  return (!types.length || types.includes(item.type)) && (!outcomes.length || outcomes.includes(item.verdict))
    && (!parameters.severity || levels.indexOf(severityOf(item)) >= levels.indexOf(parameters.severity))
    && (!parameters.ip || item.ip === parameters.ip) && (!parameters.country || item.countryCode === parameters.country)
    && (!parameters.asn || String(item.asn) === parameters.asn)
    && (parameters.own === "1" || item.origin !== "own");
}

export const MAP_DEFAULTS = {keep: 7, fadeMinutes: 30, maxDots: 300};

export function mapSettings(input) {
  const result = {};
  for (const [key, min, max] of [["keep", 0, 1000], ["fadeMinutes", 1, 1440], ["maxDots", 1, 1000]]) {
    const value = Number(input?.[key]);
    if (input?.[key] === "" || input?.[key] == null || !Number.isInteger(value) || value < min || value > max)
      throw new Error(`Map setting ${key} must be a whole number between ${min} and ${max}.`);
    result[key] = value;
  }
  if (result.keep > result.maxDots) throw new Error("Keep newest cannot exceed the maximum map dots.");
  return result;
}

export function mapActivity(events, settings, now = Date.now() / 1000, history = false) {
  const sources = new Map(), held = new Set();
  const ordered = events.filter(item => item.origin !== "own" && item.ip && Number.isFinite(item.observedAt))
    .sort((a, b) => b.observedAt - a.observedAt);
  // Replay oldest first so hits refresh their own IP, not a neighbor's fade timer.
  for (let i = ordered.length - 1; i >= 0; i--) {
    const item = ordered[i];
    const source = sources.get(item.ip) ?? {ip: item.ip, place: null, count: 0, types: {}, severities: {}};
    sources.delete(item.ip);
    sources.set(item.ip, source);
    source.latest = item;
    source.count++;
    source.types[item.type] = (source.types[item.type] || 0) + 1;
    const severity = severityOf(item);
    source.severities[severity] = (source.severities[severity] || 0) + 1;
    if (located(item)) source.place = item;
    if (!source.place) continue;
    held.delete(source);
    held.add(source);
    if (held.size > settings.keep) {
      const displaced = held.values().next().value;
      displaced.fadeStart = item.observedAt;
      held.delete(displaced);
    }
  }
  const visible = [];
  let expired = 0, unlocated = 0;
  for (const source of [...sources.values()].reverse()) {
    if (!source.place) { unlocated++; continue; }
    const opacity = held.has(source) ? 1 : Math.max(0, Math.min(1, 1 - (now - source.fadeStart) / (settings.fadeMinutes * 60)));
    if (opacity === 0) expired++;
    if (opacity > 0 || history) visible.push({...source, opacity: opacity || .12});
  }
  return {points: visible.slice(0, settings.maxDots), expired, omitted: Math.max(0, visible.length - settings.maxDots), unlocated};
}

// The sources the map leaves out and why. Silent when it draws everything it has.
export function notDrawn({faded = 0, farSide = 0, unlocated = 0, omitted = 0}) {
  const parts = [[faded, "faded"], [farSide, "on far side"], [unlocated, "unlocated"], [omitted, "over the dot limit"]]
    .filter(([count]) => count > 0).map(([count, label]) => `${count} ${label}`);
  return parts.length ? `Sources not drawn: ${parts.join(" · ")}` : "";
}

export const TYPE_ORDER = Object.keys(TYPES);
export const SEVERITY_ORDER = SEVERITIES.map(([level]) => level).reverse();

// Splits a turn among counted keys in a fixed order, clockwise from the top. Each key gets one
// contiguous part, so like colors are always joined and a key never moves as counts change.
// Every present key keeps at least `minimum` of the turn so a single odd event stays visible.
export function slices(counts, order, minimum = .1) {
  const present = order.filter(key => counts[key] > 0);
  const total = present.reduce((sum, key) => sum + counts[key], 0);
  const floor = Math.min(minimum, 1 / present.length);
  let start = 0;
  return present.map((key, index) => {
    const end = index === present.length - 1 ? 1 : start + floor + (1 - floor * present.length) * counts[key] / total;
    const part = {key, count: counts[key], start, end};
    start = end;
    return part;
  });
}

const turnPoint = turn => {
  const angle = 2 * Math.PI * turn - Math.PI / 2;
  return `${Number(Math.cos(angle).toFixed(4))} ${Number(Math.sin(angle).toFixed(4))}`;
};

// Unit-radius SVG path for a part: a pie sector, or with `ring` an open arc for stroking.
export function slicePath({start, end}, ring = false) {
  if (end - start >= 1) return `M0 -1A1 1 0 1 1 0 1A1 1 0 1 1 0 -1${ring ? "" : "Z"}`;
  const arc = `A1 1 0 ${end - start > .5 ? 1 : 0} 1 ${turnPoint(end)}`;
  return ring ? `M${turnPoint(start)}${arc}` : `M0 0L${turnPoint(start)}${arc}Z`;
}

export function countryFlag(code) {
  if (typeof code !== "string" || !/^[A-Z]{2}$/.test(code) || ["ZZ", "XX"].includes(code)) return "";
  return [...code].map(letter => String.fromCodePoint(0x1f1e6 + letter.charCodeAt(0) - 65)).join("");
}

export function mergeEvents(current, incoming, limit = 1000) {
  const all = new Map(current.map(item => [item.id, item]));
  for (const item of incoming) if (TYPES[item.type]) all.set(item.id, item);
  return [...all.values()].sort((a, b) => BigInt(a.cursor) > BigInt(b.cursor) ? -1 : BigInt(a.cursor) < BigInt(b.cursor) ? 1 : a.id.localeCompare(b.id)).slice(0, limit);
}

export function equalEarth(longitude, latitude) {
  const radians = Math.PI / 180;
  const theta = Math.asin(Math.sqrt(3) / 2 * Math.sin(latitude * radians));
  // Equal Earth (Savric, Patterson & Jenny, 2018), spherical forward equations.
  const coefficients = [[1, 1.340264], [3, -.081106], [7, .000893], [9, .003796]];
  const vertical = coefficients.reduce((sum, [power, value]) => sum + value * theta ** power, 0);
  const derivative = coefficients.reduce((sum, [power, value]) => sum + power * value * theta ** (power - 1), 0);
  return [2 * longitude * radians * Math.cos(theta) / (Math.sqrt(3) * derivative), vertical];
}

const EQUAL_EARTH_EXTENT = [equalEarth(180, 0)[0], equalEarth(0, 90)[1]];

export function project(longitude, latitude, width, height, projection = "equal-earth") {
  if (projection === "rectangular") {
    const scale = Math.min(width / 380, height / 190);
    return [width / 2 + longitude * scale, height / 2 - latitude * scale];
  }
  const [x, y] = equalEarth(longitude, latitude);
  const scale = Math.min(width / (EQUAL_EARTH_EXTENT[0] * 2.12), height / (EQUAL_EARTH_EXTENT[1] * 2.12));
  return [width / 2 + x * scale, height / 2 - y * scale];
}

export function located(event) {
  return Number.isFinite(event.latitude) && Number.isFinite(event.longitude)
    && Math.abs(event.latitude) <= 90 && Math.abs(event.longitude) <= 180;
}

export function duration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds >= 86400) return `${(seconds / 86400).toFixed(1)} d`;
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)} h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds)} s`;
}

// A telemetry sample older than this is no longer trusted to say who is still connected.
const TRAP_STALE_MS = 90000;

export function liveTrapping(sample, elapsedMs) {
  if (!sample?.available || !Number.isFinite(sample.seconds) || !Number.isFinite(sample.connections)
    || elapsedMs > TRAP_STALE_MS) return null;
  return {connections: sample.connections, seconds: sample.seconds + sample.connections * Math.max(0, elapsedMs / 1000)};
}

// Trapped time reads finer than the dashboard totals: a client held for 4 min 12 s was not held for "4 min".
export function trapDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds > 0 && seconds < .05) return "<0.1 s";
  if (seconds < 10) return `${Math.round(seconds * 10) / 10} s`;
  const total = Math.round(seconds), days = Math.floor(total / 86400), hours = Math.floor(total % 86400 / 3600);
  const minutes = Math.floor(total % 3600 / 60), rest = total % 60;
  const parts = days ? [[days, "d"], [hours, "h"]] : hours ? [[hours, "h"], [minutes, "min"]]
    : minutes ? [[minutes, "min"], [rest, "s"]] : [[rest, "s"]];
  return parts.filter(([value]) => value).map(([value, unit]) => `${value} ${unit}`).join(" ");
}

const sessionIndexes = new WeakMap();

// Endlessh events grouped by connection (source address and port), oldest first.
function sessionIndex(events) {
  let index = sessionIndexes.get(events);
  if (!index) {
    index = new Map();
    for (const item of events) {
      if ((item.kind !== "endlessh_open" && item.kind !== "endlessh_close") || !Number.isFinite(item.sourcePort)) continue;
      const key = `${item.ip}|${item.sourcePort}`;
      if (!index.has(key)) index.set(key, []);
      index.get(key).push(item);
    }
    for (const sessions of index.values()) sessions.sort((a, b) => a.timestamp - b.timestamp || a.observedAt - b.observedAt);
    sessionIndexes.set(events, index);
  }
  return index;
}

// A source port can be reused, so a connection's end is the next event for its address and port, never just any.
function laterEvent(item, events) {
  if (!Number.isFinite(item.sourcePort)) return undefined;
  return sessionIndex(events).get(`${item.ip}|${item.sourcePort}`)?.find(other => other.id !== item.id
    && (other.timestamp > item.timestamp || (other.timestamp === item.timestamp && other.observedAt > item.observedAt)));
}

// How long Endlessh held this connection: null for anything else, "ended" with the final time, "active" while
// the client is still connected (ticking from `since`), or "unknown" when nothing says how it ended.
// `sample` is the latest stats `trapping` object and `elapsedMs` how long ago it arrived.
export function trapTime(item, events, sample, elapsedMs) {
  if (item.kind === "endlessh_close") return Number.isFinite(item.duration) ? {state: "ended", seconds: item.duration} : null;
  if (item.kind !== "endlessh_open") return null;
  const next = laterEvent(item, events);
  if (next?.kind === "endlessh_close" && Number.isFinite(next.duration)) return {state: "ended", seconds: next.duration};
  const unknown = {state: "unknown"};
  // A later event for the same connection means this open's own close was never logged. The collector does not
  // track our own connections, so it cannot say whether those are still open.
  if (next || item.origin === "own" || !liveTrapping(sample, elapsedMs) || !Number.isFinite(sample.asOf)) return unknown;
  const listed = sample.active?.find(row => row.ip === item.ip && row.sourcePort === item.sourcePort
    && Math.abs(row.since - item.timestamp) < .001);
  // The published list only covers what the collector had seen by `through`; a newer open has had no chance to close yet.
  const since = listed ? listed.since : item.observedAt > sample.through ? item.timestamp : null;
  return since === null ? unknown : {state: "active", seconds: trapSince(sample, elapsedMs, since), since};
}

// Seconds a connection has been held, counted on the collector's clock so a device with the wrong time still reads right.
export function trapSince(sample, elapsedMs, since) {
  return Math.max(0, sample.asOf + elapsedMs / 1000 - since);
}

export function ago(timestamp, now = Date.now() / 1000) {
  if (!Number.isFinite(timestamp)) return "";
  // Clock skew can put an event slightly in the future.
  const seconds = Math.max(0, Math.floor(now - timestamp));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

// The flash is a short celebration of "just detected"; only genuinely fresh events earn it.
export const FLASH = {seconds: 6, maxConcurrent: 12, liveWindow: 60, loadWindow: 30};

// Follow mode moves to fresh arrivals, then holds still so they can be read. Arrivals during the hold
// are batched into the next move, so busy periods move about once per hold instead of on every event.
export const FOLLOW = {holdMs: 4000, staleMs: 15000, zoom: 3, spread: .5, inner: .7, limbDegrees: 60, statusMs: 5000};

export function isFresh(item, window, now = Date.now() / 1000) {
  return Number.isFinite(item.observedAt) && now - item.observedAt < window;
}

const DEMO_PLACES = [[-74, 40.7, "New York, United States", "US"], [13.4, 52.5, "Berlin, Germany", "DE"],
  [103.8, 1.3, "Singapore", "SG"], [-46.6, -23.6, "São Paulo, Brazil", "BR"],
  [139.7, 35.7, "Tokyo, Japan", "JP"], [2.4, 48.9, "Paris, France", "FR"],
  [151.2, -33.9, "Sydney, Australia", "AU"], [77.2, 28.6, "New Delhi, India", "IN"],
  [3.4, 6.5, "Lagos, Nigeria", "NG"], [31.2, 30, "Cairo, Egypt", "EG"], [36.8, -1.3, "Nairobi, Kenya", "KE"],
  [28, -26.2, "Johannesburg, South Africa", "ZA"], [37.6, 55.8, "Moscow, Russia", "RU"], [55.3, 25.2, "Dubai, United Arab Emirates", "AE"],
  [127, 37.6, "Seoul, South Korea", "KR"], [106.8, -6.2, "Jakarta, Indonesia", "ID"], [-99.1, 19.4, "Mexico City, Mexico", "MX"],
  [-79.4, 43.7, "Toronto, Canada", "CA"], [-74.1, 4.7, "Bogotá, Colombia", "CO"], [-70.7, -33.4, "Santiago, Chile", "CL"],
  [21, 52.2, "Warsaw, Poland", "PL"], [29, 41, "Istanbul, Türkiye", "TR"], [116.4, 39.9, "Beijing, China", "CN"],
  [-0.1, 51.5, "London, United Kingdom", "GB"], [-118.2, 34.1, "Los Angeles, United States", "US"], [-77.5, 39, "Ashburn, United States", "US"],
  [4.9, 52.4, "Amsterdam, Netherlands", "NL"], [72.9, 19.1, "Mumbai, India", "IN"], [121, 14.6, "Manila, Philippines", "PH"],
  [30.5, 50.4, "Kyiv, Ukraine", "UA"], [-21.9, 64.1, "Reykjavik, Iceland", "IS"], [-149.9, 61.2, "Anchorage, United States", "US"]];
const DEMO_PROVIDERS = ["AWS", "Azure", "Google Cloud", "Oracle Cloud", "Vercel", "Hetzner", "Cloudflare", "Example ISP"];
const DEMO_KINDS = ["endlessh_open", "ssh_probe", "auth_failure", "http_probe", "service_connection", "service_connection", "service_connection", "service_connection"];
// Weighted like real traffic: most scanners hit Endlessh or the web.
const DEMO_MIX = [0, 0, 0, 0, 3, 3, 3, 1, 1, 2, 4, 5, 6, 7];

// Titles and outcomes for the kinds that demoEvent varies by variant.
const DEMO_TITLES = {
  plex_client: ["Plex client request", "observed"], plex_probe: ["Unauthenticated Plex request", "suspected"],
  plex_reachability: ["Probable Plex remote-access check", "observed"], plex_public: ["Public Plex endpoint request", "observed"],
  hytale_rejected: ["Hytale identity token rejected", "failure"], ssh_failure: ["SSH authentication failed", "failure"],
  ssh_disconnect: ["SSH disconnected before login", "incomplete"], ssh_probe: ["Targeted real SSH port", "unclassified"],
};
// Demo events that repeat an earlier event's source (same IP, place and network), so mixed dots show on load.
const DEMO_SHARED = {10: 0, 31: 0, 11: 3, 19: 3, 21: 3};
// Endlessh connections that already ended (index into the events below, seconds held). The newest one, 0, is still open.
const DEMO_TRAPPED = [[24, 312.6], [16, 41.2], [8, 2.4]];
export function demoEvents(now = Date.now()) {
  const events = Array.from({length: 32}, (_, i) => {
    const host = DEMO_SHARED[i] ?? i;
    const item = demoEvent(i, (now - i * 17000) / 1000, `demo-${i}`, `192.0.2.${host + 1}`, DEMO_PLACES[(host * 3) % 8], host);
    if (item.kind === "endlessh_open") item.sourcePort = 40000 + (i * 7919) % 10000;
    return item;
  });
  return mergeEvents([], [...events, ...DEMO_TRAPPED.map(([i, seconds]) => demoCloseEvent(events[i], seconds))]);
}

// The "Left Endlessh" event that ends a demo connection `seconds` after it opened.
export function demoCloseEvent(open, seconds) {
  const timestamp = open.timestamp + seconds;
  return {...open, id: open.id.replace("demo-", "demo-close-"), cursor: String(BigInt(Math.floor(timestamp * 1000)) * 1000000n + 999999n),
    timestamp, observedAt: timestamp, kind: "endlessh_close", title: "Left Endlessh", duration: seconds};
}

// The stats `trapping` sample a collector would publish for demo events: an external open without a close is still connected.
export function demoTrapping(events, now) {
  const active = events.filter(item => item.kind === "endlessh_open" && item.origin !== "own" && !laterEvent(item, events))
    .map(item => ({ip: item.ip, sourcePort: item.sourcePort, since: item.timestamp}));
  return {available: true, connections: active.length, seconds: active.reduce((total, row) => total + Math.max(0, now - row.since), 0),
    active, activeTruncated: false, asOf: now, through: now, since: now - 3600};
}

// One synthetic arrival for the simulated live stream. Addresses stay inside the RFC 5737 documentation ranges.
export function demoLiveEvent(sequence, now = Date.now(), random = Math.random) {
  const type = DEMO_MIX[Math.floor(random() * DEMO_MIX.length)];
  const variants = {1: [0, 0, 0, 0, 1, 2, 3], 5: [0, 1, 1, 2, 3, 4], 6: [0, 0, 1, 1], 7: [0, 1, 1, 2, 3]}[type];
  const variant = variants ? variants[Math.floor(random() * variants.length)] : 0;
  const place = DEMO_PLACES[Math.floor(random() * DEMO_PLACES.length)];
  const prefix = ["192.0.2", "198.51.100", "203.0.113"][Math.floor(random() * 3)];
  const item = demoEvent(type + 8 * variant, now / 1000, `demo-live-${sequence}`, `${prefix}.${1 + Math.floor(random() * 254)}`, place);
  item.cursor = String(BigInt(Math.floor(now)) * 1000000n + BigInt(sequence % 1000000));
  if (item.kind === "endlessh_open") item.sourcePort = 50000 + (sequence * 7919) % 10000;
  return item;
}

function demoEvent(i, timestamp, id, ip, place, network = i) {
  const type = Object.keys(TYPES)[i % 8], n = network % 8;
  const item = {id, cursor: String(BigInt(Math.floor(timestamp * 1000)) * 1000000n),
    timestamp, observedAt: timestamp, origin: i === 9 ? "own" : "external", type, kind: DEMO_KINDS[i % 8],
    title: ["Stuck in Endlessh", "Targeted real SSH port", "Authelia sign-in failed", "Suspicious web request", "Service connection"][Math.min(i % 8, 4)],
    verdict: type === "authelia" ? "failure" : type === "web" ? "suspected" : type === "endlessh" ? "observed" : "unclassified",
    ip, port: [22, 28, 443, 443, 36676, 32400, 5205, 2222][i % 8],
    service: TYPES[type].label, source: "synthetic", user: type === "authelia" ? "example-user" : undefined,
    path: type === "web" ? "/.env" : undefined,
    longitude: place[0], latitude: place[1], location: place[2], countryCode: place[3],
    networkLookup: "ready", networkProvider: DEMO_PROVIDERS[n], asn: 64512 + n,
    networkOrganization: "Synthetic example network (private-use ASN)", networkEvidence: "Synthetic preview association, not a real IP lookup",
    privacyServices: n > 0 && n < 4 ? [{
      name: ["", "Mullvad", "NordVPN", "Tor"][n], kind: n === 3 ? "tor_exit" : "vpn_server",
      evidence: "Synthetic association for preview only; not a real VPN or Tor lookup", updatedAt: timestamp,
    }] : []};
  if (type === "ssh") {
    const variant = Math.floor(i / 8);
    item.user = variant === 0 ? "root123" : "example-user";
    if (variant === 0) Object.assign(item, {kind: "ssh_failure", title: "SSH authentication failed", verdict: "failure", authMethod: "unknown", rejectionReason: "Username does not exist"});
    else if (variant < 3) Object.assign(item, {kind: variant === 1 ? "ssh_accepted" : "ssh_accepted_unknown",
      title: variant === 1 ? "SSH login accepted" : "SSH accepted: unregistered credential", verdict: "accepted",
      authMethod: "publickey", keyStatus: variant === 1 ? "recognized" : "unregistered",
      keyLabel: variant === 1 ? "Example desktop (synthetic)" : undefined, keyFingerprint: "SHA256:synthetic-demo-fingerprint"});
    else Object.assign(item, {kind: "ssh_disconnect", title: "SSH disconnected before login", verdict: "incomplete", authMethod: "unknown"});
  }
  const variant = Math.floor(i / 8);
  const set = (kind, extra = {}) => Object.assign(item, {kind, title: DEMO_TITLES[kind][0], verdict: DEMO_TITLES[kind][1], ...extra});
  if (type === "plex" && variant > 0) {
    const kind = ["plex_client", "plex_probe", "plex_reachability", "plex_public"][(variant - 1) % 4];
    set(kind, {method: "GET", status: kind === "plex_probe" ? 403 : 200, path: {plex_client: undefined, plex_probe: "/robots.txt", plex_reachability: "/identity", plex_public: "/web/index.html"}[kind]});
  } else if (type === "game" && variant % 2) {
    set("hytale_rejected", {service: "Hytale", protocol: "udp", port: 5205});
  } else if (type === "git" && variant > 0) {
    const kind = ["ssh_failure", "ssh_disconnect", "ssh_probe"][(variant - 1) % 3];
    set(kind, {service: "Forgejo SSH", port: 2222, user: kind === "ssh_failure" ? "root" : undefined, protocol: "tcp"});
  }
  return item;
}
