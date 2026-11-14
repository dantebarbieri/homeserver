import { columns, defaults, preferenceKey, selectedColumns, moveColumn, placeColumn, metricValue, sortRows, formatValue } from "./service-model.mjs";
import { createReorder } from "./reorder.mjs";

const byId = new Map(columns.map(column => [column.id, column]));
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
};

export function createServicesUI({ enabled, openPopup, onError }) {
  const dialog = document.getElementById("services-dialog");
  const head = document.getElementById("services-head");
  const body = document.getElementById("services-body");
  const status = document.getElementById("services-status");
  const settings = document.getElementById("services-columns");
  const search = document.getElementById("services-search");
  const stopped = document.getElementById("services-stopped");
  const announcer = document.getElementById("services-announce");
  const expanded = new Set();
  let visible = [...defaults], sort = "cpu", direction = -1, snapshot = null;
  let timer = null, controller = null, generation = 0, pending = false, dragging = false, stale = false;
  try {
    const raw = localStorage.getItem(preferenceKey);
    if (raw !== null) visible = selectedColumns(JSON.parse(raw));
  } catch (error) {
    onError(`Service column preferences could not be loaded: ${error.message}. Existing saved data was not overwritten.`);
  }

  function persist() {
    try { localStorage.setItem(preferenceKey, JSON.stringify(visible)); }
    catch (error) { onError(`Service columns could not be saved: ${error.message}`); }
  }

  function changeColumns(next) {
    visible = next;
    if (!visible.includes(sort)) { sort = visible[0]; direction = -1; }
    persist();
    renderColumns();
    renderHead();
    renderRows();
  }

  function announce(text) {
    announcer.textContent = "";
    setTimeout(() => { announcer.textContent = text; }, 30);
  }

  function reorder(id, next, focus) {
    const position = next.indexOf(id) + 1, label = byId.get(id).label;
    changeColumns(next);
    if (focus) settings.querySelector(`button[data-column="${id}"]`)?.focus();
    announce(`${label} moved to position ${position} of ${next.length}`);
  }

  function renderColumns() {
    settings.replaceChildren();
    for (const id of [...visible, ...columns.map(column => column.id).filter(id => !visible.includes(id))]) {
      const column = byId.get(id), line = node("div", "", "service-column-option");
      line.dataset.column = id;
      const label = node("label");
      const input = node("input");
      input.type = "checkbox";
      input.checked = visible.includes(id);
      input.disabled = input.checked && visible.length === 1;
      input.dataset.column = id;
      input.title = column.note;
      label.append(input, node("span", column.label));
      input.addEventListener("change", () => {
        changeColumns(input.checked ? [...visible, id] : visible.filter(value => value !== id));
        settings.querySelector(`input[data-column="${id}"]`)?.focus();
      });
      if (input.checked) {
        line.dataset.visible = "";
        const grip = node("button", "\u22ee\u22ee", "service-column-grip");
        grip.type = "button";
        grip.dataset.column = id;
        grip.dataset.grip = "";
        grip.setAttribute("aria-label", `Reorder ${column.label}: drag, or use the arrow keys`);
        grip.addEventListener("keydown", event => {
          const move = { ArrowUp: -1, ArrowLeft: -1, ArrowDown: 1, ArrowRight: 1 }[event.key];
          if (move === undefined && event.key !== "Home" && event.key !== "End") return;
          event.preventDefault();
          reorder(id, move === undefined ? placeColumn(visible, id, event.key === "Home" ? 0 : visible.length) : moveColumn(visible, id, move), true);
        });
        line.append(grip);
      }
      line.append(label);
      settings.append(line);
    }
  }

  function renderHead() {
    const row = node("tr");
    for (const id of ["name", ...visible]) {
      const column = byId.get(id), cell = node("th");
      cell.scope = "col";
      cell.dataset.column = id;
      cell.setAttribute("aria-sort", id === sort ? direction === -1 ? "descending" : "ascending" : "none");
      const button = node("button", `${column?.label ?? "Name"}${sort === id ? direction === -1 ? " \u2193" : " \u2191" : ""}`);
      button.type = "button";
      button.title = column ? `${column.note}\n\nDrag to reorder; on touch, press and hold first. Keyboard: use Columns.` :
        "Service names and icons come from Homepage. Other containers keep their Docker names.";
      button.addEventListener("click", () => {
        direction = sort === id ? -direction : id === "name" ? 1 : -1;
        sort = id;
        renderHead();
        renderRows();
        head.querySelector(`th[data-column="${id}"] button`)?.focus();
      });
      cell.append(button);
      row.append(cell);
    }
    head.replaceChildren(row);
  }

  function renderRows() {
    if (dragging) { stale = true; return; }
    stale = false;
    const focus = document.activeElement?.dataset.serviceToggle;
    const fragment = document.createDocumentFragment();
    const all = snapshot?.services ?? [];
    const names = new Map(all.map(service => [service.id, service.container]));
    const needle = search.value.trim().toLowerCase();
    const services = all.filter(service =>
      (stopped.checked || !["exited", "dead", "created"].includes(service.state)) &&
      [service.name, service.container, service.group, ...service.processes.map(process => process.name)]
        .some(value => value.toLowerCase().includes(needle)));
    const maxima = Object.fromEntries(visible.map(id => [id, Math.max(0, ...services.map(service => metricValue(service, id) ?? 0))]));
    const networkDescription = service => service.networkOwner === null
      ? "Host/disabled/unknown network namespace: no per-container attribution."
      : service.networkOwner !== service.id
        ? `Shared network: traffic counted once on ${names.get(service.networkOwner) ?? "namespace owner"}.`
        : all.some(other => other.id !== service.id && other.networkOwner === service.id)
          ? `Shared network with ${all.filter(other => other.id !== service.id && other.networkOwner === service.id).map(other => other.container).join(", ")}. Traffic is not separable by service.` : "";

    function appendRow(item, parent = null) {
      const row = node("tr", "", parent ? "service-process" : "service-row");
      row.dataset.serviceId = parent?.id ?? item.id;
      const name = node("th");
      name.scope = "row";
      const title = node("div", "", "service-name");
      if (!parent) {
        const toggle = node("button", expanded.has(item.id) ? "\u25be" : "\u25b8", "service-expand");
        toggle.type = "button";
        toggle.dataset.serviceToggle = item.id;
        toggle.setAttribute("aria-expanded", String(expanded.has(item.id)));
        toggle.setAttribute("aria-label", `${expanded.has(item.id) ? "Collapse" : "Expand"} ${item.name} processes`);
        toggle.addEventListener("click", () => {
          expanded.has(item.id) ? expanded.delete(item.id) : expanded.add(item.id);
          renderRows();
          body.querySelector(`[data-service-toggle="${item.id}"]`)?.focus();
        });
        title.append(toggle);
        const iconBox = node("span", "", "service-icon-box");
        const fallback = node("span", item.name.slice(0, 1).toUpperCase(), "service-icon-fallback");
        iconBox.append(fallback);
        title.append(iconBox);
        if (item.icon) {
          const image = node("img", "", "service-icon");
          image.src = item.icon;
          image.alt = "";
          image.width = image.height = 24;
          image.loading = "lazy";
          if (item.icon.includes("/@mdi/") || item.icon.includes("/simple-icons@")) image.classList.add("service-monochrome");
          image.addEventListener("load", () => { fallback.hidden = true; });
          image.addEventListener("error", () => { image.hidden = true; });
          iconBox.append(image);
        }
      }
      const label = node("span", "", "service-label");
      label.append(node("strong", item.name));
      const detail = parent ? `PID ${item.pid}` :
        `${item.container}${item.state !== "running" ? ` \u00b7 ${item.state}` : ""}`;
      label.append(node("small", detail));
      title.append(label);
      name.append(title);
      const network = parent ? "Process network attribution is unavailable without additional instrumentation." :
        networkDescription(item);
      name.title = parent ? "Process resident memory includes shared pages; it is not additive container working set." :
        [item.group, network, ...(item.issues ?? [])].filter(Boolean).join("\n");
      row.append(name);
      for (const id of visible) {
        const value = metricValue(item, id), column = byId.get(id);
        const cell = node("td", formatValue(value, column.unit), value === null ? "service-unavailable" : "");
        cell.dataset.column = id;
        cell.title = column.note + (["network", "rx", "tx"].includes(id) && network ? `\n${network}` : "");
        if (value !== null && maxima[id]) cell.style.backgroundColor = `rgba(80, 160, 195, ${Math.min(.36, .035 + value / maxima[id] * .28)})`;
        row.append(cell);
      }
      fragment.append(row);
    }

    for (const service of sortRows(services, sort, direction)) {
      appendRow(service);
      if (expanded.has(service.id)) {
        for (const process of sortRows(service.processes, sort, direction)) appendRow(process, service);
        const note = node("tr", "", "service-process-note"), cell = node("td");
        cell.colSpan = visible.length + 1;
        cell.textContent = service.processStatus === "unavailable" ? "Process enumeration unavailable." :
          `${service.processes.length} processes${service.processStatus === "partial" ? " \u00b7 partial snapshot; some processes exited or could not be read" : ""}. Process RSS and I/O need not sum to container accounting; process network rates are unavailable.`;
        cell.textContent += ` ${[networkDescription(service), ...(service.issues ?? [])].filter(Boolean).join(" ")}`;
        note.append(cell);
        fragment.append(note);
      }
    }
    if (!services.length) {
      const row = node("tr"), cell = node("td", snapshot ? "No matching containers." : "No live service data available.", "service-empty");
      cell.colSpan = visible.length + 1;
      row.append(cell);
      fragment.append(row);
    }
    body.replaceChildren(fragment);
    if (focus) body.querySelector(`[data-service-toggle="${focus}"]`)?.focus({ preventScroll: true });
    document.getElementById("services-count").textContent = snapshot ? `${services.length} of ${all.length} containers` : "";
  }

  function stop() {
    generation++;
    clearTimeout(timer);
    controller?.abort();
    headReorder.cancel();
    menuReorder.cancel();
    snapshot = null;
    status.textContent = "Waiting for live accounting";
    renderRows();
  }
  async function poll() {
    if (!dialog.open || document.hidden || pending) return;
    if (snapshot && Date.now() - Date.parse(snapshot.capturedAt) > 20000) {
      snapshot = null;
      renderRows();
    }
    const epoch = generation;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 8000);
    pending = true;
    try {
      const response = await fetch("./api/services", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const age = Date.now() - Date.parse(data.capturedAt);
      if (data.version !== 1 || data.mode !== "live" || data.status !== "ok" ||
          !Array.isArray(data.services) || !Number.isFinite(age) || age < -10000 || age > 20000) {
        throw new Error("Stale or invalid service snapshot");
      }
      if (epoch !== generation || !dialog.open) return;
      snapshot = data;
      status.textContent = `LIVE \u00b7 every ${data.intervalSeconds}s \u00b7 ${new Date(data.capturedAt).toLocaleTimeString()}`;
      status.classList.remove("error");
      const issues = [...data.issues, ...data.services.flatMap(service => service.issues.map(issue => `${service.container}: ${issue}`))];
      document.getElementById("services-issues").textContent = issues.join(" ");
      renderRows();
    } catch (error) {
      if (epoch !== generation || !dialog.open) return;
      snapshot = null;
      status.textContent = `UNAVAILABLE \u00b7 ${error.message}. Previous readings are not shown.`;
      status.classList.add("error");
      document.getElementById("services-issues").textContent = "";
      renderRows();
    } finally {
      clearTimeout(timeout);
      pending = false;
      if (dialog.open && !document.hidden) timer = setTimeout(poll, 5000);
    }
  }
  document.getElementById("services-button").addEventListener("click", () => {
    openPopup(dialog);
    if (enabled) poll();
    else status.textContent = "Services require the live read-only collector; no synthetic process data is shown.";
  });
  dialog.addEventListener("close", stop);
  document.addEventListener("visibilitychange", () => {
    stop();
    if (!document.hidden && dialog.open && enabled) poll();
  });
  search.addEventListener("input", renderRows);
  stopped.addEventListener("change", renderRows);
  document.getElementById("services-reset-columns").addEventListener("click", () => changeColumns([...defaults]));
  const scrollRegion = document.querySelector(".services-table-scroll");
  const metricCells = () => [...head.querySelectorAll("th[data-column]")].filter(cell => cell.dataset.column !== "name");
  const endDrag = changed => {
    dragging = false;
    if (!changed && stale) renderRows();
  };
  const headReorder = createReorder({
    root: head,
    axis: "x",
    scroller: scrollRegion,
    bounds: () => [head.querySelector('th[data-column="name"]').getBoundingClientRect().right, scrollRegion.getBoundingClientRect().right],
    resolve: event => {
      const cell = event.target.closest?.("th[data-column]");
      return cell && cell.dataset.column !== "name" ? { id: cell.dataset.column, element: cell } : null;
    },
    items: () => metricCells().map(cell => ({ id: cell.dataset.column, element: cell })),
    follow: id => body.querySelectorAll(`td[data-column="${id}"]`),
    onStart: () => { dragging = true; },
    onEnd: endDrag,
    onCommit: (id, index) => reorder(id, placeColumn(visible, id, index), false),
  });
  const menuReorder = createReorder({
    root: settings,
    axis: "y",
    scroller: settings.closest(".services-column-menu"),
    resolve: event => {
      const grip = event.target.closest?.("[data-grip]");
      return grip ? { id: grip.dataset.column, element: grip.closest(".service-column-option"), handle: grip, immediate: true } : null;
    },
    items: () => [...settings.querySelectorAll(".service-column-option[data-visible]")].map(row => ({ id: row.dataset.column, element: row })),
    onStart: () => { dragging = true; },
    onEnd: endDrag,
    onCommit: (id, index) => reorder(id, placeColumn(visible, id, index), true),
  });
  renderColumns();
  renderHead();
  renderRows();
}
