import { metricGroups, metricCards, metricBadges, metrics, demoProfiles, demoDisks, demoNics, demoSensors, demoFans, demoValue, demoSeries, demoMemory, metricPath, metricNumber } from "./metric-model.mjs";

const $ = id => document.getElementById(id);
function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  node.textContent = text;
  return node;
}
function svg(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}
const preferenceKey = "homeserver.hardware-metrics.v1";
const colors = ["#81bddf", "#e7b66b", "#b9a2df", "#77d7c1"];

export function createMetricUI({ openPopup, closePopup, onError, isVisible }) {
  let settings = { groups: Object.fromEntries(Object.keys(metricGroups).map(id => [id, true])), hidden: [], positions: {}, profile: "mixed", window: 120 };
  try {
    const saved = localStorage.getItem(preferenceKey);
    if (saved) {
      const value = JSON.parse(saved);
      if (value.version !== 1 || !Object.hasOwn(demoProfiles, value.profile) || ![60, 120, 300].includes(value.window) ||
          !value.groups || Object.keys(metricGroups).some(id => typeof value.groups[id] !== "boolean") ||
          !Array.isArray(value.hidden) || value.hidden.some(id => !metricCards.some(card => card.id === id)) ||
          !value.positions || Object.entries(value.positions).some(([id, point]) =>
            !metricCards.some(card => card.id === id) || !Array.isArray(point) || point.length !== 2 ||
            point.some((number, axis) => !Number.isFinite(number) || number < 0 || number > [1440, 840][axis]))) {
        throw new Error("Unrecognized metric layout");
      }
      settings = value;
    }
  } catch (error) {
    onError(`Metric preferences could not be loaded: ${error.message}. Default layout is in use; inspection annotations are untouched.`);
  }
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let playing = !reducedMotion.matches, playbackChosen = false;
  let second = 300, activePanel = "layers", disk = "array", nic = "bond0", cpuView = "cores";
  let charts = [];
  const cards = new Map(), badges = new Map(), lines = new Map();
  const frame = () => ({ second, profile: settings.profile, provenance: "synthetic" });
  const value = id => demoValue(id, second, settings.profile);
  const save = () => {
    try { localStorage.setItem(preferenceKey, JSON.stringify({ ...settings, version: 1 })); }
    catch (error) { onError(`Metric layout is tab-only: ${error.message}. Inspection annotations are unaffected.`); }
  };
  const button = (text, action, attrs = {}) => {
    const node = el("button", { type: "button", ...attrs }, text);
    node.addEventListener("click", action);
    return node;
  };
  function group(id, visible) {
    settings.groups[id] = visible;
    if (visible) settings.hidden = settings.hidden.filter(card => metricCards.find(definition => definition.id === card).group !== id);
    save(); controls(); updateVisibility();
  }
  function openPanel(id) {
    activePanel = id;
    renderPanel();
    openPopup($("metrics-dialog"));
    updateCharts();
  }
  function chart(ids, title, compact = false) {
    const box = el("article", { class: `performance-chart${compact ? " mini-chart" : ""}` });
    const header = el("div", { class: "metric-chart-heading" });
    header.append(el("span", {}, title), el("span", { class: "metric-chart-values" }));
    if (ids.length > 1) {
      const labels = title.split(" / ");
      header.firstChild.replaceChildren(...ids.flatMap((id, index) => {
        const label = el("span", {}, labels.length === ids.length ? labels[index] : metrics.get(id).label);
        label.style.color = colors[index % colors.length];
        return index ? [document.createTextNode(" / "), label] : [label];
      }));
    }
    const plot = svg("svg", { viewBox: "0 0 300 80", preserveAspectRatio: "none", role: "img", "aria-label": `${title} · synthetic history` });
    for (const y of [0, 20, 40, 60, 80]) plot.append(svg("path", { d: `M0 ${y}H300`, class: "metric-gridline" }));
    for (const x of [75, 150, 225]) plot.append(svg("path", { d: `M${x} 0V80`, class: "metric-gridline" }));
    const area = svg("path", { fill: ids.length > 1 ? colors[0] : metricGroups[metrics.get(ids[0]).group].color, opacity: ".09", stroke: "none" });
    plot.append(area);
    const paths = ids.map((id, index) => {
      const path = svg("path", { class: "metric-trace", fill: "none", stroke: ids.length > 1 ? colors[index % colors.length] : metricGroups[metrics.get(id).group].color });
      plot.append(path); return path;
    });
    const cursor = svg("path", { class: "metric-cursor", visibility: "hidden" });
    const tooltip = el("div", { class: "metric-tooltip", hidden: "" });
    plot.append(cursor);
    const footer = el("div", { class: "metric-chart-footer" });
    box.append(header, plot, footer, tooltip);
    const record = { box, header, plot, area, paths, footer, ids, compact, values: [] };
    plot.addEventListener("pointermove", event => {
      const bounds = plot.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
      const index = Math.round(ratio * settings.window);
      cursor.setAttribute("d", `M${ratio * 300} 0V80`);
      cursor.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      tooltip.textContent = `DEMO · −${settings.window - index}s · ${ids.map((id, i) => `${metrics.get(id).label}: ${metricNumber(record.values[i]?.[index], metrics.get(id).unit)}`).join(" / ")}`;
    });
    plot.addEventListener("pointerleave", () => { tooltip.hidden = true; cursor.setAttribute("visibility", "hidden"); });
    charts.push(record);
    return box;
  }
  function composition() {
    const container = el("div", { class: "metric-composition" });
    const bar = el("div", { class: "metric-memory-bar", role: "img", "aria-label": "Synthetic memory composition" });
    for (const key of ["apps", "cache", "kernel", "free"]) bar.append(el("span", { "data-memory-part": key }));
    container.append(bar, el("div", { class: "metric-composition-label" }));
    return container;
  }
  function updateCharts() {
    charts = charts.filter(record => record.box.isConnected);
    for (const record of charts) {
      const signalGroup = metrics.get(record.ids[0]).group;
      if (record.box.closest("#metric-panel") && ["temperatures", "fans"].includes(signalGroup)) record.box.hidden = !settings.groups[signalGroup];
      if (record.box.closest("[hidden]") || (record.box.closest("dialog") && !record.box.closest("dialog").open)) continue;
      record.values = record.ids.map(id => demoSeries(id, second, settings.window, settings.profile));
      record.ids.forEach((id, i) => {
        const definition = metrics.get(id);
        record.paths[i].setAttribute("d", metricPath(record.values[i], definition.minimum, definition.maximum));
      });
      record.area.setAttribute("d", record.values[0].every(Number.isFinite) ? `${record.paths[0].getAttribute("d")}L300,80L0,80Z` : "");
      record.header.lastChild.replaceChildren(...record.ids.map((id, index) => {
        const node = el("span", {}, metricNumber(value(id), metrics.get(id).unit));
        if (record.ids.length > 1) node.style.color = colors[index % colors.length];
        return node;
      }));
      const first = metrics.get(record.ids[0]);
      const samples = record.values[0].filter(Number.isFinite);
      record.footer.textContent = record.compact
        ? `${settings.window / 60}m ago → now · DEMO`
        : `${settings.window / 60}m ago → now · scale ${first.minimum}–${metricNumber(first.maximum, first.unit)} · ${record.ids.length > 1 ? `${first.label} peak` : "peak"} ${metricNumber(Math.max(...samples), first.unit)}`;
      record.plot.setAttribute("aria-label", `${record.header.firstChild.textContent}. Synthetic, not live. ${record.header.lastChild.textContent}. ${record.footer.textContent}`);
    }
    for (const node of document.querySelectorAll("[data-metric-value]")) {
      const id = node.dataset.metricValue;
      node.textContent = metricNumber(value(id), metrics.get(id).unit);
    }
    const memory = demoMemory(second, settings.profile);
    for (const node of document.querySelectorAll(".metric-composition")) {
      for (const part of node.querySelectorAll("[data-memory-part]")) {
        const amount = memory[part.dataset.memoryPart];
        part.style.width = `${amount / 128 * 100}%`;
        part.title = `${part.dataset.memoryPart}: ${metricNumber(amount, "GiB")}`;
      }
      node.querySelector(".metric-memory-bar").setAttribute("aria-label", `Synthetic memory: ${Object.entries(memory).filter(([id]) => id !== "used").map(([id, amount]) => `${id} ${metricNumber(amount, "GiB")}`).join(", ")}`);
      node.querySelector(".metric-composition-label").textContent = `${memory.used.toFixed(1)} / 128 GiB in use · ${(memory.used / 128 * 100).toFixed(1)}%`;
    }
    for (const node of document.querySelectorAll("[data-fullness]")) {
      const id = node.dataset.fullness, definition = metrics.get(id), used = value(id);
      node.querySelector("span").style.width = `${used / definition.maximum * 100}%`;
      node.querySelector("p").textContent = `${node.dataset.compact === "true" ? "" : `${definition.label}: `}${used.toFixed(2)} / ${definition.maximum} ${definition.unit} · ${(used / definition.maximum * 100).toFixed(1)}% used · DEMO`;
    }
    for (const [id, node] of badges) {
      const badge = metricBadges.find(b => b.id === id);
      const readout = badge.ids
        ? `${Math.min(...badge.ids.map(value)).toFixed(0)}–${Math.max(...badge.ids.map(value)).toFixed(0)} °C`
        : metricNumber(value(id), metrics.get(id).unit);
      node.textContent = `${badge.label} ${readout} · DEMO`;
    }
    $("metric-clock").textContent = `${Math.floor(second / 60)}:${String(second % 60).padStart(2, "0")} simulated`;
    scheduleLayout();
  }
  function fullness(id, compact = false) {
    const node = el("div", { class: "metric-fullness", "data-fullness": id, "data-compact": String(compact) });
    const bar = el("div"); bar.append(el("span"));
    node.append(bar, el("p"));
    return node;
  }
  for (const definition of metricCards) {
    const card = el("article", { class: `metric-card${definition.mobileOnly ? " mobile-metric-card" : ""}`, "data-card": definition.id });
    card.style.setProperty("--metric-color", metricGroups[definition.group].color);
    const heading = el("header", { class: "metric-card-heading" });
    const handle = button("⠿", () => {}, { class: "metric-drag", "aria-label": `Move ${definition.label}; arrow keys also move it`, title: "Drag to position; arrow keys move, Shift moves faster" });
    heading.append(handle, button(definition.label, () => {
      if (definition.id === "nvme") disk = "nvme1n1";
      if (definition.id === "storage") disk = "array";
      openPanel(definition.group === "temperatures" || definition.group === "fans" ? "sensors" : definition.group);
    }, { class: "metric-card-title", title: definition.label }),
      button("×", () => { settings.hidden.push(definition.id); save(); updateVisibility(); $("metrics-button").focus({ preventScroll: true }); }, { class: "metric-card-close", "aria-label": `Hide ${definition.label}` }));
    const titles = { gpu: "3D / video encode", network: "Receive / send", storage: "Read / write", nvme: "Read / write", fans: "Hub tach speed", temperatures: "Temperatures", memory: "In use" };
    card.append(heading, chart(definition.series, titles[definition.id] ?? "Utilization", true));
    if (definition.id === "memory") card.append(composition());
    else if (definition.id === "storage") card.append(fullness("data-used", true));
    else if (definition.footer.length) {
      const footer = el("div", { class: "metric-card-extra" });
      for (const id of definition.footer) footer.append(el("span", {}, `${metrics.get(id).label}: `), el("strong", { "data-metric-value": id }));
      card.append(footer);
    }
    $("metric-layer").append(card); cards.set(definition.id, card);
    const line = svg("path", { class: "metric-leader", stroke: metricGroups[definition.group].color });
    $("metric-leaders").append(line); lines.set(definition.id, line);
    let drag = null;
    handle.addEventListener("pointerdown", event => {
      if (event.button !== 0) return;
      const point = scenePoint(event.clientX, event.clientY);
      const current = currentPosition(definition.id);
      drag = { start: point, current };
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    handle.addEventListener("pointermove", event => {
      if (!drag) return;
      const point = scenePoint(event.clientX, event.clientY);
      move(definition, drag.current[0] + point.x - drag.start.x, drag.current[1] + point.y - drag.start.y);
    });
    const finish = () => { if (drag) { drag = null; save(); } };
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
    handle.addEventListener("lostpointercapture", finish);
    handle.addEventListener("keydown", event => {
      const delta = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      if (!delta) return;
      event.preventDefault();
      const current = currentPosition(definition.id), step = event.shiftKey ? 40 : 10;
      move(definition, current[0] + delta[0] * step, current[1] + delta[1] * step); save();
    });
  }
  function scenePoint(x, y) {
    return new DOMPoint(x, y).matrixTransform($("board").getScreenCTM().inverse());
  }
  function currentPosition(id) {
    const bounds = cards.get(id).getBoundingClientRect(), point = scenePoint(bounds.left, bounds.top);
    return [point.x, point.y];
  }
  function move(definition, x, y) {
    const scale = $("board").getScreenCTM().a, card = cards.get(definition.id);
    settings.positions[definition.id] = [Math.max(20, Math.min(1440 - card.offsetWidth / scale - 12, x)), Math.max(65, Math.min(840 - card.offsetHeight / scale - 12, y))];
    layout();
  }
  for (const definition of metricBadges) {
    const node = button("", () => openPanel("sensors"), { class: "metric-badge", title: "Invented channel. Open all synthetic sensor graphs; * means physical binding or real telemetry support is unverified." });
    node.style.setProperty("--metric-color", metricGroups[definition.group].color);
    $("metric-layer").append(node); badges.set(definition.id, node);
  }
  function layout() {
    const bounds = $("metric-layer").getBoundingClientRect(), matrix = $("board").getScreenCTM();
    if (!matrix) return;
    $("metric-leaders").setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
    const point = (x, y) => {
      const p = new DOMPoint(x, y).matrixTransform(matrix);
      return { x: p.x - bounds.left, y: p.y - bounds.top };
    };
    const automatic = new Map();
    let stackBottom = -Infinity;
    for (const id of ["gpu", "memory", "cpu"]) {
      if (settings.positions[id] || cards.get(id).hidden) continue;
      const definition = metricCards.find(card => card.id === id), p = point(definition.x, definition.y);
      p.y = Math.max(p.y, stackBottom);
      automatic.set(id, p);
      stackBottom = p.y + cards.get(id).offsetHeight + 10;
    }
    for (const definition of metricCards) {
      const node = cards.get(definition.id), position = settings.positions[definition.id] ?? [definition.x, definition.y];
      const p = automatic.get(definition.id) ?? point(...position);
      if (!settings.positions[definition.id] && !automatic.has(definition.id)) p.y = Math.min(p.y, point(1440, 840).y - node.offsetHeight - 8);
      node.style.left = `${p.x}px`; node.style.top = `${p.y}px`;
      const anchor = anchorBounds(definition.anchor);
      const line = lines.get(definition.id);
      if (anchor) {
        const a = point(anchor.x + anchor.width / 2, anchor.y + anchor.height / 2);
        const edge = p.x + (a.x > p.x + node.offsetWidth / 2 ? node.offsetWidth : 0), mid = p.y + Math.min(40, node.offsetHeight / 2);
        line.setAttribute("d", `M${a.x},${a.y}L${edge + (a.x > edge ? 12 : -12)},${mid}L${edge},${mid}`);
      }
      line.hidden = node.hidden || !anchor || definition.mobileOnly;
      line.style.display = line.hidden ? "none" : "";
    }
    for (const definition of metricBadges) {
      const p = point(definition.x, definition.y), node = badges.get(definition.id);
      node.style.left = `${p.x}px`; node.style.top = `${p.y}px`;
    }
  }
  function anchorBounds(id) {
    if (id === "nvme-group") {
      const bounds = ["drive-M2_1", "drive-M2_2"].map(part => anchorBounds(part)).filter(Boolean);
      if (!bounds.length) return undefined;
      const x = Math.min(...bounds.map(box => box.x)), y = Math.min(...bounds.map(box => box.y));
      return { x, y, width: Math.max(...bounds.map(box => box.x + box.width)) - x, height: Math.max(...bounds.map(box => box.y + box.height)) - y };
    }
    return document.querySelector(`.hardware-part[data-id="${id}"]`)?.getBBox();
  }
  function updateVisibility() {
    for (const definition of metricCards) cards.get(definition.id).hidden = !settings.groups[definition.group] || settings.hidden.includes(definition.id) || !isVisible(definition.anchor);
    for (const definition of metricBadges) badges.get(definition.id).hidden = !settings.groups[definition.group] || !isVisible(definition.anchor);
    $("metric-layer").hidden = !isVisible(null) || ![...cards.values(), ...badges.values()].some(node => !node.hidden && getComputedStyle(node).display !== "none");
    $("metric-controls").classList.toggle("metrics-context-hidden", !isVisible(null));
    updateCharts();
  }
  function controls() {
    $("metric-play").textContent = playing ? "Pause" : "Play demo";
    $("metric-play").setAttribute("aria-pressed", String(playing));
    $("metric-play-dialog").textContent = playing ? "Pause demo" : "Play demo";
    $("metric-play-dialog").setAttribute("aria-pressed", String(playing));
    $("metric-playback-note").textContent = playing ? "Invented data advancing at 1 simulated second / second." : `Paused synthetic history.${reducedMotion.matches ? " Reduced Motion is honored; Play demo is an explicit opt-in." : ""}`;
    for (const node of $("metric-group-controls").children) {
      node.setAttribute("aria-pressed", String(settings.groups[node.dataset.group]));
      node.title = `${settings.groups[node.dataset.group] ? "Hide" : "Show"} all ${metricGroups[node.dataset.group].label.toLowerCase()}`;
    }
    for (const node of document.querySelectorAll("[data-group-check]")) node.checked = settings.groups[node.dataset.groupCheck];
    for (const node of document.querySelectorAll("[data-card-check]")) node.checked = !settings.hidden.includes(node.dataset.cardCheck);
  }
  function playback() { playing = !playing; playbackChosen = true; controls(); }
  $("metric-play").addEventListener("click", playback);
  $("metric-play-dialog").addEventListener("click", playback);
  reducedMotion.addEventListener("change", () => { if (!playbackChosen) playing = !reducedMotion.matches; controls(); });
  for (const [id, definition] of Object.entries(metricGroups)) {
    const node = button(definition.label, () => group(id, !settings.groups[id]), { "data-group": id, "aria-pressed": "true" });
    node.style.setProperty("--metric-color", definition.color);
    $("metric-group-controls").append(node);
  }
  function all(visible) {
    for (const id of Object.keys(settings.groups)) settings.groups[id] = visible;
    if (visible) settings.hidden = [];
    save(); controls(); updateVisibility();
  }
  $("metric-show-all").addEventListener("click", () => all(true));
  $("metric-hide-all").addEventListener("click", () => all(false));
  $("metrics-button").addEventListener("click", () => openPanel("layers"));
  $("close-metrics").addEventListener("click", () => closePopup($("metrics-dialog")));
  $("metric-reset-layout").addEventListener("click", () => { settings.positions = {}; save(); updateVisibility(); renderPanel(); });
  for (const [id, label] of Object.entries(demoProfiles)) $("metric-profile").append(el("option", { value: id }, label));
  $("metric-profile").value = settings.profile;
  $("metric-window").value = String(settings.window);
  $("metric-profile").addEventListener("change", () => { settings.profile = $("metric-profile").value; save(); updateCharts(); });
  $("metric-window").addEventListener("change", () => { settings.window = Number($("metric-window").value); save(); updateCharts(); });
  const panelLabels = { layers: "Layers & layout", cpu: "CPU", memory: "Memory", storage: "Storage", gpu: "GPU", network: "Network", sensors: "Sensors & fans" };
  for (const [id, label] of Object.entries(panelLabels)) $("metric-panel-nav").append(button(label, () => { activePanel = id; renderPanel(); }, { "data-panel": id, "aria-pressed": "false" }));
  function select(options, current, action, label) {
    const control = el("select", { "aria-label": label });
    for (const [id, text] of options) control.append(el("option", { value: id }, text));
    control.value = current;
    control.addEventListener("change", () => {
      action(control.value); renderPanel();
      $("metric-panel").querySelector("select")?.focus({ preventScroll: true });
    });
    return control;
  }
  function renderPanel() {
    const body = $("metric-panel");
    body.replaceChildren();
    for (const tab of $("metric-panel-nav").children) tab.setAttribute("aria-pressed", String(tab.dataset.panel === activePanel));
    body.append(el("h3", {}, panelLabels[activePanel]));
    const grid = el("div", { class: "metric-detail-grid" });
    const add = (ids, title) => grid.append(chart(ids, title));
    if (activePanel === "layers") {
      body.append(el("p", { class: "muted compact" }, "Charts are movable callouts, not physical measurements. Drag a chart's grip or use its arrow keys; positions and layer choices are saved only in this browser. Narrow screens dock charts in a swipeable tray."));
      const checks = el("div", { class: "metric-layer-checks" });
      for (const [id, definition] of Object.entries(metricGroups)) {
        const label = el("label"), input = el("input", { type: "checkbox", "data-group-check": id });
        input.checked = settings.groups[id];
        input.addEventListener("change", () => group(id, input.checked));
        label.append(input, document.createTextNode(definition.label)); checks.append(label);
      }
      body.append(checks);
      const actions = el("div", { class: "toolbar" });
      actions.append(button("Show all temperatures", () => group("temperatures", true)), button("Hide all temperatures", () => group("temperatures", false)), button("Show all layers", () => all(true)), button("Hide all layers", () => all(false)));
      body.append(actions, el("h4", {}, "Individual chart cards"));
      for (const definition of metricCards) {
        const label = el("label", { class: "metric-card-check" }), input = el("input", { type: "checkbox", "data-card-check": definition.id });
        input.checked = !settings.hidden.includes(definition.id);
        input.addEventListener("change", () => {
          settings.hidden = settings.hidden.filter(id => id !== definition.id);
          if (!input.checked) settings.hidden.push(definition.id);
          save(); updateVisibility();
        });
        label.append(input, document.createTextNode(`${definition.label}${definition.mobileOnly ? " (compact screens)" : ""}`)); body.append(label);
      }
      body.append(el("p", { class: "metric-demo-explainer" }, "All current values and histories are fabricated. Scenarios regenerate the entire invented history. Colors identify signal families, not alarm thresholds. Sensor badges summarize groups where disk/socket mappings are unknown; a badge is not a new hardware binding. Connector inspection hides these overlays. Fan-motion studies remain independently controlled."));
    } else if (activePanel === "cpu") {
      add(["cpu"], "Overall · 16 cores / 32 logical CPUs");
      add(["cpu-clock"], "CPU clock");
      add(["cpu-power"], "Package power");
      body.append(select([["cores", "16 cores"], ["threads", "32 logical CPUs"]], cpuView, next => { cpuView = next; }, "CPU graph grouping"));
      const cores = el("div", { class: "metric-core-grid" });
      for (let i = 0; i < (cpuView === "cores" ? 16 : 32); i += 1) cores.append(chart([`${cpuView === "cores" ? "core" : "thread"}-${i}`], `${cpuView === "cores" ? "Core" : "Logical CPU"} ${i}`, true));
      body.append(grid, el("p", { class: "muted compact" }, "Synthetic core/thread grouping only. Physical Linux CPU IDs and SMT sibling topology have not been bound."), cores);
    } else if (activePanel === "memory") {
      const legend = el("div", { class: "metric-memory-legend" });
      for (const [id, label] of [["apps", "Applications"], ["cache", "File cache / reclaimable"], ["kernel", "Kernel"], ["free", "Free"]]) {
        const item = el("span", { "data-memory-label": id }, `${label} `);
        item.append(el("strong", { "data-metric-value": `memory-${id}` }));
        legend.append(item);
      }
      body.append(composition(), legend);
      for (const id of ["memory-used", "memory-apps", "memory-cache", "memory-kernel", "memory-free", "swap"]) add([id], metrics.get(id).label);
      body.append(grid, el("p", { class: "muted compact" }, "128 GiB illustrative accounting: in use = apps + kernel; all four composition buckets sum to capacity. A Linux collector must define non-overlapping accounting; /proc/meminfo fields cannot simply be added together."));
    } else if (activePanel === "storage") {
      body.append(select([["array", "HDD set / data workload"], ...demoDisks.map(node => [node.id, `${node.label} · ${node.kind}`])], disk, next => { disk = next; }, "Storage device"));
      add([`disk-${disk}-read`, `disk-${disk}-write`], "Read / write transfer rate");
      add([`disk-${disk}-active`], "Active time · busy, not capacity");
      add([`disk-${disk}-latency`], "Response time");
      add([`disk-${disk}-queue`], "Queue depth");
      body.append(grid, el("h4", {}, "Filesystem fullness · not per RAID-member usage"), fullness("data-used"), fullness("root-used"),
        el("p", { class: "muted compact" }, "Raw member disks do not each have a /data fullness percentage. Physical bays and NVMe socket bindings remain unknown. The /data LV includes ordinary NVMe extents as well as RAID and cache. Activity above is invented, not the Linux inventory snapshot."));
    } else if (activePanel === "gpu") {
      for (const id of ["gpu-3d", "gpu-copy", "gpu-encode", "gpu-decode", "gpu-dedicated", "gpu-shared", "gpu-power", "temp-gpu"]) add([id], metrics.get(id).label);
      body.append(grid, el("p", { class: "muted compact" }, "Task-Manager-inspired, all synthetic. 3D, copy and shared/host memory require collector-specific Linux definitions and may be unavailable. Generic NVIDIA GPU utilization must not be relabeled as 3D. Missing engines must stay unavailable, not zero. Shared/host chart scale is illustrative, not a hardware pool limit."));
    } else if (activePanel === "network") {
      body.append(select(demoNics.map(id => [id, id]), nic, next => { nic = next; }, "Network interface"));
      add([`net-${nic}-rx`, `net-${nic}-tx`], "Receive / send · separate full-duplex directions");
      body.append(grid, el("p", { class: "muted compact" }, "10 Gb/s per direction; active-backup is not a 20 Gb/s bond. Interface names come from a separate Linux snapshot, traffic is entirely invented. LAN1/LAN2 port pairing is unassigned."));
    } else if (activePanel === "sensors") {
      const actions = el("div", { class: "toolbar" });
      actions.append(button("Show all temperatures", () => group("temperatures", true)), button("Hide all temperatures", () => group("temperatures", false)),
        button("Show all fan speeds", () => group("fans", true)), button("Hide all fan speeds", () => group("fans", false)));
      body.append(actions, el("p", { class: "muted compact" }, "Every channel below is fabricated, including rear fan RPMs: those fans have no tach. FAN3 represents one hub return, not six individually measured fans. Secondary NVMe channels are illustrative; real availability/meaning must be verified. No air probes or physical disk/socket bindings are invented."));
      for (const definition of [...demoSensors, ...demoFans]) add([definition.id], definition.label);
      body.append(grid);
    }
    controls(); updateCharts();
  }
  let layoutPending = false;
  const scheduleLayout = () => {
    if (layoutPending) return;
    layoutPending = true;
    requestAnimationFrame(() => { layoutPending = false; layout(); });
  };
  document.querySelector(".map-scroll").addEventListener("scroll", scheduleLayout, { passive: true });
  new ResizeObserver(scheduleLayout).observe(document.querySelector(".map-panel"));
  matchMedia("(max-width: 1000px)").addEventListener("change", updateVisibility);
  $("metrics-dialog").addEventListener("close", () => {
    updateCharts();
    if (document.activeElement === document.body || document.activeElement.closest("[hidden]")) $("metrics-button").focus({ preventScroll: true });
  });
  const timer = setInterval(() => {
    if (!playing || document.hidden) return;
    second += 1; updateCharts();
  }, 1000);
  controls(); updateVisibility();
  return {
    updateVisibility, layout: scheduleLayout, openPanel, frame,
    panelFor(part) {
      if (!part) return null;
      if (part === "cpu") return "cpu";
      if (part.startsWith("dimm-")) return "memory";
      if (part === "gpu") return "gpu";
      if (part === "network-ports") return "network";
      if (part === "disk-bays" || part === "hba" || part.startsWith("drive-")) return "storage";
      if (part.includes("fan") || part === "motherboard") return "sensors";
      return null;
    },
    destroy() { clearInterval(timer); },
  };
}
