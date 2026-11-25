import {TYPES, OUTCOMES, SEVERITIES, REPUTATIONS, reputationGrade, severityOf, matchesFilters, facetCounts, mergeEvents, diffEvents, project, duration, liveTrapping, trapDuration, trapTime, trapSince, ago, demoEvents, demoLiveEvent, demoCloseEvent, demoTrapping, FLASH, FOLLOW, isFresh, countryFlag, MAP_DEFAULTS, mapSettings, mapActivity, notDrawn, TYPE_ORDER, SEVERITY_ORDER, slices, slicePath, groupBySource, rateSummary} from "./model.mjs";
import {createMapView, fitView, placeArrival} from "./map-view.mjs";
import {createGlobe, detailLevel, followCenter, prepareGrid} from "./globe.mjs";
import {MAP_FILES} from "./atlas.mjs";
import "./pwa.mjs";

const $ = id => document.getElementById(id);
const demo = new URLSearchParams(location.search).get("demo") === "1";
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
// Live queries, so the per-frame map code never parses a new one.
const coarse = matchMedia("(pointer: coarse)"), narrow = matchMedia("(max-width: 650px)"), hovering = matchMedia("(hover: hover)");
let events = [], world = null, live = true, latest = null, older = null, hasOlder = false;
let generation = 0, busy = false, selected = null, selectedCount = 0, parameters = {range: "24h"};
const errors = new Map(), pulses = new Map(), freshIds = new Set();
const demoLive = [];
let demoSequence = 0;
// Demo events are all generated from one moment, so a given event keeps its time between calls.
let demoBase = Date.now();
const demoFeed = () => mergeEvents(demoLive, demoEvents(demoBase));
let sourceIssues = [];
let trapSample = null, trapReceived = 0, completedTrapSeconds = null, renderedTrap = "";
let highlighted = null;
let dotSettings = {...MAP_DEFAULTS}, catchingUp = false;
const pointNodes = new Map();
const pointData = new WeakMap();
const arrivals = new Map();
let arrivalsOmitted = 0;
let mapShapes = [], mapHidden = {};
let activeDetail = null, wantedDetail = "110m", countryLabels = [];
// Pending arrivals are keyed by source IP, like the markers and cards.
const followQueue = new Map();
let following = false, followZoom = FOLLOW.zoom, followHold = 0, followStatusTimer = 0;
const atlas = new Map(), atlasPending = new Set(), atlasFailed = new Map();
const globe = createGlobe();
const isGlobe = () => $("projection").value === "globe";
const SVG = "http://www.w3.org/2000/svg";

$("projection").value = coarse.matches ? "globe" : "equal-earth";
try {
  const saved = localStorage.getItem("attacks.map-projection");
  if (saved) {
    if (!["globe", "equal-earth", "rectangular"].includes(saved)) throw new Error("Unrecognized projection");
    $("projection").value = saved;
  }
} catch (error) {
  errors.set("projection", `Saved projection could not be loaded; the device default is active. ${error.message}`);
}

try {
  const saved = localStorage.getItem("attacks.map-settings");
  if (saved) dotSettings = mapSettings(JSON.parse(saved));
} catch (error) {
  errors.set("mapSettings", `Saved map settings could not be loaded; defaults are active. ${error.message}`);
}

try {
  following = localStorage.getItem("attacks.map-follow") === "1";
} catch (error) {
  errors.set("follow", `Saved follow setting could not be loaded; follow starts off. ${error.message}`);
}
$("map-follow").setAttribute("aria-pressed", String(following));

function node(tag, value, className) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
}

// Per-frame map code writes only what changed, so a rotation never invalidates layout for nothing.
function setText(element, text) { if (element.textContent !== text) element.textContent = text; }

function counter(id, value) {
  const element = $(id), text = String(value), previous = element.dataset.counterText;
  if (previous === text) return;
  element.dataset.counterText = text;
  const parts = text.split(/(\d[\d,.:/]*)/), before = (previous || "").split(/(\d[\d,.:/]*)/);
  const content = parts.map((part, index) => {
    if (index % 2 === 0) return document.createTextNode(part);
    const token = node("span", undefined, "number-token");
    // One real text value for selection and assistive technology; the reels are visual only.
    token.append(node("span", part, "number-value"));
    const old = before[index] || "";
    for (const [position, character] of [...part].entries()) {
      const digit = /\d/.test(character), from = old[position + old.length - part.length];
      const glyph = node("span", undefined, digit ? "number-digit" : "number-separator");
      glyph.setAttribute("aria-hidden", "true");
      glyph.dataset.digit = character;
      if (digit && /\d/.test(from || "") && from !== character && !reduced.matches) {
        glyph.dataset.from = from;
        glyph.classList.add("rolling");
        glyph.addEventListener("animationend", () => {
          glyph.classList.remove("rolling");
          delete glyph.dataset.from;
        }, {once: true});
      }
      token.append(glyph);
    }
    return token;
  });
  element.replaceChildren(...content);
}

reduced.addEventListener("change", () => {
  if (reduced.matches) for (const glyph of document.querySelectorAll(".number-digit.rolling")) {
    glyph.classList.remove("rolling");
    delete glyph.dataset.from;
  }
});

if (demo) $("map-panel").querySelector(".panel-top>div").append(node("span", "Synthetic demo", "badge map-demo"));

function notices() {
  const messages = [...errors.values(), ...sourceIssues];
  if (demo) messages.unshift("DEMO · All events, addresses, locations, and statistics on this preview are synthetic. No live telemetry is connected.");
  $("notice").hidden = !messages.length;
  $("notice").textContent = messages.join(" · ");
  $("health").textContent = demo ? "Synthetic demo" : messages.length ? "Collection issues" : latest ? (live ? catchingUp ? "Catching up" : "Live observation" : "Feed paused") : "Connecting";
  $("health").classList.toggle("error", !!messages.length && !demo);
}

function locationLabel(item) {
  const line = node("span", undefined, "location-line");
  const flag = countryFlag(item.countryCode);
  if (flag) {
    const icon = node("span", flag, "country-flag");
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", `${item.countryCode} country flag`);
    line.append(icon);
  }
  line.append(node("span", item.location || "Location unavailable", "event-secondary"));
  return line;
}

function networkBadges(item) {
  const badges = node("span", undefined, "badges network-badges");
  const owner = item.networkProvider || item.networkOrganization;
  const provider = node("span", owner || (item.asn ? `AS${item.asn}` : "Network unknown"), "badge network-owner");
  provider.title = item.networkOrganization || "No network attribution available";
  badges.append(provider);
  if (item.asn && owner) badges.append(node("span", `AS${item.asn}`, "badge"));
  const reputation = reputationBadge(item);
  if (reputation) badges.append(reputation);
  if (item.reputation?.reportedAt) {
    const reported = node("span", "Reported by us", "badge reputation-reported");
    reported.title = `Reported to AbuseIPDB by this server ${new Date(item.reputation.reportedAt * 1000).toLocaleString()}`;
    badges.append(reported);
  }
  for (const service of item.privacyServices || []) {
    const badge = node("span", service.kind === "tor_exit" ? "Tor exit" : `VPN server · ${service.name}`, "badge privacy-service");
    badge.title = service.evidence;
    badges.append(badge);
  }
  return badges;
}

function reputationBadge(item) {
  const value = item.reputation;
  if (!value || value.score === undefined) return null;
  const level = value.score >= 50 ? "high" : value.score > 0 ? "medium" : "clean";
  const badge = node("span", `AbuseIPDB ${value.score}%`, `badge reputation reputation-${level}`);
  badge.title = `AbuseIPDB confidence ${value.score}%: ${value.reports.toLocaleString()} reports from ${value.users.toLocaleString()} users in 90 days`;
  return badge;
}

function reputationField(value) {
  if (!value) return undefined;
  const lines = [];
  if (value.score !== undefined) {
    lines.push(`${value.score}% abuse confidence; ${value.reports.toLocaleString()} reports from ${value.users.toLocaleString()} users in 90 days`);
    if (value.lastReportedAt) lines.push(`Last reported ${new Date(value.lastReportedAt).toLocaleString()}`);
    if (value.usage) lines.push(`Usage: ${value.usage}`);
    if (value.tor) lines.push("Tor exit node");
    if (value.whitelisted) lines.push("Whitelisted by AbuseIPDB");
    lines.push(`Checked ${new Date(value.checkedAt * 1000).toLocaleString()}`);
  }
  if (value.reportedAt) lines.push(`Reported by this server ${new Date(value.reportedAt * 1000).toLocaleString()}`);
  return lines.join("\n");
}

async function request(path, params = {}) {
  const response = await fetch(`${path}?${new URLSearchParams(params)}`, {cache: "no-store", signal: AbortSignal.timeout(15000), redirect: "error"});
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error || `Telemetry unavailable (${response.status}); sign in again if your session expired.`);
  }
  if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("Authentication required or unexpected response. Reload to sign in.");
  return response.json();
}

function severityBadge(item) {
  const level = severityOf(item), [, label, hint] = SEVERITIES.find(([value]) => value === level);
  const badge = node("span", label, `badge severity severity-${level}`);
  badge.title = `Severity ${label}: ${hint}`;
  return badge;
}

const SEVERITY_LABELS = Object.fromEntries(SEVERITIES.map(([level, label]) => [level, label]));

// A source's kinds and severities, listed in the same clockwise order as its dot slices and ring arcs.
function sourceMix(source) {
  const kinds = slices(source.types, TYPE_ORDER), levels = slices(source.severities, SEVERITY_ORDER);
  return kinds.length > 1 || levels.length > 1 ? {kinds, levels} : null;
}

function mixBadges(source) {
  const mix = sourceMix(source);
  if (!mix) return [];
  const kinds = node("span", undefined, "badges mix"), levels = node("span", undefined, "badges mix");
  for (const {key, count} of mix.kinds) {
    const badge = node("span", undefined, `badge type-${key}`);
    badge.append(node("span", undefined, "legend-dot"), `${count} ${TYPES[key].label}`);
    kinds.append(badge);
  }
  for (const {key, count} of mix.levels) levels.append(node("span", `${count} ${SEVERITY_LABELS[key]}`, `badge severity severity-${key}`));
  return [kinds, levels];
}

function mixText(source) {
  const mix = sourceMix(source);
  if (!mix) return "";
  const list = (parts, label) => parts.map(({key, count}) => `${count} ${label(key)}`).join(", ");
  return ` Mix: ${list(mix.kinds, key => TYPES[key].label)}. Severity: ${list(mix.levels, key => SEVERITY_LABELS[key])}.`;
}

const trapElapsed = () => performance.now() - trapReceived;

// How long Endlessh held, or is still holding, the connection behind an event; null for anything else.
const trapOf = item => trapTime(item, events, trapSample, trapElapsed());

// The running time of a connection that is still held; the 1 s tick keeps it moving.
function trapClock(trap) {
  const clock = node("span", trapDuration(Math.floor(trap.seconds)));
  clock.dataset.trapSince = String(trap.since);
  return clock;
}

// Says how long a client was held, but only when the log or live telemetry actually shows it.
function trapBadge(item, trap = trapOf(item)) {
  if (trap?.state === "ended") return node("span", `Trapped for ${trapDuration(trap.seconds)}`, "badge trap");
  if (trap?.state !== "active") return null;
  const badge = node("span", undefined, "badge trap live");
  badge.append(node("span", undefined, "legend-dot"), "Trapped now · ", trapClock(trap));
  return badge;
}

function trapBadges(item) {
  const badge = trapBadge(item);
  if (!badge) return [];
  const row = node("span", undefined, "badges");
  row.append(badge);
  return [row];
}

// Telemetry that is recent enough to say who is still held; older samples stop vouching for anyone.
const trapLive = () => Boolean(liveTrapping(trapSample, trapElapsed())) && Number.isFinite(trapSample.asOf);

// What the trapped badges depend on besides the loaded events: whether telemetry can be trusted, and who it lists.
function trapKey() {
  if (!trapLive()) return "";
  return `${trapSample.activeTruncated}|${(trapSample.active || []).map(row => `${row.ip}|${row.sourcePort}|${row.since}`).join(",")}`;
}

// What an event's trapped badge currently says, so an open tooltip, dialog or stream row can tell when it has gone stale.
function trapSignature(item, trap = trapOf(item)) {
  return !trap ? "" : trap.state === "ended" ? `ended|${trap.seconds}` : trap.state;
}

// Redraws whatever shows trapped time once the connections it describes change, instead of waiting for the next event poll.
function syncTrap() {
  if (events.length && trapKey() !== renderedTrap) render();
  const tip = $("map-tooltip"), point = tip.hidden ? null : pointNodes.get(tip.dataset.sourceIp), source = point && pointData.get(point);
  if (source && trapSignature(source.latest) !== tip.dataset.trap) tooltip(point);
  if ($("detail").open && selected && trapSignature(selected) !== $("detail").dataset.trap) detail(selected, selectedCount);
}

// Runs every second: moves the clocks of connections still held, and drops them from cards once telemetry is too old to vouch for them.
function tickTrapping() {
  syncTrap();
  const clocks = document.querySelectorAll("[data-trap-since]");
  if (!clocks.length) return;
  if (!trapLive()) {
    for (const clock of document.querySelectorAll("#map-arrivals [data-trap-since]")) clock.closest(".badges")?.remove();
    return;
  }
  const elapsed = trapElapsed();
  for (const clock of clocks) setText(clock, trapDuration(Math.floor(trapSince(trapSample, elapsed, Number(clock.dataset.trapSince)))));
}

// Rows are rebuilt only when their event or its trapped state changes, so a redraw touches just what moved.
const rowCache = new WeakMap();

function eventRow(item) {
  const trap = trapOf(item), key = trapSignature(item, trap), cached = rowCache.get(item);
  if (cached?.key === key) return cached.row;
  const row = node("button", undefined, "event-row");
  row.type = "button";
  row.dataset.eventId = item.id;
  row.addEventListener("click", () => detail(item));
  const time = node("time", new Date(item.timestamp * 1000).toLocaleTimeString([], {hour12: false}));
  time.dateTime = new Date(item.timestamp * 1000).toISOString();
  time.title = new Date(item.timestamp * 1000).toLocaleString();
  const classification = node("span", undefined, "event-cell");
  classification.append(node("span", item.title, "event-primary"));
  const badges = node("span", undefined, "badges");
  const category = node("span", undefined, `badge type-${item.type}`);
  category.append(node("span", undefined, "legend-dot"), node("span", TYPES[item.type].label));
  badges.append(severityBadge(item), category, node("span", item.verdict, `badge verdict-${item.verdict}`));
  const trapped = trapBadge(item, trap);
  if (trapped) badges.append(trapped);
  if (item.origin === "own") badges.append(node("span", "Own", "badge origin-own"));
  if (item.keyStatus) badges.append(node("span", item.keyStatus === "recognized" ? "known key" : "unregistered key", `badge key-${item.keyStatus}`));
  classification.append(badges);
  const source = node("span", undefined, "event-cell");
  source.append(node("span", item.ip, "event-primary mono"), locationLabel(item), networkBadges(item));
  const extra = node("span", undefined, "event-cell event-detail");
  const target = item.user ? `user: ${item.user}` : item.path || item.service;
  extra.append(node("span", target, "event-primary mono"),
    node("span", item.host || `port ${item.port}`, "event-secondary"));
  row.append(time, classification, source, extra, node("span", "↗", "event-arrow"));
  rowCache.set(item, {key, row});
  return row;
}

// Puts a container's children in the order of `rows`, moving or inserting only what differs.
function syncRows(container, rows) {
  const keep = new Set(rows);
  for (const child of [...container.children]) if (!keep.has(child)) child.remove();
  let next = container.firstElementChild;
  for (const row of rows) {
    if (row === next) next = next.nextElementSibling;
    else container.insertBefore(row, next);
  }
}

// Grouped mode bundles the stream per source; open groups and their elements survive redraws.
let grouped = localStorage.getItem("attacks.group-sources") === "1";
const openGroups = new Set(), groupCache = new Map();

function countBadges(group) {
  const kinds = node("span", undefined, "badges"), levels = node("span", undefined, "badges");
  for (const {key, count} of slices(group.types, TYPE_ORDER)) {
    const badge = node("span", undefined, `badge type-${key}`);
    badge.append(node("span", undefined, "legend-dot"), `${count} ${TYPES[key].label}`);
    kinds.append(badge);
  }
  for (const {key, count} of slices(group.severities, SEVERITY_ORDER)) levels.append(node("span", `${count} ${SEVERITY_LABELS[key]}`, `badge severity severity-${key}`));
  return [kinds, levels];
}

function groupRow(group) {
  const key = `${group.count}|${group.latest.id}|${group.first.id}|${JSON.stringify(group.latest.reputation || null)}`;
  let cached = groupCache.get(group.ip);
  if (!cached) {
    const element = node("details", undefined, "source-group");
    element.dataset.sourceIp = group.ip;
    element.open = openGroups.has(group.ip);
    const summary = node("summary", undefined, "event-row source-summary"), body = node("div", undefined, "source-events");
    element.append(summary, body);
    element.addEventListener("toggle", () => {
      if (element.open) openGroups.add(group.ip); else openGroups.delete(group.ip);
      fillGroup(cached);
    });
    groupCache.set(group.ip, cached = {element, summary, body});
  }
  cached.group = group;
  if (cached.key !== key) {
    cached.key = key;
    const item = group.latest, at = new Date(item.timestamp * 1000);
    const time = node("time", at.toLocaleTimeString([], {hour12: false}));
    time.dateTime = at.toISOString();
    time.title = `Latest ${at.toLocaleString()}`;
    const counts = node("span", undefined, "event-cell");
    counts.append(node("span", `${group.count.toLocaleString()} ${group.count === 1 ? "event" : "events"}`, "event-primary"), ...countBadges(group));
    const source = node("span", undefined, "event-cell");
    source.append(node("span", group.ip || "Unknown source", "event-primary mono"), locationLabel(item), networkBadges(item));
    const extra = node("span", undefined, "event-cell event-detail");
    const targets = new Set(group.events.map(event => event.user ? `user: ${event.user}` : event.path || event.service));
    extra.append(node("span", targets.size > 1 ? `${targets.size} targets` : [...targets][0] || "", "event-primary mono"),
      node("span", group.count > 1 ? `since ${new Date(group.first.timestamp * 1000).toLocaleString([], {hour12: false})}` : item.host || `port ${item.port}`, "event-secondary"));
    cached.summary.replaceChildren(time, counts, source, extra, node("span", "›", "event-arrow group-chevron"));
  }
  fillGroup(cached);
  return cached.element;
}

// A group's own rows are only built while it is open.
function fillGroup(cached) {
  if (!cached.element.open) { cached.body.replaceChildren(); return; }
  syncRows(cached.body, cached.group.events.map(item => {
    const row = eventRow(item);
    row.classList.toggle("highlighted", item.id === highlighted);
    return row;
  }));
}

function render() {
  renderedTrap = trapKey();
  const container = $("events");
  container.classList.toggle("grouped", grouped);
  const focusedId = container.contains(document.activeElement) ? document.activeElement.dataset.eventId : null;
  let groups = [];
  if (grouped) {
    groups = groupBySource(events);
    const present = new Set(groups.map(group => group.ip));
    for (const ip of groupCache.keys()) if (!present.has(ip)) { groupCache.delete(ip); openGroups.delete(ip); }
    if (groups.length === 1 && !groupCache.has(groups[0].ip)) openGroups.add(groups[0].ip);
    syncRows(container, groups.map(groupRow));
  } else {
    groupCache.clear();
    syncRows(container, events.map(item => {
      const row = eventRow(item);
      row.classList.toggle("highlighted", item.id === highlighted);
      return row;
    }));
  }
  if (focusedId) container.querySelector(`[data-event-id="${CSS.escape(focusedId)}"]`)?.focus({preventScroll: true});
  $("empty").hidden = events.length > 0;
  $("empty").textContent = errors.has("feed") ? "Events unavailable. Check collection health above." : "No matching events in this observation window.";
  counter("feed-count", grouped ? `${groups.length} ${groups.length === 1 ? "source" : "sources"} · ${events.length} events` : `${events.length} shown`);
  $("older").hidden = !hasOlder || demo || events.length >= 1000;
  mapPoints();
}

function setGrouped(value, draw = true) {
  grouped = value;
  localStorage.setItem("attacks.group-sources", value ? "1" : "0");
  $("group").setAttribute("aria-pressed", String(value));
  $("group").textContent = value ? "Show all events" : "Group by source";
  if (draw) render();
}

function trapField(item) {
  const trap = trapOf(item);
  if (!trap) return undefined;
  if (trap.state === "ended") return trapDuration(trap.seconds);
  if (trap.state === "unknown") {
    return "Unknown. No matching close was logged, and live connection data can't confirm it is still open (own traffic is not tracked; restarts and lost log lines leave gaps).";
  }
  const field = node("span");
  field.append(trapClock(trap), " so far · still connected");
  return field;
}

function detail(item, sourceCount) {
  hideTooltip();
  selected = item; selectedCount = sourceCount;
  $("detail").dataset.trap = trapSignature(item);
  $("detail-title").textContent = item.title;
  const fields = {
    "Source activity": sourceCount > 1 ? `${loadedEvents(sourceCount)}; showing the latest. View this source's events below.` : undefined,
    "Event time": new Date(item.timestamp * 1000).toLocaleString(),
    "Collected": new Date(item.observedAt * 1000).toLocaleString(),
    "Classification": item.verdict, "Severity": `${severityBadge(item).textContent}: ${SEVERITIES.find(([value]) => value === severityOf(item))[2]}`,
    "Traffic": item.origin === "own" ? "Own network (not proof of who is using it)" : "External",
    "Source IP": item.ip, "Approx. location": item.location,
    "Evidence": item.reason,
    "Network owner": item.networkOrganization, "ASN": item.asn ? `AS${item.asn}` : undefined,
    "Cloud / provider": item.networkProvider, "Network evidence": item.networkEvidence,
    "Network sources": item.networkSources?.join("\n"),
    "ASN data updated": item.asnUpdatedAt ? new Date(item.asnUpdatedAt * 1000).toLocaleString() : undefined,
    "Range data checked": item.networkUpdatedAt ? new Date(item.networkUpdatedAt * 1000).toLocaleString() : undefined,
    "VPN / relay": item.networkLookup === "not-public" ? "Not applicable (private / reserved address)"
      : item.privacyServices?.length ? item.privacyServices.map(service =>
        `${service.name}: ${service.evidence}\nDataset checked: ${new Date(service.updatedAt * 1000).toLocaleString()}${service.source ? `\n${service.source}` : ""}`).join("\n\n")
      : "Unknown. No listed service matched; this does not establish that the address is not a VPN.",
    "AbuseIPDB": reputationField(item.reputation),
    "Lookup coverage": item.networkLookup || "Not enriched (older event)",
    "Service": item.service, "Destination port": item.port, "Source port": item.sourcePort,
    "Protocol": item.protocol, "Attempted user": item.user, "Auth factor": item.factor,
    "Auth method": item.authMethod, "Rejection reason": item.rejectionReason,
    "Key status": item.keyStatus, "Key label": item.keyLabel, "Key fingerprint": item.keyFingerprint,
    "Host": item.host, "Request path": item.path, "Method": item.method, "HTTP status": item.status,
    "Time stuck": trapField(item),
    "Log source": item.source, "Event ID": item.id,
  };
  $("detail-fields").replaceChildren(...Object.entries(fields).filter(([, value]) => value !== undefined && value !== null && value !== "")
    .flatMap(([key, value]) => {
      const field = node("dd");
      field.append(value instanceof Node ? value : String(value));
      return [node("dt", key), field];
    }));
  $("filter-country").hidden = !item.countryCode;
  $("filter-country").textContent = `Only ${item.countryCode ? countryName(item.countryCode) : "this country"}`;
  $("filter-network").hidden = !item.asn;
  $("filter-network").textContent = `Only AS${item.asn}`;
  // Opens only on click, so no address leaves the page unless asked.
  $("abuse-check").hidden = !item.ip || item.origin === "own" || item.networkLookup === "not-public";
  $("abuse-check").href = `https://www.abuseipdb.com/check/${encodeURIComponent(item.ip || "")}`;
  if (!$("detail").open) {
    document.body.classList.add("detail-open");
    $("detail").showModal();
  }
}
$("close").onclick = () => $("detail").close();
// On phones both bottom sheets close with a downward swipe, as native sheets do. A swipe only starts when the sheet
// is scrolled to its top, so scrolling long content still works; a short or slow pull springs back.
function swipeToDismiss(sheet, dismiss) {
  let start = null, offset = 0, moved = false;
  const motion = () => !matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reset = () => { sheet.style.transition = sheet.style.transform = ""; };
  sheet.addEventListener("touchstart", event => {
    moved = false;
    if (!narrow.matches || event.touches.length !== 1) { start = null; return; }
    start = {y: event.touches[0].clientY, x: event.touches[0].clientX, time: performance.now(), top: sheet.scrollTop <= 0};
    offset = 0;
  }, {passive: true});
  sheet.addEventListener("touchmove", event => {
    if (!start) return;
    const dy = event.touches[0].clientY - start.y, dx = event.touches[0].clientX - start.x;
    if (!moved) {
      if (Math.hypot(dx, dy) < 8) return;
      // Sideways moves (a slider) and upward or mid-content drags stay with the content.
      if (!start.top || sheet.scrollTop > 0 || dy <= 0 || Math.abs(dx) > dy || event.target.closest?.("input[type=range]")) { start = null; return; }
      moved = true; start.y += 8; sheet.style.transition = "none";
    }
    event.preventDefault();
    offset = Math.max(0, event.touches[0].clientY - start.y);
    sheet.style.transform = `translateY(${offset}px)`;
  }, {passive: false});
  const end = () => {
    if (!start || !moved) { start = null; return; }
    const speed = offset / Math.max(1, performance.now() - start.time);
    start = null;
    if (offset > Math.min(120, sheet.offsetHeight / 3) || (offset > 30 && speed > .5)) {
      if (!motion()) { reset(); dismiss(); return; }
      sheet.style.transition = "transform .18s ease-in";
      sheet.style.transform = "translateY(100%)";
      setTimeout(() => { dismiss(); reset(); }, 180);
    } else {
      sheet.style.transition = motion() ? "transform .2s ease-out" : "none";
      sheet.style.transform = "";
      setTimeout(() => { if (!start) reset(); }, 200);
    }
  };
  sheet.addEventListener("touchend", end);
  sheet.addEventListener("touchcancel", end);
  // A swipe that ends over a button must not also press it.
  sheet.addEventListener("click", event => { if (moved) { moved = false; event.preventDefault(); event.stopPropagation(); } }, true);
}
swipeToDismiss($("detail"), () => $("detail").close());
$("detail").addEventListener("close", () => document.body.classList.remove("detail-open"));
$("detail").addEventListener("click", event => { if (event.target === $("detail")) { const box = $("detail").getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) $("detail").close(); } });
async function showEvents(change) {
  hideTooltip();
  for (const picker of document.querySelectorAll(".picker[open]")) picker.open = false;
  if (mapView.expanded()) await mapView.exit();
  await applyFilters(change);
  $("events").scrollIntoView({block: "start"});
  $("events").querySelector(".event-row")?.focus({preventScroll: true});
}
const showSource = ip => showEvents({ip});
$("filter-ip").onclick = () => { $("detail").close(); showSource(selected.ip); };
$("filter-country").onclick = () => { $("detail").close(); showEvents({country: selected.countryCode}); };
$("filter-network").onclick = () => {
  $("detail").close();
  if (selected.networkOrganization) networkNames.set(String(selected.asn), selected.networkOrganization);
  showEvents({asn: String(selected.asn)});
};
$("health").onclick = () => { $("sources").hidden = !$("sources").hidden; };

// Filters live here, not in the form, so the detail dialog and map can set them too.
const filters = {severity: "", type: new Set(), outcome: new Set(), reputation: new Set(), ip: "", country: "", asn: ""};
const SETS = ["type", "outcome", "reputation"];
const networkNames = new Map();
let sourcesKey = "", sourcesAt = 0;
const regionNames = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(undefined, {type: "region"}) : null;

function countryName(code) {
  try { return regionNames?.of(code) || code; } catch { return code; }
}

function filterParameters() {
  const result = {};
  if (filters.severity) result.severity = filters.severity;
  for (const name of SETS) if (filters[name].size) result[name] = [...filters[name]].join(",");
  for (const name of ["ip", "country", "asn"]) if (filters[name]) result[name] = filters[name];
  return result;
}

function activeFilters() {
  const label = (options, values) => options.filter(([value]) => values.has(value)).map(([, text]) => text).join(", ");
  const types = Object.entries(TYPES).map(([value, {label: text}]) => [value, text]);
  const level = SEVERITIES.find(([value]) => value === filters.severity);
  return [
    level && [["severity"], `Severity: ${level[1]} or higher`],
    filters.type.size && [["type"], `Type: ${label(types, filters.type)}`],
    filters.outcome.size && [["outcome"], `Outcome: ${label(OUTCOMES, filters.outcome)}`],
    filters.reputation.size && [["reputation"], `AbuseIPDB: ${label(REPUTATIONS, filters.reputation)}`],
    filters.ip && [["ip"], `IP: ${filters.ip}`],
    filters.country && [["country"], `Country: ${countryName(filters.country)}`],
    filters.asn && [["asn"], `Network: ${networkNames.get(filters.asn) || `AS${filters.asn}`}`],
    $("own").checked && [["own"], "Including own traffic"],
  ].filter(Boolean);
}

function fillSources(select, any, rows, current, currentLabel) {
  const options = [["", any], ...rows];
  if (current && !rows.some(([value]) => value === current)) options.push([current, currentLabel]);
  select.replaceChildren(...options.map(([value, text]) => {
    const option = node("option", text);
    option.value = value;
    return option;
  }));
  select.value = current;
}

function syncFilters() {
  for (const input of $("severity").querySelectorAll("input")) input.checked = input.value === filters.severity;
  for (const name of SETS) for (const input of $(name).querySelectorAll("input")) input.checked = filters[name].has(input.value);
  $("ip").value = filters.ip;
  for (const [id, any, current, label] of [["country", "Any country", filters.country, countryName(filters.country)],
    ["asn", "Any network", filters.asn, networkNames.get(filters.asn) || `AS${filters.asn}`]]) {
    const rows = [...$(id).options].slice(1).map(option => [option.value, option.textContent]);
    fillSources($(id), any, rows, current, label);
  }
  const counts = {"type-picker": filters.type.size, "outcome-picker": filters.outcome.size, "reputation-picker": filters.reputation.size,
    "source-picker": [filters.ip, filters.country, filters.asn].filter(Boolean).length};
  for (const [id, count] of Object.entries(counts)) {
    const badge = $(id).querySelector("summary b");
    badge.textContent = count || "";
    $(id).classList.toggle("active", count > 0);
  }
  const active = activeFilters();
  $("clear-filters").disabled = !active.length;
  $("active-filters").hidden = !active.length;
  $("active-filters").replaceChildren(...active.map(([[name], text]) => {
    const chip = node("button", text, "chip");
    chip.type = "button";
    chip.append(node("span", "✕", "chip-remove"));
    chip.querySelector(".chip-remove").setAttribute("aria-hidden", "true");
    chip.setAttribute("aria-label", `Remove filter ${text}`);
    chip.onclick = () => name === "own" ? ($("own").checked = false, applyFilters())
      : applyFilters({[name]: SETS.includes(name) ? new Set() : ""});
    return chip;
  }));
  renderFacets();
  loadFacets();
}

function applyFilters(change = {}) {
  Object.assign(filters, change);
  syncFilters();
  return load(true);
}

function clearFilters() {
  $("own").checked = false;
  sourcesKey = "";
  return applyFilters({severity: "", type: new Set(), outcome: new Set(), reputation: new Set(), ip: "", country: "", asn: ""});
}

function buildFilters() {
  const segments = [["", "Any", "Every event, including routine ones."], ...SEVERITIES.slice(1)];
  for (const [value, label, hint] of segments) {
    const choice = node("label", undefined, `segment severity-${value || "any"}`);
    const input = node("input");
    Object.assign(input, {type: "radio", name: "severity", value});
    choice.title = hint;
    const text = node("i", undefined, "segment-text");
    text.append(node("b", label), node("small", undefined, "count"));
    choice.append(input, node("span"));
    choice.querySelector("span").append(text);
    $("severity").append(choice);
  }
  const groups = {type: Object.entries(TYPES).map(([value, {label}]) => [value, label]), outcome: OUTCOMES, reputation: REPUTATIONS};
  for (const [name, options] of Object.entries(groups)) for (const [value, label] of options) {
    const choice = node("label", undefined, "choice");
    const input = node("input");
    Object.assign(input, {type: "checkbox", value});
    choice.append(input);
    if (name === "type") choice.append(node("span", undefined, `legend-dot type-${value}`));
    if (name === "reputation") choice.append(node("span", undefined, `legend-dot reputation-${value}`));
    choice.append(node("span", label), node("small", undefined, "count"));
    $(name).append(choice);
  }
}

// Counts for every picker option, grouped server-side by type, outcome and severity for the
// current range and source filters; the pickers themselves are faceted locally (facetCounts).
let facetRows = null, facetsKey = "", facetsAt = 0;
const compact = new Intl.NumberFormat(undefined, {notation: "compact", maximumFractionDigits: 1});

function renderFacets() {
  const counts = facetRows && facetCounts(facetRows, filterParameters());
  const show = (choice, value) => {
    const count = Math.round(value || 0);
    choice.querySelector(".count").textContent = counts ? (count < 10000 ? count.toLocaleString() : compact.format(count)) : "";
    choice.classList.toggle("zero", !!counts && !count);
  };
  for (const input of $("severity").querySelectorAll("input")) show(input.closest("label"), counts?.severity[input.value || SEVERITIES[0][0]]);
  for (const name of SETS) for (const input of $(name).querySelectorAll("input")) show(input.closest("label"), counts?.[name][input.value]);
}

function demoFacets(scope) {
  const rows = new Map();
  for (const item of demoFeed().filter(item => matchesFilters(item, scope))) {
    const row = {type: item.type, outcome: item.verdict, severity: severityOf(item), reputation: reputationGrade(item), reported: !!item.reputation?.reportedAt};
    const key = Object.values(row).join("|");
    rows.set(key, {...row, count: (rows.get(key)?.count || 0) + 1});
  }
  return {reputation: true, counts: [...rows.values()]};
}

async function loadFacets() {
  const scope = {range: $("range").value};
  for (const name of ["ip", "country", "asn"]) if (filters[name]) scope[name] = filters[name];
  if ($("own").checked) scope.own = "1";
  const key = JSON.stringify(scope);
  if (facetsKey === key && performance.now() - facetsAt < 25000) return;
  if (facetsKey !== key) { facetRows = null; renderFacets(); }
  facetsKey = key; facetsAt = performance.now();
  try {
    const result = demo ? demoFacets(scope) : await request("/api/facets", scope);
    if (key !== facetsKey) return;
    facetRows = result.counts;
    reputationAvailable(result.reputation === true);
  } catch {
    if (key !== facetsKey) return;
    facetRows = null; facetsAt = 0;
  }
  renderFacets();
}

// The AbuseIPDB filter only exists while the server can apply it (a key is configured).
function reputationAvailable(available) {
  $("reputation-picker").hidden = !available;
  if (!available && filters.reputation.size) applyFilters({reputation: new Set()});
}

function demoSources() {
  const count = (key, extra) => [...Map.groupBy(demoFeed().filter(item => item.origin !== "own" && item[key]), item => item[key])]
    .map(([value, rows]) => ({[key]: String(value), ...extra?.(rows[0]), count: rows.length})).sort((a, b) => b.count - a.count).slice(0, 12);
  return {countries: count("countryCode"), networks: count("asn", item => ({networkOrganization: item.networkOrganization}))};
}

async function loadSources() {
  const range = $("range").value, own = $("own").checked;
  const key = `${range}|${own}`;
  if (sourcesKey === key && performance.now() - sourcesAt < 60000) return;
  sourcesKey = key; sourcesAt = performance.now();
  try {
    const result = demo ? demoSources() : await request("/api/sources", own ? {range, own: "1"} : {range});
    if (key !== `${$("range").value}|${$("own").checked}`) return;
    for (const row of result.networks) networkNames.set(row.asn, row.networkOrganization || `AS${row.asn}`);
    const amount = row => ` · ${Math.round(row.count).toLocaleString()}`;
    fillSources($("country"), "Any country", result.countries.map(row => [row.countryCode, countryName(row.countryCode) + amount(row)]),
      filters.country, countryName(filters.country));
    fillSources($("asn"), "Any network", result.networks.map(row => [row.asn, `${row.networkOrganization || "Unknown"} (AS${row.asn})${amount(row)}`]),
      filters.asn, networkNames.get(filters.asn) || `AS${filters.asn}`);
    $("source-note").textContent = "Top countries and networks by event count in the selected period.";
  } catch (error) {
    sourcesKey = "";
    $("source-note").textContent = `Country and network lists are unavailable: ${error.message}`;
  }
}

function commitIp() {
  const value = $("ip").value.trim();
  if (value !== filters.ip) applyFilters({ip: value});
}

buildFilters();
$("severity").onchange = event => applyFilters({severity: event.target.value});
for (const name of SETS) $(name).onchange = event => {
  const next = new Set(filters[name]);
  event.target.checked ? next.add(event.target.value) : next.delete(event.target.value);
  applyFilters({[name]: next});
};
$("country").onchange = event => applyFilters({country: event.target.value});
$("asn").onchange = event => {
  const option = event.target.selectedOptions[0];
  if (option?.value) networkNames.set(option.value, option.textContent.replace(/ \(AS\d+\).*$/, ""));
  applyFilters({asn: event.target.value});
};
$("ip").onchange = commitIp;
$("filters").onsubmit = event => { event.preventDefault(); commitIp(); };
$("clear-filters").onclick = clearFilters;
// One menu at a time; click-away and Escape close it.
for (const picker of document.querySelectorAll(".picker")) picker.addEventListener("toggle", () => {
  if (!picker.open) return;
  for (const other of document.querySelectorAll(".picker[open]")) if (other !== picker) other.open = false;
  if (picker.id === "source-picker") loadSources();
});
document.addEventListener("pointerdown", event => {
  for (const picker of document.querySelectorAll(".picker[open]")) if (!picker.contains(event.target)) picker.open = false;
});
$("filters").addEventListener("keydown", event => {
  const open = event.key === "Escape" && document.querySelector(".picker[open]");
  if (!open) return;
  open.open = false;
  open.querySelector("summary").focus();
});

// Demo only: a simulated Endlessh connection is let go after a few seconds to a minute, like a scanner giving up.
function demoClose(open) {
  const seconds = Math.round((4 + Math.random() * 40) * 10) / 10;
  setTimeout(() => {
    const close = demoCloseEvent(open, seconds);
    demoLive.unshift(close);
    demoLive.length = Math.min(demoLive.length, 200);
    if (!live || !matchesFilters(close, parameters)) return;
    events = mergeEvents(events, [close]);
    if (document.hidden) return;
    freshIds.add(close.id);
    render();
  }, seconds * 1000);
}

// Demo only: simulate scanners arriving every few seconds, with occasional bursts.
function demoArrivals() {
  setTimeout(demoArrivals, 2500 + Math.random() * 3500);
  if (document.hidden || !live || busy) return;
  const count = Math.random() < 0.12 ? 3 + Math.floor(Math.random() * 4) : 1;
  const now = Date.now(), fresh = [];
  for (let i = 0; i < count; i++) fresh.push(demoLiveEvent(++demoSequence, now + i));
  demoLive.unshift(...fresh.toReversed());
  demoLive.length = Math.min(demoLive.length, 200);
  for (const item of fresh) if (item.kind === "endlessh_open") demoClose(item);
  const shown = fresh.filter(item => matchesFilters(item, parameters));
  if (!shown.length) return;
  events = mergeEvents(events, shown);
  for (const item of shown) freshIds.add(item.id);
  render();
}

async function load(reset = false, history = false) {
  if ((busy && !reset) || (!live && !reset && !history)) return;
  const epoch = reset ? ++generation : generation;
  busy = true;
  // A poll that finds nothing new leaves the list alone; a reset or an older page always redraws it.
  let redraw = reset || history;
  if (reset) {
    parameters = {range: $("range").value, ...filterParameters()};
    if ($("own").checked) parameters.own = "1";
    events = []; latest = null; older = null; highlighted = null; catchingUp = false; pulses.clear(); freshIds.clear();
    followQueue.clear();
    for (const {node} of arrivals.values()) node.remove();
    arrivals.clear(); arrivalsOmitted = 0;
  }
  try {
    if (demo) {
      demoBase = Date.now();
      events = demoFeed().filter(item => matchesFilters(item, parameters));
      // The demo's live list is built from the same events, so every open connection's start matches its row.
      trapSample = demoTrapping(demoFeed(), demoBase / 1000); trapReceived = performance.now();
      latest = "demo";
      redraw = true;
      if (reset) for (const item of events) if (isFresh(item, FLASH.loadWindow)) freshIds.add(item.id);
    } else {
      const query = {...parameters};
      if (history && older) query.before = older;
      else if (latest) query.after = latest;
      for (let page = 0; page < (reset || history ? 1 : 8); page++) {
        const result = await request("/api/events", query);
        if (epoch !== generation) return;
        const {added, revised} = diffEvents(events, result.events);
        // Server time keeps freshness correct when this device's clock is off.
        if (!history) for (const item of added) if (isFresh(item, reset ? FLASH.loadWindow : FLASH.liveWindow, result.queriedAt)) freshIds.add(item.id);
        // Events already loaded keep their objects, so their rows survive the redraw untouched.
        if (added.length || revised.length) { events = mergeEvents(events, [...added, ...revised]); redraw = true; }
        if (reset || history) { older = result.next; hasOlder = result.more; }
        if (!history) {
          // Inclusive overlap tolerates normal log-delivery delay; IDs remove replays.
          catchingUp = result.more && !!query.after;
          latest = catchingUp ? String(BigInt(result.next) + 1n) : String(BigInt(result.latest) - 15000000000n);
        }
        if (reset || history || !catchingUp) break;
        query.after = latest;
      }
      if (errors.delete("feed")) redraw = true;
    }
    if (redraw) render();
  } catch (error) {
    if (epoch === generation) { errors.set("feed", error.message); render(); }
  } finally {
    if (epoch === generation) { busy = false; notices(); }
  }
}

// With an AbuseIPDB key the card counts our reports; without one it falls back to failed sign-ins.
function reportCard(result, failures) {
  const abuse = result.abuse;
  if (!abuse?.enabled) {
    $("report-label").textContent = "FAILED SIGN-INS";
    $("report-card").title = "";
    counter("failures", result.available ? Math.round(failures).toLocaleString() : "—");
    counter("report-detail", "Real SSH + Authelia");
    return;
  }
  $("report-label").textContent = "REPORTED TO ABUSEIPDB";
  $("report-card").title = "Abuse reports this server submitted to AbuseIPDB in the selected window, and the share of external sources seen in the window that they covered. An address is reported at most once a day.";
  if (abuse.error) {
    counter("failures", "—");
    counter("report-detail", abuse.error);
    return;
  }
  counter("failures", abuse.reports.toLocaleString());
  const seen = result.sources || 0, share = seen ? Math.min(100, abuse.sources / seen * 100) : 0;
  const percent = !abuse.sources ? "0%" : share < 1 ? "<1%" : `${Math.round(share)}%`;
  counter("report-detail", `${percent} of ${seen.toLocaleString()} ${seen === 1 ? "source" : "sources"} seen`);
}

async function stats() {
  const period = $("range").value;
  try {
    const result = demo ? {available: true, totals: [{kind: "endlessh_open", value: 6821}, {kind: "ssh_failure", value: 143}, {kind: "auth_failure", value: 12}, {kind: "http_probe", value: 924}], trappedSeconds: 184800, lifetimeTrappedSeconds: 2064000,
      sources: 412, abuse: {enabled: true, reports: 57, sources: 49},
      trapping: demoTrapping(demoFeed(), Date.now() / 1000),
      timeline: Array.from({length: 120}, (_, i) => [i, String(5 + (Math.sin(i * 1.9) + 1) * 7 + (i % 29 === 0 ? 30 : 0))])}
      : await request("/api/stats", {range: period});
    if (period !== $("range").value) return;
    const sum = result.totals.reduce((total, item) => total + item.value, 0);
    const failures = result.totals.filter(item => ["ssh_failure", "auth_failure"].includes(item.kind)).reduce((total, item) => total + item.value, 0);
    counter("total", result.available ? Math.round(sum).toLocaleString() : "—");
    reportCard(result, failures);
    trapSample = result.trapping; trapReceived = performance.now(); completedTrapSeconds = result.trappedSeconds;
    updateTrapping();
    syncTrap();
    const since = new Date(trapSample.since * 1000).toLocaleString();
    counter("trapped-lifetime", `${duration(result.lifetimeTrappedSeconds)} completed external · since ${since}`);
    $("metric-status").textContent = rateLabel(result.timeline, period);
    $("metric-status").title = demo ? "Synthetic preview" : "Loki · logged events per minute, own traffic excluded";
    spark(result.timeline);
    errors.delete("metrics");
  } catch (error) {
    if (period !== $("range").value) return;
    for (const id of ["total", "failures", "trapped"]) counter(id, "—");
    trapSample = null;
    syncTrap();
    counter("trapping-now", "Live trapping unavailable");
    counter("trapped-lifetime", "Completed Endlessh connection time");
    $("metric-status").textContent = "Metrics unavailable";
    spark([]);
    errors.set("metrics", error.message);
  }
  notices();
}

function updateTrapping() {
  if (!trapSample) return;
  const active = liveTrapping(trapSample, performance.now() - trapReceived);
  counter("trapped", duration(completedTrapSeconds + (active?.seconds || 0)));
  counter("trapping-now", active ? `${active.connections} trapped now · ${duration(active.seconds)} ongoing`
    : "Completed only · live trapping unavailable");
}

async function health() {
  if (demo) { $("source-list").textContent = "Synthetic preview. No collectors are connected."; return; }
  try {
    const result = await request("/api/status");
    sourceIssues = [];
    const cards = [];
    const lookupSources = Object.fromEntries(Object.entries(result.networks?.feeds || {}).map(([name, value]) => [`network:${name}`, value]));
    for (const [name, source] of Object.entries({...result.sources, geo: result.geo, sshKeys: result.sshKeys, ownTraffic: result.ownTraffic,
      ...(result.abuseipdb ? {abuseipdb: result.abuseipdb} : {}),
      ...(result.networks ? {asn: result.networks.asn} : {}), ...lookupSources})) {
      const message = source.message || (source.lagSeconds > 90 ? `Catching up: ${Math.round(source.lagSeconds)}s behind` : "Ready; a quiet source can have no matching events");
      const issue = !["ready", "disabled"].includes(source.state) || source.lagSeconds > 90;
      const card = node("div", `${name} · ${issue ? source.state === "ready" ? "catching up" : source.state : source.state === "disabled" ? "off" : "ready"}`, `source-card${issue ? " error" : ""}`);
      card.append(node("small", message));
      cards.push(card);
      if (issue) sourceIssues.push(`${name}: ${message}`);
    }
    if (result.capture?.suppressed) cards.push(node("div", `${result.capture.suppressed.toLocaleString()} repeated/rate-limited packet observations suppressed since capture start`, "source-card"));
    if (result.startedAt) cards.push(node("div", `Collection began ${new Date(result.startedAt * 1000).toLocaleString()}`, "source-card"));
    if (result.sources.npm?.bootstrapSkippedBytes) cards.push(node("div", `${result.sources.npm.bootstrapSkippedBytes.toLocaleString()} older NPM bytes skipped during initial bootstrap; earlier history is incomplete`, "source-card"));
    $("source-list").replaceChildren(...cards);
    errors.delete("health");
  } catch (error) {
    errors.set("health", error.message);
    $("source-list").textContent = "Collector status unavailable. Previously displayed health cannot be trusted.";
  }
  notices();
}

function size(canvas) {
  const box = canvas.getBoundingClientRect(), ratio = Math.min(devicePixelRatio || 1, 2);
  const w = Math.round(box.width * ratio), h = Math.round(box.height * ratio);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, box.width, box.height);
  return {ctx, width: box.width, height: box.height};
}

function rateLabel(timeline, period) {
  const summary = rateSummary(timeline);
  if (!summary) return "No events in window";
  const rate = value => value < 10 ? value.toFixed(1) : Math.round(value).toLocaleString();
  const long = period === "7d" || period === "30d";
  const at = new Date(summary.peakAt * 1000).toLocaleString([], long ? {month: "short", day: "numeric", hour: "numeric"} : {hour: "numeric", minute: "2-digit"});
  return `Peak ${rate(summary.peak)} at ${at} · mean ${rate(summary.mean)} · median ${rate(summary.median)}`;
}

function spark(values) {
  const {ctx, width, height} = size($("spark"));
  const points = values.map(([, value]) => Number(value));
  if (!points.length) return;
  const max = Math.max(...points.filter(Number.isFinite), 1);
  ctx.strokeStyle = "#8bdcd4"; ctx.lineWidth = 1.4; ctx.beginPath();
  let gap = true;
  points.forEach((value, i) => {
    if (!Number.isFinite(value)) { gap = true; return; }
    const x = i / Math.max(points.length - 1, 1) * width, y = height - 4 - value / max * (height - 8);
    if (gap) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    gap = false;
  });
  ctx.stroke();
}

function svg(tag, attributes = {}) {
  const element = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function mapProject(longitude, latitude, name = $("projection").value) {
  return project(longitude, latitude, 1000, 500, name);
}

function linePath(coordinates, name) {
  let path = "";
  for (let index = 0; index < coordinates.length; index++) {
    const [x, y] = mapProject(coordinates[index][0], coordinates[index][1], name);
    path += `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
  }
  return path;
}

const landPaths = [], landFeatures = new WeakMap();

function setPath(element, path) {
  const current = element.getAttribute("d");
  if (path !== current && (path || current)) element.setAttribute("d", path);
}

function setTransform(element, value) {
  if (value === null) element.removeAttribute("transform");
  else if (element.getAttribute("transform") !== value) element.setAttribute("transform", value);
}

// Flat maps move by changing the viewBox, so the atlas worker builds each projection's country paths once per detail.
function flatPaths(data, name) {
  return data.flat[name];
}

// The globe is repainted for every rotation and zoom step, so it comes from the painter, clipped to the viewport.
function mapLand() {
  const globeMode = isGlobe(), name = $("projection").value, data = atlas.get(activeDetail);
  let grid = "", scale = null;
  if (globeMode) {
    const unit = globe.aim();
    scale = `scale(${1 / unit})`;
    grid = globe.lines(prepareGrid(activeDetail ?? "110m"));
  } else {
    for (let lon = -180; lon <= 180; lon += 30)
      grid += linePath(Array.from({length: 91}, (_, i) => [lon, -90 + i * 2]), name);
    for (let lat = -60; lat <= 60; lat += 30)
      grid += linePath([[-180, lat], [180, lat]], name);
  }
  if (!$("map-grid").firstChild) $("map-grid").append(svg("path"));
  setPath($("map-grid").firstChild, grid);
  setTransform($("map-grid"), scale);
  setTransform($("map-land"), scale);
  for (const id of ["map-sphere", "map-shading"]) {
    $(id).toggleAttribute("hidden", !globeMode);
    if (globeMode) setPath($(id), globe.sphere());
  }
  const features = world?.features || [];
  while (landPaths.length > features.length) landPaths.pop().remove();
  while (landPaths.length < features.length) {
    const country = svg("path");
    country.append(svg("title"));
    landPaths.push(country);
    $("map-land").append(country);
  }
  const flat = !globeMode && data ? flatPaths(data, name) : null;
  for (let index = 0; index < features.length; index++) {
    const country = landPaths[index], feature = features[index];
    setPath(country, globeMode ? globe.shape(mapShapes[index]) : flat?.[index] ?? "");
    // A shape's index maps to a different country once the detail changes.
    if (landFeatures.get(country) !== feature) {
      landFeatures.set(country, feature);
      country.dataset.country = feature.id;
      country.firstChild.textContent = feature.properties.name;
    }
  }
}

function activateAtlas(level) {
  if (activeDetail === level) return;
  const data = atlas.get(level);
  world = data.world; mapShapes = data.shapes;
  activeDetail = level;
  countryLabels = data.labels;
  mapLand(); positionCountryLabels();
}

const DETAILS = ["110m", "50m", "10m"];
let atlasWorker = null;
const atlasWaiting = new Map();

function prepareInWorker(level) {
  if (!atlasWorker) {
    atlasWorker = new Worker(new URL("./atlas-worker.mjs", import.meta.url), {type: "module"});
    atlasWorker.onmessage = ({data: {level, data, error}}) => {
      const waiting = atlasWaiting.get(level);
      atlasWaiting.delete(level);
      if (error) waiting?.reject(new Error(error)); else waiting?.resolve(data);
    };
    atlasWorker.onerror = event => {
      event.preventDefault?.();
      for (const waiting of atlasWaiting.values()) waiting.reject(new Error("Border worker failed"));
      atlasWaiting.clear(); atlasWorker = null;
    };
  }
  return new Promise((resolve, reject) => {
    atlasWaiting.set(level, {resolve, reject});
    atlasWorker.postMessage({url: MAP_FILES[level], level});
  });
}

// Prepare the next finer level while the user looks at this one, so zooming in rarely waits for it.
function prepareAhead(level) {
  const next = DETAILS[DETAILS.indexOf(level) + 1];
  if (next && !atlas.has(next)) setTimeout(() => loadAtlas(next), 1500);
}

async function loadAtlas(level) {
  if (atlas.has(level) || atlasPending.has(level) || performance.now() - (atlasFailed.get(level) ?? -Infinity) < 30000) return;
  atlasPending.add(level);
  try {
    const data = await prepareInWorker(level);
    prepareGrid(level);
    atlas.set(level, data);
    atlasFailed.delete(level);
    if (wantedDetail === level) await updateMapDetail();
  } catch (error) {
    atlasFailed.set(level, performance.now());
    if (wantedDetail === level) {
      $("map-detail-status").textContent = activeDetail ? `Borders · 1:${activeDetail} (requested detail unavailable)` : "Borders unavailable";
      errors.set("map", `${error.message}. ${activeDetail ? "Keeping the available border detail." : "Event coordinates are still available."}`);
      notices();
    }
  } finally { atlasPending.delete(level); }
}

async function updateMapDetail() {
  const level = detailLevel(mapView.zoom());
  wantedDetail = level;
  if (atlas.has(level)) {
    activateAtlas(level);
    const message = `Borders · 1:${level} · ${world.features.length} country/territory shapes`;
    if ($("map-detail-status").textContent !== message) $("map-detail-status").textContent = message;
    if (errors.delete("map")) notices();
    prepareAhead(level);
    return;
  }
  if (atlasPending.has(level) || performance.now() - (atlasFailed.get(level) ?? -Infinity) < 30000) return;
  $("map-detail-status").textContent = `Loading 1:${level} borders${activeDetail ? `; showing 1:${activeDetail}` : ""}…`;
  await loadAtlas(level);
}

// Labels are reused between frames: only moved when their position or the zoom changed.
const labelNodes = new Map();

function positionCountryLabels() {
  const scale = mapView.scale(), view = mapView.viewport(), layer = $("map-labels");
  if (!scale || !view.width || mapView.zoom() < 4) {
    if (labelNodes.size) { layer.replaceChildren(); labelNodes.clear(); }
    return;
  }
  const occupied = [], shown = new Set();
  for (const item of countryLabels) {
    const {x, y, visible} = pointPosition(item);
    if (!visible || Math.abs(x - view.x) > view.width / 2 || Math.abs(y - view.y) > view.height / 2) continue;
    const labelWidth = Math.min(180, item.name.length * 5.5) / scale, labelHeight = 17 / scale;
    const rect = {left: x, right: x + labelWidth, top: y - labelHeight, bottom: y};
    if (occupied.some(other => other.left < rect.right && other.right > rect.left && other.top < rect.bottom && other.bottom > rect.top)) continue;
    occupied.push(rect); shown.add(item);
    let entry = labelNodes.get(item);
    if (!entry) {
      const label = svg("text", {"data-country": item.id});
      label.textContent = item.name;
      layer.append(label);
      entry = {label, x: NaN, y: NaN, scale: 0};
      labelNodes.set(item, entry);
    }
    if (entry.x !== x || entry.y !== y) {
      entry.label.setAttribute("x", x); entry.label.setAttribute("y", y);
      entry.x = x; entry.y = y;
    }
    if (entry.scale !== scale) {
      entry.label.setAttribute("dx", 4 / scale); entry.label.setAttribute("dy", -4 / scale);
      entry.label.setAttribute("font-size", 10 / scale);
      entry.scale = scale;
    }
  }
  for (const [item, entry] of labelNodes) if (!shown.has(item)) { entry.label.remove(); labelNodes.delete(item); }
}

function hideTooltip() { if (!$("map-tooltip").hidden) $("map-tooltip").hidden = true; }

function refreshTooltipAge() {
  const target = $("map-tooltip"), age = target.querySelector(".tip-ago");
  if (!target.hidden && age) age.textContent = ago(Number(target.dataset.timestamp));
}

function loadedEvents(count) { return `${count} loaded event${count === 1 ? "" : "s"}`; }

function clickHint(count) {
  if (opensDetail()) return count > 1 ? "Click for source and latest event details" : "Click for details";
  return count > 1 ? "Click to show this source's events" : "Click to find in stream";
}

function tooltip(point) {
  const source = pointData.get(point), {latest: item, place, count} = source;
  const target = $("map-tooltip");
  target.dataset.sourceIp = item.ip;
  target.dataset.timestamp = String(item.timestamp);
  target.dataset.trap = trapSignature(item);
  const head = node("div", undefined, "tip-head");
  head.append(node("strong", item.title), node("time", ago(item.timestamp), "tip-ago"));
  target.replaceChildren(head,
    node("span", `${item.ip} · ${loadedEvents(count)}`), ...mixBadges(source), locationLabel(place), networkBadges(item),
    node("span", `${count > 1 ? "Latest: " : ""}${TYPES[item.type].label} · port ${item.port}${item.user ? ` · user ${item.user}` : ""}`),
    ...trapBadges(item),
    node("small", `${new Date(item.timestamp * 1000).toLocaleString()} · ${clickHint(count)}`));
  target.hidden = false;
  const center = point.getScreenCTM(), parent = $("map").parentElement.getBoundingClientRect();
  target.style.left = `${Math.max(8, Math.min(center.e - parent.left + 12, parent.width - target.offsetWidth - 8))}px`;
  target.style.top = `${Math.max(8, Math.min(center.f - parent.top - target.offsetHeight - 12, parent.height - target.offsetHeight - 8))}px`;
}

// Mobile/fullscreen keep their detail sheet; the inline map goes straight to the stream.
function opensDetail() { return mapView.expanded() || narrow.matches; }

function reveal({latest: item, count}) {
  if (opensDetail()) { detail(item, count); return; }
  if (count > 1) { showSource(item.ip); return; }
  highlighted = item.id;
  hideTooltip();
  if (grouped && !openGroups.has(item.ip)) { openGroups.add(item.ip); const group = groupCache.get(item.ip); if (group) group.element.open = true; render(); }
  for (const row of $("events").querySelectorAll(".event-row[data-event-id]")) row.classList.toggle("highlighted", row.dataset.eventId === item.id);
  const row = $("events").querySelector(`[data-event-id="${CSS.escape(item.id)}"]`);
  row?.scrollIntoView({block: "center", behavior: reduced.matches ? "instant" : "smooth"});
  row?.focus({preventScroll: true});
}

function positionArrivals() {
  if (arrivals.size) {
    const parent = $("map").parentElement.getBoundingClientRect(), mobile = narrow.matches, placed = [];
    // Cards steer around the map's controls and the settings popover instead of hiding behind them.
    if (!mobile) for (const control of document.querySelectorAll(".tool-rows, #map-popover:not([hidden])")) {
      const box = control.getBoundingClientRect();
      placed.push({left: box.left - parent.left, top: box.top - parent.top, width: box.width, height: box.height});
    }
    for (const [id, entry] of arrivals) {
      const point = pointNodes.get(id);
      if (!point || point.hasAttribute("hidden") || performance.now() >= entry.expires) {
        entry.node.remove(); arrivals.delete(id); continue;
      }
      if (mobile) {
        entry.node.style.left = "10px"; entry.node.style.top = "auto"; entry.node.style.bottom = "12px";
      } else {
        entry.node.style.bottom = "auto";
        // The group's origin is the projected dot; its bounding box includes the animated flash rings.
        const center = point.getScreenCTM();
        const spot = placeArrival(center.e - parent.left, center.f - parent.top, entry.node.offsetWidth,
          entry.node.offsetHeight, parent, placed, entry.spot);
        entry.spot = spot;
        placed.push(spot);
        entry.node.style.left = `${spot.left}px`; entry.node.style.top = `${spot.top}px`;
      }
    }
  }
  if (!arrivals.size) arrivalsOmitted = 0;
  setText($("arrival-status"), arrivalsOmitted ? `${arrivalsOmitted} more arrivals in this burst; hover or tap dots for details.` : "");
}

function arrival(source) {
  const {latest: item, place, count} = source;
  const previous = arrivals.get(item.ip);
  previous?.node.remove();
  arrivals.delete(item.ip);
  const limit = narrow.matches ? 1 : 3;
  while (arrivals.size >= limit) {
    const oldest = arrivals.keys().next().value;
    arrivals.get(oldest).node.remove(); arrivals.delete(oldest); arrivalsOmitted++;
  }
  const card = node("div", undefined, `arrival-summary type-${item.type}`);
  const label = node("span", undefined, "mono"), entry = {node: card, label, mix: [], expires: performance.now() + 4500, spot: previous?.spot};
  card.append(node("strong", item.title), label, locationLabel(place),
    node("small", `${TYPES[item.type].label} · ${item.verdict}${item.user ? ` · user ${item.user}` : item.path ? ` · ${item.path}` : ` · port ${item.port}`}`),
    ...trapBadges(item), networkBadges(item));
  refreshArrival(entry, source);
  $("map-arrivals").append(card);
  arrivals.set(item.ip, entry);
}

// Keeps an open card's count and mix current when more of its source's events load.
function refreshArrival(entry, source) {
  entry.label.textContent = `${source.ip} · ${loadedEvents(source.count)}`;
  for (const old of entry.mix) old.remove();
  entry.mix = mixBadges(source);
  entry.label.after(...entry.mix);
}

// Each marker's parts and the size last written to them, so a frame only touches markers whose size changed.
const markerSizes = new WeakMap();

function sizeMapMarkers() {
  const scale = mapView.scale();
  if (!scale) return;
  const touch = coarse.matches || narrow.matches;
  for (const point of pointNodes.values()) {
    let sized = markerSizes.get(point);
    if (!sized) {
      sized = {
        hit: point.querySelector(".map-hit"), flash: point.querySelector(".map-flash"),
        dot: point.querySelector(".map-dot > g"), rings: [...point.querySelectorAll(".map-ring > g")],
        scale: 0, touch: null,
      };
      markerSizes.set(point, sized);
    }
    if (sized.scale === scale && sized.touch === touch) continue;
    sized.scale = scale; sized.touch = touch;
    sized.hit.setAttribute("r", String((touch ? 24 : 12) / scale));
    sized.flash.setAttribute("r", String(7 / scale));
    // Slices and arcs are unit-radius paths, sized by their wrapper so they never need redrawing on zoom.
    sized.dot.setAttribute("transform", `scale(${(touch ? 4.5 : 3) / scale})`);
    for (const ring of sized.rings) ring.setAttribute("transform", `scale(${7 / scale})`);
  }
}

const RING_GAP = .04;

// Updates parts in place by key, so a count change never restarts a running arrival animation.
function drawParts(group, parts, ring) {
  const stale = new Map([...group.children].map(child => [child.dataset.key, child]));
  const gap = ring && parts.length > 1 ? RING_GAP / 2 : 0;
  for (const part of parts) {
    let element = stale.get(part.key);
    stale.delete(part.key);
    if (!element) {
      element = svg("path", {class: ring ? `severity-${part.key}` : `type-${part.key}`});
      element.dataset.key = part.key;
      group.append(element);
    }
    element.setAttribute("d", slicePath({start: part.start + gap, end: part.end - gap}, ring));
  }
  for (const element of stale.values()) element.remove();
}

function drawMix(point, source) {
  drawParts(point.querySelector(".map-slices"), slices(source.types, TYPE_ORDER), false);
  const levels = slices(source.severities, SEVERITY_ORDER);
  for (const ring of point.querySelectorAll(".map-ring > g")) drawParts(ring, levels, true);
}

function marker(className, ...children) {
  const outer = svg("g", {class: className}), inner = svg("g");
  inner.append(...children);
  outer.append(inner);
  return outer;
}

function mixSignature({types, severities}) {
  return [...TYPE_ORDER.map(key => types[key] ?? 0), ...SEVERITY_ORDER.map(key => severities[key] ?? 0)].join(",");
}

function pointPosition(item) {
  if (isGlobe()) return globe.position(item.longitude, item.latitude);
  const [x, y] = mapProject(item.longitude, item.latitude);
  return {x, y, visible: true};
}

// Whether a dot sits within the central `fraction` of the viewport; on the globe, also clear of the squashed limb.
function onScreen(item, fraction = 1) {
  const {x, y, visible, angle} = pointPosition(item), view = mapView.viewport();
  if (!visible || !view.width) return visible;
  const limb = fraction < 1 ? FOLLOW.limbDegrees * Math.PI / 180 : Math.PI / 2;
  return Math.abs(x - view.x) <= view.width * fraction / 2 && Math.abs(y - view.y) <= view.height * fraction / 2
    && (!isGlobe() || angle <= limb);
}

function setFollowing(value, message = "") {
  following = value;
  followQueue.clear();
  $("map-follow").setAttribute("aria-pressed", String(value));
  clearTimeout(followStatusTimer);
  $("follow-status").textContent = message;
  if (message) followStatusTimer = setTimeout(() => { $("follow-status").textContent = ""; }, FOLLOW.statusMs);
  try {
    localStorage.setItem("attacks.map-follow", value ? "1" : "0");
    errors.delete("follow");
  } catch (error) {
    errors.set("follow", `Follow applies only to this tab because it could not be saved. ${error.message}`);
  }
  notices();
}

function flash(point) {
  point.classList.remove("recent");
  point.getBoundingClientRect();
  point.classList.add("recent");
}

function followTick() {
  const now = performance.now();
  for (const [id, entry] of followQueue) if (!pointNodes.has(id) || now - entry.queued > FOLLOW.staleMs) followQueue.delete(id);
  if (!following || !mapView.interactive()) { followQueue.clear(); return; }
  if (!followQueue.size || now < followHold || mapView.moving() || mapView.held() || document.hidden
    || !$("map-tooltip").hidden || $("detail").open) return;
  const queued = new Map(followQueue), epoch = generation;
  const sources = [...queued.keys()].map(ip => pointData.get(pointNodes.get(ip)))
    .sort((a, b) => b.latest.observedAt - a.latest.observedAt);
  const items = sources.map(source => source.place);
  followQueue.clear();
  function showMissed() {
    let room = FLASH.maxConcurrent - pulses.size;
    const missed = sources.filter(({ip, latest, place}) => queued.get(ip).unseen && pointNodes.has(ip)
      && pointData.get(pointNodes.get(ip)).latest.id === latest.id && onScreen(place)
      && (pulses.has(ip) || room-- > 0));
    for (const {ip, latest} of missed.toReversed()) {
      const point = pointNodes.get(ip);
      pulses.set(ip, {id: latest.id, started: performance.now()});
      flash(point); arrival(pointData.get(point));
    }
    if (missed.length) positionArrivals();
  }
  let target;
  if (isGlobe()) {
    if (items.every(item => onScreen(item, FOLLOW.inner))) return showMissed();
    const [longitude, latitude] = followCenter(items, FOLLOW.spread * globe.reach());
    target = {longitude, latitude};
  } else {
    const points = items.map(item => { const [x, y] = mapProject(item.longitude, item.latitude); return {x, y}; });
    const box = $("map").getBoundingClientRect(), goal = fitView(points, followZoom, box.width, box.height);
    if (items.every(item => onScreen(item, FOLLOW.inner)) && mapView.zoom() >= goal.zoom * .8) return showMissed();
    target = {points, zoom: followZoom};
  }
  mapView.flyTo(target, landed => {
    if (epoch !== generation || !following) return;
    followHold = performance.now() + FOLLOW.holdMs;
    // An interrupted move (zoom, projection change) keeps its dots queued for the next one.
    if (!landed) { for (const [id, entry] of queued) if (!followQueue.has(id)) followQueue.set(id, entry); return; }
    showMissed();
  });
}

// Last values written per point: a still dot (any flat map pan, or far-side globe dots) costs no attribute writes.
const pointPlacement = new WeakMap();

function placePoint(point, {x, y, visible}) {
  let last = pointPlacement.get(point);
  if (!last) { last = {x: NaN, y: NaN, visible: null}; pointPlacement.set(point, last); }
  if (visible && (last.x !== x || last.y !== y)) {
    point.setAttribute("transform", `translate(${x} ${y})`);
    last.x = x; last.y = y;
  }
  if (last.visible !== visible) { point.toggleAttribute("hidden", !visible); last.visible = visible; }
}

function positionMapPoints() {
  let backside = 0;
  const tipIp = $("map-tooltip").hidden ? null : $("map-tooltip").dataset.sourceIp;
  for (const point of pointNodes.values()) {
    const source = pointData.get(point), position = pointPosition(source.place);
    placePoint(point, position);
    if (!position.visible) {
      backside++;
      if (tipIp === source.ip) hideTooltip();
    }
  }
  setText($("map-caption"), notDrawn({...mapHidden, farSide: isGlobe() ? backside : 0}));
}

function currentMapActivity() {
  return mapActivity(events, dotSettings, Date.now() / 1000, $("history-dots").checked);
}

function mapPoints() {
  refreshTooltipAge();
  const activity = currentMapActivity();
  const ips = new Set(activity.points.map(source => source.ip));
  const represented = activity.points.reduce((sum, source) => sum + source.count, 0);
  counter("map-count", `${ips.size} source${ips.size === 1 ? "" : "s"} · ${loadedEvents(represented)}`);
  // With "Show faded dots" on, faded sources are drawn dimly, so they are not left out.
  mapHidden = {faded: $("history-dots").checked ? 0 : activity.expired, omitted: activity.omitted, unlocated: activity.unlocated};
  for (const [ip, point] of pointNodes) {
    if (!ips.has(ip)) {
      if ($("map-tooltip").dataset.sourceIp === ip) hideTooltip();
      point.remove(); pointNodes.delete(ip);
    }
  }
  const now = performance.now();
  for (const [ip, {started}] of pulses) if (!ips.has(ip) || now - started >= FLASH.seconds * 1000) pulses.delete(ip);
  for (const {ip, latest} of activity.points) {
    if (freshIds.delete(latest.id) && (pulses.has(ip) || pulses.size < FLASH.maxConcurrent))
      pulses.set(ip, {id: latest.id, started: now});
  }
  freshIds.clear();
  for (const source of activity.points.toReversed()) {
    const {ip, latest: item, place, count, opacity} = source;
    let point = pointNodes.get(ip);
    const previous = point && pointData.get(point);
    if (!point) {
      point = svg("g", {class: "map-point", tabindex: "0", role: "button", "aria-describedby": "map-tooltip"});
      point.dataset.sourceIp = ip;
      const slicesGroup = svg("g", {class: "map-slices"});
      point.append(svg("circle", {r: 12, class: "map-hit"}), svg("circle", {r: 5, class: "map-flash"}),
        marker("map-ring"), marker("map-ring late"), marker("map-dot", slicesGroup, svg("circle", {r: 1, class: "map-dot-edge"})));
      point.addEventListener("pointerenter", event => { if (event.pointerType === "mouse") tooltip(point); });
      point.addEventListener("pointerleave", hideTooltip);
      point.addEventListener("focus", () => { if (hovering.matches) tooltip(point); });
      point.addEventListener("blur", hideTooltip);
      point.addEventListener("click", () => reveal(pointData.get(point)));
      point.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); reveal(pointData.get(point)); }
        if (event.key === "Escape") hideTooltip();
      });
      $("map-points").append(point);
      pointNodes.set(ip, point);
    }
    pointData.set(point, source);
    const mix = mixSignature(source);
    if (!previous || previous.latest.id !== item.id || previous.count !== count || previous.place.id !== place.id
      || mixSignature(previous) !== mix) {
      if (previous) point.classList.remove(`type-${previous.latest.type}`);
      point.classList.add(`type-${item.type}`);
      point.dataset.eventId = item.id;
      point.dataset.mix = mix;
      drawMix(point, source);
      const pos = pointPosition(place);
      placePoint(point, pos);
      point.setAttribute("aria-label", `${ip}, ${place.location}: ${loadedEvents(count)}.${mixText(source)} Latest: ${item.title}. ${clickHint(count)}.`);
      if (!$("map-tooltip").hidden && $("map-tooltip").dataset.sourceIp === ip) tooltip(point);
      if (arrivals.has(ip)) refreshArrival(arrivals.get(ip), source);
      if (previous?.latest.id !== item.id && pulses.get(ip)?.id === item.id) {
        flash(point);
        const tracking = following && mapView.interactive();
        const seen = tracking ? onScreen(place) : pos.visible;
        if (seen) arrival(source);
        if (tracking) followQueue.set(ip, {queued: performance.now(), unseen: !seen});
      }
    }
    point.style.setProperty("--opacity", String(opacity));
    if (pulses.get(ip)?.id !== item.id) point.classList.remove("recent");
  }
  positionMapPoints(); sizeMapMarkers(); positionArrivals(); positionCountryLabels();
  updateMapDetail();
  followTick();
}
$("history-dots").onchange = () => { hideTooltip(); mapPoints(); };
$("projection").onchange = () => {
  hideTooltip(); mapView.reset(); updateMapDetail(); mapLand(); mapPoints();
  try {
    localStorage.setItem("attacks.map-projection", $("projection").value);
    errors.delete("projection");
  } catch (error) {
    errors.set("projection", `Projection applies only to this tab because it could not be saved. ${error.message}`);
  }
  notices();
};
function showMapSettings() {
  for (const [key, value] of Object.entries(dotSettings)) $(key).value = value;
  $("map-explainer").textContent = `One dot per source IP, split into slices by event kind; rings show severity. The newest ${dotSettings.keep} sources stay bright, older ones fade over ${dotSettings.fadeMinutes} minutes, and at most ${dotSettings.maxDots} are shown. Locations are approximate.`;
}
$("map-settings").onsubmit = event => {
  event.preventDefault();
  let applied = false;
  try {
    const next = mapSettings(Object.fromEntries(Object.keys(MAP_DEFAULTS).map(key => [key, $(key).value])));
    dotSettings = next; applied = true;
    showMapSettings(); hideTooltip(); mapPoints();
    localStorage.setItem("attacks.map-settings", JSON.stringify(next));
    errors.delete("mapSettings");
  } catch (error) {
    errors.set("mapSettings", `Map settings: ${error.message} Settings that cannot be saved apply only to this tab.`);
  }
  notices();
  if (applied) setMapSettingsOpen(false, true);
};
showMapSettings();

// The settings popover floats over the map. Escape, its close button, an outside press and Apply dismiss it.
const settingsPopover = $("map-popover"), settingsToggle = $("map-settings-toggle");
function setMapSettingsOpen(open, restoreFocus = false) {
  if (settingsPopover.hidden === !open) return;
  settingsPopover.hidden = !open;
  settingsToggle.setAttribute("aria-expanded", String(open));
  if (open) { hideTooltip(); settingsPopover.focus({preventScroll: true}); }
  else if (restoreFocus) settingsToggle.focus({preventScroll: true});
  positionArrivals();
}
settingsToggle.onclick = () => setMapSettingsOpen(settingsPopover.hidden);
$("map-popover-close").onclick = () => setMapSettingsOpen(false, true);
swipeToDismiss(settingsPopover, () => setMapSettingsOpen(false, true));
document.addEventListener("pointerdown", event => {
  if (!settingsPopover.hidden && !event.target.closest?.("#map-popover, #map-settings-toggle")) setMapSettingsOpen(false);
});
// Capture phase, so the first Escape closes the popover before full screen sees it.
document.addEventListener("keydown", event => {
  if (event.key !== "Escape" || settingsPopover.hidden || $("detail").open) return;
  if (event.target !== document.body && !$("map-panel").contains(event.target)) return;
  event.preventDefault(); event.stopPropagation();
  setMapSettingsOpen(false, true);
}, true);
for (const [key, value] of Object.entries(TYPES)) {
  const item = node("span", undefined, `legend-item type-${key}`);
  item.append(node("span", undefined, "legend-dot"), node("span", value.label));
  $("legend").append(item);
}
{
  const rings = node("span", undefined, "legend-rings");
  for (const [level] of SEVERITIES) rings.append(node("span", undefined, `legend-ring severity-${level}`));
  const item = node("span", undefined, "legend-item legend-severity");
  item.title = `Ring colors by severity, lowest to highest: ${SEVERITIES.map(([, label]) => label).join(", ")}`;
  item.append(rings, node("span", "Ring: severity"));
  $("legend").append(item);
}

$("own").onchange = () => applyFilters();
$("range").onchange = () => { load(true); stats(); loadFacets(); };
$("older").onclick = () => load(false, true);
$("group").onclick = () => setGrouped(!grouped);
setGrouped(grouped, false);
$("pause").onclick = () => {
  live = !live;
  $("pause").textContent = live ? "Pause live" : "Resume live";
  $("feed-note").textContent = live ? "Updates every 3 seconds. Events are not unique attacks." : "Feed paused; collection and aggregate metrics continue.";
  notices(); if (live) load();
};
const mapView = createMapView({
  panel: $("map-panel"), svg: $("map"), globe, isGlobe,
  resetPoints: () => currentMapActivity().points.map(({place}) => place),
  changed: () => {
    hideTooltip();
    const previousDetail = activeDetail;
    updateMapDetail();
    if (isGlobe() && previousDetail === activeDetail) mapLand();
    positionMapPoints(); sizeMapMarkers(); positionArrivals(); positionCountryLabels();
    const hint = $("map-gesture-hint"), hintHidden = !isGlobe() && !mapView.expanded();
    if (hint.hidden !== hintHidden) hint.hidden = hintHidden;
    setText(hint, `Drag to ${isGlobe() ? "rotate" : "pan"} · ${coarse.matches ? "Pinch" : "Scroll"} to zoom`);
  },
  closed: hideTooltip,
  // Zooming refines what is followed; taking the view elsewhere by hand ends following.
  interacted: kind => {
    followHold = performance.now() + FOLLOW.holdMs;
    if (kind === "zoom") { if (!isGlobe()) followZoom = mapView.zoom(); }
    else if (following) setFollowing(false, "Follow off: the map was moved by hand.");
  },
});
$("map-follow").onclick = () => {
  const value = !following;
  setFollowing(value, value ? "Following new attacks." : "Follow off.");
  if (!value) return;
  followZoom = !isGlobe() && mapView.zoom() > 1 ? mapView.zoom() : FOLLOW.zoom;
  followHold = 0;
  // Start by showing the newest dot; it is not fresh, so it does not replay an arrival.
  const newest = currentMapActivity().points[0];
  if (newest && pointNodes.has(newest.ip)) followQueue.set(newest.ip, {queued: performance.now(), unseen: false});
  followTick();
};
window.addEventListener("offline", () => {
  errors.set("network", "Offline: no fresh telemetry. Only previously loaded events may remain visible.");
  notices();
});
window.addEventListener("online", () => { errors.delete("network"); atlasFailed.clear(); updateMapDetail(); notices(); load(); stats(); health(); });
if (!navigator.onLine) errors.set("network", "Offline: live telemetry is unavailable. Event data is never cached.");

mapLand(); updateMapDetail(); applyFilters(); stats(); health();
if (demo && new URLSearchParams(location.search).get("simulate") !== "0") setTimeout(demoArrivals, 3000);
setInterval(() => { if (!document.hidden) { mapPoints(); updateTrapping(); tickTrapping(); } }, 1000);
setInterval(() => { if (!document.hidden && !demo) load(); }, 3000);
setInterval(() => { if (!document.hidden) { stats(); health(); loadFacets(); } }, 30000);
// Timers pause in a hidden tab, so telemetry is refreshed on return before its running times can mislead.
document.addEventListener("visibilitychange", () => { if (!document.hidden) stats(); });
