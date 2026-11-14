// Health summary and notifications. One fixed-size chip in the header always
// says how trustworthy the page is; details open in an anchored panel and new
// problems are announced once as a toast. Nothing here moves the page layout.
import { anchorPopover } from "./popover.mjs";

const sourceNames = {
  inventory: "Device inventory", cpu: "CPU usage", "cpu-power": "CPU package power", k10temp: "CPU temperature",
  memory: "Memory", block: "Disk activity", filesystems: "Filesystems", cache: "dm-cache", smart: "SMART",
  network: "Network", bmc: "BMC sensors", gpu: "GPU", "gpu-engines": "GPU engines", "rear-fans": "Rear fans",
};
const healthyStates = new Set(["ok", "assumed"]);
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

export function ageText(milliseconds) {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  if (seconds < 90) return `${seconds} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

// Per-disk SMART sources collapse into one row, which also keeps device
// identifiers out of the interface.
export function sourceGroups(sources = {}) {
  const groups = new Map();
  for (const [id, source] of Object.entries(sources)) {
    const key = id.startsWith("smart:") ? "smart" : id;
    if (!groups.has(key)) groups.set(key, { id: key, label: sourceNames[key] ?? key, total: 0, failing: 0, states: new Set(), note: "" });
    const group = groups.get(key);
    group.total += 1;
    group.states.add(source.status);
    if (!healthyStates.has(source.status)) group.failing += 1;
    if (source.note && group.total === 1) group.note = source.note;
  }
  return [...groups.values()].map(({ states, ...group }) => ({
    ...group,
    state: group.failing ? "failing" : states.has("assumed") ? "assumed" : "ok",
    text: group.failing
      ? group.total > 1 ? `${group.failing} of ${group.total} ${[...states].filter(state => !healthyStates.has(state)).join("/")}` : [...states][0]
      : states.has("assumed") ? "assumed" : group.total > 1 ? `${group.total} OK` : "OK",
  })).sort((a, b) => b.failing - a.failing || a.label.localeCompare(b.label));
}

function issueItem(text) {
  const split = text.indexOf(": ");
  const subject = split > 0 && split <= 40 && !text.slice(0, split).includes(" ") ? text.slice(0, split) : "";
  return {
    severity: /operator attention|needs_check|read-only/.test(text) ? "error" : "warn",
    title: subject || "Collector notice",
    detail: subject ? text.slice(split + 2) : text,
  };
}

export function healthOf(data, now = Date.now()) {
  if (data.mode !== "live") {
    return { level: "demo", label: "Demo", headline: "Synthetic demo data",
      note: "Nothing on this page is measured. The deployed monitor shows live readings.", items: [], sources: [], age: null };
  }
  const captured = Date.parse(data.snapshot?.capturedAt);
  const age = Number.isFinite(captured) ? now - captured : null;
  const items = [];
  if (data.error) {
    items.push({ severity: "error", title: "Live data request failed",
      detail: `${data.error}. Retrying every 5 seconds. Readings are hidden rather than shown out of date.` });
  } else if (data.snapshot && data.stale) {
    items.push({ severity: "error", title: "Collector has stopped updating",
      detail: `The newest snapshot is ${ageText(age)} old. Readings are hidden until a fresh one arrives.` });
  }
  // Notices inside an out-of-date snapshot describe the past, so they wait for a fresh one.
  if (!data.stale) for (const issue of data.snapshotIssues ?? []) items.push(issueItem(issue));
  if (data.historyError && !data.stale) {
    items.push({ severity: "warn", title: "Chart history unavailable",
      detail: `${data.historyError}. Current readings are unaffected.` });
  }
  const level = !data.snapshot && !data.error ? "connecting" : data.stale ? "down" : items.length ? "warn" : "ok";
  return {
    level, items, age,
    sources: data.stale ? [] : sourceGroups(data.snapshot?.sources),
    label: { connecting: "Connecting…", down: "No live data", warn: plural(items.length, "issue"), ok: "Live" }[level],
    headline: { connecting: "Waiting for the first snapshot", down: "Live data unavailable",
      warn: `Live, with ${plural(items.length, "issue")}`, ok: "Live · all sources reporting" }[level],
    note: age === null ? "" : data.stale ? `Last snapshot ${ageText(age)} ago`
      : `Snapshot ${ageText(age)} old · refreshed every ${data.snapshot.intervalSeconds ?? 5} s`,
  };
}

// A problem must persist this long before it is announced, so a single
// failed request never flashes a toast.
export const announceAfter = 8000;

export function createStatusCenter({ chip, panel, region }) {
  const make = (tag, className, text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  };
  const label = chip.querySelector(".status-label"), badge = chip.querySelector(".status-badge");
  const menu = anchorPopover(chip, panel, { align: "start" });
  const local = [];
  const issues = new Map();
  let health = null, signature = "", hadAnnouncement = false;

  const topLayer = "popover" in region && typeof region.showPopover === "function";
  if (topLayer) region.popover = "manual";
  function syncRegion(raise = false) {
    if (!topLayer) return;
    const open = region.matches(":popover-open");
    if (open && (raise || !region.childElementCount)) region.hidePopover();
    if (region.childElementCount && !region.matches(":popover-open")) region.showPopover();
  }

  function toast({ level = "info", title, detail = "", details = false, lifetime = 7000 }) {
    const node = make("div", "toast");
    node.dataset.level = level;
    node.setAttribute("role", level === "error" ? "alert" : "status");
    const text = make("div", "toast-text");
    text.append(make("strong", "", title));
    if (detail) text.append(make("p", "", detail));
    node.append(text);
    let timer = null;
    const dismiss = () => { clearTimeout(timer); node.remove(); syncRegion(); };
    const arm = () => { clearTimeout(timer); timer = setTimeout(dismiss, lifetime); };
    if (details) {
      const action = make("button", "toast-action", "Details");
      action.type = "button";
      action.addEventListener("click", () => { dismiss(); menu.show(); });
      node.append(action);
    }
    const close = make("button", "toast-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss notification");
    close.addEventListener("click", dismiss);
    node.append(close);
    node.addEventListener("pointerenter", () => clearTimeout(timer));
    node.addEventListener("pointerleave", arm);
    while (region.childElementCount >= 3) region.firstElementChild.remove();
    region.append(node);
    syncRegion();
    arm();
  }

  function render() {
    const body = document.createDocumentFragment();
    const head = make("div", "status-head");
    const words = make("div");
    words.append(make("strong", "", health.headline), make("span", "status-note", health.note));
    head.append(make("i", "status-dot"), words);
    body.append(head);
    if (health.items.length) {
      const list = make("ul", "status-items");
      for (const item of health.items) {
        const row = make("li");
        row.dataset.severity = item.severity;
        row.append(make("strong", "", item.title), make("p", "", item.detail));
        list.append(row);
      }
      body.append(list);
    }
    if (health.sources.length) {
      const section = make("section", "status-sources");
      const failing = health.sources.filter(source => source.failing).length;
      section.append(make("h3", "", failing ? `Sources · ${failing} of ${health.sources.length} need attention` : `Sources · ${health.sources.length} reporting`));
      const list = make("ul");
      for (const source of health.sources) {
        const row = make("li");
        row.dataset.state = source.state;
        if (source.note) row.title = source.note;
        row.append(make("i", "status-dot"), make("span", "", source.label), make("span", "status-source-state", source.text));
        list.append(row);
      }
      section.append(list);
      body.append(section);
    }
    if (local.length) {
      const section = make("section", "status-local");
      section.append(make("h3", "", "This browser"));
      const list = make("ul", "status-items");
      for (const entry of local) {
        const row = make("li");
        row.dataset.severity = entry.error ? "warn" : "info";
        const dismiss = make("button", "", "Dismiss");
        dismiss.type = "button";
        dismiss.addEventListener("click", () => { local.splice(local.indexOf(entry), 1); signature = ""; refresh(); });
        row.append(make("p", "", entry.message), dismiss);
        list.append(row);
      }
      section.append(list);
      body.append(section);
    }
    panel.replaceChildren(body);
    panel.dataset.level = health.level;
    menu.place();
  }

  function refresh() {
    if (!health) return;
    chip.dataset.level = health.level;
    label.textContent = health.label;
    badge.hidden = !local.length;
    badge.textContent = String(local.length);
    chip.setAttribute("aria-label", `Status: ${health.headline}${local.length ? `, ${plural(local.length, "browser notice")}` : ""}. Show details`);
    const next = JSON.stringify([health.level, health.headline, health.items, health.sources, local]);
    if (next !== signature) { signature = next; render(); }
    else panel.querySelector(".status-note").textContent = health.note;
  }

  return {
    update(next, now = Date.now()) {
      health = next;
      refresh();
      const problem = health.level === "down" || health.level === "warn";
      const active = new Set();
      if (problem) for (const item of health.items) {
        // An outage stays the same problem as its snapshot age/retry reason changes.
        const key = health.level === "down" ? "down" : JSON.stringify([item.severity, item.title, item.detail]);
        active.add(key);
        if (!issues.has(key)) issues.set(key, { since: now, announced: false });
        const issue = issues.get(key);
        if (!issue.announced && now - issue.since >= announceAfter) {
          issue.announced = true;
          hadAnnouncement = true;
          toast({ level: item.severity, title: item.title, detail: item.detail, details: true, lifetime: 12000 });
        }
      }
      for (const key of issues.keys()) if (!active.has(key)) issues.delete(key);
      if (hadAnnouncement && health.level === "ok") {
        hadAnnouncement = false;
        toast({ level: "ok", title: "Live data is healthy again" });
      }
    },
    notify(message, error = false) {
      if (local.some(entry => entry.message === message)) return;
      if (error) { local.push({ message, error }); refresh(); }
      toast({ level: error ? "warn" : "info", title: message, lifetime: error ? 12000 : 7000 });
    },
    // A modal dialog opened later sits above earlier top-layer content.
    raise() { syncRegion(true); },
  };
}
