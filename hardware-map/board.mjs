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
  "photo-uncertain": "Photo observation — uncertain",
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
  connector("M2_2", "M2_2", "Storage", 420, 510, 90, 32,
    "M.2 socket; supported module lengths 2230 / 2242 / 2260 / 2280 / 22110. The two installed 990 EVO drives are not yet matched to physical sockets."),
  connector("M2_1", "M2_1", "Storage", 520, 510, 90, 32,
    "M.2 socket; supported module lengths 2230 / 2242 / 2260 / 2280. Shares configurable resources with PCIE2 / SATA_4_7 / OCU1 / OCU2; inspect, do not change, jumper settings."),
  connector("SATA_0_3", "SATA 0–3", "Storage", 615, 500, 96, 36,
    "Mini-SAS HD connector for four SATA data links via breakout cable. Eight disks are reported on onboard SATA, but cable-to-drive identities are unknown.",
    { source: "Official manual rev. 1.30, printed p. 29 (PDF p. 36)." }),
  connector("SATA_4_7", "SATA 4–7", "Storage", 615, 590, 96, 36,
    "Mini-SAS HD connector for four SATA links. Lane availability depends on the PCIE2 selection jumpers; their installed positions are unverified.",
    { source: "Official manual rev. 1.30, printed pp. 26, 29 (PDF pp. 33, 36)." }),
  ...Array.from({ length: 7 }, (_, i) => {
    const number = 7 - i;
    return connector(`PCIE${number}`, `PCIE${number}`, "Expansion", 145, 475 + i * 49, 245, 29,
      `PCIe expansion slot. RTX 2070 SUPER and an HBA are installed, but their slots are unknown.${number === 2 ? " PCIE2 lane selection interacts with M2_1, SATA_4_7 and OCuLink; document jumper positions without changing them." : ""}`);
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

function observation(target, confidence, occupancy, provenance, evidence, note = "") {
  return { target, confidence, occupancy, provenance, evidence: `${snapshotDate}: ${evidence}`, note, updatedAt: null };
}

export const inspectionConnections = {
  M2_1: observation("NVMe SSD; logical A/B identity unknown", "confirmed", "occupied", "photo-confirmed",
    "Cleaning photos show both M.2 sockets populated, with no heatsinks. Relayed by the coordinating session."),
  M2_2: observation("NVMe SSD; logical A/B identity unknown", "confirmed", "occupied", "photo-confirmed",
    "Cleaning photos show both M.2 sockets populated, with no heatsinks. Relayed by the coordinating session."),
  SATA_0_3: observation("SATA breakout cable; drive routing unknown", "confirmed", "occupied", "photo-confirmed",
    "Connector appears cabled in the cleaning photos, as relayed by the coordinating session."),
  SATA_4_7: observation("SATA breakout cable; drive routing unknown", "confirmed", "occupied", "photo-confirmed",
    "Connector appears cabled in the cleaning photos, as relayed by the coordinating session."),
  GFX_12V1: observation("", "inferred", "free", "photo-uncertain",
    "Appears empty in the cleaning photos, but this is not certain.", "Not a verified-free connector."),
  PCIE1: observation("Low-profile HBA — reported slot, UNVERIFIED", "unknown", "unverified", "user-reported",
    "User reports HBA in PCIE1; slot-label photo pending.",
    "A dual-slot GPU reported in PCIE2 could overlap PCIE1. Do not resolve the slot assignment from that report alone. Photos confirm a low-profile HBA with two SFF-8643 cables below the GPU's fan side."),
  PCIE2: observation("GV-N2070SGAMING OC-8GD — reported slot, UNVERIFIED", "unknown", "unverified", "user-reported",
    "User reports GPU in PCIE2; slot-label photo pending.",
    "A dual-slot GPU here could overlap the HBA's reported PCIE1 position. Photos confirm the GPU label and its fan side directly above the HBA, not the slot numbers."),
  ...Object.fromEntries(["A", "B", "G", "H"].map(letter => [
    `DDR4_${letter}1`, observation("ECC DDR4 DIMM", "inferred", "occupied", "user-reported",
      "User reports DIMMs in A1, B1, G1 and H1; independent socket-label verification pending."),
  ])),
  FAN1: observation("NH-U9 cooler fan — first of two", "inferred", "occupied", "user-reported",
    "User reports the two NH-U9 fans on FAN1 and FAN2. BMC tach readings are consistent but do not independently establish the wiring."),
  FAN2: observation("NH-U9 cooler fan — second of two", "inferred", "occupied", "user-reported",
    "User reports the two NH-U9 fans on FAN1 and FAN2. BMC tach readings are consistent but do not independently establish the wiring."),
  ...Object.fromEntries([3, 4, 5, 6, 7].map(number => [
    `FAN${number}`, observation("", "unknown", "unverified", "unverified",
      "No BMC tach reading; occupancy remains unknown.",
      `${number >= 4 ? "Hidden under the GPU. " : ""}The user suspects these headers are empty, but no reading is not evidence that a header is free. The front/middle fan chain endpoint is unknown.`),
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
  { id: "memory", label: "Memory", model: "ECC DDR4 · A1 / B1 / G1 / H1 reported", capacity: "128 GB reported", status: "User-reported; socket labels not independently verified" },
  { id: "gpu", label: "Graphics", model: "GV-N2070SGAMING OC-8GD rev 1.0", capacity: "RTX 2070 SUPER · 8 GB VRAM", status: "Photo-confirmed label (relayed)", note: "Fan side directly above the low-profile HBA: photo-confirmed. PCIE2 is user-reported and UNVERIFIED; potential PCIE1 overlap needs a slot-label photo." },
  { id: "nvme-a", label: "NVMe A", model: "Samsung 990 EVO · logical socket binding unknown", capacity: "2 TB nominal", status: "Both M.2 sockets photo-confirmed populated; no heatsinks" },
  { id: "nvme-b", label: "NVMe B", model: "Samsung 990 EVO · logical socket binding unknown", capacity: "2 TB nominal", status: "Both M.2 sockets photo-confirmed populated; no heatsinks" },
  { id: "disks", label: "Disk array", model: "12 × WD80EFPX · 8 onboard / 4 HBA", capacity: "11 active + 1 hot spare · RAID6", status: "Reported installed" },
  { id: "hba", label: "Storage HBA", model: "Low-profile HBA · two SFF-8643 cables", capacity: "4 connected HDDs reported", status: "Photo-confirmed appearance (relayed); model unknown", note: "PCIE1 is user-reported and UNVERIFIED; the GPU's reported PCIE2 position could overlap it." },
  { id: "case-fans", label: "Front + middle fans", model: "3 front + 3 middle · likely 120 mm", capacity: "6 fans reported daisy-chained", status: "User-reported; size not verified", note: "Where the chain ends is unknown. No motherboard header, power source or control group is assigned." },
  { id: "rear-fans", label: "Rear fans", model: "2 × 80 mm · Molex-powered", capacity: "Fixed speed · no tach connection reported", status: "User-reported", note: "Not assigned to FAN1–FAN7; no RPM value is invented." },
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
