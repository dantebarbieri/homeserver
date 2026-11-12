export const manual = Object.freeze({
  title: "ASRock Rack ROMED8-2T / ROMED8-NL / ROMED8-2T/BCM",
  url: "https://download.asrock.com/Manual/ROMED8-2T.pdf",
  revision: "1.30",
  published: "April 2026",
  sha256: "9ccde5548e447d1e74408a2bfe246450d8291c10bb250fc178df0e310775a613",
});

export const boardId = "asrock-rack-romed8-2t";
export const snapshotDate = "2026-11-12";
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
    "AMD EPYC 7313P installed; Noctua NH-U9 TR4-SP3 cooler. The cooler's fan wiring is not yet verified."),
  ...["H", "G", "F", "E"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 65 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. 128 GB total installed RAM is reported; populated socket identities await inspection.")),
  ...["A", "B", "C", "D"].map((letter, i) =>
    connector(`DDR4_${letter}1`, `DDR4 ${letter}1`, "Memory", 200, 370 + i * 21, 310, 15,
      "DDR4 ECC DIMM socket. Do not infer socket population from the BMC's DDR4 temperature-channel labels.")),
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
];

export const connectorById = new Map(connectors.map(item => [item.id, item]));

export const components = [
  { id: "cpu", label: "CPU + cooler", model: "EPYC 7313P · NH-U9 TR4-SP3", capacity: "16 cores / 32 threads", status: "Reported installed" },
  { id: "memory", label: "Memory", model: "ECC DDR4 · populated slots unknown", capacity: "128 GB reported", status: "Reported installed" },
  { id: "gpu", label: "Graphics", model: "RTX 2070 SUPER · slot unknown", capacity: "8 GB VRAM", status: "Reported installed" },
  { id: "nvme-a", label: "NVMe A", model: "Samsung 990 EVO · socket unknown", capacity: "2 TB nominal", status: "Reported installed" },
  { id: "nvme-b", label: "NVMe B", model: "Samsung 990 EVO · socket unknown", capacity: "2 TB nominal", status: "Reported installed" },
  { id: "disks", label: "Disk array", model: "12 × WD80EFPX · 8 onboard / 4 HBA", capacity: "11 active + 1 hot spare · RAID6", status: "Reported installed" },
  { id: "hba", label: "Storage HBA", model: "Model and PCIe slot unknown", capacity: "4 connected HDDs reported", status: "Reported installed" },
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
  { id: "FAN1", label: "FAN1 · primary tach", value: 1300, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN1; attached physical fan unknown", observedAt: snapshotDate },
  { id: "FAN2", label: "FAN2 · primary tach", value: 1400, unit: "RPM", kind: "fan", provenance: "snapshot", source: "BMC / FAN2; attached physical fan unknown", observedAt: snapshotDate },
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
