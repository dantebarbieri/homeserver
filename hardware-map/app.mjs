import { connectors, connectorById, components, boardRevision, inspectionConnections, provenanceLabels, snapshotDate, observedReadings, syntheticReadings } from "./board.mjs";
import { emptyDocument, emptyConnection, loadDocument, saveDocument, updateConnection, serializeDocument, parseDocument, withInspectionDefaults, connectionCounts, fanAvailability, readingFor, interpolateAir, maxImportBytes, storageKey } from "./model.mjs";

const $ = id => document.getElementById(id);
let inventory = withInspectionDefaults(emptyDocument());
let selectedId = "FAN1";
let mode = "snapshot";
let zoom = 100;
let dirty = false;
let storageBlocked = false;
let pendingPersistence = false;

function notify(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
  $("notice").setAttribute("role", error ? "alert" : "status");
  $("notice").hidden = false;
}

try {
  inventory = withInspectionDefaults(loadDocument(window.localStorage));
} catch (error) {
  storageBlocked = true;
  notify(`Saved map could not be loaded: ${error.message} Existing data was not overwritten. Import a valid JSON export to replace it; exports remain available for this tab.`, true);
}

function element(tag, attributes = {}, text = "") {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  node.textContent = text;
  return node;
}

function svgElement(tag, attributes, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  node.textContent = text;
  return node;
}

function currentReadings() {
  return mode === "snapshot" ? observedReadings : syntheticReadings;
}

function formatValue(value) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
}

function connectionFor(id) {
  return inventory.connections[id] ?? emptyConnection();
}

function describeConnection(id) {
  const connection = connectionFor(id);
  return `${id}, ${connection.confidence} connection, ${connection.occupancy}, ${provenanceLabels[connection.provenance]}${connection.target ? ` to ${connection.target}` : ""}`;
}

function selectConnector(id) {
  if (!connectorById.has(id)) return;
  if (dirty && !window.confirm("Discard the unsaved connection changes?")) return;
  selectedId = id;
  dirty = false;
  renderSelection();
}

function renderBoard() {
  const board = $("board");
  board.replaceChildren();
  board.append(svgElement("rect", { x: 65, y: 10, width: 675, height: 910, rx: 17, class: "board-outline" }));
  for (const x of [100, 180, 400, 550, 725]) {
    board.append(svgElement("path", { d: `M${x} 165 V840`, class: "board-rail" }));
  }
  board.append(svgElement("text", { x: 92, y: 38, class: "board-label" }, `ASROCK RACK / ROMED8-2T / REV ${boardRevision}`));
  board.append(svgElement("text", { x: 145, y: 840, class: "board-caption" }, "GPU / HBA slot reports UNVERIFIED · see PCIE1 / PCIE2"));
  board.append(svgElement("text", { x: 92, y: 910, class: "board-label" }, "ORIGINAL LOGICAL SCHEMATIC / NOT A WIRING GUIDE"));
  for (const connector of connectors) {
    const { id, x, y, width, height } = connector;
    const group = svgElement("g", { class: "connector", "data-id": id, role: "button", tabindex: "0" });
    group.append(svgElement("rect", { x, y, width, height, rx: 4 }));
    group.append(svgElement("text", { x: x + width / 2, y: y + height / 2 + 3.5 }, connector.label));
    if (connector.category === "Fans") {
      for (let i = 0; i < 6; i += 1) {
        group.append(svgElement("circle", { cx: x + 12 + i * 14, cy: y + height - 4, r: 1.3, class: "header-pins" }));
      }
    }
    group.addEventListener("click", () => selectConnector(id));
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectConnector(id);
      }
    });
    board.append(group);
  }
}

function renderList() {
  const search = $("filter").value.trim().toLowerCase();
  const category = $("category").value;
  const filtered = connectors.filter(connector =>
    (!category || connector.category === category) &&
    `${connector.id} ${connector.label} ${connector.category}`.toLowerCase().includes(search),
  );
  const list = $("connector-list");
  list.replaceChildren();
  for (const connector of filtered) {
    const button = element("button", {
      type: "button", class: `connector-item${connector.id === selectedId ? " selected" : ""}`,
      "data-id": connector.id, "aria-pressed": String(connector.id === selectedId),
      "aria-label": describeConnection(connector.id),
    });
    button.append(element("i", { class: `legend-dot ${connectionFor(connector.id).confidence}`, "aria-hidden": "true" }));
    button.append(element("span", {}, connector.id));
    button.append(element("span", { class: "list-category" }, connector.category));
    button.addEventListener("click", () => selectConnector(connector.id));
    list.append(button);
  }
  if (!filtered.length) list.append(element("p", { class: "empty-list" }, "No matching connectors."));
}

function renderSelection() {
  const connector = connectorById.get(selectedId);
  const connection = connectionFor(selectedId);
  for (const group of $("board").querySelectorAll(".connector")) {
    const id = group.dataset.id;
    group.classList.toggle("selected", id === selectedId);
    group.dataset.confidence = connectionFor(id).confidence;
    group.setAttribute("aria-label", describeConnection(id));
    group.setAttribute("aria-pressed", String(id === selectedId));
  }
  renderList();
  const counts = connectionCounts(inventory);
  for (const confidence of ["confirmed", "inferred", "unknown"]) {
    $(`${confidence}-count`).textContent = counts[confidence];
  }
  const availability = fanAvailability(inventory);
  $("fan-availability").textContent = `${availability.free} / ${availability.occupied}`;
  const reportedOccupied = connectors.filter(connector =>
    connector.category === "Fans" && connectionFor(connector.id).provenance === "user-reported" &&
    connectionFor(connector.id).confidence !== "confirmed" && connectionFor(connector.id).occupancy === "occupied",
  ).length;
  $("fan-unverified").textContent = `${availability.unverified} not independently verified; ${reportedOccupied} user-reported occupied`;
  $("detail-category").textContent = `${connector.category.toUpperCase()} / SELECTED CONNECTOR`;
  $("detail-name").textContent = connector.id;
  $("detail-confidence").className = `badge ${connection.confidence}`;
  $("detail-confidence").textContent = `${connection.confidence[0].toUpperCase()}${connection.confidence.slice(1)} connection`;
  $("detail-occupancy").textContent = `${connection.occupancy[0].toUpperCase()}${connection.occupancy.slice(1)} occupancy`;
  $("detail-provenance").textContent = provenanceLabels[connection.provenance];
  const observation = inspectionConnections[selectedId];
  $("inspection-observation").hidden = !observation;
  $("inspection-observation").textContent = observation
    ? `Supplied inspection record — ${provenanceLabels[observation.provenance]}; ${observation.confidence}, ${observation.occupancy}${observation.target ? `: ${observation.target}` : ""}. ${observation.evidence} ${observation.note}`
    : "";
  $("detail-description").textContent = connector.detail;
  $("detail-source").textContent = connector.source;
  const reading = readingFor(currentReadings(), selectedId);
  $("detail-reading").textContent = reading
    ? `${mode === "snapshot" ? `Observed ${snapshotDate}; not live` : "Synthetic example"}: ${formatValue(reading.value)} ${reading.unit}. ${reading.source}.`
    : connector.category === "Fans"
      ? "No reading in this dataset. This does not prove that the header is empty or that a fan is stopped."
      : "Physical cable / slot assignment is separate from the reported installed inventory.";
  $("pin-section").hidden = connector.pins.length === 0;
  $("no-pins").hidden = connector.pins.length !== 0;
  $("pin-strip").replaceChildren();
  $("pin-table").replaceChildren();
  $("fan-location").textContent = connector.location ?? "";
  for (const pin of [...connector.pins].reverse()) {
    $("pin-strip").append(element("span", { class: "pin", title: pin.signal }, String(pin.number)));
  }
  for (const pin of connector.pins) {
    const row = element("tr");
    const signal = element("td");
    signal.append(element("div", {}, pin.signal), element("small", { class: "pin-function" }, pin.description));
    row.append(element("td", {}, String(pin.number)), signal);
    $("pin-table").append(row);
  }
  $("pin-caution").textContent = connector.caution ?? "";
  for (const key of ["target", "confidence", "occupancy", "provenance", "evidence", "note"]) $(key).value = connection[key];
  $("save-status").textContent = pendingPersistence
    ? "NOT PERSISTED — tab-only changes. Export JSON to keep them."
    : connection.updatedAt
      ? `Last annotated ${new Date(connection.updatedAt).toLocaleString()}. Browser-local; export a backup.`
      : observation ? "Inspection default / existing annotation; no local edit timestamp. Export a backup." : "Saved only in this browser. Export a backup.";
}

$("connection-form").addEventListener("input", () => { dirty = true; });
$("connection-form").addEventListener("submit", event => {
  event.preventDefault();
  const fields = Object.fromEntries(["target", "confidence", "occupancy", "provenance", "evidence", "note"].map(key => [key, $(key).value]));
  let next;
  try {
    next = updateConnection(inventory, selectedId, fields);
  } catch (error) {
    notify(error.message, true);
    return;
  }
  inventory = next;
  dirty = false;
  let persisted = false;
  try {
    if (storageBlocked) throw new Error("Existing browser data could not be loaded; import a valid export before replacing it.");
    saveDocument(window.localStorage, inventory);
    persisted = true;
    pendingPersistence = false;
  } catch (error) {
    pendingPersistence = true;
    notify(`Changes are in this tab only: ${error.message} Export JSON now to keep them.`, true);
  }
  renderSelection();
  if (persisted) notify(`${selectedId} saved in this browser. Nothing was sent to the server.`);
});

function downloadDocument() {
  const blob = new Blob([serializeDocument(inventory)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = element("a", { href: url, download: "server-atlas-connections.json" });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("export").addEventListener("click", () => {
  if (dirty) {
    notify("Save the current form before exporting. Unsaved fields are not included.", true);
    return;
  }
  downloadDocument();
  notify("JSON export downloaded. Treat your private notes as private; exports are not uploaded.");
});
$("import-button").addEventListener("click", () => $("import-file").click());
$("import-file").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > maxImportBytes) throw new Error("Import must be smaller than 256 KiB.");
    const next = withInspectionDefaults(parseDocument(await file.text()));
    if (!window.confirm("Replace this browser's connection annotations with the imported map? Export first if you need a backup.")) return;
    saveDocument(window.localStorage, next);
    inventory = next;
    dirty = false;
    storageBlocked = false;
    pendingPersistence = false;
    renderSelection();
    notify("Map imported and saved in this browser. Inspection defaults fill only missing connectors; imported annotations take precedence. Imported labels are assertions, not independent verification.");
  } catch (error) {
    notify(`Import failed: ${error.message} Existing annotations were not replaced.`, true);
  } finally {
    event.target.value = "";
  }
});

window.addEventListener("beforeunload", event => {
  if (dirty || pendingPersistence) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("storage", event => {
  if (event.key === storageKey || event.key === null) {
    storageBlocked = true;
    notify("Annotations changed in another tab. Saving is blocked to avoid overwriting them. Export this tab's work, then reload to read the latest saved map.", true);
  }
});
$("filter").addEventListener("input", renderList);
$("category").addEventListener("change", renderList);
for (const category of [...new Set(connectors.map(connector => connector.category))]) {
  $("category").append(element("option", { value: category }, category));
}
for (const [value, label] of Object.entries(provenanceLabels)) $("provenance").append(element("option", { value }, label));
$("board-revision").textContent = `ROMED8-2T · REV ${boardRevision}`;
for (const component of components) $("component-options").append(element("option", { value: component.model }));
$("connector-total").textContent = connectors.length;

function setZoom(next) {
  zoom = Math.max(75, Math.min(175, next));
  $("board").style.width = `${zoom}%`;
  $("zoom-label").textContent = `${zoom}%`;
  $("zoom-out").disabled = zoom === 75;
  $("zoom-in").disabled = zoom === 175;
}
$("zoom-in").addEventListener("click", () => setZoom(zoom + 25));
$("zoom-out").addEventListener("click", () => setZoom(zoom - 25));

function setView(view) {
  for (const id of ["board", "case"]) {
    $(`${id}-view`).hidden = id !== view;
    $(`${id}-tab`).classList.toggle("active", id === view);
    $(`${id}-tab`).setAttribute("aria-pressed", String(id === view));
  }
}
$("board-tab").addEventListener("click", () => setView("board"));
$("case-tab").addEventListener("click", () => setView("case"));

function renderAir() {
  const readings = currentReadings();
  const position = Number($("air-position").value) / 100;
  const value = interpolateAir(readings, position, mode);
  $("air-position").disabled = value === null;
  $("air-result").textContent = value === null ? "Unavailable" : `≈ ${formatValue(value)} °C at ${Math.round(position * 100)}%`;
  $("air-field").setAttribute("opacity", value === null ? "0" : ".28");
  $("air-front-label").textContent = value === null ? "INLET AIR: UNKNOWN" : "SYNTHETIC INLET: 24 °C";
  $("air-mid-label").textContent = value === null ? "NO VERIFIED AIR PROBES" : "LERP MIDPOINT: ≈31.5 °C";
  $("air-rear-label").textContent = value === null ? "OUTLET AIR: UNKNOWN" : "SYNTHETIC OUTLET: 39 °C";
  $("air-explanation").textContent = value === null
    ? "No air estimate: there are no verified, located air-temperature probes in the observed dataset. Component temperatures are intentionally excluded."
    : "SYNTHETIC ESTIMATE — linear interpolation between two invented air probes. Not measured air, an airflow simulation, or evidence of real hot spots. Case geometry and airflow are conceptual.";
}

function renderTelemetry() {
  $("observed-mode").classList.toggle("active", mode === "snapshot");
  $("synthetic-mode").classList.toggle("active", mode === "synthetic");
  $("observed-mode").setAttribute("aria-pressed", String(mode === "snapshot"));
  $("synthetic-mode").setAttribute("aria-pressed", String(mode === "synthetic"));
  $("telemetry-warning").classList.toggle("synthetic", mode === "synthetic");
  $("telemetry-warning").textContent = mode === "snapshot"
    ? `OBSERVED SNAPSHOT · ${snapshotDate} · Not live and not current. Values were read at separate moments; no exact synchronized capture time is available. GPU / HDD temperatures and case air remain unknown.`
    : "SYNTHETIC DEMO · Every displayed sensor value below is invented. The air overlay is an estimated interpolation of invented probes, not a measurement.";
  $("reading-grid").replaceChildren();
  for (const reading of currentReadings()) {
    const card = element("article", { class: `reading-card ${reading.provenance}` });
    card.append(element("h4", {}, reading.label));
    const value = element("div", { class: "reading-value" }, formatValue(reading.value));
    value.append(element("small", {}, reading.unit));
    card.append(value, element("div", { class: "reading-provenance" }, mode === "snapshot" ? `OBSERVED / ${reading.observedAt}` : "SYNTHETIC EXAMPLE"));
    card.append(element("p", {}, reading.source));
    $("reading-grid").append(card);
  }
  const unknown = element("article", { class: "reading-card" });
  unknown.append(element("h4", {}, "Unobserved channels"), element("div", { class: "reading-value" }, "Unknown"));
  unknown.append(element("p", {}, "GPU and HDD temperatures; FAN3–FAN7 and all secondary tach channels. Missing data is not zero."));
  $("reading-grid").append(unknown);
  renderAir();
  // Updating mode must not replace unsaved connection form fields.
  if (!dirty) renderSelection();
}
$("observed-mode").addEventListener("click", () => { mode = "snapshot"; renderTelemetry(); });
$("synthetic-mode").addEventListener("click", () => { mode = "synthetic"; renderTelemetry(); });
$("air-position").addEventListener("input", renderAir);
for (const component of components) {
  const card = element("article", { class: "inventory-card" });
  card.append(element("h4", {}, component.label), element("p", {}, component.model), element("strong", {}, component.capacity), element("p", {}, component.status));
  if (component.note) card.append(element("p", {}, component.note));
  $("inventory-grid").append(card);
}
renderBoard();
renderSelection();
renderTelemetry();
document.documentElement.dataset.ready = "true";
