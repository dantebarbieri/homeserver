import { connectors, connectorById, components, driveCages, psuPorts, inspectedJumpers, pcie2Modes, hardwareCategories, partReferences, boardRevision, landscapeBounds, occupancyLabels } from "./board.mjs";
import { emptyDocument, emptyConnection, loadDocument, withInspectionDefaults, occupancyCounts, matchesHardware, fanMotionForSpeed, buildLinuxTopology, linuxNodeSummary, pcie2ModeFor, storageKey } from "./model.mjs";
import { linuxSnapshot } from "./linux-snapshot.mjs";
import { createMetricUI } from "./metrics.mjs";
import { applyLiveSnapshot } from "./metric-model.mjs";
import { LiveData } from "./live-data.mjs";
import { createBottomSheet } from "./mobile-ui.mjs";
import { setupPwa } from "./pwa.mjs";

const $ = id => document.getElementById(id);
let inventory = withInspectionDefaults(emptyDocument());
let selectedId = "FAN1";
let selectedPartId = "cpu";
let focusMode = "hardware";
let activeCategory = "*";
const componentById = new Map(components.map(component => [component.id, component]));
const sceneParts = new Map();
let metricUI = null;
let linuxTopology = buildLinuxTopology(linuxSnapshot);
const dataSource = new LiveData({ enabled: document.querySelector('meta[name="atlas-data"]').content === "live" && new URLSearchParams(location.search).get("demo") !== "1" });
let zoom = 100;
let metricFanFrame = null;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let fanRotationEnabled = !reducedMotion.matches;
let fanRotationOverride = false;
let linuxReturnId = null;
const popupContexts = new Map();
const popupSheets = new Map();

function notify(message, error = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.setAttribute("role", error ? "alert" : "status");
  notice.hidden = false;
}
setupPwa(message => notify(message, true));

try {
  inventory = withInspectionDefaults(loadDocument(window.localStorage));
} catch (error) {
  notify(`Saved map could not be loaded: ${error.message} Inspection defaults are shown; existing browser data was not changed.`, true);
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

function connectionFor(id) {
  return inventory.connections[id] ?? emptyConnection();
}

function describeConnection(id) {
  const connection = connectionFor(id);
  return `${id}, ${occupancyLabels[connection.occupancy]}${connection.target ? ` · ${connection.target}` : ""}`;
}

function capturePopupContext() {
  const opener = document.activeElement;
  const map = document.querySelector(".map-scroll");
  return {
    opener,
    selector: opener.matches(".connector-item") ? `.connector-item[data-id="${opener.dataset.id}"]` : null,
    left: map.scrollLeft, top: map.scrollTop, pageLeft: scrollX, pageTop: scrollY,
  };
}

function openPopup(dialog, context = capturePopupContext()) {
  if (dialog.open) return;
  popupContexts.set(dialog, context);
  dialog.showModal();
  popupSheets.get(dialog)?.open();
}

function inspect(changeSelection) {
  const context = $("inspector-dialog").open ? null : capturePopupContext();
  changeSelection();
  renderSelection();
  $("inspector-title").textContent = selectedPartId ? sceneParts.get(selectedPartId).label : selectedId;
  if (!$("inspector-dialog").open) openPopup($("inspector-dialog"), context);
  metricUI?.refresh();
  $("inspector-dialog").querySelector(".popup-body").scrollTop = 0;
  $("close-inspector").focus({ preventScroll: true });
}

function requestPopupClose(dialog) {
  popupSheets.get(dialog)?.close();
}

for (const id of ["inspector-dialog", "tools-dialog", "metrics-dialog"]) {
  const dialog = $(id);
  popupSheets.set(dialog, createBottomSheet(dialog, () => dialog.close()));
  let backdropStart = false;
  const outside = event => {
    const bounds = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom);
  };
  dialog.addEventListener("pointerdown", event => { backdropStart = outside(event); });
  dialog.addEventListener("pointerup", event => {
    if (backdropStart && outside(event)) requestPopupClose(dialog);
    backdropStart = false;
  });
  dialog.addEventListener("cancel", event => {
    event.preventDefault();
    requestPopupClose(dialog);
  });
  dialog.addEventListener("close", () => {
    const context = popupContexts.get(dialog);
    popupContexts.delete(dialog);
    backdropStart = false;
    if (!context) return;
    const opener = context.opener.isConnected ? context.opener : document.querySelector(context.selector ?? "#tools-button");
    opener?.focus({ preventScroll: true });
    document.querySelector(".map-scroll").scrollTo(context.left, context.top);
    window.scrollTo(context.pageLeft, context.pageTop);
  });
}
$("close-inspector").addEventListener("click", () => requestPopupClose($("inspector-dialog")));
$("close-tools").addEventListener("click", () => requestPopupClose($("tools-dialog")));
$("tools-button").addEventListener("click", () => {
  $("tools-button").focus({ preventScroll: true });
  openPopup($("tools-dialog"));
});
function selectConnector(id) {
  if (!connectorById.has(id)) return;
  inspect(() => {
    selectedId = id;
    selectedPartId = null;
  });
}

function selectComponent(id) {
  if (!sceneParts.has(id) || connectorFocus()) return;
  inspect(() => { selectedPartId = id; });
}

function connectorFocus() {
  return focusMode === "connectors";
}

function matchesFocus(connector) {
  return activeCategory === "*" || connector.category === activeCategory;
}

function matchesPart(part) {
  const component = componentById.get(part.componentId);
  return matchesHardware({ ...part, model: component?.model ?? part.model }, activeCategory, "");
}

function interactiveGroup(className, id, label, onSelect) {
  const group = svgElement("g", { class: className, "data-id": id, role: "button", tabindex: "0", "aria-label": label });
  group.append(svgElement("title", {}, label));
  const activate = () => {
    if (group.getAttribute("aria-disabled") === "true") return;
    group.focus({ preventScroll: true });
    onSelect();
  };
  group.addEventListener("click", activate);
  group.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate();
    }
  });
  return group;
}

function hardwarePart(id, componentId, label, placement, connectorIds = [], extra = {}) {
  sceneParts.set(id, { id, componentId, label, placement, connectorIds, ...extra });
  return interactiveGroup("hardware-part", id, label, () => {
    if (connectorFocus()) return;
    selectComponent(id);
  });
}

function drawJumperCap(parent, connector) {
  const bounds = landscapeBounds(connector);
  const pair = inspectedJumpers[connector.id].split("-").map(Number);
  const pinX = number => bounds.x + bounds.width - (number - .5) * bounds.width / 3;
  const y = bounds.y + bounds.height - 8;
  parent.append(svgElement("rect", {
    x: Math.min(...pair.map(pinX)) - 3, y: y - 5,
    width: bounds.width / 3 + 6, height: 10, rx: 2, class: "jumper-cap",
    "data-jumper": connector.id, "data-pair": inspectedJumpers[connector.id],
  }));
  for (const number of [1, 2, 3]) {
    parent.append(svgElement("circle", { cx: pinX(number), cy: y, r: 1.8, class: "jumper-pin-dot", "data-pin": number }));
  }
}

function renderJumperConfigurations() {
  const current = pcie2ModeFor(inspectedJumpers.PE8_SEL, inspectedJumpers.PE16_SEL);
  $("jumper-current").textContent = `Current: PE8_SEL pins ${current.PE8_SEL.replace("-", "–")} · PE16_SEL pins ${current.PE16_SEL.replace("-", "–")} — ${current.label}`;
  const configurations = $("jumper-configurations");
  configurations.replaceChildren();
  for (const mode of pcie2Modes) {
    const installed = mode.id === current.id;
    const card = element("article", { class: `jumper-configuration${installed ? " current" : ""}`, "data-mode": mode.id });
    card.append(element("h5", {}, mode.label));
    if (installed) card.append(element("p", { class: "jumper-current-label" }, "Current arrangement"));
    for (const id of ["PE8_SEL", "PE16_SEL"]) {
      const row = element("div", { class: "jumper-pin-row" });
      row.append(element("span", {}, id));
      const pair = mode[id].split("-").map(Number);
      const pins = element("div", {
        class: "jumper-pins", role: "img", "aria-label": `${id}: cap bridges pins ${pair.join(" and ")}`,
        "data-jumper": id, "data-pair": mode[id],
      });
      for (const number of [1, 2, 3]) {
        const joined = pair.includes(number);
        const edge = number === pair[0] ? " bridge-start" : number === pair[1] ? " bridge-end" : "";
        pins.append(element("span", { class: `jumper-pin${joined ? ` bridged${edge}` : ""}`, "aria-hidden": "true" }, String(number)));
      }
      row.append(pins);
      card.append(row);
    }
    const resources = element("ul", { class: "jumper-resources" });
    for (const [name, enabled, description] of [
      ["PCIE2", mode.pcie2Lanes > 0, mode.pcie2Lanes ? `x${mode.pcie2Lanes}` : "Disabled"],
      ["M2_1", mode.m2, mode.m2 ? "Enabled" : "Disabled"],
      ["SATA_4_7", mode.sata, mode.sata ? "Enabled" : "Disabled"],
      ["OCU1 / OCU2", mode.oculink, mode.oculink ? "Enabled" : "Disabled"],
    ]) {
      resources.append(element("li", { class: enabled ? "enabled" : "disabled" }, `${name}: ${description}`));
    }
    card.append(resources);
    configurations.append(card);
  }
}

function drawFan(parent, x, y, size, redux = false, fraction = null) {
  const fan = svgElement("g", {
    class: `fan-face${redux ? " redux" : ""}`, "data-size": size,
    "data-center-x": x + size / 2, "data-center-y": y + size / 2, "aria-hidden": "true",
  });
  fan.append(svgElement("title", {}));
  fan.append(svgElement("rect", { x, y, width: size, height: size, rx: 5, class: "fan-frame" }));
  fan.append(svgElement("circle", { cx: x + size / 2, cy: y + size / 2, r: size * .43, class: "fan-ring" }));
  fan.append(svgElement("circle", { cx: x + size / 2, cy: y + size / 2, r: size * .42, class: "fan-motion-disc" }));
  fan.append(svgElement("g", { class: "fan-rotor" }), svgElement("g", { class: "fan-speed-lines" }));
  fan.append(svgElement("circle", { cx: x + size / 2, cy: y + size / 2, r: size * .15, class: "fan-hub" }));
  if (parent.dataset.id) fan.append(svgElement("text", { x: x + size / 2, y: y + size + 15, class: "fan-motion-caption centered" }));
  applyFanMotion(fan, fraction);
  parent.append(fan);
}

function applyFanMotion(fan, fraction) {
  const stage = fanMotionForSpeed(fraction);
  fan.dataset.motionStage = stage?.id ?? "unknown";
  fan.dataset.spinning = String(Boolean(stage?.period));
  fan.style.setProperty("--fan-period", `${stage?.period ?? 0}s`);
  fan.style.setProperty("--fan-blade-opacity", stage?.bladeOpacity ?? 1);
  const lines = fan.querySelector(".fan-speed-lines");
  lines.replaceChildren();
  const size = Number(fan.dataset.size);
  const cx = Number(fan.dataset.centerX);
  const cy = Number(fan.dataset.centerY);
  const x = cx - size / 2, y = cy - size / 2;
  const impressions = stage?.impressions ?? 6;
  const pitch = 360 / impressions;
  const point = (radius, angle) => `${cx + size * radius * Math.cos(angle * Math.PI / 180)} ${cy + size * radius * Math.sin(angle * Math.PI / 180)}`;
  const blade = stage?.impressions
    ? `M${point(.13, -90)} Q${point(.3, -90 - pitch * .6)} ${point(.42, -90 - pitch * .4)} A${size * .42} ${size * .42} 0 0 1 ${point(.42, -90 + pitch * .4)} Q${point(.3, -90 + pitch * .75)} ${point(.13, -90 + pitch * .4)} Z`
    : `M${x + size * .5} ${y + size * .49} Q${x + size * .07} ${y + size * .18} ${x + size * .45} ${y + size * .08} Q${x + size * .77} ${y + size * .09} ${x + size * .57} ${y + size * .48} Z`;
  const rotor = fan.querySelector(".fan-rotor");
  rotor.replaceChildren();
  for (let index = 0; index < impressions; index += 1) {
    rotor.append(svgElement("path", { d: blade, transform: `rotate(${index * pitch} ${cx} ${cy})`, class: "fan-blade" }));
  }
  fan.style.setProperty("--fan-disc-opacity", stage?.discOpacity ?? 0);
  fan.style.setProperty("--fan-line-opacity", stage?.impressions ? .28 : .72);
  for (let ring = 0; ring < (stage?.rings ?? 0); ring += 1) {
    const radius = size * .405;
    for (let segment = 0; segment < stage.segments; segment += 1) {
      const start = (segment * 360 / stage.segments - 90 - stage.sweep) * Math.PI / 180;
      const end = start + stage.sweep * Math.PI / 180;
      lines.append(svgElement("path", {
        d: `M${cx + Math.cos(start) * radius} ${cy + Math.sin(start) * radius} A${radius} ${radius} 0 0 1 ${cx + Math.cos(end) * radius} ${cy + Math.sin(end) * radius}`,
        class: "fan-speed-line",
      }));
    }
  }
  fan.querySelector("title").textContent = stage ? stage.label : "Speed unavailable";
  const caption = fan.querySelector(".fan-motion-caption");
  if (caption) caption.textContent = stage ? `DEMO · ${stage.label}` : "";
}

function renderCaseFanMotion() {
  document.documentElement.classList.toggle("fan-rotation-enabled", fanRotationEnabled);
  $("fan-rotation-toggle").setAttribute("aria-pressed", String(fanRotationEnabled));
  $("fan-rotation-toggle").textContent = `Fan motion: ${fanRotationEnabled ? "on" : "off"}`;
  $("fan-rotation-toggle").title = reducedMotion.matches && !fanRotationEnabled
    ? "Reduced motion is enabled. Turn on to animate fans for this session."
    : "Toggle animation without changing fan speeds";
  for (const [index, fan] of [...$("board").querySelectorAll(".fan-face")].entries()) {
    const rpm = index < 6 ? metricFanFrame?.hubRpm : metricFanFrame?.rearRpm;
    const stage = fanMotionForSpeed(Number.isFinite(rpm) ? rpm / (index < 6 ? 1700 : 2000) : null);
    if (fan.dataset.motionStage !== (stage?.id ?? "unknown")) applyFanMotion(fan, stage?.example ?? null);
    if (Number.isFinite(rpm)) {
      fan.dataset.rpm = rpm;
      fan.dataset.rpmSource = index < 6 ? metricFanFrame?.provenance === "live" ? "collected-shared-assumption" : "synthetic-shared-assumption" : "assumed-constant";
      const source = index < 6 ? metricFanFrame?.provenance === "live" ? "" : "DEMO " : "ASSUMED ";
      fan.querySelector("title").textContent = `${source}${Math.round(rpm)} RPM${index < 6 ? " · shared hub speed" : ""}`;
      fan.querySelector(".fan-motion-caption").textContent = "";
    } else {
      delete fan.dataset.rpm;
      delete fan.dataset.rpmSource;
    }
    const part = fan.closest(".hardware-part");
    const label = `${sceneParts.get(part.dataset.id).label}. ${fan.querySelector("title").textContent}`;
    part.setAttribute("aria-label", label);
    part.querySelector("title").textContent = label;
  }
}
$("fan-rotation-toggle").addEventListener("click", () => {
  fanRotationEnabled = !fanRotationEnabled;
  fanRotationOverride = true;
  renderCaseFanMotion();
});
reducedMotion.addEventListener("change", () => {
  if (!fanRotationOverride) fanRotationEnabled = !reducedMotion.matches;
  renderCaseFanMotion();
});

function renderBoard() {
  const board = $("board");
  board.replaceChildren();
  const enclosure = hardwarePart("chassis", null, "Rosewill RSV-L4500U", "Original top-view schematic informed by inspection photos. Case-part positions, proportions and component outlines are approximate, not measured.", [], {
    model: "Rosewill RSV-L4500U · 4U rack chassis", capacity: "15 HDD bays · 12 installed / 3 empty",
    status: "Chassis model user-reported; bay capacity and installed count user-confirmed",
    note: "Fan faces are unfolded for identification, not mounting angle. User confirms four HDDs plus the bottom bay empty in each front-view cage. Cage 1 uses HBA leads P1–P4 top-to-bottom; cage 2 uses SATA 4–7 leads 0–3; cage 3 uses SATA 0–3 leads 0–3, both top-to-bottom. Mounting clearances remain unmeasured.",
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
    if (connector.category === "Jumpers") {
      group.querySelector("text").setAttribute("y", y + 8);
      drawJumperCap(group, connector);
    }
    if (connector.category === "Fans") {
      for (let i = 0; i < 6; i += 1) {
        group.append(svgElement("circle", { cx: x + 7 + i * 10, cy: y + height - 2, r: 1, class: "header-pins" }));
      }
    }
    connectorLayer.append(group);
  }
  board.append(connectorLayer);

  const hardware = svgElement("g", { id: "installed-hardware" });
  const jumpers = hardwarePart("pcie2-jumpers", "board", "PCIE2 lane-selection jumpers", "Two three-pin jumpers beside AUX_PANEL1. Blue caps follow the installed photo arrangement; schematic positions are not measurements.", ["PE8_SEL", "PE16_SEL"], {
    model: "PE8_SEL (#27) + PE16_SEL (#26)", capacity: "PCIE2 x8 · M2_1 / SATA_4_7 enabled · OCuLink disabled",
  });
  for (const id of ["PE8_SEL", "PE16_SEL"]) {
    const connector = connectorById.get(id), bounds = landscapeBounds(connector);
    jumpers.append(svgElement("rect", { ...bounds, rx: 2, class: "jumper-base part-outline" }));
    jumpers.append(svgElement("text", { x: bounds.x + bounds.width / 2, y: bounds.y + 8, class: "hardware-label centered" }, connector.label));
    drawJumperCap(jumpers, connector);
  }
  hardware.append(jumpers);
  const network = hardwarePart("network-ports", "rear-io", "Network ports / Linux interfaces", "Rear connector locations follow the manual. Linux interface names are known, but their LAN1/LAN2 physical-port pairing remains unassigned.", ["LAN1", "LAN2", "IPMI_LAN1"]);
  for (const id of ["LAN1", "LAN2", "IPMI_LAN1"]) {
    const bounds = landscapeBounds(connectorById.get(id));
    network.append(svgElement("rect", { ...bounds, rx: 2, class: "nic-port part-outline" }));
    network.append(svgElement("text", { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 + 3, class: "hardware-label centered" }, id === "IPMI_LAN1" ? "BMC" : id));
  }
  hardware.append(network);
  const lan = hardwarePart("lan-controller", "rear-io", "Intel X550 / onboard LAN controller", "Original chip outline near PCIE5/PCIE6 follows the official motherboard layout; position and size are schematic. This is a controller reference, not a verified location for the BMC Onboard LAN Temp sensor package.", [], {
    model: "Intel X550 · onboard dual-port 10GbE controller", capacity: "Shared controller context, not per-port temperature",
    status: "Controller identified in official ROMED8-2T manual; exact thermal sensor implementation unverified",
    note: "The temperature badge references this controller rather than the RJ45 jacks. Physical LAN1/LAN2-to-Linux-interface pairing remains unassigned.",
  });
  lan.append(svgElement("rect", { x: 1260, y: 275, width: 42, height: 43, rx: 2, class: "lan-chip part-outline" }));
  lan.append(svgElement("text", { x: 1281, y: 300, class: "hardware-label centered" }, "X550"));
  hardware.append(lan);
  const disks = hardwarePart("disk-bays", "disks", "12 HDDs / 15 bays", "Three front-view cages are unfolded down the scene for visibility, not depicted in their physical mounting plane. User confirms four HDDs with the bottom bay empty in each cage.", driveCages.map(cage => cage.connectorId), {
    connectionNote: "Cage 1 → SAS 9300-8i, P1–P4 top-to-bottom; cage 2 → SATA 4–7, leads 0–3 top-to-bottom; cage 3 → SATA 0–3, leads 0–3 top-to-bottom. Separate SATA power harnesses from PSU S4/S5/S2 respectively. Four spare HBA SATA data ends have no drives or SATA power.",
  });
  const individualDisks = [];
  for (let cage = 0; cage < 3; cage += 1) {
    const routing = driveCages[cage];
    const y = 124 + cage * 196;
    disks.append(svgElement("rect", { x: 172, y, width: 231, height: 173, rx: 4, class: "drive-cage part-outline" }));
    disks.append(svgElement("text", { x: 173, y: y - 5, class: "scene-note" }, `CAGE ${routing.number} / ${routing.number === 1 ? "HBA" : routing.route}`));
    for (let bay = 0; bay < 5; bay += 1) {
      const drive = bay < 4 ? hardwarePart(`drive-cage-${cage + 1}-bay-${bay + 1}`, "disks", `Cage ${cage + 1} / bay ${bay + 1}`, "Physical disk identity is unverified unless a confirmed live binding is present; provisional serial-sorted identities are not physical observations.", [routing.connectorId], {
        connectionNote: `Cage ${routing.number}, bay ${bay + 1} (top-to-bottom) → ${routing.route}, cable lead ${routing.leads[bay]}. SATA power from PSU ${psuPorts.find(port => port.targetId === `cage-${routing.number}`).id}.`,
      }) : disks;
      drive.append(svgElement("rect", { x: 185, y: y + 15 + bay * 29, width: 205, height: 22, rx: 2, class: bay === 4 ? "drive-bay empty" : "drive-bay part-outline" }));
      if (bay < 4) {
        drive.append(svgElement("rect", { x: 193, y: y + 21 + bay * 29, width: 28, height: 10, class: "drive-label" }));
        drive.append(svgElement("circle", { cx: 379, cy: y + 26 + bay * 29, r: 2, class: "drive-screw" }));
        drive.append(svgElement("text", { x: 229, y: y + 30 + bay * 29, class: "disk-linux-label" }));
        drive.append(svgElement("text", { x: 351, y: y + 30 + bay * 29, class: "hardware-label" }, routing.leads[bay]));
        individualDisks.push(drive);
      }
    }
  }
  disks.append(svgElement("text", { x: 173, y: 738, class: "scene-heading" }, "12 HDDs / 15 BAYS"));
  disks.append(svgElement("text", { x: 173, y: 758, class: "scene-note" }, "BOTTOM BAY EMPTY IN EACH CAGE"));
  hardware.append(disks);
  hardware.append(...individualDisks);
  for (const [region, x] of [["front", 60], ["middle", 440]]) {
    for (let i = 0; i < 3; i += 1) {
      const id = `${region}-fan-${i + 1}`;
      const returnsTach = componentById.get("case-fans").tachPartId === id;
      const fan = hardwarePart(id, "case-fans", `${region === "front" ? "Front" : "Middle"} Noctua NF-P12 redux-1700 PWM ${i + 1} · ${returnsTach ? "FAN3 tach return" : "shared FAN3 hub"}`, `User confirms all six blow front to rear. ${returnsTach ? "This is the PSU-side middle fan supplying the hub's single tach return (user-confirmed 2026-11-13)." : "No individual RPM reading or hub-port assignment is known for this fan."} Positions are schematic and fan faces are unfolded, not a cable or measured airflow trace.`, ["FAN3"], returnsTach ? { readingId: "FAN3" } : {});
      drawFan(fan, x, 159 + i * 196, 94, true);
      hardware.append(fan);
    }
    hardware.append(svgElement("text", { x, y: 112, class: "scene-heading" }, region === "front" ? "3 FRONT" : "3 MIDDLE"));
    hardware.append(svgElement("text", { x, y: 716, class: "scene-note" }, "HUB / FAN3"));
  }

  const psu = hardwarePart("psu", "psu", "Corsair HX1000i", "Rear PSU region is photo-informed. Size, mounting offsets and clearance are approximate; modular port counts do not verify cable routing.", ["ATXPWR1", "ATX12V1"], {
    connectionNote: "MB18 + MB10 together feed ATXPWR1 (24-pin); C2 separately feeds ATX12V1 (EPS 8-pin). S1 powers the fan hub; S6 powers the rear-fan Molex harness. S3 and C3–C6 are empty. USB/iCUE is not connected.",
  });
  psu.append(svgElement("rect", { x: 1035, y: 650, width: 300, height: 115, rx: 5, class: "psu-body part-outline" }));
  for (let y = 665; y < 751; y += 7) psu.append(svgElement("path", { d: `M1250 ${y} H1315`, class: "psu-grille" }));
  psu.append(svgElement("text", { x: 1060, y: 698, class: "psu-label" }, "HX1000i"));
  psu.append(svgElement("text", { x: 1060, y: 723, class: "hardware-subtitle" }, "CORSAIR / PSU"));
  hardware.append(psu);
  const hub = hardwarePart("fan-hub", "fan-hub", "Thermalright fan hub / FAN3", "User places the hub between the motherboard and middle fan wall, near the case centerline and FAN1–FAN3. Outline and exact position are approximate, not a cable-routing diagram.", ["FAN3"], {
    connectionNote: "Dedicated SATA power harness from PSU S1; motherboard control/tach lead on FAN3. The hub returns one fan's tach.",
  });
  hub.append(svgElement("rect", { x: 672, y: 409, width: 113, height: 66, rx: 4, class: "psu-body part-outline" }));
  hub.append(svgElement("text", { x: 682, y: 435, class: "hardware-label" }, "PWM HUB"));
  hub.append(svgElement("text", { x: 682, y: 455, class: "hardware-subtitle" }, "6 FANS / 1 TACH"));
  hardware.append(hub);
  for (let i = 0; i < 2; i += 1) {
    const fan = hardwarePart(`rear-fan-${i + 1}`, "rear-fans", `Rear 80 mm fan ${i + 1} · Molex chain B`, "Rear bank is photo-informed; centers and mounting geometry are approximate. Width is specification-based plus user-confirmed factory-original fans, not photo-measured.", [], {
      connectionNote: "Shared Molex harness from PSU S6. No motherboard tach/control connection.",
    });
    drawFan(fan, 1314, 420 + i * 111, 63);
    hardware.append(fan);
  }
  hardware.append(svgElement("text", { x: 1304, y: 398, class: "scene-heading" }, "2 REAR"));

  for (const id of ["M2_2", "M2_1"]) {
    const connector = connectorById.get(id);
    const drive = hardwarePart(`drive-${id}`, null, `${id} / bare Samsung 2280`, "Drive direction follows inspection evidence: perpendicular to PCIe slots across PCIE6→PCIE2. Outline and GPU overhang are approximate; clearance is unmeasured.", [id], {
      model: "Samsung 990 EVO · MZ-V9E2T0 · bare 2280 SSD", capacity: "2 TB nominal per drive · no heatsink",
      status: "Installed labels and socket placements photo-confirmed",
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
    const dimm = hardwarePart(`dimm-${socket}`, "memory", `${socket} / Kingston 32 GB ECC DIMM`, "User confirms KSM32RD4/32HDR modules, 32 GB each, in A1/B1/G1/H1. Board positions follow the manual; module heights and appearance are schematic.", [socket]);
    dimm.append(svgElement("rect", { x, y: y - 4, width, height: height + 5, rx: 1, class: `dimm-body part-outline ${["DDR4_A1", "DDR4_H1"].includes(socket) ? "blue-slot" : ""}` }));
    for (let i = 0; i < 8; i += 1) {
      dimm.append(svgElement("rect", { x: x + 8 + i * 25, y: y - 1, width: 17, height: height - 1, class: "dimm-chip" }));
    }
    dimm.append(svgElement("text", { x: x - 8, y: y + 7, class: "dimm-label" }, socket.replace("DDR4_", "")));
    hardware.append(dimm);
  }

  const cpu = hardwarePart("cpu", "cpu", "EPYC 7313P / NH-U9 TR4-SP3", "CPU is beneath the cooler. Cooler silhouette is photo-inspired: silver fins, beige Noctua frames and brown corners. Outline, fan mounting and clearance are not measured.", ["CPU1", "FAN1", "FAN2", "ATX12V1"], {
    readingId: "cpu",
    connectionNote: "CPU power: PSU C2 → ATX12V1 (EPS 8-pin). MB18 + MB10 supply the motherboard's 24-pin ATX connector. Cooler fans connect to FAN1/FAN2.",
  });
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

  const gpu = hardwarePart("gpu", "gpu", "RTX 2070 SUPER / PCIE4", "PCIE4 placement and PCIE3/PCIE2 cooler obstruction are user-confirmed. Outline, exact footprint and M.2 clearance are unmeasured.", ["PCIE4", "PCIE3", "PCIE2"], {
    readingId: "gpu",
    connectionNote: "Auxiliary GPU power comes directly from PSU C1. The motherboard's separate GFX_12V1 connector is empty.",
  });
  const gpuSlot = landscapeBounds(connectorById.get("PCIE4"));
  const gpuTop = landscapeBounds(connectorById.get("PCIE2")).y - 4;
  gpu.append(svgElement("rect", { x: 872, y: gpuTop, width: 418, height: gpuSlot.y + gpuSlot.height - gpuTop + 5, rx: 4, class: "gpu-body part-outline" }));
  gpu.append(svgElement("path", { d: `M882 ${gpuTop + 10} H1050 L1085 ${gpuTop + 45} H1280`, class: "gpu-trim" }));
  gpu.append(svgElement("text", { x: 913, y: gpuTop + 26, class: "hardware-label" }, "GIGABYTE / RTX 2070 SUPER"));
  gpu.append(svgElement("text", { x: 913, y: gpuTop + 45, class: "hardware-subtitle" }, "PCIE4 · PCIE3/2 COVERED · M.2 OVERHANG"));
  hardware.append(gpu);
  const hba = hardwarePart("hba", "hba", "SAS 9300-8i / PCIE1", "Model, PCIE1 placement and cage 1 routing are user-confirmed. Outline, spacing and airflow impact are not measurements.", ["PCIE1", "HBA_DATA"], {
    connectionNote: "Cage 1 uses breakout leads P1, P2, P3, P4 top-to-bottom. The second breakout has four spare SATA data ends with no drives or SATA power.",
  });
  const hbaSlot = landscapeBounds(connectorById.get("PCIE1"));
  hba.append(svgElement("rect", { x: 1042, y: hbaSlot.y - 9, width: 248, height: 34, rx: 2, class: "hba-body part-outline" }));
  for (const y of [hbaSlot.y - 5, hbaSlot.y + 10]) {
    hba.append(svgElement("rect", { x: 1044, y, width: 21, height: 10, rx: 1, class: "hba-connector" }));
  }
  hba.append(svgElement("rect", { x: 1076, y: hbaSlot.y - 5, width: 65, height: 26, rx: 1, class: "hba-heatsink" }));
  for (let x = 1082; x < 1138; x += 5) hba.append(svgElement("path", { d: `M${x} ${hbaSlot.y - 3} v22`, class: "hba-fin" }));
  hba.append(svgElement("text", { x: 1152, y: hbaSlot.y + 12, class: "hardware-label" }, "9300-8i / PCIE1"));
  hardware.append(hba);
  board.append(hardware);
  const scene = svgElement("g", { id: "server-scene" });
  scene.append(...board.childNodes);
  board.append(scene);
}

function renderList() {
  const filtered = connectors.filter(matchesFocus);
  const list = $("connector-list");
  const scrollTop = list.scrollTop;
  $("connector-picker").hidden = !connectorFocus();
  list.replaceChildren();
  for (const connector of filtered) {
    const button = element("button", {
      type: "button", class: `connector-item${!selectedPartId && connector.id === selectedId ? " selected" : ""}`,
      "data-id": connector.id, "aria-pressed": String(!selectedPartId && connector.id === selectedId),
      "aria-label": describeConnection(connector.id),
    });
    button.append(element("i", { class: `legend-dot ${connectionFor(connector.id).occupancy}`, "aria-hidden": "true" }));
    button.append(element("span", {}, connector.id));
    button.append(element("span", { class: "list-category" }, connector.category));
    button.addEventListener("click", () => {
      button.focus({ preventScroll: true });
      selectConnector(connector.id);
    });
    list.append(button);
  }
  if (!filtered.length) list.append(element("p", { class: "empty-list" }, "No matching connectors."));
  list.scrollTop = scrollTop;
}

function renderFocus() {
  const focused = connectorFocus();
  $("board").classList.toggle("connector-focus", focused);
  for (const button of $("focus-modes").children) {
    const active = button.dataset.mode === focusMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  for (const button of $("categories").children) {
    const active = button.dataset.category === activeCategory;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  for (const group of $("board").querySelectorAll(".hardware-part")) {
    const available = !focused && matchesPart(sceneParts.get(group.dataset.id));
    group.setAttribute("tabindex", available ? "0" : "-1");
    group.setAttribute("aria-disabled", String(!available));
    group.classList.toggle("selected", group.dataset.id === selectedPartId);
    group.setAttribute("aria-pressed", String(group.dataset.id === selectedPartId));
  }
  for (const group of $("board").querySelectorAll(".connector")) {
    const available = focused && matchesFocus(connectorById.get(group.dataset.id));
    group.classList.toggle("out-of-focus", focused ? !available : activeCategory !== "*");
    group.setAttribute("aria-disabled", String(!available));
    group.setAttribute("tabindex", available ? "0" : "-1");
  }
  $("focus-status").textContent = focused
    ? `${connectors.filter(matchesFocus).length} / ${connectors.length} connectors shown · hardware dimmed and disabled; outlines do not verify physical access.`
    : `${[...sceneParts.values()].filter(matchesPart).length} / ${sceneParts.size} hardware parts shown · click a matching component for details. Switch to Connectors to inspect motherboard headers.`;
  renderList();
  metricUI?.updateVisibility();
}

function appendReferences(container, references) {
  for (const reference of references) {
    const row = element("p", { class: "compact" });
    row.append(element("a", { href: reference.url, target: "_blank", rel: "noopener noreferrer" }, reference.label));
    container.append(row);
  }
}

function renderComponentDetails() {
  const part = sceneParts.get(selectedPartId);
  const component = { ...(componentById.get(part.componentId) ?? {}), ...part };
  $("component-name").textContent = part.label;
  $("component-model").textContent = component.model;
  $("component-capacity").textContent = component.capacity;
  $("component-connection-note").hidden = !part.connectionNote;
  $("component-connection-note").textContent = part.connectionNote ?? "";
  const portMap = $("component-port-map");
  portMap.hidden = selectedPartId !== "psu";
  $("component-port-rows").replaceChildren();
  if (!portMap.hidden) {
    for (const port of psuPorts) {
      const row = element("tr", { "data-port-id": port.id });
      row.append(element("th", { scope: "row" }, port.id),
        element("td", {}, `${port.group} · ${port.position}`),
        element("td", {}, port.target));
      $("component-port-rows").append(row);
    }
  }
  const binding = dataSource.snapshot?.inventory?.disks?.find(disk => disk.id === part.bindingId);
  $("component-identifiers").hidden = !binding;
  $("component-identifiers").textContent = binding ? `Display slot mapping · Serial: ${binding.serial ?? "unavailable"}` : "";
  renderLinuxAssociation(selectedPartId);
  $("component-metrics-button").hidden = !metricUI?.panelFor(selectedPartId);
  metricUI?.renderComponent(selectedPartId, part.bindingId);
  $("component-reference-links").replaceChildren();
  appendReferences($("component-reference-links"), partReferences[part.componentId ?? selectedPartId] ?? []);
  $("component-connectors").replaceChildren();
  for (const id of part.connectorIds) {
    const button = element("button", { type: "button" }, id);
    button.addEventListener("click", () => selectConnector(id));
    $("component-connectors").append(button);
  }
  if (!part.connectorIds.length) {
    $("component-connectors").append(element("p", { class: "compact muted" },
      part.componentId === "rear-fans"
        ? "Reported PSU/Molex power only; no motherboard tach or control connection."
        : "No connector assigned"));
  }
}

function linuxNodeButton(id, label = linuxTopology.nodes.get(id).label) {
  const button = element("button", { type: "button", "data-linux-node": id }, label);
  button.addEventListener("click", () => renderLinuxNode(id));
  return button;
}

function linuxCapacity(node) {
  const tib = bytes => `${(bytes / 2 ** 40).toLocaleString(undefined, { maximumFractionDigits: 2 })} TiB`;
  if (!Number.isFinite(node.sizeBytes)) return "";
  return node.usedBytes === undefined ? tib(node.sizeBytes) : `${tib(node.usedBytes)} used / ${tib(node.sizeBytes)} total`;
}

function renderLinuxNode(id) {
  const node = linuxTopology.nodes.get(id);
  if (!$("linux-list").hidden) linuxReturnId = id;
  $("linux-list").hidden = true;
  const detail = $("linux-node");
  detail.hidden = false;
  detail.replaceChildren();
  const back = element("button", { type: "button" }, "← Back to this part's Linux devices");
  back.addEventListener("click", () => {
    detail.hidden = true;
    $("linux-list").hidden = false;
    const buttons = [...$("linux-list").querySelectorAll("button")];
    (buttons.find(button => button.dataset.linuxNode === linuxReturnId) ?? buttons[0])?.focus();
  });
  const heading = element("h4", { tabindex: "-1" }, node.label);
  detail.append(back, heading, element("p", { class: "compact" }, `${node.kind}${node.model ? ` · ${node.model}` : ""}${node.sizeBytes ? ` · ${linuxCapacity(node)}` : ""}`));
  detail.append(element("p", { class: "reading-note" }, linuxNodeSummary(linuxTopology, id)));
  if (node.aliases?.length) detail.append(element("p", { class: "compact" }, `Same Linux object / aliases: ${node.aliases.join(", ")}`));
  if (node.summary && node.summary !== linuxNodeSummary(linuxTopology, id)) detail.append(element("p", { class: "compact muted" }, node.summary));
  const relationships = [
    ["Underlying / associated objects", node.parents],
    ["Used by / represented as", [...linuxTopology.nodes.values()].flatMap(child =>
      child.parents.filter(parent => parent.id === id).map(parent => ({ id: child.id, relation: parent.relation })),
    )],
  ];
  for (const [label, links] of relationships) {
    if (!links.length) continue;
    detail.append(element("h4", {}, label));
    const list = element("ul", { class: "linux-relationships" });
    for (const link of links) {
      const row = element("li");
      row.append(linuxNodeButton(link.id), element("span", { class: "compact muted" }, link.relation));
      list.append(row);
    }
    detail.append(list);
  }
  heading.focus();
}

function renderLinuxAssociation(target) {
  const snapshot = linuxTopology.snapshot;
  const association = snapshot.associations.find(entry => entry.targets.includes(target));
  $("linux-details").hidden = !association;
  if (!association) return;
  const host = selectedPartId ? $("component-details") : $("connector-details");
  host.insertBefore($("linux-details"), selectedPartId ? $("component-reference-links").closest(".reference") : $("pin-section"));
  $("linux-node").hidden = true;
  const list = $("linux-list");
  list.hidden = false;
  list.replaceChildren();
  const table = element("table");
  const head = element("thead"), headings = element("tr");
  headings.append(element("th", {}, "Linux object"), element("th", {}, "Role / representation"));
  head.append(headings);
  const body = element("tbody");
  for (const id of association.nodes) {
    const row = element("tr"), name = element("td"), info = element("td");
    const node = linuxTopology.nodes.get(id);
    name.append(linuxNodeButton(id));
    info.textContent = `${linuxNodeSummary(linuxTopology, id)}${node.sizeBytes ? ` · ${linuxCapacity(node)}` : ""}`;
    row.append(name, info);
    body.append(row);
  }
  table.append(head, body);
  list.append(table);
  if (association.nodes.some(id => linuxTopology.nodes.get(id).memberships.length)) {
    for (const raid of snapshot.raids) list.append(linuxNodeButton(raid.id, `${linuxTopology.nodes.get(raid.id).label} · ${linuxNodeSummary(linuxTopology, raid.id)}`));
    if (linuxTopology.nodes.has("data-filesystem")) list.append(linuxNodeButton("data-filesystem", "/data · explore LVM / cache / backing devices"));
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
  const counts = occupancyCounts(inventory);
  for (const occupancy of Object.keys(occupancyLabels)) {
    $(`${occupancy}-count`).textContent = counts[occupancy];
  }
  $("component-details").hidden = !selectedPartId;
  $("connector-details").hidden = Boolean(selectedPartId);
  $("jumper-section").hidden = selectedPartId
    ? selectedPartId !== "pcie2-jumpers"
    : !Object.hasOwn(inspectedJumpers, selectedId);
  if (!$("jumper-section").hidden) renderJumperConfigurations();
  if (selectedPartId) {
    renderComponentDetails();
    return;
  }
  renderLinuxAssociation(selectedId);
  $("detail-category").textContent = `${connector.category.toUpperCase()} / SELECTED CONNECTOR`;
  $("detail-name").textContent = connector.id;
  $("detail-occupancy").className = `badge ${connection.occupancy}`;
  $("detail-occupancy").textContent = occupancyLabels[connection.occupancy];
  $("detail-description").textContent = connector.detail;
  $("connection-target").textContent = connection.target || occupancyLabels[connection.occupancy];
  $("pin-section").hidden = connector.pins.length === 0;
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
}

window.addEventListener("storage", event => {
  if (event.key === storageKey || event.key === null) {
    try {
      inventory = withInspectionDefaults(loadDocument(window.localStorage));
      renderSelection();
    } catch (error) {
      notify(`Saved map update could not be loaded: ${error.message} Previous view retained; browser data was not changed.`, true);
    }
  }
});
function renderCategories() {
  const focused = connectorFocus();
  const categories = focused
    ? [...new Set(connectors.map(connector => connector.category))]
    : Object.keys(hardwareCategories);
  $("categories").replaceChildren();
  $("categories").setAttribute("aria-label", focused ? "Connector categories" : "Hardware categories");
  $("connector-picker").open = false;
  for (const category of ["*", ...categories]) {
    const label = category === "*" ? focused ? "All connectors" : "All hardware" : category;
    const button = element("button", { type: "button", "data-category": category, "aria-pressed": "false" }, label);
    button.addEventListener("click", () => {
      activeCategory = category;
      renderFocus();
    });
    $("categories").append(button);
  }
}
for (const button of $("focus-modes").children) {
  button.addEventListener("click", () => {
    focusMode = button.dataset.mode;
    activeCategory = "*";
    renderCategories();
    renderFocus();
  });
}
renderCategories();
$("board-revision").textContent = `ROMED8-2T · REV ${boardRevision}`;
function setZoom(next) {
  zoom = Math.max(75, Math.min(175, next));
  $("board").style.width = `${zoom}%`;
  $("board").style.height = `${zoom}%`;
  $("zoom-label").textContent = `${zoom}%`;
  $("zoom-out").disabled = zoom === 75;
  $("zoom-in").disabled = zoom === 175;
  metricUI?.layout();
}
$("zoom-in").addEventListener("click", () => setZoom(zoom + 25));
$("zoom-out").addEventListener("click", () => setZoom(zoom - 25));

for (const component of components) {
  const card = element("article", { class: "inventory-card" });
  card.append(element("h4", {}, component.label), element("p", {}, component.model), element("strong", {}, component.capacity));
  $("inventory-grid").append(card);
}
renderBoard();
const portraitMap = matchMedia("(orientation: portrait)");
function orientMap() {
  $("board").setAttribute("viewBox", portraitMap.matches ? "0 0 840 1440" : "0 0 1440 840");
  $("server-scene").setAttribute("transform", portraitMap.matches ? "translate(840 0) rotate(90)" : "");
  $("board-view").classList.toggle("portrait-map", portraitMap.matches);
  metricUI?.layout();
}
portraitMap.addEventListener("change", orientMap);
orientMap();
let appliedSnapshot = null;
function applyCollectedInventory(data) {
  if (!data || data === appliedSnapshot) return;
  applyLiveSnapshot(data);
  if (data.inventory?.snapshot) linuxTopology = buildLinuxTopology(data.inventory.snapshot);
  const bindings = data.inventory?.disks ?? [];
  for (const [id, part] of sceneParts) {
    if (!part.bindingId || bindings.some(binding => `drive-${binding.slot}` === id)) continue;
    part.bindingId = undefined;
    part.label = `${id.slice(6)} · current inventory unavailable`;
    part.status = "No current disk observed for this reserved slot; not proof of physical removal.";
    part.note = "The persisted slot reservation is retained. No previous device identity is substituted for missing inventory.";
    part.model = "Unavailable";
    part.capacity = "Unavailable";
    const node = $("board").querySelector(`.hardware-part[data-id="${id}"]`);
    node?.setAttribute("aria-label", part.label);
    const label = node?.querySelector(".disk-linux-label");
    if (label) label.textContent = "Not observed";
  }
  for (const binding of bindings) {
    if (!binding.slot) continue;
    const id = `drive-${binding.slot}`, part = sceneParts.get(id);
    if (!part) continue;
    part.label = `${binding.slot} · /dev/${binding.id}`;
    part.bindingId = binding.id;
    part.model = binding.model;
    part.capacity = `${(binding.sizeBytes / 2 ** 40).toFixed(2)} TiB`;
    const confirmed = binding.mapping === "confirmed";
    part.status = confirmed ? "Physical placement confirmed" : "PROVISIONAL · serial-sorted assignment, NOT physically verified";
    part.note = `Serial: ${binding.serial ?? "unavailable"}. Stable identity: ${binding.stableId ?? "unavailable"}. This private mapping persists across Linux device renumbering. ${confirmed ? "Installed-label inspection establishes this placement, not individual cable routing." : "Correct it after physical inspection; do not infer cabling from this placeholder."}`;
    const node = $("board").querySelector(`.hardware-part[data-id="${id}"]`);
    node?.setAttribute("aria-label", part.label);
    const label = node?.querySelector(".disk-linux-label");
    const disk = linuxTopology.nodes.get(binding.id);
    if (label) label.textContent = `/dev/${binding.id}${confirmed ? "" : " *"}${disk?.memberships?.some(member => member.state.includes("spare")) ? " · SPARE" : ""}`;
  }
  appliedSnapshot = data;
  if ($("inspector-dialog").open) renderSelection();
}
if (dataSource.mode === "live") {
  await dataSource.poll();
  applyCollectedInventory(dataSource.snapshot);
  dataSource.subscribe(applyCollectedInventory);
}
metricUI = createMetricUI({
  dataSource,
  openPopup, closePopup: requestPopupClose, onError: message => notify(message, true),
  onFanFrame: frame => {
    metricFanFrame = frame;
    renderCaseFanMotion();
  },
  isVisible: id => !connectorFocus() && (id === null || (id === "nvme-group"
    ? ["drive-M2_1", "drive-M2_2"].some(part => document.querySelector(`.hardware-part[data-id="${part}"][aria-disabled="false"]`))
    : Boolean(document.querySelector(`.hardware-part[data-id="${id}"][aria-disabled="false"]`)))),
});
dataSource.start();
$("component-metrics-button").addEventListener("click", () => metricUI.openComponent(selectedPartId, sceneParts.get(selectedPartId)?.bindingId));
renderCaseFanMotion();
renderSelection();
document.documentElement.dataset.ready = "true";
