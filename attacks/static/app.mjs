import {TYPES, OUTCOMES, SEVERITIES, severityOf, matchesFilters, mergeEvents, project, duration, liveTrapping, ago, demoEvents, demoLiveEvent, FLASH, FOLLOW, isFresh, countryFlag, MAP_DEFAULTS, mapSettings, mapActivity} from "./model.mjs";
import {createMapView, fitView, placeArrival} from "./map-view.mjs";
import {createGlobe, globeGeometry, detailLevel, followCenter} from "./globe.mjs";
import {feature as decodeTopology, geoArea, geoCentroid} from "./geo-vendor.mjs";
import {MAP_FILES} from "./atlas.mjs";
import "./pwa.mjs";

const $ = id => document.getElementById(id);
const demo = new URLSearchParams(location.search).get("demo") === "1";
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
let events = [], world = null, live = true, latest = null, older = null, hasOlder = false;
let generation = 0, busy = false, selected = null, parameters = {range: "24h"};
const errors = new Map(), pulses = new Map(), freshIds = new Set();
const demoLive = [];
let demoSequence = 0;
let sourceIssues = [];
let trapSample = null, trapReceived = 0, completedTrapSeconds = null;
let highlighted = null;
let dotSettings = {...MAP_DEFAULTS}, catchingUp = false;
const pointNodes = new Map();
const pointData = new WeakMap();
const arrivals = new Map();
let arrivalsOmitted = 0;
let globeLand = [], mapCaption = "Waiting for telemetry";
let activeDetail = null, wantedDetail = "110m", countryLabels = [];
// Pending arrivals are keyed by source IP, like the markers and cards.
const followQueue = new Map();
let following = false, followZoom = FOLLOW.zoom, followHold = 0, followStatusTimer = 0;
const atlas = new Map(), atlasPending = new Set(), atlasFailed = new Map();
const globe = createGlobe();
const isGlobe = () => $("projection").value === "globe";
const SVG = "http://www.w3.org/2000/svg";

$("projection").value = matchMedia("(pointer: coarse)").matches ? "globe" : "equal-earth";
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

function counter(id, value) {
  const element = $(id), text = String(value), previous = element.dataset.counterText;
  if (previous === text) return;
  element.dataset.counterText = text;
  const parts = text.split(/(\d[\d,.]*)/), before = (previous || "").split(/(\d[\d,.]*)/);
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
  for (const service of item.privacyServices || []) {
    const badge = node("span", service.kind === "tor_exit" ? "Tor exit" : `VPN server · ${service.name}`, "badge privacy-service");
    badge.title = service.evidence;
    badges.append(badge);
  }
  return badges;
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

function render() {
  const fragment = document.createDocumentFragment();
  for (const item of events) {
    const row = node("button", undefined, `event-row${item.id === highlighted ? " highlighted" : ""}`);
    row.type = "button";
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
    if (item.origin === "own") badges.append(node("span", "Own", "badge origin-own"));
    if (item.keyStatus) badges.append(node("span", item.keyStatus === "recognized" ? "known key" : "unregistered key", `badge key-${item.keyStatus}`));
    classification.append(badges);
    const source = node("span", undefined, "event-cell");
    source.append(node("span", item.ip, "event-primary mono"), locationLabel(item), networkBadges(item));
    const extra = node("span", undefined, "event-cell event-detail");
    const target = item.user ? `user: ${item.user}` : item.path || item.service;
    extra.append(node("span", target, "event-primary mono"),
      node("span", `${item.host || `port ${item.port}`} ${item.duration !== undefined ? `· ${duration(item.duration)} trapped` : ""}`, "event-secondary"));
    row.append(time, classification, source, extra, node("span", "↗", "event-arrow"));
    fragment.append(row);
  }
  const focusedId = $("events").contains(document.activeElement) ? document.activeElement.dataset.eventId : null;
  [...fragment.children].forEach((row, i) => { row.dataset.eventId = events[i].id; });
  $("events").replaceChildren(fragment);
  if (focusedId) [...$("events").children].find(row => row.dataset.eventId === focusedId)?.focus({preventScroll: true});
  $("empty").hidden = events.length > 0;
  $("empty").textContent = errors.has("feed") ? "Events unavailable. Check collection health above." : "No matching events in this observation window.";
  counter("feed-count", `${events.length} shown`);
  $("older").hidden = !hasOlder || demo || events.length >= 1000;
  mapPoints();
}

function detail(item, sourceCount) {
  hideTooltip();
  selected = item;
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
    "Lookup coverage": item.networkLookup || "Not enriched (older event)",
    "Service": item.service, "Destination port": item.port, "Source port": item.sourcePort,
    "Protocol": item.protocol, "Attempted user": item.user, "Auth factor": item.factor,
    "Auth method": item.authMethod, "Rejection reason": item.rejectionReason,
    "Key status": item.keyStatus, "Key label": item.keyLabel, "Key fingerprint": item.keyFingerprint,
    "Host": item.host, "Request path": item.path, "Method": item.method, "HTTP status": item.status,
    "Time stuck": item.duration === undefined ? undefined : duration(item.duration),
    "Log source": item.source, "Event ID": item.id,
  };
  $("detail-fields").replaceChildren(...Object.entries(fields).filter(([, value]) => value !== undefined && value !== null && value !== "")
    .flatMap(([key, value]) => [node("dt", key), node("dd", String(value))]));
  $("filter-country").hidden = !item.countryCode;
  $("filter-country").textContent = `Only ${item.countryCode ? countryName(item.countryCode) : "this country"}`;
  $("filter-network").hidden = !item.asn;
  $("filter-network").textContent = `Only AS${item.asn}`;
  if (!$("detail").open) {
    document.body.classList.add("detail-open");
    $("detail").showModal();
  }
}
$("close").onclick = () => $("detail").close();
$("detail").addEventListener("close", () => document.body.classList.remove("detail-open"));
$("detail").addEventListener("click", event => { if (event.target === $("detail")) { const box = $("detail").getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) $("detail").close(); } });
async function showEvents(change) {
  hideTooltip();
  for (const picker of document.querySelectorAll(".picker[open]")) picker.open = false;
  if (mapView.expanded()) await mapView.exit();
  await applyFilters(change);
  $("events").scrollIntoView({block: "start"});
  $("events").firstElementChild?.focus({preventScroll: true});
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
const filters = {severity: "", type: new Set(), outcome: new Set(), ip: "", country: "", asn: ""};
const networkNames = new Map();
let sourcesKey = "", sourcesAt = 0;
const regionNames = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(undefined, {type: "region"}) : null;

function countryName(code) {
  try { return regionNames?.of(code) || code; } catch { return code; }
}

function filterParameters() {
  const result = {};
  if (filters.severity) result.severity = filters.severity;
  for (const name of ["type", "outcome"]) if (filters[name].size) result[name] = [...filters[name]].join(",");
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
  for (const name of ["type", "outcome"]) for (const input of $(name).querySelectorAll("input")) input.checked = filters[name].has(input.value);
  $("ip").value = filters.ip;
  for (const [id, any, current, label] of [["country", "Any country", filters.country, countryName(filters.country)],
    ["asn", "Any network", filters.asn, networkNames.get(filters.asn) || `AS${filters.asn}`]]) {
    const rows = [...$(id).options].slice(1).map(option => [option.value, option.textContent]);
    fillSources($(id), any, rows, current, label);
  }
  const counts = {"type-picker": filters.type.size, "outcome-picker": filters.outcome.size,
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
      : applyFilters({[name]: name === "type" || name === "outcome" ? new Set() : ""});
    return chip;
  }));
}

function applyFilters(change = {}) {
  Object.assign(filters, change);
  syncFilters();
  return load(true);
}

function clearFilters() {
  $("own").checked = false;
  sourcesKey = "";
  return applyFilters({severity: "", type: new Set(), outcome: new Set(), ip: "", country: "", asn: ""});
}

function buildFilters() {
  const segments = [["", "Any", "Every event, including routine ones."], ...SEVERITIES.slice(1)];
  for (const [value, label, hint] of segments) {
    const choice = node("label", undefined, `segment severity-${value || "any"}`);
    const input = node("input");
    Object.assign(input, {type: "radio", name: "severity", value});
    choice.title = hint;
    choice.append(input, node("span", label));
    $("severity").append(choice);
  }
  const groups = {type: Object.entries(TYPES).map(([value, {label}]) => [value, label]), outcome: OUTCOMES};
  for (const [name, options] of Object.entries(groups)) for (const [value, label] of options) {
    const choice = node("label", undefined, "choice");
    const input = node("input");
    Object.assign(input, {type: "checkbox", value});
    choice.append(input);
    if (name === "type") choice.append(node("span", undefined, `legend-dot type-${value}`));
    choice.append(node("span", label));
    $(name).append(choice);
  }
}

function demoSources() {
  const count = (key, extra) => [...Map.groupBy(mergeEvents(demoLive, demoEvents()).filter(item => item.origin !== "own" && item[key]), item => item[key])]
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
for (const name of ["type", "outcome"]) $(name).onchange = event => {
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

// Demo only: simulate scanners arriving every few seconds, with occasional bursts.
function demoArrivals() {
  setTimeout(demoArrivals, 2500 + Math.random() * 3500);
  if (document.hidden || !live || busy) return;
  const count = Math.random() < 0.12 ? 3 + Math.floor(Math.random() * 4) : 1;
  const now = Date.now(), fresh = [];
  for (let i = 0; i < count; i++) fresh.push(demoLiveEvent(++demoSequence, now + i));
  demoLive.unshift(...fresh.toReversed());
  demoLive.length = Math.min(demoLive.length, 200);
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
      events = mergeEvents(demoLive, demoEvents()).filter(item => matchesFilters(item, parameters));
      latest = "demo";
      if (reset) for (const item of events) if (isFresh(item, FLASH.loadWindow)) freshIds.add(item.id);
    } else {
      const query = {...parameters};
      if (history && older) query.before = older;
      else if (latest) query.after = latest;
      for (let page = 0; page < (reset || history ? 1 : 8); page++) {
        const result = await request("/api/events", query);
        if (epoch !== generation) return;
        const known = new Set(events.map(item => item.id));
        for (const item of result.events) {
          // Server time keeps freshness correct when this device's clock is off.
          if (!known.has(item.id) && !history && isFresh(item, reset ? FLASH.loadWindow : FLASH.liveWindow, result.queriedAt)) freshIds.add(item.id);
        }
        events = mergeEvents(events, result.events);
        if (reset || history) { older = result.next; hasOlder = result.more; }
        if (!history) {
          // Inclusive overlap tolerates normal log-delivery delay; IDs remove replays.
          catchingUp = result.more && !!query.after;
          latest = catchingUp ? String(BigInt(result.next) + 1n) : String(BigInt(result.latest) - 15000000000n);
        }
        if (reset || history || !catchingUp) break;
        query.after = latest;
      }
      errors.delete("feed");
    }
    render();
  } catch (error) {
    if (epoch === generation) { errors.set("feed", error.message); render(); }
  } finally {
    if (epoch === generation) { busy = false; notices(); }
  }
}

async function stats() {
  const period = $("range").value;
  try {
    const result = demo ? {available: true, totals: [{kind: "endlessh_open", value: 6821}, {kind: "ssh_failure", value: 143}, {kind: "auth_failure", value: 12}, {kind: "http_probe", value: 924}], trappedSeconds: 184800, lifetimeTrappedSeconds: 2064000,
      trapping: {available: true, connections: 3, seconds: 340, since: Date.now() / 1000 - 3600},
      timeline: Array.from({length: 120}, (_, i) => [i, String(5 + (Math.sin(i * 1.9) + 1) * 7 + (i % 29 === 0 ? 30 : 0))])}
      : await request("/api/stats", {range: period});
    if (period !== $("range").value) return;
    const sum = result.totals.reduce((total, item) => total + item.value, 0);
    const failures = result.totals.filter(item => ["ssh_failure", "auth_failure"].includes(item.kind)).reduce((total, item) => total + item.value, 0);
    counter("total", result.available ? Math.round(sum).toLocaleString() : "—");
    counter("failures", result.available ? Math.round(failures).toLocaleString() : "—");
    trapSample = result.trapping; trapReceived = performance.now(); completedTrapSeconds = result.trappedSeconds;
    updateTrapping();
    const since = new Date(trapSample.since * 1000).toLocaleString();
    counter("trapped-lifetime", `${duration(result.lifetimeTrappedSeconds)} completed external · since ${since}`);
    $("metric-status").textContent = demo ? "Synthetic preview" : "Loki · logged events (own excluded)";
    spark(result.timeline);
    errors.delete("metrics");
  } catch (error) {
    if (period !== $("range").value) return;
    for (const id of ["total", "failures", "trapped"]) counter(id, "—");
    trapSample = null;
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
      ...(result.networks ? {asn: result.networks.asn} : {}), ...lookupSources})) {
      const message = source.message || (source.lagSeconds > 90 ? `Catching up: ${Math.round(source.lagSeconds)}s behind` : "Ready; a quiet source can have no matching events");
      const issue = source.state !== "ready" || source.lagSeconds > 90;
      const card = node("div", `${name} · ${issue ? source.state === "ready" ? "catching up" : source.state : "ready"}`, `source-card${issue ? " error" : ""}`);
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

function mapProject(longitude, latitude) {
  return project(longitude, latitude, 1000, 500, $("projection").value);
}

function linePath(coordinates) {
  return coordinates.map(([lon, lat], index) => `${index ? "L" : "M"}${mapProject(lon, lat).map(value => value.toFixed(2)).join(",")}`).join("");
}

function mapLand() {
  let grid = "";
  if (isGlobe()) grid = globe.grid();
  else {
    for (let lon = -180; lon <= 180; lon += 30)
      grid += linePath(Array.from({length: 91}, (_, i) => [lon, -90 + i * 2]));
    for (let lat = -60; lat <= 60; lat += 30)
      grid += linePath([[-180, lat], [180, lat]]);
  }
  if (!$("map-grid").firstChild) $("map-grid").append(svg("path"));
  $("map-grid").firstChild.setAttribute("d", grid);
  for (const id of ["map-sphere", "map-shading"]) {
    $(id).toggleAttribute("hidden", !isGlobe());
    if (isGlobe()) $(id).setAttribute("d", globe.sphere());
  }
  const features = world?.features || [];
  while ($("map-land").children.length > features.length) $("map-land").lastChild.remove();
  while ($("map-land").children.length < features.length) $("map-land").append(svg("path"));
  for (const [index, feature] of features.entries()) {
    let d = "";
    if (isGlobe()) d = globe.path(globeLand[index]);
    else {
      const polygons = feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
      for (const polygon of polygons) for (const ring of polygon) d += linePath(ring) + "Z";
    }
    const country = $("map-land").children[index];
    country.setAttribute("d", d);
    country.dataset.country = feature.id;
    if (!country.firstChild) country.append(svg("title"));
    country.firstChild.textContent = feature.properties.name;
  }
}

function activateAtlas(level) {
  if (activeDetail === level) return;
  const data = atlas.get(level);
  world = data.world; globeLand = data.globeLand;
  activeDetail = level;
  countryLabels = data.labels;
  mapLand(); positionCountryLabels();
}

async function updateMapDetail() {
  const level = detailLevel(mapView.zoom());
  wantedDetail = level;
  if (atlas.has(level)) {
    activateAtlas(level);
    const message = `Borders · 1:${level} · ${world.features.length} country/territory shapes`;
    if ($("map-detail-status").textContent !== message) $("map-detail-status").textContent = message;
    if (errors.delete("map")) notices();
    return;
  }
  if (atlasPending.has(level) || performance.now() - (atlasFailed.get(level) ?? -Infinity) < 30000) return;
  atlasPending.add(level);
  $("map-detail-status").textContent = `Loading 1:${level} borders${activeDetail ? `; showing 1:${activeDetail}` : ""}…`;
  try {
    const response = await fetch(MAP_FILES[level], {cache: "force-cache", redirect: "error", signal: AbortSignal.timeout(30000)});
    if (!response.ok) throw new Error(`Border data unavailable (${response.status})`);
    const topology = await response.json();
    if (topology.type !== "Topology" || !topology.objects?.countries) throw new Error("Invalid border data");
    const world = decodeTopology(topology, topology.objects.countries), prepared = [];
    let slice = performance.now();
    for (const item of world.features) {
      const geometry = globeGeometry(item.geometry), area = geoArea(geometry) * 6371 ** 2;
      prepared.push({item, geometry, area});
      if (performance.now() - slice > 8) {
        await new Promise(resolve => setTimeout(resolve, 0));
        slice = performance.now();
      }
    }
    // Tiny enclaves draw last so a larger neighbour cannot cover their borders.
    prepared.sort((a, b) => b.area - a.area);
    world.features = prepared.map(value => value.item);
    const globeLand = prepared.map(value => value.geometry);
    const labels = prepared.filter(value => value.area <= 3000).toReversed().map(({item, geometry, area}) => {
      const [longitude, latitude] = geoCentroid(geometry);
      return {id: item.id, name: item.properties.name, longitude, latitude, area};
    });
    atlas.set(level, {world, globeLand, labels});
    atlasFailed.delete(level);
    if (wantedDetail === level) { activateAtlas(level); await updateMapDetail(); }
  } catch (error) {
    atlasFailed.set(level, performance.now());
    if (wantedDetail === level) {
      $("map-detail-status").textContent = activeDetail ? `Borders · 1:${activeDetail} (requested detail unavailable)` : "Borders unavailable";
      errors.set("map", `${error.message}. ${activeDetail ? "Keeping the available border detail." : "Event coordinates are still available."}`);
      notices();
    }
  } finally { atlasPending.delete(level); }
}

function positionCountryLabels() {
  const matrix = $("map").getScreenCTM();
  if (!matrix || !mapView.viewport().width || mapView.zoom() < 4) {
    $("map-labels").replaceChildren(); return;
  }
  const scale = Math.hypot(matrix.a, matrix.b), view = mapView.viewport(), occupied = [];
  const fragment = document.createDocumentFragment();
  for (const item of countryLabels) {
    const {x, y, visible} = pointPosition(item);
    if (!visible || Math.abs(x - view.x) > view.width / 2 || Math.abs(y - view.y) > view.height / 2) continue;
    const labelWidth = Math.min(180, item.name.length * 5.5) / scale, labelHeight = 17 / scale;
    const rect = {left: x, right: x + labelWidth, top: y - labelHeight, bottom: y};
    if (occupied.some(other => other.left < rect.right && other.right > rect.left && other.top < rect.bottom && other.bottom > rect.top)) continue;
    const label = svg("text", {x, y, dx: 4 / scale, dy: -4 / scale, "font-size": 10 / scale, "data-country": item.id});
    label.textContent = item.name;
    fragment.append(label); occupied.push(rect);
  }
  $("map-labels").replaceChildren(fragment);
}

function hideTooltip() { $("map-tooltip").hidden = true; }

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
  const {latest: item, place, count} = pointData.get(point);
  const target = $("map-tooltip");
  target.dataset.sourceIp = item.ip;
  target.dataset.timestamp = String(item.timestamp);
  const head = node("div", undefined, "tip-head");
  head.append(node("strong", item.title), node("time", ago(item.timestamp), "tip-ago"));
  target.replaceChildren(head,
    node("span", `${item.ip} · ${loadedEvents(count)}`), locationLabel(place), networkBadges(item),
    node("span", `${TYPES[item.type].label} · port ${item.port}${item.user ? ` · user ${item.user}` : ""}`),
    node("small", `${new Date(item.timestamp * 1000).toLocaleString()} · ${clickHint(count)}`));
  target.hidden = false;
  const center = point.getScreenCTM(), parent = $("map").parentElement.getBoundingClientRect();
  target.style.left = `${Math.max(8, Math.min(center.e - parent.left + 12, parent.width - target.offsetWidth - 8))}px`;
  target.style.top = `${Math.max(8, Math.min(center.f - parent.top - target.offsetHeight - 12, parent.height - target.offsetHeight - 8))}px`;
}

// Mobile/fullscreen keep their detail sheet; the inline map goes straight to the stream.
function opensDetail() { return mapView.expanded() || matchMedia("(max-width: 650px)").matches; }

function reveal({latest: item, count}) {
  if (opensDetail()) { detail(item, count); return; }
  if (count > 1) { showSource(item.ip); return; }
  highlighted = item.id;
  hideTooltip();
  for (const row of $("events").children) row.classList.toggle("highlighted", row.dataset.eventId === item.id);
  const row = [...$("events").children].find(value => value.dataset.eventId === item.id);
  row?.scrollIntoView({block: "center", behavior: reduced.matches ? "instant" : "smooth"});
  row?.focus({preventScroll: true});
}

function positionArrivals() {
  const parent = $("map").parentElement.getBoundingClientRect();
  const mobile = matchMedia("(max-width: 650px)").matches;
  const placed = [];
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
  if (!arrivals.size) arrivalsOmitted = 0;
  $("arrival-status").textContent = arrivalsOmitted ? `${arrivalsOmitted} more arrivals in this burst; hover or tap dots for details.` : "";
}

function arrival({latest: item, place, count}) {
  const previous = arrivals.get(item.ip);
  previous?.node.remove();
  arrivals.delete(item.ip);
  const limit = matchMedia("(max-width: 650px)").matches ? 1 : 3;
  while (arrivals.size >= limit) {
    const oldest = arrivals.keys().next().value;
    arrivals.get(oldest).node.remove(); arrivals.delete(oldest); arrivalsOmitted++;
  }
  const card = node("div", undefined, `arrival-summary type-${item.type}`);
  const label = node("span", `${item.ip} · ${loadedEvents(count)}`, "mono");
  card.append(node("strong", item.title), label, locationLabel(place),
    node("small", `${TYPES[item.type].label} · ${item.verdict}${item.user ? ` · user ${item.user}` : item.path ? ` · ${item.path}` : ` · port ${item.port}`}`),
    networkBadges(item));
  $("map-arrivals").append(card);
  arrivals.set(item.ip, {node: card, label, expires: performance.now() + 4500, spot: previous?.spot});
}

function sizeMapMarkers() {
  const matrix = $("map").getScreenCTM();
  if (!matrix) return;
  const scale = Math.hypot(matrix.a, matrix.b);
  if (!scale) return;
  const touch = matchMedia("(pointer: coarse)").matches || matchMedia("(max-width: 650px)").matches;
  for (const point of pointNodes.values()) {
    point.querySelector(".map-hit").setAttribute("r", String((touch ? 24 : 12) / scale));
    point.querySelector(".map-dot").setAttribute("r", String((touch ? 4.5 : 3) / scale));
    for (const ring of point.querySelectorAll(".map-ring, .map-flash")) ring.setAttribute("r", String(7 / scale));
  }
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

function positionMapPoints() {
  let backside = 0;
  for (const point of pointNodes.values()) {
    const source = pointData.get(point), {x, y, visible} = pointPosition(source.place);
    point.setAttribute("transform", `translate(${x} ${y})`);
    point.toggleAttribute("hidden", !visible);
    if (!visible) {
      backside++;
      if ($("map-tooltip").dataset.sourceIp === source.ip) hideTooltip();
    }
  }
  $("map-caption").textContent = `${mapCaption}${isGlobe() ? ` · ${backside} on far side` : ""}`;
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
  mapCaption = `${activity.expired} faded · ${activity.omitted} outside dot limit · ${activity.unlocated} unlocated`;
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
      point.append(svg("circle", {r: 12, class: "map-hit"}), svg("circle", {r: 5, class: "map-flash"}),
        svg("circle", {r: 5, class: "map-ring"}), svg("circle", {r: 5, class: "map-ring late"}), svg("circle", {r: 2.5, class: "map-dot"}));
      point.addEventListener("pointerenter", event => { if (event.pointerType === "mouse") tooltip(point); });
      point.addEventListener("pointerleave", hideTooltip);
      point.addEventListener("focus", () => { if (matchMedia("(hover: hover)").matches) tooltip(point); });
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
    if (!previous || previous.latest.id !== item.id || previous.count !== count || previous.place.id !== place.id) {
      if (previous) point.classList.remove(`type-${previous.latest.type}`);
      point.classList.add(`type-${item.type}`);
      point.dataset.eventId = item.id;
      const pos = pointPosition(place);
      point.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
      point.setAttribute("aria-label", `${ip}, ${place.location}: ${loadedEvents(count)}. Latest: ${item.title}. ${clickHint(count)}.`);
      if (!$("map-tooltip").hidden && $("map-tooltip").dataset.sourceIp === ip) tooltip(point);
      if (arrivals.has(ip)) arrivals.get(ip).label.textContent = `${ip} · ${loadedEvents(count)}`;
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
  $("map-setting-summary").textContent = `Map settings · hold ${dotSettings.keep} · fade ${dotSettings.fadeMinutes}m · limit ${dotSettings.maxDots}`;
  $("map-explainer").textContent = `One dot per source IP, colored by its latest matching event. Repeat requests refresh the same dot. The newest ${dotSettings.keep} sources stay bright; older dots fade over ${dotSettings.fadeMinutes} minutes. At most ${dotSettings.maxDots} are shown. Select a dot to explore its events. On the globe or in full screen, Follow moves to new activity; dragging or Reset view turns it off. IP locations are approximate.`;
}
$("map-settings").onsubmit = event => {
  event.preventDefault();
  try {
    const next = mapSettings(Object.fromEntries(Object.keys(MAP_DEFAULTS).map(key => [key, $(key).value])));
    dotSettings = next;
    showMapSettings(); hideTooltip(); mapPoints();
    localStorage.setItem("attacks.map-settings", JSON.stringify(next));
    errors.delete("mapSettings");
  } catch (error) {
    errors.set("mapSettings", `Map settings: ${error.message} Settings that cannot be saved apply only to this tab.`);
  }
  notices();
};
showMapSettings();
for (const [key, value] of Object.entries(TYPES)) {
  const item = node("span", undefined, `legend-item type-${key}`);
  item.append(node("span", undefined, "legend-dot"), node("span", value.label));
  $("legend").append(item);
}

$("own").onchange = () => applyFilters();
$("range").onchange = () => { load(true); stats(); };
$("older").onclick = () => load(false, true);
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
    $("map-gesture-hint").hidden = !isGlobe() && !mapView.expanded();
    $("map-gesture-hint").textContent = `Drag to ${isGlobe() ? "rotate" : "pan"} · ${matchMedia("(pointer: coarse)").matches ? "Pinch" : "Scroll"} to zoom`;
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
setInterval(() => { if (!document.hidden) { mapPoints(); updateTrapping(); } }, 1000);
setInterval(() => { if (!document.hidden && !demo) load(); }, 3000);
setInterval(() => { if (!document.hidden) { stats(); health(); } }, 30000);
