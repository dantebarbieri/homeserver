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
  "photo-confirmed": "Photo-confirmed (relayed)",
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
    "AMD EPYC 7313P installed; Noctua NH-U9 TR4-SP3 cooler. The user reports its two fans on FAN1 and FAN2; that wiring has not been independently traced."),
  ...["H", "G", "F", "E"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 65 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. The user reports DIMMs in A1, B1, G1 and H1; 128 GB total. Other sockets are not independently verified free.")),
  ...["A", "B", "C", "D"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 370 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. The user reports DIMMs in A1, B1, G1 and H1. Do not infer population from BMC temperature-channel labels.")),
  connector("ATX12V1", "EPS 8-pin", "Power", 565, 65, 75, 35,
    "8-pin ATX 12 V connector. Cable connection awaits visual confirmation.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("ATX12V2", "ATX 4-pin", "Power", 650, 65, 65, 35,
    "4-pin ATX 12 V connector. Cable connection awaits visual confirmation.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("ATXPWR1", "ATX 24-pin", "Power", 565, 115, 150, 35,
    "24-pin motherboard power connector. No PSU cable or modular-PSU pinout is implied.",
    { source: "Official manual rev. 1.30, printed p. 30 (PDF p. 37)." }),
  connector("GFX_12V1", "GFX 6-pin", "Power", 615, 832, 96, 25,
    "6-pin graphics 12 V power connector. Physical connection unverified; this is not a GPU card's own power socket or a modular PSU pinout.",
    { source: "Official manual rev. 1.30, printed p. 31 (PDF p. 38)." }),
  connector("USB3_3_4", "Front USB 3", "Front panel", 570, 180, 140, 27,
    "19-pin USB 3.2 Gen 1 front-panel header. Physical case cable unverified."),
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
      `PCIe expansion slot. PCIE7 is nearest the CPU/DIMMs; PCIE1 is at the bottom board edge. GPU in PCIE3 and HBA in PCIE1 are user-confirmed and photo-consistent.${number === 2 ? " PCIE2 is physically blocked by the GPU cooler, not occupied by the GPU's electrical connector. Lane-selection jumper positions remain unverified." : ""}`);
  }),
  connector("OCU1", "OCU1", "Storage", 515, 370, 90, 28,
    "OCuLink connector; enabled/disabled by the PCIE2 selection jumpers. Connection unknown."),
  connector("OCU2", "OCU2", "Storage", 515, 410, 90, 28,
    "OCuLink connector; enabled/disabled by the PCIE2 selection jumpers. Connection unknown."),
  connector("PANEL1", "PANEL1", "Front panel", 600, 865, 110, 28,
    "System front-panel header. Power/reset/indicator cable connections await inspection. A pin-level diagram is not yet included."),
  connector("AUX_PANEL1", "AUX PANEL", "Front panel", 450, 865, 135, 28,
    "Auxiliary front-panel header. Connection unknown; verify the exact cable and manual before use."),
  connector("TR1", "TR1", "Sensors", 330, 865, 45, 28,
    "Thermal sensor header. No connected probe has been verified; IPMI reports no reading.",
    { source: "Official manual rev. 1.30, printed p. 32 (PDF p. 39)." }),
  connector("TR2", "TR2", "Sensors", 260, 865, 45, 28,
    "Thermal sensor header. No connected probe has been verified; IPMI reports no reading.",
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

function observation(target, confidence, occupancy, provenance, evidence, note = "") {
  return { target, confidence, occupancy, provenance, evidence: `${snapshotDate}: ${evidence}`, note, updatedAt: null };
}

export const inspectionConnections = {
  ...Object.fromEntries(["M2_1", "M2_2"].map(id => [
    id, observation("Bare Samsung 2280 SSD; logical A/B identity unknown", "confirmed", "occupied", "photo-confirmed",
      "Photo set 2 shows both M.2 sockets populated without heatsinks. The drives run perpendicular to the PCIe slots across the PCIE6→PCIE2 rows.",
      "The GPU shroud overhangs both drives. The visible gap is estimated as a few mm from the photo, NOT measured and not a verified heatsink-clearance allowance."),
  ])),
  SATA_0_3: observation("SATA breakout cable; drive routing unknown", "confirmed", "occupied", "photo-confirmed",
    "Connector appears cabled in the cleaning photos, as relayed by the coordinating session."),
  SATA_4_7: observation("SATA breakout cable; drive routing unknown", "confirmed", "occupied", "photo-confirmed",
    "Connector appears cabled in the cleaning photos, as relayed by the coordinating session."),
  GFX_12V1: observation("", "inferred", "free", "photo-uncertain",
    "Appears empty in the cleaning photos, but this is not certain.", "Not a verified-free connector."),
  PCIE1: observation("Low-profile HBA with two SFF-8643 cables", "confirmed", "occupied", "user-confirmed",
    "Updated user confirmation and photo set 2 place the HBA in PCIE1, directly at the GPU fan intake."),
  PCIE2: observation("GPU's 2.5-slot cooler — physical obstruction only", "confirmed", "blocked", "user-confirmed",
    "The GPU is in PCIE3; its cooler physically blocks PCIE2. Updated user confirmation is photo-consistent.",
    "Blocked does not mean electrically occupied. This supersedes the earlier unverified claim that the GPU was installed in PCIE2."),
  PCIE3: observation("GV-N2070SGAMING OC-8GD rev 1.0", "confirmed", "occupied", "user-confirmed",
    "User-confirmed PCIE3 placement, consistent with photo set 2.",
    "The 2.5-slot cooler blocks PCIE2. Its fan intake faces the HBA in PCIE1; the shroud also overhangs both M.2 drives."),
  ...Object.fromEntries([4, 5, 6, 7].map(number => [
    `PCIE${number}`, observation("", "inferred", "free", "user-reported",
      "User reports PCIE4–PCIE7 free. This is not an independent clearance or slot-population inspection."),
  ])),
  ...Object.fromEntries(["A", "B", "G", "H"].map(letter => [
    `DDR4_${letter}1`, observation("ECC DDR4 DIMM", "inferred", "occupied", "user-reported",
      "User reports DIMMs in A1, B1, G1 and H1; independent socket-label verification pending."),
  ])),
  ...Object.fromEntries([1, 2].map(number => [
    `FAN${number}`, observation("Noctua 4-pin fan plug on pins 1–4", "confirmed", "occupied", "photo-confirmed",
      "Photo set 2 shows this Noctua 4-pin plug seated on pins 1–4 of the six-pin header.",
      "NH-U9 cooler fan identity is user-reported. This is in-situ evidence that these particular plugs fit these headers, not universal connector compatibility; physical keying remains unverified."),
  ])),
  FAN3: observation("", "confirmed", "free", "photo-confirmed",
    "Photo set 2 shows FAN3 / LED_FAN3 silkscreen and an empty header; the user also confirms it is free."),
  ...Object.fromEntries([4, 5, 6, 7].map(number => [
    `FAN${number}`, observation("", "inferred", "free", "photo-inferred",
      "Appears empty in the under-GPU photo, partly beneath the GPU overhang.",
      "Not confirmed-free. Lack of BMC tach does not establish occupancy. All case fans are separately reported to use Molex power, with no board header or tach connection."),
  ])),
  USB3_3_4: observation("Case front-panel USB 3 cable", "inferred", "occupied", "user-reported",
    "User reports the case front-panel USB 3 cable connected here."),
  ...Object.fromEntries(["LAN1", "LAN2", "IPMI_LAN1"].map(id => [
    id, observation("TP-Link TL-SX1008 switch", "inferred", "occupied", "user-reported",
      "User reports both onboard LAN ports and the dedicated BMC LAN connected to the switch."),
  ])),
  REAR_OTHER: observation("", "inferred", "free", "user-reported",
    "User reports no other rear I/O connections except power.", "Power refers to the PSU inlet; this does not verify the motherboard's internal power-header wiring."),
};

export const components = [
  { id: "board", label: "Motherboard", model: "ROMED8-2T REV 1.03", capacity: "Silkscreen revision", status: "Photo-confirmed (relayed)" },
  { id: "cpu", label: "CPU + cooler", model: "EPYC 7313P · NH-U9 TR4-SP3", capacity: "16 cores / 32 threads", status: "Reported installed" },
  { id: "memory", label: "Memory", model: "ECC DDR4 · A1 / B1 / G1 / H1 reported", capacity: "128 GB total system memory across four reported DIMMs; per-module capacity unassigned", status: "User-reported; socket labels not independently verified" },
  { id: "gpu", label: "Graphics", model: "GV-N2070SGAMING OC-8GD rev 1.0", capacity: "PCIE3 · 2.5-slot cooler blocks PCIE2", status: "Label photo-confirmed; slot user-confirmed / photo-consistent", note: "Fan intake directly faces the HBA in PCIE1. Shroud overhangs both M.2 drives; a few-mm gap is a photo estimate, not a measurement." },
  { id: "nvme-a", label: "NVMe A", model: "Samsung 990 EVO reported · physical socket binding unknown", capacity: "2 TB nominal", status: "Bare Samsung 2280 drives photo-confirmed in both sockets", note: "No heatsinks. Drives run perpendicular to the slots across PCIE6→PCIE2, under the GPU overhang. Clearance is unmeasured." },
  { id: "nvme-b", label: "NVMe B", model: "Samsung 990 EVO reported · physical socket binding unknown", capacity: "2 TB nominal", status: "Bare Samsung 2280 drives photo-confirmed in both sockets", note: "No heatsinks. A/B telemetry identities are not assigned to M2_1/M2_2; the observed GPU gap is not a verified heatsink allowance." },
  { id: "disks", label: "Disk array", model: "12 × WD80EFPX · 8 onboard / 4 HBA", capacity: "12 / 15 bays populated · 3 empty", status: "12 disks and 15-bay capacity user-confirmed", note: "11 active + 1 hot spare, RAID6. No drives are being added. Individual bay assignments and the locations of the three empty bays are unknown; the diagram is a count illustration, not a physical bay map." },
  { id: "hba", label: "Storage HBA", model: "Low-profile HBA · two SFF-8643 cables", capacity: "PCIE1 · 4 connected HDDs reported", status: "Slot user-confirmed / photo-consistent; model unknown", note: "Directly at the GPU fan intake. Appearance and cable count are photo-confirmed; airflow impact is not measured." },
  { id: "case-fans", label: "Front + middle fans / chain A", model: "6 × BoK BDM12025S · 120 mm reported", capacity: "Label: 12 V / 0.10 A per fan", status: "User-reported Molex wiring; label photographed (relayed)", note: "3 front + 3 middle. None are on motherboard headers; no tach connection is reported. Actual current and RPM are not measured." },
  { id: "rear-fans", label: "Rear fans / chain B", model: "2 × 80 mm BoK · thickness and exact model UNVERIFIED", capacity: "Reported label: 12 V / 0.1 A / 2000 RPM", status: "Width: manufacturer chassis specification + user-confirmed original fans", note: "Rosewill RSV-L4500U manual specifies rear 80 mm fans; the user confirms both installed rear fans are factory-original. Width is specification-based, NOT photo-measured. Thickness and tentative model transcription BDM180255 remain unverified. Molex wiring is user-reported. Label-rated 2000 RPM is NOT a measured speed; no tach connection or board header is reported." },
  { id: "psu", label: "PSU modular-port inventory", model: "Corsair HX1000i", capacity: "Free: 2 SATA/PATA + 4 PCIe/CPU ports", status: "User-reported; PSU-side counts only", note: "Used: all motherboard ports, 1 CPU, 1 PCIe and 3 SATA/PATA. User suspects one SATA/PATA harness powers all 12 HDDs; upstream routing and splitter topology remain untraced. Two SATA/PATA feed the Molex fan chains. This does not verify load limits or individual board-header wiring." },
  { id: "case-header", label: "Board-to-case header", model: "Case pin header is not a fan connector", capacity: "Exact header designator unverified", status: "User-reported identification", note: "Do not assign it to FAN1–FAN7 or assume PANEL1 without a label or cable trace." },
  { id: "unidentified-cable", label: "Lower-edge flat cable", model: "Red / white / green / black, under GPU", capacity: "Possibly internal USB 2.0", status: "Photo-inferred; identity unverified", note: "No exact header or pinout assigned. Wire colors alone do not confirm a USB connection." },
  { id: "rear-io", label: "Rear connections", model: "LAN1 / LAN2 / BMC LAN → switch", capacity: "Other rear I/O unused except PSU power", status: "User-reported" },
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
