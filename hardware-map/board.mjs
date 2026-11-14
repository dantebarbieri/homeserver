export const manual = Object.freeze({
  title: "ASRock Rack ROMED8-2T / ROMED8-NL / ROMED8-2T/BCM",
  url: "https://download.asrock.com/Manual/ROMED8-2T.pdf",
  revision: "1.30",
  published: "April 2026",
  sha256: "9ccde5548e447d1e74408a2bfe246450d8291c10bb250fc178df0e310775a613",
});

export const boardId = "asrock-rack-romed8-2t";
export const snapshotDate = "2026-11-12";
export const boardRevision = "1.03";
export const provenanceLabels = {
  "photo-confirmed": "Photo-confirmed",
  "photo-inferred": "Photo-inferred",
  "photo-uncertain": "Photo observation — uncertain",
  "user-confirmed": "Confirmed",
  "user-reported": "Confirmed",
  "user-annotation": "Local user annotation",
  unverified: "Unverified",
};
export const layoutSource = "Official manual rev. 1.30, printed pp. 7–8 (PDF pp. 14–15).";
export const occupancyLabels = { occupied: "Connected", free: "Empty", blocked: "Blocked", unverified: "Unverified" };
const fanPins = [
  { number: 1, signal: "GND", description: "Ground" },
  { number: 2, signal: "FAN_VOLTAGE", description: "Fan power" },
  { number: 3, signal: "FAN_SPEED_SENSOR1", description: "Primary tachometer input" },
  { number: 4, signal: "FAN_SPEED_CONTROL", description: "Speed-control signal" },
  { number: 5, signal: "FAN_SPEED_SENSOR2", description: "Secondary tachometer input" },
  { number: 6, signal: "NC", description: "Not connected" },
];

function connector(id, label, category, x, y, width, height, detail, extra = {}) {
  return { id, label, category, x, y, width, height, detail, source: layoutSource, pins: [], ...extra };
}

export const connectors = [
  connector("CPU1", "SP3 / CPU", "Compute", 235, 180, 240, 155,
    "AMD EPYC 7313P with Noctua NH-U9 TR4-SP3 cooler. Original cooler fans use FAN1/FAN2; airflow runs from the PSU side toward the GPU side."),
  ...["H", "G", "F", "E"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 65 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. Population: 32 GB Kingston KSM32RD4/32HDR modules in A1/B1/G1/H1; C1/D1/E1/F1 empty. 128 GB total system memory.")),
  ...["A", "B", "C", "D"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 370 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. Population: 32 GB Kingston KSM32RD4/32HDR modules in A1/B1/G1/H1; C1/D1/E1/F1 empty. Do not infer population from BMC temperature-channel labels.")),
  connector("ATX12V1", "EPS 8-pin", "Power", 565, 65, 75, 35,
    "8-pin ATX 12 V / EPS motherboard connector. Occupied in IMG_4538; it is not a GPU PCIe power socket.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("ATX12V2", "ATX 4-pin", "Power", 650, 65, 65, 35,
    "4-pin ATX 12 V motherboard connector. Empty in IMG_4538. This schematic is not an instruction to add or change a power cable.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("ATXPWR1", "ATX 24-pin", "Power", 565, 115, 150, 35,
    "24-pin motherboard power connector. No PSU cable or modular-PSU pinout is implied.",
    { source: "Official manual rev. 1.30, printed p. 30 (PDF p. 37)." }),
  connector("GFX_12V1", "GFX 6-pin", "Power", 615, 832, 96, 25,
    "6-pin motherboard graphics 12 V connector, empty. This is not the GPU card's own power socket or a modular PSU pinout.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("USB3_3_4", "Front USB 3", "Front panel", 570, 180, 140, 27,
    "19-pin USB 3.2 Gen 1 front-panel header. The case front USB cable is connected here."),
  ...Array.from({ length: 7 }, (_, i) =>
    connector(`FAN${i + 1}`, `FAN${i + 1}`, "Fans", 615, i < 3 ? 345 + i * 34 : 665 + (i - 3) * 34, 96, 29,
      "Six-pin fan header, not a standard four-pin header. Primary and secondary tach inputs can appear as FANn and FANn_2 in IPMI. An RPM reading does not identify the attached fan.",
      {
        pins: fanPins,
        location: i < 3
          ? `Right edge, upper group near the lower DIMM bank and OCuLink: ${["top", "middle", "bottom"][i]} header (FAN${i + 1}).`
          : `Right edge, lower group below SATA_4_7: position ${i - 2} of 4, counting from top to bottom (FAN${i + 1}).`,
        source: "Official manual rev. 1.30, printed p. 30 (PDF p. 37).",
        caution: "The two housing bars follow the manual's drawing; its text does not identify them as keying. Physical keying, pin-1 orientation and the cable mating-side view remain unverified. Check the actual header before connecting anything. Do not shift a plug onto pins 3–6 or force a connector.",
      })),
  connector("M2_2", "M2_2", "Storage", 420, 480, 90, 26,
    "M.2 socket right of PCIE7's end. The installed bare Samsung 2280 drive runs perpendicular to the PCIe slots across the PCIE6→PCIE2 rows. Logical NVMe A/B identity is still unknown."),
  connector("M2_1", "M2_1", "Storage", 520, 480, 90, 26,
    "M.2 socket right of PCIE7's end. The bare Samsung 2280 drive runs across the PCIE6→PCIE2 rows, beneath the GPU shroud overhang. Shares configurable resources with PCIE2 / SATA_4_7 / OCuLink; do not change jumpers."),
  connector("SATA_0_3", "SATA 0–3", "Storage", 615, 500, 96, 36,
    "Mini-SAS HD connector for four SATA data links via breakout cable. Cage 3 uses leads 0, 1, 2, 3 from top to bottom. These are cable labels, not Linux device names.",
    { source: "Official manual rev. 1.30, printed p. 29 (PDF p. 36)." }),
  connector("SATA_4_7", "SATA 4–7", "Storage", 615, 590, 96, 36,
    "Mini-SAS HD connector for four SATA links to cage 2. Its leads are labeled 0, 1, 2, 3 from top to bottom. The photographed PE8_SEL 1–2 / PE16_SEL 2–3 arrangement enables SATA_4_7 and M2_1.",
    { source: "Official manual rev. 1.30, printed pp. 26, 29 (PDF pp. 33, 36)." }),
  connector("HBA_DATA", "HBA SAS", "Storage", 322, 765, 96, 42,
    "Logical group of the SAS 9300-8i's two internal SFF-8643 connectors, NOT a motherboard header. Cage 1 uses breakout leads P1, P2, P3, P4 from top to bottom; the other breakout has four spare SATA data ends with no drives or accompanying SATA power. Which socket serves which breakout is untraced. P1–P4 are lead labels, not HBA socket numbers.",
    { source: "Installed cage routing; schematic position does not identify individual HBA sockets." }),
  ...Array.from({ length: 7 }, (_, i) => {
    const number = 7 - i;
    return connector(`PCIE${number}`, `PCIE${number}`, "Expansion", 145, 475 + i * 49, 245, 29,
      `CPU-connected PCIe 4.0 x16 expansion slot; actual negotiated speed/width is not measured here. PCIE7 is nearest the CPU/DIMMs; PCIE1 is at the bottom board edge.${number === 2 ? " The photographed PE8_SEL 1–2 / PE16_SEL 2–3 arrangement allocates x8 to PCIE2 and enables M2_1/SATA_4_7." : ""}`);
  }),
  connector("PE8_SEL", "PE8", "Jumpers", 380, 845, 30, 48,
    "Board-layout item 27: PCIE2 x8 selection jumper. Current cap bridges pins 1–2. Its setting works together with PE16_SEL; inspect both before interpreting lane allocation.",
    { source: "Official manual rev. 1.30, printed pp. 7–8, 26 (PDF pp. 14–15, 33); installed cap position is a photo/manual interpretation." }),
  connector("PE16_SEL", "PE16", "Jumpers", 415, 845, 30, 48,
    "Board-layout item 26: PCIE2 x16 selection jumper. Current cap bridges pins 2–3. Its setting works together with PE8_SEL; this is not an AUX_PANEL1 connection.",
    { source: "Official manual rev. 1.30, printed pp. 7–8, 26 (PDF pp. 14–15, 33); installed cap position is a photo/manual interpretation." }),
  connector("OCU1", "OCU1", "Storage", 515, 370, 90, 28,
    "OCuLink connector, empty. Disabled by the photographed PE8_SEL 1–2 / PE16_SEL 2–3 arrangement."),
  connector("OCU2", "OCU2", "Storage", 515, 410, 90, 28,
    "OCuLink connector, empty. Disabled by the photographed PE8_SEL 1–2 / PE16_SEL 2–3 arrangement."),
  connector("PANEL1", "PANEL1", "Front panel", 600, 865, 110, 28,
    "System front-panel header. IMG_4570 shows attached switch/LED leads, including a readable POWER SW plug. Individual lead polarity is not modeled.",
    { source: "Official manual rev. 1.30, printed p. 28 (PDF p. 35)." }),
  connector("AUX_PANEL1", "AUX PANEL", "Front panel", 450, 865, 135, 28,
    "18-pin auxiliary front-panel header, empty. The neighboring blue caps are separate configuration jumpers, including PE8_SEL and PE16_SEL, not AUX_PANEL1 connections.",
    { source: "Official manual rev. 1.30, printed pp. 7–8, 26, 29 (PDF pp. 14–15, 33, 36); private inspection photos IMG_4561–4563." }),
  connector("TR1", "TR1", "Sensors", 330, 865, 45, 28,
    "Thermal sensor header. No separate temperature probe is connected.",
    { source: "Official manual rev. 1.30, printed p. 32 (PDF p. 39)." }),
  connector("TR2", "TR2", "Sensors", 260, 865, 45, 28,
    "Thermal sensor header. No separate temperature probe is connected.",
    { source: "Official manual rev. 1.30, printed p. 32 (PDF p. 39)." }),
  connector("PSU_SMB1", "PSU SMB", "Sensors", 565, 20, 100, 25,
    "PSU SMBus header, empty. This is separate from the PSU's USB/iCUE connector."),
  connector("REAR_OTHER", "VGA/COM/USB", "Rear I/O", 35, 186, 86, 44,
    "Logical group of other rear I/O ports, not a motherboard header identifier. Nothing is connected here; rear power refers to the PSU inlet, not these ports."),
  connector("IPMI_LAN1", "BMC LAN", "Rear I/O", 35, 247, 86, 44,
    "Dedicated BMC Ethernet port, connected to the switch."),
  connector("LAN1", "10G LAN1", "Rear I/O", 35, 308, 86, 44,
    "First onboard 10 GbE port, connected to the switch."),
  connector("LAN2", "10G LAN2", "Rear I/O", 35, 369, 86, 44,
    "Second onboard 10 GbE port, connected to the switch."),
];

export const connectorById = new Map(connectors.map(item => [item.id, item]));

// Rotate the manual-oriented geometry 180 degrees into a front-left/rear-right chassis.
// Unequal schematic scales reserve room for readable labels; these are not dimensions.
export function landscapeBounds({ x, y, width, height }) {
  return { x: 1345 - (x + width) * .72, y: 635 - (y + height) * .6, width: width * .72, height: height * .6 };
}

function observation(target, confidence, occupancy, provenance, evidence, note = "", evidenceDate = snapshotDate) {
  return { target, confidence, occupancy, provenance, evidence: `${evidenceDate}: ${evidence}`, note, updatedAt: null };
}

export const inspectionConnections = {
  CPU1: observation("AMD EPYC 7313P beneath NH-U9 TR4-SP3", "confirmed", "occupied", "photo-confirmed",
    "Cleaning photos show the cooler mounted over the board's sole SP3 socket. CPU model comes from the earlier supplied read-only inventory, not a visible processor label.",
    "The cooler retains its original fan pair; no cooler removal or new server query was performed.", "2026-11-13"),
  ...Object.fromEntries(["M2_1", "M2_2"].map(id => [
    id, observation("Samsung 990 EVO 2 TB · MZ-V9E2T0B; logical A/B identity unknown", "confirmed", "occupied", "photo-confirmed",
      "Both sockets contain Samsung 990 EVO 2 TB drives without heatsinks, perpendicular to the PCIe slots across PCIE6→PCIE2.",
      "GPU overhang and its few-mm gap are photo observations, NOT measured heatsink-clearance allowances.", "2026-11-13"),
  ])),
  SATA_0_3: observation("Cage 3 · four HDDs", "confirmed", "occupied", "user-confirmed",
    "SATA 0–3 serve cage 3; cable leads 0–3 run top-to-bottom.",
    "Bay 1 → lead 0; bay 2 → lead 1; bay 3 → lead 2; bay 4 → lead 3. Cable labels are not Linux device names.", "2026-11-13"),
  SATA_4_7: observation("Cage 2 · four HDDs", "confirmed", "occupied", "user-confirmed",
    "SATA 4–7 serve cage 2; this cable's leads are also labeled 0–3, top-to-bottom.",
    "Bay 1 → lead 0; bay 2 → lead 1; bay 3 → lead 2; bay 4 → lead 3. Preserve the printed cable labels, not an invented 4–7 lead numbering.", "2026-11-13"),
  HBA_DATA: observation("Cage 1 · four HDDs; four spare SATA data ends", "confirmed", "occupied", "user-confirmed",
    "Cage 1 uses HBA breakout leads P1–P4 in ascending order top-to-bottom, plus a second set of four unconnected SATA data cables with no accompanying drives or SATA power.",
    "Bay 1 → P1; bay 2 → P2; bay 3 → P3; bay 4 → P4. This groups both HBA sockets; socket-to-breakout assignment remains untraced. Spare cables do not represent installed drives.", "2026-11-13"),
  GFX_12V1: observation("", "confirmed", "free", "user-confirmed",
    "The motherboard GFX_12V1 six-pin socket is empty.",
    "This is distinct from the power sockets on the GPU card.", "2026-11-13"),
  ...Object.fromEntries(["ATXPWR1", "ATX12V1"].map(id => [
    id, observation(id === "ATXPWR1" ? "PSU 24-pin ATX cable" : "PSU EPS 8-pin cable", "confirmed", "occupied", "photo-confirmed",
      "The motherboard 24-pin and EPS 8-pin sockets are occupied.",
      id === "ATXPWR1"
        ? "The PSU-side MB18 + MB10 pair is the split end of this main ATX cable; it does not supply the EPS 8-pin connector."
        : "Separate PSU PCIe/CPU socket C2 supplies this EPS 8-pin cable. This is not a branch of the MB18 + MB10 ATX cable.", "2026-11-13"),
  ])),
  ATX12V2: observation("", "confirmed", "free", "photo-confirmed",
    "IMG_4538 shows the separate motherboard four-pin ATX 12 V socket empty.",
    "This records occupancy, not a recommendation to change power wiring.", "2026-11-13"),
  PCIE1: observation("Low-profile HBA with two SFF-8643 cables", "confirmed", "occupied", "user-confirmed",
    "The HBA occupies PCIE1, directly at the GPU fan intake."),
  PCIE2: observation("GPU cooler — physical obstruction only", "confirmed", "blocked", "user-confirmed",
    "GPU in PCIE4, with its cooler covering PCIE3/PCIE2.",
    "Blocked does not mean electrically occupied. The earlier PCIE3 electrical assignment is superseded.", "2026-11-13"),
  PCIE3: observation("GPU cooler — physical obstruction only", "confirmed", "blocked", "user-confirmed",
    "GPU in PCIE4, cooler covering PCIE3/PCIE2.",
    "PCIE3 is physically blocked, not electrically occupied. Clearance is unmeasured.", "2026-11-13"),
  PCIE4: observation("GV-N207SGAMING OC-8GD rev 1.0", "confirmed", "occupied", "user-confirmed",
    "PCIE4 is the GPU's electrical slot; PCIE7/6/5 remain exposed.",
    "Cooler covers PCIE3/PCIE2; M.2 overhang clearance remains unmeasured.", "2026-11-13"),
  ...Object.fromEntries([5, 6, 7].map(number => [
    `PCIE${number}`, observation("", "confirmed", "free", "user-confirmed",
      "PCIE5/6/7 are empty.",
      "Supersedes the earlier PCIE4–PCIE7-free report; PCIE4 holds the GPU.", "2026-11-13"),
  ])),
  ...Object.fromEntries(["A", "B", "G", "H"].map(letter => [
    `DDR4_${letter}1`, observation("Kingston KSM32RD4/32HDR · 32 GB ECC RDIMM", "confirmed", "occupied", "user-confirmed",
      "Four 32 GB Kingston KSM32RD4/32HDR modules are installed in A1/B1/G1/H1; 128 GB total.",
      "DDR4-3200 is the module specification, not a measurement of current memory clock.", "2026-11-13"),
  ])),
  ...Object.fromEntries(["C", "D", "E", "F"].map(letter => [
    `DDR4_${letter}1`, observation("", "confirmed", "free", "user-confirmed",
      "C1/D1/E1/F1 are empty.", "", "2026-11-13"),
  ])),
  ...Object.fromEntries([1, 2].map(number => [
    `FAN${number}`, observation("Noctua 4-pin fan plug on pins 1–4", "confirmed", "occupied", "photo-confirmed",
      "Photo set 2 shows this Noctua 4-pin plug seated on pins 1–4 of the six-pin header.",
      "Both CPU-cooler fans are the originals supplied with the NH-U9 TR4-SP3. These particular plugs fit these headers; this does not establish universal connector compatibility, and physical keying remains unverified."),
  ])),
  FAN3: observation("Thermalright ARGB FAN HUB X8 PWM/tach lead", "confirmed", "occupied", "user-confirmed",
    "The hub lead occupies FAN3, seated like FAN1/FAN2 with two of six header pins exposed. The hub serves six redux fans, installed 2026-11-12.",
    "Middle-fan-3, on the PSU side of the middle bank, supplies the single tach return. Historical BMC reading: approximately 1100 RPM; capture time unavailable. Lower alarm: 100 RPM. Other five fan speeds are unmeasured. In-situ fit is not universal keying verification.", "2026-11-13"),
  ...Object.fromEntries([4, 5, 6, 7].map(number => [
    `FAN${number}`, observation("", "confirmed", "free", "user-confirmed",
      "FAN4–FAN7 are all empty.",
      "Supersedes the earlier photo-inferred empty status. This confirmation is physical, not inferred from missing tach readings. Electrical limits and independent BMC control groups remain subject to the documented limitations.", "2026-11-13"),
  ])),
  USB3_3_4: observation("Case front-panel USB 3 cable", "confirmed", "occupied", "user-confirmed",
    "The case front USB cable is connected to USB3_3_4.", "", "2026-11-13"),
  PANEL1: observation("Case front-panel switch/LED leads", "confirmed", "occupied", "photo-confirmed",
    "IMG_4570 shows plugs at the PANEL1 silkscreen, including a readable POWER SW plug.",
    "Individual LED/switch wire assignments and polarity have not been mapped. This is not a USB header.", "2026-11-13"),
  AUX_PANEL1: observation("", "confirmed", "free", "photo-confirmed",
    "IMG_4562 shows the AUX_PANEL1 label and bare header with no attached external cable.",
    "The neighboring blue caps belong to the separate configuration-jumper area (CHASSIS_ID0, PE8_SEL and PE16_SEL in the official layout). PE8_SEL/PE16_SEL are now modeled separately; the third cap's CHASSIS_ID0 pin pair is not assigned.", "2026-11-13"),
  PE8_SEL: observation("Jumper cap · pins 1–2", "inferred", "occupied", "photo-inferred",
    "Board-layout item 27 is PE8_SEL. The photo shows the left pair capped, matched against the manual's pin-1 and neighboring-header layout.",
    "Together with PE16_SEL 2–3, the documented configuration allocates PCIE2 x8, enables M2_1/SATA_4_7 and disables OCU1/2. This is photo/manual interpretation, not a live link-width measurement.", "2026-11-13"),
  PE16_SEL: observation("Jumper cap · pins 2–3", "inferred", "occupied", "photo-inferred",
    "Board-layout item 26 is PE16_SEL. The photo shows the right pair capped, matched against the manual's pin-1 and neighboring-header layout.",
    "Read-only record of installed caps; no jumper or server configuration was changed.", "2026-11-13"),
  ...Object.fromEntries(["TR1", "TR2"].map(id => [
    id, observation("", "confirmed", "free", "user-confirmed",
      "Neither TR1 nor TR2 has a separate temperature probe.", "", "2026-11-13"),
  ])),
  ...Object.fromEntries(["OCU1", "OCU2", "PSU_SMB1"].map(id => [
    id, observation("", "confirmed", "free", "user-confirmed",
      "This connector is empty.", "", "2026-11-13"),
  ])),
  ...Object.fromEntries(["LAN1", "LAN2", "IPMI_LAN1"].map(id => [
    id, observation("TP-Link TL-SX1008 switch", "confirmed", "occupied", "user-confirmed",
      "LAN1, LAN2 and dedicated BMC LAN connect to the switch; these are the three connected rear-I/O ports.", "", "2026-11-13"),
  ])),
  REAR_OTHER: observation("", "confirmed", "free", "user-confirmed",
    "No rear USB, display or serial devices are connected.",
    "The PSU AC power cord is separate from rear motherboard I/O.", "2026-11-13"),
};

export const inspectedJumpers = Object.freeze({ PE8_SEL: "1-2", PE16_SEL: "2-3" });
export const pcie2Modes = [
  { id: "pcie-x16", label: "PCIE2 x16 · default", PE8_SEL: "1-2", PE16_SEL: "1-2", pcie2Lanes: 16, m2: false, sata: false, oculink: false },
  { id: "pcie-x8-storage", label: "PCIE2 x8 + M.2 / SATA", PE8_SEL: "1-2", PE16_SEL: "2-3", pcie2Lanes: 8, m2: true, sata: true, oculink: false },
  { id: "oculink", label: "OCuLink only", PE8_SEL: "2-3", PE16_SEL: "1-2", pcie2Lanes: 0, m2: false, sata: false, oculink: true },
  { id: "all-storage", label: "M.2 / SATA + OCuLink", PE8_SEL: "2-3", PE16_SEL: "2-3", pcie2Lanes: 0, m2: true, sata: true, oculink: true },
];

export const psuPorts = [
  ...[18, 10].map((pins, index) => ({
    id: `MB${pins}`, group: `Motherboard · ${pins}-pin`, position: index ? "Top, beside MB18" : "Top left",
    occupancy: "occupied", target: "ATXPWR1 · shared 24-pin ATX cable", targetId: "ATXPWR1",
    provenance: "user-reported",
  })),
  ...Array.from({ length: 6 }, (_, index) => ({
    id: `C${index + 1}`, group: "PCIe / CPU · 8-pin",
    position: `${["Top", "Middle", "Bottom"][Math.floor(index / 2)]} right, ${index % 2 ? "right" : "left"} socket`,
    occupancy: index < 2 ? "occupied" : "free",
    target: ["GPU auxiliary power", "CPU EPS cable → ATX12V1"][index] ?? "Empty",
    targetId: ["gpu", "ATX12V1"][index] ?? null, provenance: "user-reported",
  })),
  ...["Fan hub", "Cage 3 · SATA power", "Empty", "Cage 1 · SATA power", "Cage 2 · SATA power", "Rear fans · Molex harness"].map((target, index) => ({
    id: `S${index + 1}`, group: "SATA / PATA · 6-pin",
    position: `${index < 3 ? "Middle" : "Bottom"} peripheral row, ${["left", "center", "right"][index % 3]} socket`,
    occupancy: index === 2 ? "free" : "occupied", target,
    targetId: ["fan-hub", "cage-3", null, "cage-1", "cage-2", "rear-fans"][index],
    provenance: index === 0 || index === 5 ? "user-confirmed" : "user-reported",
  })),
];

export const driveCages = [
  { number: 1, connectorId: "HBA_DATA", route: "SAS 9300-8i", leads: ["P1", "P2", "P3", "P4"] },
  { number: 2, connectorId: "SATA_4_7", route: "SATA 4–7", leads: ["0", "1", "2", "3"] },
  { number: 3, connectorId: "SATA_0_3", route: "SATA 0–3", leads: ["0", "1", "2", "3"] },
];

export const components = [
  { id: "board", label: "Motherboard", model: "ROMED8-2T REV 1.03", capacity: "Silkscreen revision", status: "Photo-confirmed (relayed)" },
  { id: "cpu", label: "CPU + cooler", model: "EPYC 7313P · NH-U9 TR4-SP3", capacity: "16 cores / 32 threads", status: "Installed with original cooler fan pair", note: "Both fans are the originals supplied with the cooler. FAN1 is on the PSU side; FAN2 is on the GPU side. Airflow through the heatsink runs from the PSU side toward the GPU side, NOT front to rear. This depicts orientation, not measured airflow or a thermal simulation." },
  { id: "memory", label: "Memory", model: "Kingston KSM32RD4/32HDR · ECC RDIMM · A1/B1/G1/H1", capacity: "32 GB per installed module · 4 × 32 GB = 128 GB total system memory", status: "Four modules installed in A1/B1/G1/H1", note: "C1/D1/E1/F1 are empty. DDR4-3200 is a rated specification; actual running clock and utilization are not measured here." },
  { id: "gpu", label: "Graphics", model: "GV-N207SGAMING OC-8GD rev 1.0", capacity: "PCIE4 · cooler covers PCIE3/PCIE2", status: "Installed in PCIE4; cooler blocks PCIE3/PCIE2", note: "PCIE4 is the electrical slot. Fan intake faces the HBA in PCIE1. M.2 shroud clearance is unmeasured." },
  { id: "nvme-a", label: "NVMe A", model: "Samsung 990 EVO · MZ-V9E2T0", capacity: "2 TB nominal per drive", status: "Installed labels and socket placements photo-confirmed 2026-11-13", note: "No heatsinks. Drives run perpendicular to the slots across PCIE6→PCIE2, under the GPU overhang. Private label EUIs uniquely match M2_2 to the root NVMe and M2_1 to the cache/data NVMe in live inventory. Historical A/B readings are not retroactively assigned to sockets. Clearance is unmeasured." },
  { id: "nvme-b", label: "NVMe B", model: "Samsung 990 EVO · MZ-V9E2T0", capacity: "2 TB nominal per drive", status: "Installed labels and socket placements photo-confirmed 2026-11-13", note: "No heatsinks. Live socket bindings use privately reconciled label EUIs, not Linux enumeration order or historical A/B readings. The observed GPU gap is not a verified heatsink allowance." },
  { id: "disks", label: "Disk array", model: "12 × WD80EFPX · 8 onboard / 4 HBA", capacity: "3 cages × 4 HDDs · bottom bay empty in each", status: "All 12 occupied bay placements, cage routing and lead order established", note: "Cage 1 → SAS 9300-8i, P1–P4 top-to-bottom; cage 2 → SATA 4–7, leads 0–3 top-to-bottom; cage 3 → SATA 0–3, leads 0–3 top-to-bottom. Front-view left/center/right cages each have their bottom bay empty. Each group of four HDDs has its own PSU SATA power harness. Private installed-label observations uniquely match all 12 HDDs to their bays in live inventory. Cable labels are not Linux device names. Current Linux RAID membership is separate from physical placement and may change after a rebuild. No drives being added." },
  { id: "hba", label: "Storage HBA", model: "LSI Broadcom SAS 9300-8i · two SFF-8643 cables", capacity: "PCIE1 · cage 1 / 4 HDDs + 4 spare SATA data ends", status: "Installed in PCIE1; breakout serves cage 1", note: "One breakout serves cage 1 via P1–P4 top-to-bottom; the other has four unconnected SATA data cables with no accompanying drives or SATA power. Socket-to-breakout assignment remains untraced. The official SAS 9300-8i guide specifies a 6.0 × 2.7 inch board (152.4 × 68.6 mm); schematic geometry and clearances are not measured. Visible auxiliary chip markings do not independently establish the HBA model; the SAS controller is covered by its heatsink. Firmware/mode is not inferred. Directly at the GPU fan intake; airflow impact is not measured." },
  { id: "case-fans", label: "Front + middle fans / FAN3 hub", model: "6 × Noctua NF-P12 redux-1700 PWM", capacity: "120 × 25 mm · rated maximum 1700 RPM / 0.09 A per fan", tachPartId: "middle-fan-3", status: "Installed 2026-11-12; front-to-rear airflow", note: "3 front + 3 middle, all blowing front to rear. The PSU-side middle fan (middle-fan-3) supplies the single hub tach return; other hub-port assignments remain untraced. Replaced the six BoK BDM12025S fans and their Molex chain A. All six use a SATA-powered Thermalright ARGB FAN HUB X8 with its lead on FAN3. Approximately 1100 RPM is one BMC-observed hub return, not six measured speeds. Ratings are specifications, not measured current/RPM. Micro Center SKU 062398." },
  { id: "fan-hub", label: "Case-fan hub", model: "Thermalright ARGB 8 Group Fan HUB/Controller · ARGB FAN HUB X8", capacity: "6 fans · dedicated PSU SATA harness / FAN3 PWM + one tach return", status: "Dedicated SATA power; FAN3 control and middle-fan-3 tach return", note: "Between motherboard and middle fan wall, near case centerline and FAN1–FAN3; exact coordinates are approximate. Micro Center product 710163, SKU 025247. Tach-return fan: middle-fan-3, PSU side of middle bank. Historical reading approximately 1100 RPM; capture time unavailable. Lower alarm 100 RPM. This one tach value drives all six animations as a shared-speed assumption. Other five speeds are not individually monitored; other port assignments remain untraced." },
  { id: "rear-fans", label: "Rear fans / chain B", model: "2 × 80 mm BoK BDM8025S", capacity: "Label: 12 V / 0.10 A / 2000 RPM", status: "Factory-original rear exhaust pair", note: "The rear-fan label identifies BDM8025S. Rosewill case specification establishes 80 mm width, not a photo measurement; frame thickness has not been measured. Both fans are factory-original and exhaust out the back. One separate PSU Molex harness powers both. Label-rated 2000 RPM is NOT measured; no board tach/control connection." },
  { id: "psu", label: "PSU + power routing", model: "Corsair HX1000i · CP-9020259 / RPS0131", capacity: "1000 W rated · 3 HDD SATA harnesses + 1 hub SATA + 1 rear-fan Molex", status: "Installed model and socket assignments established", note: "The installed label identifies RPS0131, part CP-9020259 / 75-005684 and 1000 W rated output. Local reference labels follow the empty-panel photo, not official Corsair numbering: MB18 + MB10 together feed ATXPWR1 (24-pin); C1 feeds GPU power; C2 separately feeds ATX12V1 (EPS 8-pin). S1 feeds the fan hub, S2 cage 3, S4 cage 1, S5 cage 2 and S6 the rear-fan Molex harness. S3 and C3–C6 are empty. Earlier S-port assignments are superseded. USB/iCUE is not connected. Motherboard ATX12V2 (4-pin) and GFX_12V1 are empty. Each HDD cage has a separate power harness; four spare HBA SATA data ends have no drives or SATA power. Cable part numbers and power headroom remain unverified. No modular pinout or cable interchangeability is implied; the current retail title does not establish a newer ATX certification for this unit." },
  { id: "case-header", label: "Front-panel connections", model: "PANEL1 · case switch/LED leads", capacity: "9-pin system-panel header", status: "Photo-confirmed in IMG_4570", note: "PANEL1 silkscreen and POWER SW plug are readable. Other switch/LED leads are present, but their individual assignments/polarity have not been mapped. This is not a fan header." },
  { id: "unidentified-cable", label: "Lower-edge flat cable", model: "Red / white / green / black, under GPU", capacity: "Likely part of the front-panel switch/LED loom", status: "Photo-inferred from IMG_4570 terminations; full cable trace unverified", note: "POWER SW and other front-panel plugs are visible at PANEL1. The earlier USB 2.0 suggestion was based only on wire colors and is not established. No individual wire-to-pin assignment is implied." },
  { id: "rear-io", label: "Rear connections", model: "LAN1 / LAN2 / BMC LAN → switch", capacity: "No rear USB, display or serial devices", status: "Three Ethernet connections", note: "The PSU AC power cord is separate. The PSU USB telemetry cable is not connected internally either." },
  { id: "filesystem", label: "/data", model: "LVM + XFS over RAID6", capacity: "≈53 / 66 TiB used", status: "Reported snapshot; approximate" },
];

// Sanitized observations, not live queries. A/B are logical labels, not M.2 socket bindings.
export const observedReadings = [
  { id: "cpu", label: "CPU Tctl", value: 65.5, unit: "°C", kind: "component", provenance: "snapshot", source: "Prometheus / node-exporter hwmon", observedAt: snapshotDate },
  { id: "nvme-a", label: "NVMe A · composite", value: 43.85, unit: "°C", kind: "component", provenance: "snapshot", source: "Prometheus / node-exporter hwmon", observedAt: snapshotDate },
  { id: "nvme-b", label: "NVMe B · composite", value: 47.85, unit: "°C", kind: "component", provenance: "snapshot", source: "Prometheus / node-exporter hwmon", observedAt: snapshotDate },
  { id: "nvme-b-secondary", label: "NVMe B · Sensor 1", value: 71.85, unit: "°C", kind: "component", provenance: "snapshot", source: "Prometheus / node-exporter hwmon; sensor meaning not independently verified", observedAt: snapshotDate },
  { id: "mb", label: "Motherboard sensor", value: 39, unit: "°C", kind: "component", provenance: "snapshot", source: "BMC / MB Temp; physical sensor position unverified", observedAt: snapshotDate },
  { id: "lan", label: "Onboard LAN sensor", value: 66, unit: "°C", kind: "component", provenance: "snapshot", source: "BMC / Onboard LAN Temp", observedAt: snapshotDate },
  { id: "FAN1", label: "FAN1 · primary tach", value: 1300, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN1; historical tach reading, not a measurement of fan position", observedAt: snapshotDate },
  { id: "FAN2", label: "FAN2 · primary tach", value: 1400, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN2; historical tach reading, not a measurement of fan position", observedAt: snapshotDate },
  { id: "FAN3", label: "FAN3 · single hub tach return", value: 1100, approximate: true, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN3; exact capture time unavailable. Middle-fan-3 (PSU side of middle bank) supplies the hub's single tach return, not six individual fan speeds.", observedAt: null },
];

export const syntheticReadings = [
  { id: "cpu", label: "Example CPU", value: 78, unit: "°C", kind: "component", provenance: "synthetic", source: "Invented demonstration value", observedAt: null },
  { id: "nvme-a", label: "Example NVMe A", value: 52, unit: "°C", kind: "component", provenance: "synthetic", source: "Invented demonstration value", observedAt: null },
  { id: "nvme-b", label: "Example NVMe B", value: 61, unit: "°C", kind: "component", provenance: "synthetic", source: "Invented demonstration value", observedAt: null },
  { id: "FAN1", label: "Example FAN1", value: 1600, unit: "RPM", kind: "fan", provenance: "synthetic", source: "Invented demonstration value", observedAt: null },
  { id: "FAN2", label: "Example FAN2", value: 1700, unit: "RPM", kind: "fan", provenance: "synthetic", source: "Invented demonstration value", observedAt: null },
  { id: "air-front", label: "Example inlet air", value: 24, unit: "°C", kind: "air", position: 0, provenance: "synthetic", source: "Invented air probe, not installed", observedAt: null },
  { id: "air-rear", label: "Example outlet air", value: 39, unit: "°C", kind: "air", position: 1, provenance: "synthetic", source: "Invented air probe, not installed", observedAt: null },
];

const motherboardReference = {
  label: "ASRock Rack ROMED8-2T manual (PDF)",
  url: "https://download.asrock.com/Manual/ROMED8-2T.pdf",
  note: "Internal revision 1.30 / April 2026; the cover still names an older revision.",
};
const chassisReference = {
  label: "Rosewill RSV-L4500U manual (PDF)",
  url: "https://c1.neweggimages.com/IMAttachment/UserManual/User%20Manual-1741922402096.pdf",
  note: "Manufacturer chassis documentation; the factory-original rear fans are specified as 80 mm. This is not a physical measurement.",
};
const nvmeReference = {
  label: "Samsung 990 EVO datasheet (PDF)",
  url: "https://download.semiconductor.samsung.com/resources/data-sheet/samsung_nvme_ssd_990_evo_datasheet_rev.1.1.pdf",
  note: "Revision 1.1; covers the confirmed MZ-V9E2T0B family. Specifications are not live measurements.",
};
export const hardwareCategories = {
  Compute: ["cpu", "gpu"],
  Memory: ["memory"],
  Storage: ["disks", "nvme-a", "nvme-b", "drive-M2_1", "drive-M2_2", "hba"],
  Networking: ["rear-io"],
  Cooling: ["cpu", "case-fans", "rear-fans", "fan-hub"],
  Expansion: ["gpu", "hba"],
  Power: ["psu", "fan-hub"],
  Chassis: ["chassis"],
  Motherboard: ["board"],
};

export const partReferences = {
  board: [motherboardReference],
  chassis: [chassisReference],
  cpu: [{
    label: "Noctua NH-U9 TR4-SP3 installation manual (PDF)",
    url: "https://cdn.noctua.at/media/noctua_nh_u9_tr4-sp3_manual_en.pdf?download=true",
  }, {
    label: "AMD EPYC 7003 family datasheet (PDF)",
    url: "https://www.amd.com/content/dam/amd/en/documents/epyc-business-docs/datasheets/amd-epyc-7003-series-product-datasheet.pdf",
    note: "Manufacturer-published family reference; exact-model specifications are linked below.",
  }, {
    label: "AMD EPYC 7313P specifications (HTML)",
    url: "https://www.amd.com/en/products/processors/server/epyc/7003-series/amd-epyc-7313p.html",
  }, motherboardReference],
  memory: [{
    label: "Kingston KSM32RD4/32HDR datasheet (PDF)",
    url: "https://www.kingston.com/datasheets/KSM32RD4_32HDR.pdf",
    note: "32 GB per module; rated DDR4-3200 ECC RDIMM specifications, not measured operating speed.",
  }],
  gpu: [{
    label: "Gigabyte graphics-card installation guide (PDF; generic)",
    url: "https://download.gigabyte.com/FileList/Manual/VGAGUIDE_web.pdf",
    note: "Generic installation guide from the spreadsheet, not a model-specific pinout or clearance drawing.",
  }, {
    label: "GV-N207SGAMING OC-8GD rev. 1.0/1.1 support (HTML)",
    url: "https://www.gigabyte.com/us/Graphics-Card/GV-N207SGAMING-OC-8GD-rev-10-11/support",
  }],
  "nvme-a": [nvmeReference],
  "nvme-b": [nvmeReference],
  "drive-M2_1": [nvmeReference],
  "drive-M2_2": [nvmeReference],
  disks: [{
    label: "WD Red Plus product brief (PDF)",
    url: "https://documents.westerndigital.com/content/dam/doc-library/en_us/assets/public/western-digital/product/internal-drives/wd-red-plus-hdd/product-brief-western-digital-wd-red-plus-hdd.pdf",
    note: "Includes WD80EFPX. Product ratings do not identify logical disks or their physical bays.",
  }],
  hba: [{
    label: "Broadcom SAS 9300-8i user guide (PDF)",
    url: "https://docs.broadcom.com/doc/12354877",
    note: "Revision 1.3 / March 2015; matches the installed SAS 9300-8i. Board dimensions are specifications, not measured clearances; firmware/mode remains unverified.",
  }],
  "case-fans": [{
    label: "Noctua NF-P12 redux-1700 PWM specification (PDF)",
    url: "https://cdn.noctua.at/media/55101b81/Noctua%20NF-P12%20redux-1700%20PWM%20Specification.pdf?download=true",
  }],
  "fan-hub": [{
    label: "Thermalright TL-FAN and ARGB HUB x8 product reference (HTML)",
    url: "https://www.thermalright.com/product/tl-fan-and-argb-hub-x8/",
    note: "Manufacturer-listed PDF download returned HTTP 404 during verification; no verified matching PDF is available here. Do not substitute the x8 IR variant's manual.",
  }],
  "rear-fans": [chassisReference],
  psu: [{
    label: "Corsair HXi series manual (PDF; HX1000i / RPS0131)",
    url: "https://assets.corsair.com/image/upload/v1701372411/documents/49_002658_AA_WW_HXi_Series_QSG_Web.pdf#page=4",
    note: "Linked by Corsair for CP-9020259; the installed label confirms CP-9020259 / RPS0131 / 75-005684. The label does not establish a newer retailer-advertised ATX revision. Use only cables verified compatible with this PSU.",
  }],
  "case-header": [motherboardReference, chassisReference],
  "unidentified-cable": [motherboardReference],
  "rear-io": [motherboardReference],
};
