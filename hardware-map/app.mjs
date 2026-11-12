import { connectors, connectorById, components, boardRevision, landscapeBounds, inspectionConnections, provenanceLabels, snapshotDate, observedReadings, syntheticReadings } from "./board.mjs";
import { emptyDocument, emptyConnection, loadDocument, saveDocument, updateConnection, serializeDocument, parseDocument, withInspectionDefaults, connectionCounts, fanAvailability, readingFor, interpolateAir, maxImportBytes, storageKey } from "./model.mjs";

const $ = id => document.getElementById(id);
let inventory = withInspectionDefaults(emptyDocument());
let selectedId = "FAN1";
let selectedPartId = "cpu";
let activeCategory = "";
const componentById = new Map(components.map(component => [component.id, component]));
const sceneParts = new Map();
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
  selectedPartId = null;
  if (!activeCategory) activeCategory = connectorById.get(id).category;
  dirty = false;
  renderSelection();
}

function selectComponent(id) {
  if (!sceneParts.has(id) || connectorFocus()) return;
  if (dirty && !window.confirm("Discard the unsaved connection changes?")) return;
  selectedPartId = id;
  dirty = false;
  renderSelection();
}

function connectorFocus() {
  return Boolean(activeCategory || $("filter").value.trim());
}

function matchesFocus(connector) {
  const search = $("filter").value.trim().toLowerCase();
  return (!activeCategory || activeCategory === "*" || connector.category === activeCategory) &&
    `${connector.id} ${connector.label} ${connector.category}`.toLowerCase().includes(search);
}

function interactiveGroup(className, id, label, onSelect) {
  const group = svgElement("g", { class: className, "data-id": id, role: "button", tabindex: "0", "aria-label": label });
  group.append(svgElement("title", {}, label));
  group.addEventListener("click", onSelect);
  group.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  });
  return group;
}

function hardwarePart(id, componentId, label, placement, connectorIds = [], extra = {}) {
  sceneParts.set(id, { componentId, label, placement, connectorIds, ...extra });
  return interactiveGroup("hardware-part", id, label, () => {
    if (connectorFocus()) return;
    selectComponent(id);
  });
}

function drawFan(parent, x, y, size) {
  const fan = svgElement("g", { class: "fan-face" });
  fan.append(svgElement("rect", { x, y, width: size, height: size, rx: 5, class: "fan-frame" }));
  fan.append(svgElement("circle", { cx: x + size / 2, cy: y + size / 2, r: size * .43, class: "fan-ring" }));
  for (let angle = 0; angle < 360; angle += 60) {
    fan.append(svgElement("path", {
      d: `M${x + size * .5} ${y + size * .49} Q${x + size * .07} ${y + size * .18} ${x + size * .45} ${y + size * .08} Q${x + size * .77} ${y + size * .09} ${x + size * .57} ${y + size * .48} Z`,
      transform: `rotate(${angle} ${x + size / 2} ${y + size / 2})`, class: "fan-blade",
    }));
  }
  fan.append(svgElement("circle", { cx: x + size / 2, cy: y + size / 2, r: size * .15, class: "fan-hub" }));
  parent.append(fan);
}

function renderBoard() {
  const board = $("board");
  board.replaceChildren();
  const enclosure = hardwarePart("chassis", null, "Rosewill RSV-L4500U", "Original top-view schematic informed by inspection photos. Case-part positions, proportions and component outlines are approximate, not measured.", [], {
    model: "Rosewill RSV-L4500U · 4U rack chassis", capacity: "15 HDD bays · 12 installed / 3 empty",
    status: "Chassis model user-reported; bay capacity and installed count user-confirmed",
    note: "Fan faces are unfolded for identification, not their physical mounting angle. No actual bay identity, cable route, airflow direction or mounting clearance is established by this drawing.",
  });
  enclosure.append(svgElement("rect", { x: 35, y: 65, width: 1365, height: 725, rx: 9, class: "chassis-shell part-outline" }));
  for (const y of [81, 774]) enclosure.append(svgElement("path", { d: `M50 ${y} H1383`, class: "chassis-rail" }));
  for (const x of [45, 1388]) {
    for (const y of [105, 745]) enclosure.append(svgElement("circle", { cx: x, cy: y, r: 4, class: "chassis-screw" }));
  }
  board.append(enclosure);
  board.append(svgElement("text", { x: 55, y: 38, class: "scene-heading" }, "ROSEWILL / RSV-L4500U"));
  board.append(svgElement("text", { x: 55, y: 59, class: "scene-note" }, "FRONT / DRIVE CAGES"));
  board.append(svgElement("text", { x: 1220, y: 38, class: "scene-heading" }, "REAR / I/O"));
  board.append(svgElement("text", { x: 55, y: 817, class: "scene-note" }, "ORIGINAL SCHEMATIC · APPROXIMATE POSITIONS · FAN FACES UNFOLDED · NO CABLE ROUTES OR CLEARANCE GUARANTEE"));

  const motherboard = hardwarePart("motherboard", "board", "ROMED8-2T REV 1.03", "Connector neighbors and ordering follow the manual, rotated 180° with rear I/O on the right. Distances are schematic; physical pin-1 orientation remains unverified.");
  motherboard.append(svgElement("rect", { ...landscapeBounds({ x: 65, y: 10, width: 675, height: 910 }), rx: 5, class: "board-outline part-outline" }));
  for (const x of [180, 400, 550]) {
    const rail = landscapeBounds({ x, y: 165, width: 0, height: 675 });
    motherboard.append(svgElement("path", { d: `M${rail.x} ${rail.y} v${rail.height}`, class: "board-rail" }));
  }
  motherboard.append(svgElement("text", { x: 835, y: 608, class: "board-label" }, `ASROCK RACK / ROMED8-2T REV ${boardRevision}`));
  board.append(motherboard);

  const connectorLayer = svgElement("g", { id: "connector-layer" });
  for (const connector of connectors) {
    const { id } = connector;
    const { x, y, width, height } = landscapeBounds(connector);
    const group = interactiveGroup("connector", id, describeConnection(id), () => {
      if (connectorFocus() && !matchesFocus(connector)) return;
      selectConnector(id);
    });
    group.append(svgElement("rect", { x, y, width, height, rx: 2 }));
    group.append(svgElement("text", { x: x + width / 2, y: y + height / 2 + 3.5 }, connector.label));
    if (connector.category === "Fans") {
      for (let i = 0; i < 6; i += 1) {
        group.append(svgElement("circle", { cx: x + 7 + i * 10, cy: y + height - 2, r: 1, class: "header-pins" }));
      }
    }
    connectorLayer.append(group);
  }
  board.append(connectorLayer);

  const hardware = svgElement("g", { id: "installed-hardware" });
  const disks = hardwarePart("disk-bays", "disks", "12 HDDs / 15 bays", "Three cage regions are approximate. Twelve filled and three outlined bays illustrate counts ONLY; they do not assign drives or empty positions to a cage.");
  for (let cage = 0; cage < 3; cage += 1) {
    const y = 124 + cage * 196;
    disks.append(svgElement("rect", { x: 172, y, width: 231, height: 173, rx: 4, class: "drive-cage part-outline" }));
    for (let bay = 0; bay < 5; bay += 1) {
      disks.append(svgElement("rect", { x: 185, y: y + 15 + bay * 29, width: 205, height: 22, rx: 2, class: bay === 4 ? "drive-bay empty" : "drive-bay" }));
      if (bay < 4) {
        disks.append(svgElement("rect", { x: 193, y: y + 21 + bay * 29, width: 28, height: 10, class: "drive-label" }));
        disks.append(svgElement("circle", { cx: 379, cy: y + 26 + bay * 29, r: 2, class: "drive-screw" }));
      }
    }
  }
  disks.append(svgElement("text", { x: 173, y: 738, class: "scene-heading" }, "12 HDDs / 15 BAYS"));
  disks.append(svgElement("text", { x: 173, y: 758, class: "scene-note" }, "3 EMPTY · POSITIONS UNKNOWN"));
  hardware.append(disks);
  for (const [region, x] of [["front", 60], ["middle", 440]]) {
    for (let i = 0; i < 3; i += 1) {
      const fan = hardwarePart(`${region}-fan-${i + 1}`, "case-fans", `${region === "front" ? "Front" : "Middle"} 120 mm fan ${i + 1} · Molex chain A`, "Bank placement is photo-informed but approximate. Fan faces are unfolded into this view; drawn order is not a cable or airflow trace.");
      drawFan(fan, x, 159 + i * 196, 94);
      hardware.append(fan);
    }
    hardware.append(svgElement("text", { x, y: 112, class: "scene-heading" }, region === "front" ? "3 FRONT" : "3 MIDDLE"));
    hardware.append(svgElement("text", { x, y: 716, class: "scene-note" }, "MOLEX A"));
  }

  const psu = hardwarePart("psu", "psu", "Corsair HX1000i", "Rear PSU region is photo-informed. Size, mounting offsets and clearance are approximate; modular port counts do not verify cable routing.");
  psu.append(svgElement("rect", { x: 1035, y: 650, width: 300, height: 115, rx: 5, class: "psu-body part-outline" }));
  for (let y = 665; y < 751; y += 7) psu.append(svgElement("path", { d: `M1250 ${y} H1315`, class: "psu-grille" }));
  psu.append(svgElement("text", { x: 1060, y: 698, class: "psu-label" }, "HX1000i"));
  psu.append(svgElement("text", { x: 1060, y: 723, class: "hardware-subtitle" }, "CORSAIR / PSU"));
  hardware.append(psu);
  for (let i = 0; i < 2; i += 1) {
    const fan = hardwarePart(`rear-fan-${i + 1}`, "rear-fans", `Rear 80 mm fan ${i + 1} · Molex chain B`, "Rear bank is photo-informed; centers and mounting geometry are approximate. Width is specification-based plus user-confirmed factory-original fans, not photo-measured.");
    drawFan(fan, 1314, 420 + i * 111, 63);
    hardware.append(fan);
  }
  hardware.append(svgElement("text", { x: 1304, y: 398, class: "scene-heading" }, "2 REAR"));

  for (const id of ["M2_2", "M2_1"]) {
    const connector = connectorById.get(id);
    const drive = hardwarePart(`drive-${id}`, null, `${id} / bare Samsung 2280`, "Drive direction follows inspection evidence: perpendicular to PCIe slots across PCIE6→PCIE2. Outline and GPU overhang are approximate; clearance is unmeasured.", [id], {
      model: "Bare Samsung 2280 SSD · no heatsink", capacity: "2 TB per drive reported · logical A/B binding unknown",
      status: "Both populated sockets and bare drives photo-confirmed (relayed)",
      note: "The GPU shroud overhangs both drives. The photo-estimated few-mm gap is not a measured heatsink allowance. NVMe A/B telemetry is deliberately not assigned to a physical socket.",
    });
    const bounds = landscapeBounds({ x: connector.x + 25, y: 513, width: 40, height: 236 });
    drive.append(svgElement("rect", { ...bounds, rx: 3, class: "ssd-body part-outline" }));
    for (let i = 0; i < 3; i += 1) drive.append(svgElement("rect", { x: bounds.x + 4, y: bounds.y + 13 + i * 36, width: bounds.width - 8, height: 24, class: "ssd-chip" }));
    drive.append(svgElement("text", { x: bounds.x + bounds.width / 2, y: bounds.y - 7, class: "hardware-label centered" }, id));
    hardware.append(drive);
  }
  for (const socket of ["DDR4_A1", "DDR4_B1", "DDR4_G1", "DDR4_H1"]) {
    const { x, y, width, height } = landscapeBounds(connectorById.get(socket));
    const dimm = hardwarePart(`dimm-${socket}`, "memory", `${socket} / installed ECC DIMM`, "Population in A1/B1/G1/H1 is user-reported. Board positions follow the manual; module heights and appearance are schematic.", [socket]);
    dimm.append(svgElement("rect", { x, y: y - 4, width, height: height + 5, rx: 1, class: `dimm-body part-outline ${["DDR4_A1", "DDR4_H1"].includes(socket) ? "blue-slot" : ""}` }));
    for (let i = 0; i < 8; i += 1) {
      dimm.append(svgElement("rect", { x: x + 8 + i * 25, y: y - 1, width: 17, height: height - 1, class: "dimm-chip" }));
    }
    dimm.append(svgElement("text", { x: x - 8, y: y + 7, class: "dimm-label" }, socket.replace("DDR4_", "")));
    hardware.append(dimm);
  }

  const cpu = hardwarePart("cpu", "cpu", "EPYC 7313P / NH-U9 TR4-SP3", "CPU is beneath the cooler. Cooler silhouette is photo-inspired: silver fins, beige Noctua frames and brown corners. Outline, fan mounting and clearance are not measured.", ["CPU1", "FAN1", "FAN2"], { readingId: "cpu" });
  const cpuBounds = landscapeBounds(connectorById.get("CPU1"));
  cpu.append(svgElement("rect", { ...cpuBounds, rx: 5, class: "cooler-body part-outline" }));
  for (let x = cpuBounds.x + 6; x < cpuBounds.x + cpuBounds.width - 4; x += 6) {
    cpu.append(svgElement("path", { d: `M${x} ${cpuBounds.y + 5} v${cpuBounds.height - 10}`, class: "cooler-fin" }));
  }
  for (const y of [cpuBounds.y - 19, cpuBounds.y + cpuBounds.height]) {
    cpu.append(svgElement("rect", { x: cpuBounds.x, y, width: cpuBounds.width, height: 18, rx: 2, class: "noctua-frame" }));
    for (const x of [cpuBounds.x, cpuBounds.x + cpuBounds.width - 15]) cpu.append(svgElement("rect", { x, y, width: 15, height: 18, class: "noctua-corner" }));
  }
  cpu.append(svgElement("rect", { x: cpuBounds.x + 14, y: cpuBounds.y + 30, width: cpuBounds.width - 28, height: 38, rx: 3, class: "cooler-plaque" }));
  cpu.append(svgElement("text", { x: cpuBounds.x + cpuBounds.width / 2, y: cpuBounds.y + 46, class: "cooler-label" }, "EPYC 7313P"));
  cpu.append(svgElement("text", { x: cpuBounds.x + cpuBounds.width / 2, y: cpuBounds.y + 61, class: "cooler-sublabel" }, "UNDER NH-U9 TR4-SP3"));
  hardware.append(cpu);

  const gpu = hardwarePart("gpu", "gpu", "RTX 2070 SUPER / PCIE3", "Slot PCIE3 is user-confirmed/photo-consistent. The card outline spans PCIE2 to illustrate the reported cooler blockage; its full shroud footprint and M.2 clearance are not measured.", ["PCIE3", "PCIE2"], { readingId: "gpu" });
  const gpuSlot = landscapeBounds(connectorById.get("PCIE3"));
  const gpuTop = landscapeBounds(connectorById.get("PCIE2")).y - 4;
  gpu.append(svgElement("rect", { x: 872, y: gpuTop, width: 418, height: gpuSlot.y + gpuSlot.height - gpuTop + 5, rx: 4, class: "gpu-body part-outline" }));
  gpu.append(svgElement("path", { d: `M882 ${gpuTop + 10} H1050 L1085 ${gpuTop + 45} H1280`, class: "gpu-trim" }));
  gpu.append(svgElement("text", { x: 913, y: gpuTop + 26, class: "hardware-label" }, "GIGABYTE / RTX 2070 SUPER"));
  gpu.append(svgElement("text", { x: 913, y: gpuTop + 45, class: "hardware-subtitle" }, "PCIE3 · PCIE2 BLOCKED · M.2 OVERHANG"));
  hardware.append(gpu);
  const hba = hardwarePart("hba", "hba", "Low-profile HBA / PCIE1", "PCIE1 is user-confirmed/photo-consistent. HBA sits at the GPU fan intake. Outline and spacing are not measurements; cable routes and airflow impact remain unknown.", ["PCIE1"]);
  const hbaSlot = landscapeBounds(connectorById.get("PCIE1"));
  hba.append(svgElement("rect", { x: 1123, y: hbaSlot.y - 9, width: 167, height: 34, rx: 2, class: "hba-body part-outline" }));
  for (let x = 1133; x < 1185; x += 5) hba.append(svgElement("path", { d: `M${x} ${hbaSlot.y - 5} v25`, class: "hba-fin" }));
  hba.append(svgElement("text", { x: 1193, y: hbaSlot.y + 12, class: "hardware-label" }, "HBA / PCIE1"));
  hardware.append(hba);
  hardware.append(svgElement("text", { x: 590, y: 742, class: "scene-note" }, "COMPONENT OUTLINES ≠ MEASURED FOOTPRINTS"));
  hardware.append(svgElement("text", { x: 590, y: 761, class: "scene-note" }, "SELECT A CONNECTOR CATEGORY TO SEE THROUGH HARDWARE"));
  board.append(hardware);
}

function renderList() {
  const filtered = connectors.filter(matchesFocus);
  const list = $("connector-list");
  list.hidden = !connectorFocus();
  list.replaceChildren();
  for (const connector of filtered) {
    const button = element("button", {
      type: "button", class: `connector-item${!selectedPartId && connector.id === selectedId ? " selected" : ""}`,
      "data-id": connector.id, "aria-pressed": String(!selectedPartId && connector.id === selectedId),
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

function renderFocus() {
  const focused = connectorFocus();
  $("board").classList.toggle("connector-focus", focused);
  for (const button of $("categories").children) {
    const active = button.dataset.category === activeCategory && (button.dataset.category !== "" || !focused);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  for (const group of $("board").querySelectorAll(".hardware-part")) {
    group.setAttribute("tabindex", focused ? "-1" : "0");
    group.setAttribute("aria-disabled", String(focused));
    group.classList.toggle("selected", group.dataset.id === selectedPartId);
    group.setAttribute("aria-pressed", String(group.dataset.id === selectedPartId));
  }
  for (const group of $("board").querySelectorAll(".connector")) {
    const available = focused && matchesFocus(connectorById.get(group.dataset.id));
    group.classList.toggle("out-of-focus", focused && !available);
    group.setAttribute("aria-disabled", String(focused && !available));
    group.setAttribute("tabindex", available ? "0" : "-1");
  }
  $("focus-status").textContent = focused
    ? `${connectors.filter(matchesFocus).length} / ${connectors.length} connectors shown · hardware dimmed and disabled; outlines do not verify physical access.`
    : "Hardware mode · click an installed component for details. Connector categories reveal headers beneath hardware.";
  renderList();
}

function renderComponentDetails() {
  const part = sceneParts.get(selectedPartId);
  const component = componentById.get(part.componentId) ?? part;
  $("component-name").textContent = part.label;
  $("component-model").textContent = component.model;
  $("component-capacity").textContent = component.capacity;
  $("component-provenance").textContent = component.status;
  $("component-note").textContent = component.note ?? "";
  $("component-placement").textContent = part.placement;
  const reading = part.readingId ? readingFor(currentReadings(), part.readingId) : null;
  $("component-reading").textContent = reading
    ? `${mode === "snapshot" ? `Observed ${snapshotDate}; not live` : "Synthetic example"}: ${formatValue(reading.value)} ${reading.unit}. ${reading.source}.`
    : "No sensor reading assigned to this physical component. Ratings, reported capacities and snapshot telemetry are separate evidence.";
  $("component-connectors").replaceChildren();
  for (const id of part.connectorIds) {
    const button = element("button", { type: "button" }, id);
    button.addEventListener("click", () => selectConnector(id));
    $("component-connectors").append(button);
  }
  if (!part.connectorIds.length) {
    $("component-connectors").append(element("p", { class: "compact muted" },
      part.componentId === "case-fans" || part.componentId === "rear-fans"
        ? "Reported PSU/Molex power only; no motherboard tach or control connection."
        : "No specific board connector is assigned here. Do not infer a cable route from placement."));
  }
}

function renderSelection() {
  const connector = connectorById.get(selectedId);
  const connection = connectionFor(selectedId);
  for (const group of $("board").querySelectorAll(".connector")) {
    const id = group.dataset.id;
    group.classList.toggle("selected", !selectedPartId && id === selectedId);
    group.dataset.confidence = connectionFor(id).confidence;
    group.dataset.occupancy = connectionFor(id).occupancy;
    group.querySelector("text").textContent = `${connectorById.get(id).label}${connectionFor(id).occupancy === "blocked" ? " · BLOCKED" : ""}`;
    group.setAttribute("aria-label", describeConnection(id));
    group.setAttribute("aria-pressed", String(!selectedPartId && id === selectedId));
  }
  renderFocus();
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
  $("fan-unverified").textContent = `${availability.unverified} not independently verified${reportedOccupied ? `; ${reportedOccupied} user-reported occupied` : ""}`;
  $("component-details").hidden = !selectedPartId;
  $("connector-details").hidden = Boolean(selectedPartId);
  if (selectedPartId) {
    renderComponentDetails();
    return;
  }
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
$("filter").addEventListener("input", renderFocus);
for (const [category, label] of [
  ["", "Hardware"], ["*", "All connectors"],
  ...[...new Set(connectors.map(connector => connector.category))].map(category => [category, category]),
]) {
  const button = element("button", { type: "button", "data-category": category, "aria-pressed": "false" }, label);
  button.addEventListener("click", () => {
    if (dirty && !window.confirm("Discard the unsaved connection changes?")) return;
    dirty = false;
    activeCategory = category;
    $("filter").value = "";
    selectedPartId = category ? null : "cpu";
    if (category) selectedId = connectors.find(matchesFocus).id;
    renderSelection();
  });
  $("categories").append(button);
}
for (const [value, label] of Object.entries(provenanceLabels)) $("provenance").append(element("option", { value }, label));
$("board-revision").textContent = `ROMED8-2T · REV ${boardRevision}`;
for (const component of components) $("component-options").append(element("option", { value: component.model }));
function expandWorkspace(expanded) {
  document.body.classList.toggle("map-expanded", expanded);
  for (const section of document.querySelectorAll(".masthead, main > :not(.board-workspace)")) section.inert = expanded;
  $("expand-map").setAttribute("aria-pressed", String(expanded));
  $("expand-map").textContent = expanded ? "Exit expanded view" : "Expand workspace";
}
$("expand-map").addEventListener("click", () => expandWorkspace(!document.body.classList.contains("map-expanded")));
window.addEventListener("keydown", event => {
  if (event.key === "Escape") expandWorkspace(false);
});

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
