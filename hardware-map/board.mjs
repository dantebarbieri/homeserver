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
  "user-confirmed": "User-confirmed",
  "user-reported": "User-reported",
  "user-annotation": "Local user annotation",
  unverified: "Unverified",
};
export const layoutSource = "Official manual rev. 1.30, printed pp. 7–8 (PDF pp. 14–15).";
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
    "AMD EPYC 7313P with Noctua NH-U9 TR4-SP3 cooler. Original cooler fans use FAN1/FAN2; user-confirmed airflow runs from the PSU side toward the GPU side."),
  ...["H", "G", "F", "E"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 65 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. User-confirmed population: 32 GB Kingston KSM32RD4/32HDR modules in A1/B1/G1/H1; C1/D1/E1/F1 empty. 128 GB total system memory.")),
  ...["A", "B", "C", "D"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 370 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. User-confirmed population: 32 GB Kingston KSM32RD4/32HDR modules in A1/B1/G1/H1; C1/D1/E1/F1 empty. Do not infer population from BMC temperature-channel labels.")),
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
    "6-pin motherboard graphics 12 V connector, user-confirmed empty. This is not the GPU card's own power socket or a modular PSU pinout.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("USB3_3_4", "Front USB 3", "Front panel", 570, 180, 140, 27,
    "19-pin USB 3.2 Gen 1 front-panel header. Case front USB cable is user-confirmed connected here."),
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
    "Mini-SAS HD connector for four SATA data links via breakout cable. Eight disks are reported on onboard SATA, but cable-to-drive identities are unknown.",
    { source: "Official manual rev. 1.30, printed p. 29 (PDF p. 36)." }),
  connector("SATA_4_7", "SATA 4–7", "Storage", 615, 590, 96, 36,
    "Mini-SAS HD connector for four SATA links. Lane availability depends on the PCIE2 selection jumpers; their installed positions are unverified.",
    { source: "Official manual rev. 1.30, printed pp. 26, 29 (PDF pp. 33, 36)." }),
  ...Array.from({ length: 7 }, (_, i) => {
    const number = 7 - i;
    return connector(`PCIE${number}`, `PCIE${number}`, "Expansion", 145, 475 + i * 49, 245, 29,
      `CPU-connected PCIe 4.0 x16 expansion slot; actual negotiated speed/width is not measured here. PCIE7 is nearest the CPU/DIMMs; PCIE1 is at the bottom board edge.${number === 2 ? " Lane sharing with storage is controlled by PE8_SEL/PE16_SEL; their installed positions are unverified." : ""}`);
  }),
  connector("OCU1", "OCU1", "Storage", 515, 370, 90, 28,
    "OCuLink connector; enabled/disabled by the PCIE2 selection jumpers. Connection unknown."),
  connector("OCU2", "OCU2", "Storage", 515, 410, 90, 28,
    "OCuLink connector; enabled/disabled by the PCIE2 selection jumpers. Connection unknown."),
  connector("PANEL1", "PANEL1", "Front panel", 600, 865, 110, 28,
    "System front-panel header. IMG_4570 shows attached switch/LED leads, including a readable POWER SW plug. Individual lead polarity is not modeled.",
    { source: "Official manual rev. 1.30, printed p. 28 (PDF p. 35)." }),
  connector("AUX_PANEL1", "AUX PANEL", "Front panel", 450, 865, 135, 28,
    "Auxiliary front-panel header. Connection unknown; verify the exact cable and manual before use."),
  connector("TR1", "TR1", "Sensors", 330, 865, 45, 28,
    "Thermal sensor header. User confirms no separate temperature probe is connected.",
    { source: "Official manual rev. 1.30, printed p. 32 (PDF p. 39)." }),
  connector("TR2", "TR2", "Sensors", 260, 865, 45, 28,
    "Thermal sensor header. User confirms no separate temperature probe is connected.",
    { source: "Official manual rev. 1.30, printed p. 32 (PDF p. 39)." }),
  connector("PSU_SMB1", "PSU SMB", "Sensors", 565, 20, 100, 25,
    "PSU SMBus header. Its presence does not establish that the PSU exposes telemetry or that a cable is connected."),
  connector("REAR_OTHER", "VGA/COM/USB", "Rear I/O", 35, 186, 86, 44,
    "Logical group of other rear I/O ports, not a motherboard header identifier. The user reports no connections here; rear power refers to the PSU inlet, not these ports."),
  connector("IPMI_LAN1", "BMC LAN", "Rear I/O", 35, 247, 86, 44,
    "Dedicated BMC Ethernet port. The user reports it connected to the switch."),
  connector("LAN1", "10G LAN1", "Rear I/O", 35, 308, 86, 44,
    "First onboard 10 GbE port. The user reports it connected to the switch."),
  connector("LAN2", "10G LAN2", "Rear I/O", 35, 369, 86, 44,
    "Second onboard 10 GbE port. The user reports it connected to the switch."),
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
    "The cooler and its original fan pair are user-confirmed; no cooler removal or new server query was performed.", "2026-11-13"),
  ...Object.fromEntries(["M2_1", "M2_2"].map(id => [
    id, observation("Samsung 990 EVO 2 TB · MZ-V9E2T0B; logical A/B identity unknown", "confirmed", "occupied", "photo-confirmed",
      "Photos show both sockets populated without heatsinks, drives perpendicular to the PCIe slots across PCIE6→PCIE2. User confirms both exact models/capacities on November 13.",
      "GPU overhang and its few-mm gap are photo observations, NOT measured heatsink-clearance allowances.", "2026-11-13"),
  ])),
  SATA_0_3: observation("SATA breakout cable; drive routing unknown", "confirmed", "occupied", "photo-confirmed",
    "Connector appears cabled in the cleaning photos, as relayed by the coordinating session."),
  SATA_4_7: observation("SATA breakout cable; drive routing unknown", "confirmed", "occupied", "photo-confirmed",
    "Connector appears cabled in the cleaning photos, as relayed by the coordinating session."),
  GFX_12V1: observation("", "confirmed", "free", "user-confirmed",
    "User confirms the motherboard GFX_12V1 six-pin socket is empty.",
    "This is distinct from the power sockets on the GPU card.", "2026-11-13"),
  ...Object.fromEntries(["ATXPWR1", "ATX12V1"].map(id => [
    id, observation(id === "ATXPWR1" ? "PSU 24-pin ATX cable" : "PSU EPS 8-pin cable", "confirmed", "occupied", "photo-confirmed",
      "IMG_4538 shows the motherboard 24-pin and EPS 8-pin sockets occupied, supporting the user's interpretation.",
      "The PSU-side 18-pin + 10-pin pair is the split end of the main ATX cable, not two additional motherboard connectors.", "2026-11-13"),
  ])),
  ATX12V2: observation("", "confirmed", "free", "photo-confirmed",
    "IMG_4538 shows the separate motherboard four-pin ATX 12 V socket empty.",
    "This records occupancy, not a recommendation to change power wiring.", "2026-11-13"),
  PCIE1: observation("Low-profile HBA with two SFF-8643 cables", "confirmed", "occupied", "user-confirmed",
    "Updated user confirmation and photo set 2 place the HBA in PCIE1, directly at the GPU fan intake."),
  PCIE2: observation("GPU cooler — physical obstruction only", "confirmed", "blocked", "user-confirmed",
    "PCIE2 is physically blocked by the GPU cooler. The earlier confirmed obstruction remains consistent with the revised photo-inferred GPU-in-PCIE4 placement.",
    "Blocked does not mean electrically occupied. The earlier PCIE3 electrical assignment is superseded.", "2026-11-13"),
  PCIE3: observation("GPU cooler — inferred physical obstruction", "inferred", "blocked", "photo-inferred",
    "User revises the GPU position to likely PCIE4. Three exposed slots between DIMMs and GPU in IMG_4537 support that interpretation; its cooler appears to cover PCIE3.",
    "Earlier PCIE3 electrical assignment is withdrawn. Slot labels are not readable; exact physical clearance is not measured.", "2026-11-13"),
  PCIE4: observation("GV-N207SGAMING OC-8GD rev 1.0 — likely electrical slot", "inferred", "occupied", "photo-inferred",
    "IMG_4537 shows three exposed slot rows between DIMMs and GPU, supporting PCIE7/6/5 empty and GPU in PCIE4. User independently suspects PCIE4.",
    "Position is photo-inferred, not label-confirmed. The cooler appears to cover PCIE3/PCIE2 and overhang both M.2 drives.", "2026-11-13"),
  ...Object.fromEntries([5, 6, 7].map(number => [
    `PCIE${number}`, observation("", "inferred", "free", "photo-inferred",
      "Three exposed empty slot rows in IMG_4537 align with PCIE7/6/5 in the manual. Their labels are not readable.",
      "Earlier PCIE4–PCIE7-free report is superseded by this photo-supported interpretation.", "2026-11-13"),
  ])),
  ...Object.fromEntries(["A", "B", "G", "H"].map(letter => [
    `DDR4_${letter}1`, observation("Kingston KSM32RD4/32HDR · 32 GB ECC RDIMM", "confirmed", "occupied", "user-confirmed",
      "User confirms these exact four 32 GB modules are installed in A1/B1/G1/H1; 128 GB total.",
      "DDR4-3200 is the module specification, not a measurement of current memory clock.", "2026-11-13"),
  ])),
  ...Object.fromEntries(["C", "D", "E", "F"].map(letter => [
    `DDR4_${letter}1`, observation("", "confirmed", "free", "user-confirmed",
      "User confirms C1/D1/E1/F1 are empty.", "", "2026-11-13"),
  ])),
  ...Object.fromEntries([1, 2].map(number => [
    `FAN${number}`, observation("Noctua 4-pin fan plug on pins 1–4", "confirmed", "occupied", "photo-confirmed",
      "Photo set 2 shows this Noctua 4-pin plug seated on pins 1–4 of the six-pin header.",
      "The user confirms both CPU-cooler fans are the originals supplied with the NH-U9 TR4-SP3 (2026-11-13). This is in-situ evidence that these particular plugs fit these headers, not universal connector compatibility; physical keying remains unverified."),
  ])),
  FAN3: observation("Thermalright ARGB FAN HUB X8 PWM/tach lead", "confirmed", "occupied", "user-confirmed",
    "User visually confirms the hub lead on FAN3, seated like FAN1/FAN2 with two of six header pins exposed. The hub serves six redux fans, installed 2026-11-12.",
    "Supersedes the earlier empty-header photo. The user identifies middle-fan-3, on the PSU side of the middle bank, as the single tach-return fan. Relayed BMC reading: approximately 1100 RPM; capture time unavailable. Reported lower alarm: 100 RPM. Other five fan speeds are unmeasured. In-situ fit is not universal keying verification.", "2026-11-13"),
  ...Object.fromEntries([4, 5, 6, 7].map(number => [
    `FAN${number}`, observation("", "confirmed", "free", "user-confirmed",
      "User confirms FAN4–FAN7 are all visibly empty, based on inspection or clear photos.",
      "Supersedes the earlier photo-inferred empty status. This confirmation is physical, not inferred from missing tach readings. Electrical limits and independent BMC control groups remain subject to the documented limitations.", "2026-11-13"),
  ])),
  USB3_3_4: observation("Case front-panel USB 3 cable", "confirmed", "occupied", "user-confirmed",
    "User explicitly confirms the case front USB cable is connected to USB3_3_4.", "", "2026-11-13"),
  PANEL1: observation("Case front-panel switch/LED leads", "confirmed", "occupied", "photo-confirmed",
    "IMG_4570 shows plugs at the PANEL1 silkscreen, including a readable POWER SW plug.",
    "Individual LED/switch wire assignments and polarity have not been mapped. This is not a USB header.", "2026-11-13"),
  ...Object.fromEntries(["TR1", "TR2"].map(id => [
    id, observation("", "confirmed", "free", "user-confirmed",
      "User confirms neither TR1 nor TR2 has a separate temperature probe.", "", "2026-11-13"),
  ])),
  ...Object.fromEntries(["LAN1", "LAN2", "IPMI_LAN1"].map(id => [
    id, observation("TP-Link TL-SX1008 switch", "confirmed", "occupied", "user-confirmed",
      "User confirms LAN1, LAN2 and dedicated BMC LAN are the three connected rear-I/O ports. Switch destination was previously reported.", "", "2026-11-13"),
  ])),
  REAR_OTHER: observation("", "confirmed", "free", "user-confirmed",
    "User confirms no rear USB, display or serial devices are connected.",
    "The PSU AC power cord is separate from rear motherboard I/O.", "2026-11-13"),
};

export const components = [
  { id: "board", label: "Motherboard", model: "ROMED8-2T REV 1.03", capacity: "Silkscreen revision", status: "Photo-confirmed (relayed)" },
  { id: "cpu", label: "CPU + cooler", model: "EPYC 7313P · NH-U9 TR4-SP3", capacity: "16 cores / 32 threads", status: "CPU reported installed; original cooler fan pair user-confirmed", note: "2026-11-13 walkthrough: both fans are the originals supplied with the cooler. Airflow through the heatsink runs from the PSU side toward the GPU side, NOT front to rear. Direction is user-confirmed, not measured airflow or a thermal simulation." },
  { id: "memory", label: "Memory", model: "Kingston KSM32RD4/32HDR · ECC RDIMM · A1/B1/G1/H1", capacity: "32 GB per installed module · 4 × 32 GB = 128 GB total system memory", status: "Exact modules and all eight socket states user-confirmed 2026-11-13", note: "C1/D1/E1/F1 are empty. DDR4-3200 is a rated specification; actual running clock and utilization are not measured here." },
  { id: "gpu", label: "Graphics", model: "GV-N207SGAMING OC-8GD rev 1.0", capacity: "Likely PCIE4 · cooler appears to cover PCIE3/PCIE2", status: "Model photo-confirmed; slot/extent photo-inferred, not label-confirmed", note: "IMG_4548 confirms the model spelling (the earlier extra zero was a transcription error). IMG_4537 supports the user's revised PCIE4 interpretation; the earlier PCIE3 assignment is withdrawn. Fan intake faces the HBA in PCIE1. M.2 shroud clearance is unmeasured." },
  { id: "nvme-a", label: "NVMe A", model: "Samsung 990 EVO · MZ-V9E2T0B", capacity: "2 TB nominal per drive", status: "Both installed models/capacities user-confirmed; bare drives photo-confirmed", note: "No heatsinks. Drives run perpendicular to the slots across PCIE6→PCIE2, under the GPU overhang. Logical A/B telemetry is not bound to physical sockets. Clearance is unmeasured." },
  { id: "nvme-b", label: "NVMe B", model: "Samsung 990 EVO · MZ-V9E2T0B", capacity: "2 TB nominal per drive", status: "Both installed models/capacities user-confirmed; bare drives photo-confirmed", note: "No heatsinks. A/B telemetry identities are not assigned to M2_1/M2_2; the observed GPU gap is not a verified heatsink allowance." },
  { id: "disks", label: "Disk array", model: "12 × WD80EFPX · 8 onboard / 4 HBA", capacity: "3 cages × 4 HDDs · bottom bay empty in each", status: "12 installed / 15 bays; empty positions and three power harnesses user-confirmed", note: "Front-view left/center/right cages each have their bottom bay empty. Each group of four HDDs has its own PSU SATA harness. Individual logical-drive-to-bay and data-cable assignments remain untraced. 11 active + 1 hot spare, RAID6; no drives being added." },
  { id: "hba", label: "Storage HBA", model: "Likely LSI Broadcom SAS 9300-8i · two SFF-8643 cables", capacity: "PCIE1 · 4 connected HDDs reported", status: "Slot user-confirmed; model user-suspected, installed label unverified", note: "The 9300-8i is the current candidate, not a confirmed label identification. Firmware/mode is not inferred. Directly at the GPU fan intake; cable routing and airflow impact are not measured." },
  { id: "case-fans", label: "Front + middle fans / FAN3 hub", model: "6 × Noctua NF-P12 redux-1700 PWM", capacity: "120 × 25 mm · rated maximum 1700 RPM / 0.09 A per fan", tachPartId: "middle-fan-3", status: "User-installed 2026-11-12; airflow and tach-return position user-confirmed 2026-11-13", note: "3 front + 3 middle, all blowing front to rear. The PSU-side middle fan (middle-fan-3) supplies the single hub tach return; other hub-port assignments remain untraced. Replaced the six BoK BDM12025S fans and their Molex chain A. All six use a SATA-powered Thermalright ARGB FAN HUB X8 with its lead on FAN3. Approximately 1100 RPM is one BMC-observed hub return, not six measured speeds. Ratings are specifications, not measured current/RPM. Micro Center SKU 062398." },
  { id: "fan-hub", label: "Case-fan hub", model: "Thermalright ARGB 8 Group Fan HUB/Controller · ARGB FAN HUB X8", capacity: "6 fans · dedicated PSU SATA harness / FAN3 PWM + one tach return", status: "Location, dedicated power, FAN3 lead and tach-return fan user-confirmed", note: "Between motherboard and middle fan wall, near case centerline and FAN1–FAN3; exact coordinates are approximate. Micro Center product 710163, SKU 025247. Tach-return fan: middle-fan-3, PSU side of middle bank. Relayed reading approximately 1100 RPM; capture time unavailable. Reported lower alarm 100 RPM. Other five speeds are not individually monitored; other port assignments remain untraced." },
  { id: "rear-fans", label: "Rear fans / chain B", model: "2 × 80 mm BoK · thickness and exact model UNVERIFIED", capacity: "Reported label: 12 V / 0.1 A / 2000 RPM", status: "Original fans, rear exhaust and one dedicated Molex harness user-confirmed", note: "Rosewill case specification establishes 80 mm width, not a photo measurement. Both fans are factory-original and exhaust out the back. One separate PSU Molex harness powers both. Thickness and tentative BDM180255 transcription remain unverified. Label-rated 2000 RPM is NOT measured; no board tach/control connection." },
  { id: "psu", label: "PSU + power routing", model: "Corsair HX1000i · CP-9020259-NA / RPS0131 family", capacity: "1000 W rated · 3 HDD SATA harnesses + 1 hub SATA + 1 rear-fan Molex", status: "Part family identified from listing; harness topology and USB absence user-confirmed", note: "Three separate SATA harnesses each feed four HDDs; a fourth SATA harness serves only the fan hub; one separate Molex harness serves both rear fans. This supersedes the earlier one-harness-for-12-HDDs suspicion. PSU 18+10-pin ATX pair is connected. Motherboard 24-pin/EPS 8-pin are occupied; its 4-pin and GFX_12V1 are empty. USB/iCUE cable is NOT connected. Individual PSU port IDs, cable part numbers and spare-port counts are unverified. No modular pinout, load limit or cable interchangeability is implied; the current retail title does not establish a newer ATX certification for this unit." },
  { id: "case-header", label: "Front-panel connections", model: "PANEL1 · case switch/LED leads", capacity: "9-pin system-panel header", status: "Photo-confirmed in IMG_4570", note: "PANEL1 silkscreen and POWER SW plug are readable. Other switch/LED leads are present, but their individual assignments/polarity have not been mapped. This is not a fan header." },
  { id: "unidentified-cable", label: "Lower-edge flat cable", model: "Red / white / green / black, under GPU", capacity: "Likely part of the front-panel switch/LED loom", status: "Photo-inferred from IMG_4570 terminations; full cable trace unverified", note: "POWER SW and other front-panel plugs are visible at PANEL1. The earlier USB 2.0 suggestion was based only on wire colors and is not established. No individual wire-to-pin assignment is implied." },
  { id: "rear-io", label: "Rear connections", model: "LAN1 / LAN2 / BMC LAN → switch", capacity: "No rear USB, display or serial devices", status: "User-confirmed 2026-11-13", note: "The PSU AC power cord is separate. The PSU USB telemetry cable is not connected internally either." },
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
  { id: "FAN1", label: "FAN1 · primary tach", value: 1300, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN1; cooler-fan assignment comes from a later user report, not this tach reading", observedAt: snapshotDate },
  { id: "FAN2", label: "FAN2 · primary tach", value: 1400, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN2; cooler-fan assignment comes from a later user report, not this tach reading", observedAt: snapshotDate },
  { id: "FAN3", label: "FAN3 · single hub tach return", value: 1100, approximate: true, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN3, relayed 2026-11-13; exact capture time unavailable. Physical fan middle-fan-3 (PSU side of middle bank) user-confirmed 2026-11-13. Hub passes one tach, not six individual fan speeds.", observedAt: null },
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
  note: "Manufacturer chassis documentation; rear-fan width relies on this specification plus user-confirmed original fans.",
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
    label: "AMD EPYC 7003 family datasheet (PDF; download unverified)",
    url: "https://www.amd.com/content/dam/amd/en/documents/epyc-business-docs/datasheets/amd-epyc-7003-series-product-datasheet.pdf",
    note: "Manufacturer-published family reference. Automated retrieval failed; use the exact-model specification page below if the PDF does not open.",
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
    label: "Broadcom SAS 9300-8i user guide (PDF; candidate model)",
    url: "https://docs.broadcom.com/doc/12354877",
    note: "Revision 1.3 / March 2015. The installed controller label is unverified; this guide is not evidence of its identity or firmware.",
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
    note: "Linked by Corsair for the CP-9020259 family; the installed revision is listing-based, not label-verified. Use only cables verified compatible with this PSU.",
  }],
  "case-header": [motherboardReference, chassisReference],
  "unidentified-cable": [motherboardReference],
  "rear-io": [motherboardReference],
};
