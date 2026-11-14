import { metricGroups, memoryColors, metricCards, metricBadges, metrics, demoProfiles, demoDisks, demoNics, demoSensors, demoFans, demoValue, demoSeries, demoMemory, metricPath, metricNumber, historyWindows, defaultHistoryWindows, historyLabel, sharedMetricScale, windowMetricScale, chartNumber, temperatureLevel, temperatureLevels, temperatureProfile, temperatureStops, temperatureAverage, performanceContext, storageDetails, metricTopology, cpuClockSpecification, placeMetricCard } from "./metric-model.mjs";

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

export function createMetricUI({ openPopup, closePopup, onError, isVisible, onFanFrame, dataSource }) {
  const live = dataSource?.mode === "live";
  const provenance = () => live ? dataSource.stale ? "STALE / UNAVAILABLE" : "LIVE" : "DEMO";
  for (const [part, color] of Object.entries(memoryColors)) document.documentElement.style.setProperty(`--memory-${part}`, color);
  const traceColor = (id, index, multiple) => id === "memory-free" ? memoryColors.freeTrace
    : memoryColors[id.replace(/^memory-/, "")] ?? (multiple ? colors[index % colors.length] : metricGroups[metrics.get(id).group].color);
  let settings = { groups: Object.fromEntries(Object.keys(metricGroups).map(id => [id, true])), hidden: [], positions: {}, profile: "mixed", scaleMode: "auto", windows: { ...defaultHistoryWindows } };
  try {
    const saved = localStorage.getItem(preferenceKey);
    if (saved) {
      const value = JSON.parse(saved);
      if (![1, 2].includes(value.version) || !Object.hasOwn(demoProfiles, value.profile) ||
          value.scaleMode !== undefined && !["auto", "fixed"].includes(value.scaleMode) ||
          (value.version === 1 ? !historyWindows.includes(value.window) : !value.windows || Object.keys(metricGroups).some(id => !historyWindows.includes(value.windows[id]))) ||
          !value.groups || Object.keys(metricGroups).some(id => typeof value.groups[id] !== "boolean") ||
          !Array.isArray(value.hidden) || value.hidden.some(id => !metricCards.some(card => card.id === id)) ||
          !value.positions || Object.entries(value.positions).some(([id, point]) =>
            !metricCards.some(card => card.id === id) || !Array.isArray(point) || point.length !== 2 ||
            point.some(number => !Number.isFinite(number) || Math.abs(number) > 100000))) {
        throw new Error("Unrecognized metric layout");
      }
      settings = { ...value, scaleMode: value.scaleMode ?? "auto", windows: value.version === 1 ? { ...defaultHistoryWindows, cpu: value.window, gpu: value.window, network: value.window } : value.windows };
      delete settings.window;
    }
  } catch (error) {
    onError(`Viewing preferences could not be loaded: ${error.message}. Default layout is in use; saved data was not changed.`);
  }
  const compactLayout = matchMedia("(max-width: 1000px), (max-width: 1800px) and (min-aspect-ratio: 1/1)");
  let second = 86400, activePanel = "layers", disk = "array", nic = "bond0", cpuView = "cores", sensor = "all";
  let charts = [];
  let chartSequence = 0, helpSequence = 0, componentKey = "";
  const cards = new Map(), badges = new Map(), lines = new Map();
  const frame = () => ({ second, profile: settings.profile, provenance: live ? "live" : "synthetic" });
  const hddSensors = () => demoDisks.filter(disk => disk.kind === "Physical HDD").map(disk => `temp-${disk.id}`);
  const reading = id => live ? dataSource.value(id) : demoValue(id, second, settings.profile);
  const value = id => id === "temp-hdd-average" ? temperatureAverage(hddSensors().map(reading)).value : reading(id);
  const series = (id, seconds) => {
    if (id !== "temp-hdd-average") return live ? dataSource.series(id, seconds) : demoSeries(id, second, seconds, settings.profile);
    const sources = hddSensors().map(id => live ? dataSource.series(id, seconds) : demoSeries(id, second, seconds, settings.profile));
    return Array.from({ length: Math.max(2, ...sources.map(values => values.length)) }, (_, index) => temperatureAverage(sources.map(values => values[index])).value);
  };
  const capacity = id => live ? !dataSource.stale && Number.isFinite(dataSource.snapshot?.capacities?.[id]) ? dataSource.snapshot.capacities[id] : null : metrics.get(id).maximum;
  const save = () => {
    try { localStorage.setItem(preferenceKey, JSON.stringify({ ...settings, version: 2 })); }
    catch (error) { onError(`Viewing preferences are tab-only: ${error.message}.`); }
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
  const historyGroup = () => activePanel === "sensors" ? sensor === "fans" || sensor.startsWith("fan-") ? "fans" : "temperatures" : activePanel === "layers" ? "cpu" : activePanel;
  function openPanel(id, context = {}) {
    if (context.disk) disk = context.disk;
    if (id === "sensors") sensor = context.sensor ?? "all";
    activePanel = id;
    renderPanel();
    openPopup($("metrics-dialog"));
    updateCharts();
  }
  function help(text, label) {
    const wrapper = el("span", { class: "metric-help" }), id = `metric-help-${++helpSequence}`;
    wrapper.append(button("?", () => {}, { class: "metric-help-button", "aria-label": label, "aria-describedby": id }),
      el("span", { id, role: "tooltip", class: "metric-help-tip" }, text));
    return wrapper;
  }
  function temperatureLegend(id) {
    const profile = temperatureProfile(id), details = el("details", { class: "metric-thresholds", "data-threshold-profile": profile.label });
    details.append(el("summary", {}, `${profile.label} · illustrative bands (°C)`));
    const legend = el("div", { class: "metric-temperature-legend" });
    temperatureLevels.forEach((level, index) => {
      const range = index === 0 ? `<${profile.boundaries[0]}` : index === 5 ? `≥${profile.boundaries[4]}` : `${profile.boundaries[index - 1]}–<${profile.boundaries[index]}`;
      const item = el("span", {}, `${level.icon} ${level.label} ${range}`);
      item.style.color = level.color; legend.append(item);
    });
    details.append(legend, el("p", { class: "muted compact" }, "UI guidance by sensor kind, not verified device-specific vendor limits or a safety alarm."));
    return details;
  }
  function chart(ids, title, compact = false, windowGroup = null) {
    const scale = sharedMetricScale(ids);
    const box = el("article", { class: `performance-chart${compact ? " mini-chart" : ""}` });
    box.style.setProperty("--metric-series-count", ids.length);
    const header = el("div", { class: "metric-chart-heading" });
    header.append(el("div", { class: "metric-chart-labels" }, title), el("div", { class: "metric-chart-values" }));
    if (ids.length > 1) {
      const labels = title.split(" / ");
      header.firstChild.replaceChildren(...ids.flatMap((id, index) => {
        const label = el("span", { class: "metric-series-label" }, labels.length === ids.length ? labels[index] : metrics.get(id).label);
        label.style.color = traceColor(id, index, true);
        return index ? [el("span", { class: "metric-chart-separator", "aria-hidden": "true" }, " / "), label] : [label];
      }));
    }
    const plot = svg("svg", { viewBox: "0 0 300 80", preserveAspectRatio: "none", role: "img", "aria-label": `${title} · synthetic history` });
    for (const y of [0, 20, 40, 60, 80]) plot.append(svg("path", { d: `M0 ${y}H300`, class: "metric-gridline" }));
    for (const x of [75, 150, 225]) plot.append(svg("path", { d: `M${x} 0V80`, class: "metric-gridline" }));
    const area = svg("path", { fill: traceColor(ids[0], 0, ids.length > 1), opacity: ".09", stroke: "none" });
    plot.append(area);
    const defs = svg("defs"), gradients = [];
    plot.append(defs);
    const paths = ids.map((id, index) => {
      const path = svg("path", { class: "metric-trace", fill: "none", stroke: traceColor(id, index, ids.length > 1) });
      if (metrics.get(id).group === "temperatures") {
        const gradient = svg("linearGradient", { id: `temperature-trace-${++chartSequence}`, gradientUnits: "userSpaceOnUse", x1: 0, x2: 0, y1: 0, y2: 80 });
        defs.append(gradient); gradients[index] = gradient;
        path.setAttribute("stroke", `url(#${gradient.id})`);
        if (index) path.setAttribute("stroke-dasharray", "5 3");
      }
      plot.append(path); return path;
    });
    const cursor = svg("path", { class: "metric-cursor", visibility: "hidden" });
    const tooltip = el("div", { class: "metric-tooltip", hidden: "" });
    plot.append(cursor);
    const footer = el("div", { class: "metric-chart-footer" });
    const plotArea = el("div", { class: "metric-plot" }), axis = el("div", { class: "metric-y-axis", "aria-hidden": "true" });
    for (const number of [scale.maximum, (scale.minimum + scale.maximum) / 2, scale.minimum]) axis.append(el("span", {}, chartNumber(number, scale)));
    plotArea.append(axis, plot);
    box.append(header, plotArea, footer, tooltip);
    if (!compact) {
      const profiles = new Set();
      for (const id of ids) if (metrics.get(id).group === "temperatures" && !profiles.has(temperatureProfile(id).label)) {
        profiles.add(temperatureProfile(id).label); box.append(temperatureLegend(id));
      }
      if (ids.some(id => metrics.get(id).group === "fans")) box.append(el("p", { class: "metric-fan-note" }, ids.includes("fan-gpu")
        ? "NVIDIA intended speed (%) · RPM unavailable"
        : ids.every(id => id.startsWith("fan-rear")) ? "Assumed constant 2000 RPM, not measured tachometer feedback."
          : `${live ? "Measured" : "Synthetic"} tachometer RPM`));
      if (ids.includes("temp-hdd-average")) box.append(el("p", { class: "metric-average-note", "data-temperature-coverage": "" }));
    }
    const record = { box, header, plot, area, paths, gradients, footer, ids, compact, windowGroup, scale, seconds: 120, values: [] };
    plot.addEventListener("pointermove", event => {
      const bounds = plot.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
      const index = Math.round(ratio * ((record.values[0]?.length ?? 1) - 1));
      cursor.setAttribute("d", `M${ratio * 300} 0V80`);
      cursor.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      tooltip.textContent = `${provenance()} · −${Math.round(record.seconds * (1 - ratio))}s · ${record.ids.map((id, i) => `${metrics.get(id).label}: ${metricNumber(record.values[i]?.[index], metrics.get(id).unit)}`).join(" / ")}`;
    });
    plot.addEventListener("pointerleave", () => { tooltip.hidden = true; cursor.setAttribute("visibility", "hidden"); });
    charts.push(record);
    return box;
  }
  function composition() {
    const container = el("div", { class: "metric-composition" });
    const bar = el("div", { class: "metric-memory-bar", role: "img", "aria-label": "Synthetic memory composition" });
    for (const key of ["apps", "cache", "kernel", "free"]) bar.append(el("span", { "data-memory-part": key }));
    const label = el("div", { class: "metric-composition-label" });
    label.append(el("span", { "data-memory-amount": "" }), el("span", { "data-memory-percent": "" }));
    container.append(bar, label);
    return container;
  }
  function updateCharts() {
    charts = charts.filter(record => record.box.isConnected);
    if (live) for (const definition of metricCards) {
      const card = cards.get(definition.id);
      if (!card) continue;
      const title = card.querySelector(".metric-card-title");
      title.textContent = definition.label;
      title.title = definition.label;
      const record = charts.find(item => item.box.parentElement === card);
      if (record && definition.series.length === record.ids.length) record.ids = definition.series;
    }
    for (const record of charts) {
      const signalGroup = metrics.get(record.ids[0]).group;
      if (record.box.closest("#metric-panel") && ["temperatures", "fans"].includes(signalGroup)) record.box.hidden = activePanel === "sensors" && !settings.groups[signalGroup];
      if (record.box.closest("[hidden]") || (record.box.closest("dialog") && !record.box.closest("dialog").open)) continue;
      record.seconds = settings.windows[record.windowGroup ?? (record.compact ? signalGroup : historyGroup())];
      record.values = record.ids.map(id => series(id, record.seconds));
      record.scale = windowMetricScale(record.ids, record.values, record.ids.map(value), settings.scaleMode);
      record.box.dataset.axisMode = record.scale.adaptive ? "auto" : "fixed";
      record.box.dataset.axisMinimum = record.scale.minimum;
      record.box.dataset.axisMaximum = record.scale.maximum;
      record.box.querySelector(".metric-y-axis").replaceChildren(...[record.scale.maximum, (record.scale.minimum + record.scale.maximum) / 2, record.scale.minimum].map(number => el("span", {}, chartNumber(number, record.scale))));
      record.ids.forEach((id, i) => {
        record.paths[i].setAttribute("d", metricPath(record.values[i], record.scale.minimum, record.scale.maximum));
        if (record.gradients[i]) record.gradients[i].replaceChildren(...temperatureStops(id, record.scale.minimum, record.scale.maximum).map(stop => svg("stop", { offset: stop.offset, "stop-color": stop.color })));
      });
      record.area.setAttribute("d", record.values[0].every(Number.isFinite) ? `${record.paths[0].getAttribute("d")}L300,80L0,80Z` : "");
      record.header.lastChild.replaceChildren(...record.ids.map((id, index) => {
        const node = el("span", {}, metricNumber(value(id), metrics.get(id).unit));
        node.style.color = traceColor(id, index, record.ids.length > 1);
        if (signalGroup === "temperatures") decorateTemperature(node, id, value(id), node.textContent);
        return node;
      }));
      const first = metrics.get(record.ids[0]);
      const samples = record.values[0].filter(Number.isFinite);
      const source = record.ids.every(id => id.startsWith("fan-rear")) ? "ASSUMED" : provenance();
      const sourceLabel = source === "LIVE" ? "" : `${source} · `;
      record.footer.textContent = record.compact
        ? `${sourceLabel}${historyLabel(record.seconds)} · ${record.scale.adaptive ? "AUTO" : "FIXED"}${record.ids.length > 1 ? " shared" : ""} ${chartNumber(record.scale.maximum, record.scale)}`
        : `${sourceLabel}${historyLabel(record.seconds)} ago → now · Peak ${metricNumber(Math.max(...samples), first.unit)} · ${record.scale.adaptive ? "Auto" : "Fixed"} axis ${chartNumber(record.scale.minimum, record.scale)}–${chartNumber(record.scale.maximum, record.scale)}`;
      if (record.box.querySelector("[data-temperature-coverage]")) {
        const coverage = temperatureAverage(hddSensors().map(reading));
        record.box.querySelector("[data-temperature-coverage]").textContent = `Average · ${coverage.count}/${coverage.total} disks reporting`;
      }
      record.footer.title = record.footer.textContent;
      record.plot.setAttribute("aria-label", `${record.header.firstChild.textContent}. ${live ? "Collected server history" : "Synthetic, not live"}. ${record.header.lastChild.textContent}. ${record.footer.textContent}`);
    }
    for (const node of document.querySelectorAll("[data-metric-value]")) {
      const id = node.dataset.metricValue;
      node.textContent = metricNumber(value(id), metrics.get(id).unit);
    }
    for (const node of document.querySelectorAll("[data-temperature]")) {
      node.hidden = !settings.groups.temperatures && (!node.closest("#metric-panel") || activePanel === "sensors") && !node.closest("#component-performance");
      decorateTemperature(node, node.dataset.temperature, value(node.dataset.temperature), metricNumber(value(node.dataset.temperature), "°C"));
    }
    for (const node of document.querySelectorAll("[data-clock-summary]")) node.textContent = `${Number.isFinite(value("cpu-clock")) ? value("cpu-clock").toFixed(2) : "Unavailable"} / ${cpuClockSpecification.boost} GHz boost`;
    const memory = live ? Object.fromEntries(["apps", "cache", "kernel", "free", "used"].map(id => [id, value(`memory-${id}`)])) : demoMemory(second, settings.profile);
    const totalMemory = capacity("memory-used");
    for (const node of document.querySelectorAll(".metric-composition")) {
      for (const part of node.querySelectorAll("[data-memory-part]")) {
        const amount = memory[part.dataset.memoryPart];
        part.style.width = `${Number.isFinite(amount) && totalMemory > 0 ? amount / totalMemory * 100 : 0}%`;
        part.title = `${part.dataset.memoryPart}: ${metricNumber(amount, "GiB")}`;
      }
      node.querySelector(".metric-memory-bar").setAttribute("aria-label", `${provenance()} memory: ${Object.entries(memory).filter(([id]) => id !== "used").map(([id, amount]) => `${id} ${metricNumber(amount, "GiB")}`).join(", ")}`);
      node.querySelector("[data-memory-amount]").textContent = `${Number.isFinite(memory.used) ? memory.used.toFixed(1) : "Unavailable"} / ${Number.isFinite(totalMemory) ? totalMemory.toFixed(1) : "Unavailable"} GiB in use`;
      node.querySelector("[data-memory-percent]").textContent = Number.isFinite(memory.used) && totalMemory > 0 ? `${(memory.used / totalMemory * 100).toFixed(1)}%` : "Unavailable";
    }
    for (const node of document.querySelectorAll("[data-fullness]")) {
      const id = node.dataset.fullness, definition = metrics.get(id), used = value(id), total = capacity(id);
      const percent = Number.isFinite(used) && Number.isFinite(total) ? total > 0 ? used / total * 100 : used === 0 ? 0 : null : null;
      node.querySelector(".metric-capacity-bar span").style.width = `${percent ?? 0}%`;
      node.querySelector("[data-capacity-value]").textContent = percent === null ? "Unavailable" : `${percent.toFixed(1)}%`;
      node.querySelector("[data-capacity-used]").textContent = `${metricNumber(used, definition.unit)} / ${metricNumber(total, definition.unit)}`;
      const free = live && Object.hasOwn(dataSource.snapshot?.available ?? {}, id) ? dataSource.stale ? null : dataSource.snapshot.available[id] : Number.isFinite(used) && Number.isFinite(total) ? total - used : null;
      node.querySelector("[data-capacity-free]").textContent = `${metricNumber(free, definition.unit)} ${id === "cache-used" ? "unfilled" : "free"}`;
    }
    updateBadges();
    onFanFrame?.({ hubRpm: value("fan-hub"), rearRpm: 2000, provenance: live ? "live" : "synthetic" });
    $("metric-clock").textContent = live ? dataSource.snapshot ? `Updated ${new Date(dataSource.snapshot.capturedAt).toLocaleTimeString()}` : "Waiting for collector" : `${Math.floor(second / 60)}:${String(second % 60).padStart(2, "0")} simulated`;
    if (live) {
      const status = $("live-status");
      const issues = dataSource.issues;
      status.hidden = !issues.length && !dataSource.stale;
      $("live-summary").textContent = `${dataSource.stale ? "Telemetry stale or unavailable" : "Telemetry notices"}${issues.length ? ` · ${issues.length}` : ""}`;
      $("live-issues").textContent = issues.join("; ");
      for (const label of document.querySelectorAll(".metric-provenance")) label.textContent = provenance();
      const records = charts.filter(record => !record.box.closest("[hidden]") && (!record.box.closest("dialog") || record.box.closest("dialog").open));
      void dataSource.requestHistory(records.map(record => ({ seconds: record.seconds, ids: record.ids.flatMap(id => id === "temp-hdd-average" ? hddSensors() : [id]) })));
    }
    scheduleLayout();
  }
  function updateBadges() {
    for (const [id, node] of badges) {
      const badge = metricBadges.find(b => b.id === id);
      const metricId = badge.metricId ?? id;
      const source = metricId.startsWith("fan-rear") ? "ASSUMED" : provenance();
      const readings = badge.ids?.map(value).filter(Number.isFinite);
      let readout = badge.ids
        ? readings.length ? `${Math.min(...readings).toFixed(0)}–${Math.max(...readings).toFixed(0)} °C` : "Unavailable"
        : metricNumber(value(metricId), metrics.get(metricId).unit);
      if (metricId.startsWith("fan-rear")) readout = "2,000 RPM";
      node.textContent = `${badge.label} ${readout}${source === "LIVE" ? "" : ` · ${source}`}`;
      node.dataset.source = source.toLowerCase();
      if (badge.previewBank === "hub") node.title = "Shared FAN3 hub speed";
      if (badge.previewBank === "rear") node.title = "Assumed 2000 RPM · no tachometer";
      if (id === "fan-gpu") node.title = `${live ? "Collected NVIDIA" : "Synthetic"} fan-speed percentage, not RPM or three measured physical fans. NVIDIA percentages describe intended speed, not proof of rotation.`;
      if (badge.group === "temperatures") {
        const ids = badge.ids ?? [badge.id];
        const hottest = ids.reduce((a, b) => temperatureLevels.indexOf(temperatureLevel(a, value(a))) >= temperatureLevels.indexOf(temperatureLevel(b, value(b))) ? a : b, ids[0] ?? badge.id);
        decorateTemperature(node, hottest, value(hottest), node.textContent);
      }
    }
  }
  function fullness(id, compact = false) {
    const node = el("div", { class: "metric-fullness", "data-fullness": id, "data-compact": String(compact) });
    const heading = el("div", { class: "metric-capacity-heading" });
    heading.append(el("span", {}, id === "gpu-dedicated" ? "VRAM allocated" : metrics.get(id).label), el("strong", { "data-capacity-value": "" }));
    const bar = el("div", { class: "metric-capacity-bar" }); bar.append(el("span"));
    const detail = el("p");
    detail.append(el("span", { "data-capacity-used": "" }), el("span", { "data-capacity-free": "" }));
    node.append(heading, bar, detail);
    return node;
  }
  function decorateTemperature(node, id, reading, text) {
    const level = temperatureLevel(id, reading);
    node.style.color = level.color;
    node.dataset.temperatureLevel = level.label.toLowerCase();
    node.textContent = `${level.icon} ${text}`;
    node.title = `${level.label}. Illustrative component-specific UI band, not a verified vendor alarm threshold. ${demoSensors.find(item => item.id === id)?.location ?? "Physical probe location unverified."}`;
    node.setAttribute("aria-label", `${text}. ${level.label}. ${provenance()} temperature; illustrative band.`);
  }
  function temperatureButton(id) {
    return button("", () => openPanel("sensors", { sensor: id }), { class: "metric-temperature-link", "data-temperature": id });
  }
  for (const definition of metricCards) {
    const card = el("article", { class: `metric-card${definition.mobileOnly ? " mobile-metric-card" : ""}`, "data-card": definition.id });
    card.style.setProperty("--metric-color", metricGroups[definition.group].color);
    const heading = el("header", { class: "metric-card-heading" });
    const handle = button("⠿", () => {}, { class: "metric-drag", "aria-label": `Move ${definition.label}; arrow keys also move it`, title: "Drag to position; arrow keys move, Shift moves faster" });
    heading.append(handle, button(definition.label, () => {
      if (definition.device) disk = definition.device;
      openPanel(definition.group === "temperatures" || definition.group === "fans" ? "sensors" : definition.group, definition.group === "fans" ? { sensor: "fans" } : {});
    }, { class: "metric-card-title", title: definition.label }),
      button("×", () => { settings.hidden.push(definition.id); save(); updateVisibility(); $("metrics-button").focus({ preventScroll: true }); }, { class: "metric-card-close", "aria-label": `Hide ${definition.label}` }));
    const titles = { gpu: "Engine activity / encode", network: "Receive / send", storage: "Read / write", nvme: "Read / write", fans: "Hub tach speed", temperatures: "Temperatures", memory: "In use" };
    card.append(heading);
    if (definition.fullness) card.append(fullness(definition.fullness, true));
    card.append(chart(definition.series, definition.group === "storage" ? "Read / write" : titles[definition.id] ?? "Utilization", true));
    if (definition.id === "gpu") {
      card.append(chart(["gpu-dedicated"], "VRAM allocated · not engine load", true));
    }
    if (definition.id === "memory") card.append(composition(), fullness("swap", true));
    else if (definition.footer.length) {
      const footer = el("div", { class: "metric-card-extra" });
      for (const id of definition.footer) {
        const field = el("div", { class: "metric-extra-field" });
        if (id === "cpu-clock") field.append(el("span", {}, `CPU clock · ${cpuClockSpecification.base} GHz base`), el("strong", { "data-clock-summary": "" }));
        else field.append(el("span", {}, metrics.get(id).label), el("strong", { "data-metric-value": id }));
        footer.append(field);
      }
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
    const card = cards.get(definition.id), bounds = $("metric-layer").getBoundingClientRect();
    const low = scenePoint(bounds.left + 8, bounds.top + 8), high = scenePoint(bounds.right - card.offsetWidth - 8, bounds.bottom - card.offsetHeight - 8);
    settings.positions[definition.id] = [Math.max(low.x, Math.min(high.x, x)), Math.max(low.y, Math.min(high.y, y))];
    layout();
  }
  for (const definition of metricBadges) {
    const selection = definition.ids ? definition.anchor === "nvme-group" ? "nvme" : "hdds" : definition.metricId ?? definition.id;
    const node = button("", () => openPanel("sensors", { sensor: selection }), { class: "metric-badge", "data-badge": definition.id, "data-align": definition.align ?? "start", title: "Synthetic channel; * means physical binding is unverified." });
    node.style.setProperty("--metric-color", metricGroups[definition.group].color);
    $("metric-layer").append(node); badges.set(definition.id, node);
  }
  function layout() {
    const bounds = $("metric-layer").getBoundingClientRect(), matrix = $("board").getScreenCTM();
    if (!matrix || $("metric-layer").hidden || compactLayout.matches) return;
    $("metric-leaders").setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
    const point = (x, y) => {
      const p = new DOMPoint(x, y).matrixTransform(matrix);
      return { x: p.x - bounds.left, y: p.y - bounds.top };
    };
    const occupied = [];
    for (const definition of metricBadges) {
      const p = point(definition.x, definition.y), node = badges.get(definition.id);
      node.style.left = `${p.x}px`; node.style.top = `${p.y}px`;
      if (!node.hidden) {
        const rect = node.getBoundingClientRect();
        occupied.push({ x: rect.left - bounds.left - 4, y: rect.top - bounds.top - 4, width: rect.width + 8, height: rect.height + 8 });
      }
    }
    for (const node of document.querySelectorAll('.hardware-part[aria-disabled="false"]:not([data-id="chassis"]):not([data-id="motherboard"]), .connector:not(.out-of-focus)')) {
      const rect = node.getBoundingClientRect();
      occupied.push({ x: rect.left - bounds.left, y: rect.top - bounds.top, width: rect.width, height: rect.height });
    }
    const priority = ["gpu", "cpu", "nvme-root", "nvme", "memory", "network", "storage", "temperatures", "fans"];
    const ordered = [...metricCards].sort((a, b) => Number(Boolean(settings.positions[b.id])) - Number(Boolean(settings.positions[a.id])) || priority.indexOf(a.id) - priority.indexOf(b.id));
    for (const definition of ordered) {
      const node = cards.get(definition.id), position = settings.positions[definition.id] ?? [definition.x, definition.y];
      const line = lines.get(definition.id);
      line.style.display = node.hidden || definition.mobileOnly ? "none" : "";
      if (node.hidden || definition.mobileOnly) continue;
      const clampPoint = p => ({ x: Math.max(8, Math.min(bounds.width - node.offsetWidth - 8, p.x)), y: Math.max(8, Math.min(bounds.height - node.offsetHeight - 8, p.y)) });
      let p = clampPoint(point(...position));
      if (!settings.positions[definition.id]) p = placeMetricCard({ ...p, width: node.offsetWidth, height: node.offsetHeight }, bounds, occupied);
      node.style.left = `${p.x}px`; node.style.top = `${p.y}px`;
      occupied.push({ ...p, width: node.offsetWidth, height: node.offsetHeight });
      const anchor = anchorBounds(definition.anchor);
      if (anchor) {
        const a = point(anchor.x + anchor.width / 2, anchor.y + anchor.height / 2);
        const edge = p.x + (a.x > p.x + node.offsetWidth / 2 ? node.offsetWidth : 0), mid = p.y + Math.min(40, node.offsetHeight / 2);
        line.setAttribute("d", `M${a.x},${a.y}L${edge + (a.x > edge ? 12 : -12)},${mid}L${edge},${mid}`);
      }
      if (!anchor) line.style.display = "none";
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
    for (const node of $("metric-group-controls").children) {
      node.setAttribute("aria-pressed", String(settings.groups[node.dataset.group]));
      node.title = `${settings.groups[node.dataset.group] ? "Hide" : "Show"} all ${metricGroups[node.dataset.group].label.toLowerCase()}`;
    }
    for (const node of document.querySelectorAll("[data-group-check]")) node.checked = settings.groups[node.dataset.groupCheck];
    for (const node of document.querySelectorAll("[data-card-check]")) node.checked = !settings.hidden.includes(node.dataset.cardCheck);
    for (const node of document.querySelectorAll("[data-sensor-toggle]")) {
      const visible = settings.groups[node.dataset.sensorToggle];
      node.setAttribute("aria-pressed", String(visible));
      node.textContent = `${node.dataset.sensorToggle === "temperatures" ? "Temperatures" : "Fan speeds"}: ${visible ? "shown" : "hidden"}`;
    }
    $("metric-window").value = String(settings.windows[historyGroup()]);
    $("metric-window").disabled = activePanel === "layers";
  }
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
  $("metric-window").replaceChildren(...historyWindows.map(seconds => el("option", { value: seconds }, historyLabel(seconds))));
  $("metric-window").addEventListener("change", () => { settings.windows[historyGroup()] = Number($("metric-window").value); save(); updateCharts(); });
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
  function sensorToggle(id) {
    return button("", () => group(id, !settings.groups[id]), { "data-sensor-toggle": id, "aria-pressed": String(settings.groups[id]) });
  }
  function renderComponent(part, binding) {
    const container = $("component-performance"), context = performanceContext(part, binding);
    const windowGroup = context?.panel === "sensors" ? context.sensor.startsWith("fan-") ? "fans" : "temperatures" : context?.panel;
    const key = JSON.stringify([part, binding, context, hddSensors()]);
    if (componentKey === key) {
      const control = container.querySelector("select");
      if (control) control.value = String(settings.windows[windowGroup]);
      return;
    }
    componentKey = key;
    container.replaceChildren();
    container.hidden = !context;
    if (!context) return;
    if (context.unbound) {
      container.append(el("p", { class: "muted compact" }, "No current logical-device binding for this physical slot. Open Storage for the overview; no device identity is guessed."));
      return;
    }
    const heading = el("div", { class: "component-performance-heading metric-section-heading" });
    const window = el("select", { "aria-label": "Component history" });
    window.append(...historyWindows.map(seconds => el("option", { value: seconds }, historyLabel(seconds))));
    window.value = settings.windows[windowGroup];
    window.addEventListener("change", () => { settings.windows[windowGroup] = Number(window.value); save(); updateCharts(); });
    heading.append(el("h4", {}, `${live ? "Live" : "Synthetic"} performance`), window);
    container.append(heading);
    for (const ids of context.series) {
      if (ids.some(id => !metrics.has(id))) continue;
      const title = ids.map(id => metrics.get(id).label).join(" / ");
      container.append(chart(ids, title, false, windowGroup));
    }
  }
  function diskComparison() {
    const wrapper = el("div", { class: "metric-disk-table" }), table = el("table");
    const heading = el("tr");
    for (const label of ["Drive / RAID role", "Temperature", "Read", "Write", "Busy"]) heading.append(el("th", { scope: "col" }, label));
    const head = el("thead"); head.append(heading); table.append(head);
    const body = el("tbody");
    for (const disk of demoDisks.filter(node => node.kind === "Physical HDD")) {
      const row = el("tr"), name = el("td"), info = storageDetails(disk.id);
      name.append(button(disk.label, () => { diskSelection(disk.id); }), el("small", {}, info.role));
      const temp = el("td"); temp.append(temperatureButton(`temp-${disk.id}`)); row.append(name, temp);
      for (const field of ["read", "write", "active"]) {
        const cell = el("td"); cell.append(el("span", { "data-metric-value": `disk-${disk.id}-${field}` })); row.append(cell);
      }
      body.append(row);
    }
    table.append(body); wrapper.append(table);
    const foot = el("tfoot"), row = el("tr"), mean = el("td");
    row.append(el("th", { scope: "row" }, "Mean of reporting HDD sensors"));
    mean.append(temperatureButton("temp-hdd-average")); row.append(mean);
    const note = el("td", { colspan: "3" }, "Missing excluded; inspect individual hot spots");
    row.append(note); foot.append(row); table.append(foot);
    return wrapper;
  }
  function diskSelection(id) { disk = id; renderPanel(); $("metric-panel").querySelector("select")?.focus({ preventScroll: true }); }
  function storageContext() {
    const section = el("section", { class: "metric-storage-context" });
    if (disk === "array") {
      const raid = metricTopology.snapshot.raids.find(item => item.id === "md0");
      section.append(el("strong", {}, raid ? `${raid.raidDisks} RAID6 members · ${raid.members.filter(item => item.state.includes("spare") && item.slot === null).length} hot spare · /dev/md0` : "RAID inventory unavailable"),
        el("p", {}, `${live ? "Roles follow the latest collected inventory." : "Roles come from the dated snapshot, not this simulated workload."} Per-disk counters must not be added to md0/LVM counters as if they were separate traffic.`));
    } else {
      const info = storageDetails(disk);
      section.append(el("strong", {}, `${info.node.label} · ${(info.node.sizeBytes / 1e12).toFixed(2)} TB raw capacity`),
        el("p", {}, `${info.role}. ${info.node.summary ?? ""}`));
      const layers = el("div", { class: "metric-storage-layers" });
      for (const node of info.layers.filter(node => ["LVM volume group", "LVM / device-mapper", "Mounted XFS filesystem", "mdadm RAID6"].includes(node.kind))) {
        const item = el("div"); item.append(el("strong", {}, node.aliases?.find(alias => alias.startsWith("/dev/vg_") || alias.startsWith("/dev/homeserver-vg/")) ?? node.label), el("span", {}, node.summary ?? node.kind)); layers.append(item);
      }
      section.append(layers);
    }
    return section;
  }
  function renderPanel() {
    const body = $("metric-panel");
    body.replaceChildren();
    for (const tab of $("metric-panel-nav").children) tab.setAttribute("aria-pressed", String(tab.dataset.panel === activePanel));
    body.append(el("h3", {}, panelLabels[activePanel]));
    const grid = el("div", { class: "metric-detail-grid" });
    const add = (ids, title) => grid.append(chart(ids, title));
    if (activePanel === "layers") {
      body.append(el("p", { class: "muted compact" }, "Drag chart grips or use arrow keys to arrange the map. Layout and visibility are saved in this browser."));
      const checks = el("div", { class: "metric-layer-checks" });
      for (const [id, definition] of Object.entries(metricGroups)) {
        const label = el("label"), input = el("input", { type: "checkbox", "data-group-check": id });
        input.checked = settings.groups[id];
        input.addEventListener("change", () => group(id, input.checked));
        label.append(input, document.createTextNode(definition.label)); checks.append(label);
      }
      body.append(checks);
      body.append(select([["auto", "Adaptive activity axes · percentages/capacities stay fixed"], ["fixed", "Fixed reference axes"]], settings.scaleMode, next => {
        settings.scaleMode = next; save();
      }, "Graph y-axis scaling"));
      body.append(el("p", { class: "muted compact" }, "Adaptive axes fit activity to the selected window. Percentages and capacities keep fixed scales."));
      const actions = el("div", { class: "toolbar" });
      actions.append(sensorToggle("temperatures"), sensorToggle("fans"), button("Show all layers", () => all(true)), button("Hide all layers", () => all(false)));
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
    } else if (activePanel === "cpu") {
      add(["cpu"], "Overall · 16 cores / 32 logical CPUs");
      add(["cpu-clock"], "CPU clock");
      add(["cpu-power"], "Package power");
      for (const id of ["temp-cpu", "fan-cpu1", "fan-cpu2"]) add([id], metrics.get(id).label);
      body.append(select([["cores", "16 cores"], ["threads", "32 logical CPUs"]], cpuView, next => { cpuView = next; }, "CPU graph grouping"));
      const cores = el("div", { class: "metric-core-grid" });
      for (let i = 0; i < (cpuView === "cores" ? 16 : 32); i += 1) cores.append(chart([`${cpuView === "cores" ? "core" : "thread"}-${i}`], `${cpuView === "cores" ? "Core" : "Logical CPU"} ${i}`, true));
      body.append(grid, cores);
    } else if (activePanel === "memory") {
      const legend = el("div", { class: "metric-memory-legend" });
      for (const [id, label] of [["apps", "Applications"], ["cache", "File cache / reclaimable"], ["kernel", "Kernel"], ["free", "Free"]]) {
        const item = el("span", { "data-memory-label": id }, `${live && id === "apps" ? "Other / anonymous (residual)" : label} `);
        item.append(el("strong", { "data-metric-value": `memory-${id}` }));
        legend.append(item);
      }
      body.append(composition(), legend);
      for (const id of ["memory-apps", "memory-cache", "memory-kernel", "memory-free", "swap"]) add([id], metrics.get(id).label);
      body.append(grid);
    } else if (activePanel === "storage") {
      const capacities = el("div", { class: "metric-capacity-grid" });
      capacities.append(fullness("data-used"), fullness("root-used"));
      const cacheDisk = live ? dataSource.snapshot?.inventory?.disks?.find(item => item.role === "cache")?.id : "nvme1n1";
      if (disk === cacheDisk) capacities.append(fullness("cache-used"));
      body.append(capacities, select([["array", "All HDDs / md0"], ...demoDisks.map(node => [node.id, `${node.label} · ${storageDetails(node.id).role}`])], disk, next => { disk = next; }, "Storage device"), storageContext());
      add([`disk-${disk}-read`, `disk-${disk}-write`], "Read / write transfer rate");
      add([`disk-${disk}-active`], "Active time · busy, not capacity");
      add([`disk-${disk}-latency`], "Response time");
      add([`disk-${disk}-queue`], "Queue depth");
      if (disk === cacheDisk) {
        add(["cache-used", "cache-dirty"], "Resident cached / dirty cached");
        const cache = dataSource?.snapshot?.inventory?.cache;
        body.append(el("p", { class: "muted compact" }, live ? cache
          ? `dm-cache ${cache.mode}, metadata ${cache.metadataMode}: ${cache.blockSizeBytes.toLocaleString()}-byte blocks. Occupancy measures warmed cache, not filesystem fullness; high occupancy is normally useful. Dirty blocks differ from the origin.`
          : "Live dm-cache counters have not been supplied by the installed collector. Cache allocation size alone cannot establish occupancy."
          : "Synthetic resident and dirty cache blocks. Cache occupancy is not filesystem fullness."));
      }
      if (disk !== "array") {
        const nvme = disk.match(/^nvme(\d+)n\d+$/);
        const ids = nvme ? [`temp-nvme${nvme[1]}`, `temp-nvme${nvme[1]}-secondary`] : [`temp-${disk}`];
        for (const id of ids) add([id], metrics.get(id).label);
      }
      if (disk === "array") body.append(el("h4", {}, `Individual HDDs · ${live ? "collected" : "synthetic"} activity / temperature`), diskComparison());
      if (disk === "array") add(["temp-hdd-average"], "HDD mean temperature");
      body.append(grid);
    } else if (activePanel === "gpu") {
      const memoryHeading = el("div", { class: "metric-section-heading" });
      memoryHeading.append(el("h4", {}, "GPU memory"), help("Programs can keep VRAM allocated while GPU engines are idle. Memory uses a capacity scale; engine activity uses 0–100%. Allocated memory is not evidence that an engine is busy.", "About VRAM allocation and engine activity"));
      body.append(memoryHeading, fullness("gpu-dedicated"));
      for (const id of ["gpu-util", "gpu-dedicated", "temp-gpu", "fan-gpu", "gpu-encode", "gpu-decode", "gpu-power"]) add([id], metrics.get(id).label);
      body.append(grid);
    } else if (activePanel === "network") {
      body.append(select(demoNics.map(id => [id, id]), nic, next => { nic = next; }, "Network interface"));
      add([`net-${nic}-rx`, `net-${nic}-tx`], "Receive / send · separate full-duplex directions");
      add(["temp-lan"], "Onboard LAN sensor · shared context, not per-port temperature");
      body.append(el("p", { class: "metric-storage-context" }, `${nic}: ${metricTopology.nodes.get(nic).bondRole ?? metricTopology.nodes.get(nic).summary}`), grid);
    } else if (activePanel === "sensors") {
      const actions = el("div", { class: "toolbar" });
      actions.append(sensorToggle("temperatures"), sensorToggle("fans"));
      const choices = [["all", "All sensors & fans"], ["nvme", "NVMe temperatures"], ["hdds", "HDD temperatures"], ["fans", "All fan speeds"], ...[...demoSensors, ...demoFans].map(item => [item.id, item.label])];
      body.append(select(choices, sensor, next => { sensor = next; }, "Sensor selection"), actions);
      const legend = el("div", { class: "metric-temperature-legend" });
      for (const level of temperatureLevels) { const item = el("span", {}, `${level.icon} ${level.label}`); item.style.color = level.color; legend.append(item); }
      body.append(legend, el("p", { class: "muted compact" }, "FAN1: PSU-side CPU fan · FAN2: GPU-side CPU fan · FAN3: shared case-fan hub"));
      const selected = [...demoSensors, ...demoFans].filter(item => sensor === "all" || sensor === item.id || sensor === "nvme" && item.id.startsWith("temp-nvme") || sensor === "hdds" && (item.id.startsWith("temp-sd") || item.id === "temp-hdd-average") || sensor === "fans" && item.id.startsWith("fan-"));
      const locations = [...new Set(selected.filter(item => item.location).map(item => item.location))];
      if (locations.length) {
        const notes = el("details", { class: "metric-sensor-locations" });
        notes.append(el("summary", {}, "Sensor locations and limits"));
        for (const location of locations) notes.append(el("p", {}, location));
        body.append(notes);
      }
      for (const definition of selected) add([definition.id], definition.label);
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
  compactLayout.addEventListener("change", updateVisibility);
  $("metrics-dialog").addEventListener("close", () => {
    updateCharts();
    if (document.activeElement === document.body || document.activeElement.closest("[hidden]")) $("metrics-button").focus({ preventScroll: true });
  });
  const timer = setInterval(() => {
    if (document.hidden) return;
    second += 1; updateCharts();
  }, 1000);
  let inventorySignature = "";
  if (live) dataSource.subscribe(data => {
    const inventory = data?.inventory?.snapshot;
    const cache = data?.inventory?.cache;
    const signature = JSON.stringify([inventory?.nodes, inventory?.raids, inventory?.bonds, data?.inventory?.disks,
      cache && [cache.device, cache.mode, cache.metadataMode, cache.blockSizeBytes, cache.needsCheck]]);
    if (signature !== inventorySignature) {
      inventorySignature = signature;
      if (disk !== "array" && !demoDisks.some(item => item.id === disk)) disk = "array";
      if (!demoNics.includes(nic)) nic = demoNics[0] ?? "bond0";
      if ($("metrics-dialog").open) renderPanel();
    }
    controls(); updateCharts();
  });
  if (live) {
    $("metrics-button").textContent = "Performance · LIVE";
    $("metric-controls").setAttribute("aria-label", "Collected server metric layers");
    $("metric-layer").setAttribute("aria-label", "Collected hardware metric overlays");
  }
  controls(); updateVisibility();
  return {
    updateVisibility, layout: scheduleLayout, openPanel, frame, renderComponent, refresh: updateCharts,
    openComponent(part, binding) {
      const context = performanceContext(part, binding);
      if (context) openPanel(context.panel, context);
    },
    panelFor(part) {
      return performanceContext(part)?.panel ?? null;
    },
    destroy() { clearInterval(timer); },
  };
}
