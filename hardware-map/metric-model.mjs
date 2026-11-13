import { linuxSnapshot } from "./linux-snapshot.mjs";
import { buildLinuxTopology, linuxNodeSummary } from "./model.mjs";

export const metricGroups = {
  cpu: { label: "CPU", color: "#e9b18b" },
  memory: { label: "Memory", color: "#b9a2df" },
  storage: { label: "Storage", color: "#81bddf" },
  gpu: { label: "GPU", color: "#c5d58b" },
  network: { label: "Network", color: "#77d7c1" },
  temperatures: { label: "Temps", color: "#e7a47f" },
  fans: { label: "Fans", color: "#becbd3" },
};
export const demoProfiles = { mixed: "Mixed workload", idle: "Mostly idle", transcode: "Transcode", transfer: "Storage transfer" };
export let metricTopology = buildLinuxTopology(linuxSnapshot);
let topology = metricTopology;
export const cpuClockSpecification = { base: 3, boost: 3.7 };
export const historyWindows = [60, 120, 300, 900, 1800, 3600, 7200, 21600, 86400];
export const defaultHistoryWindows = { cpu: 120, gpu: 120, network: 120, memory: 900, storage: 7200, temperatures: 1800, fans: 300 };
export const historyLabel = seconds => seconds >= 3600 ? `${seconds / 3600}h` : `${seconds / 60}m`;
export function placeMetricCard(card, viewport, occupied) {
  const gap = 10;
  const right = Math.max(gap, viewport.width - card.width - gap);
  const bottom = Math.max(gap, viewport.height - card.height - gap);
  const clamp = point => ({ x: Math.max(gap, Math.min(right, point.x)), y: Math.max(gap, Math.min(bottom, point.y)) });
  const preferred = clamp(card);
  const overlap = point => occupied.reduce((area, rect) => area +
    Math.max(0, Math.min(point.x + card.width + gap, rect.x + rect.width) - Math.max(point.x - gap, rect.x)) *
    Math.max(0, Math.min(point.y + card.height + gap, rect.y + rect.height) - Math.max(point.y - gap, rect.y)), 0);
  let best = preferred, bestArea = overlap(best), bestDistance = 0;
  if (!bestArea) return best;
  function consider(point) {
    const candidate = clamp(point);
    const distance = (candidate.x - preferred.x) ** 2 + (candidate.y - preferred.y) ** 2;
    if (!bestArea && distance >= bestDistance) return;
    const area = overlap(candidate);
    if (area < bestArea || area === bestArea && distance < bestDistance) {
      best = candidate; bestArea = area; bestDistance = distance;
    }
  }
  for (const rect of occupied) {
    for (const x of [rect.x - card.width - gap, rect.x + rect.width + gap]) {
      for (const y of [preferred.y, rect.y, rect.y + rect.height - card.height]) consider({ x, y });
    }
    for (const y of [rect.y - card.height - gap, rect.y + rect.height + gap]) consider({ x: preferred.x, y });
  }
  for (let x = gap; x < right + 32; x += 32) {
    for (let y = gap; y < bottom + 32; y += 32) consider({ x, y });
  }
  return best;
}
export const temperatureLevels = [
  { label: "Cold", icon: "❄", color: "#83c9f4" }, { label: "Cool", icon: "◌", color: "#72d3cc" },
  { label: "Moderate", icon: "●", color: "#b5d590" }, { label: "Warm", icon: "☀", color: "#eac26f" },
  { label: "Hot", icon: "▲", color: "#ee936b" }, { label: "Dangerous", icon: "⚠", color: "#ff717f" },
];
export function temperatureLevel(id, value) {
  if (!Number.isFinite(value)) return { label: "Unavailable", icon: "?", color: "#93aab9" };
  const boundaries = id.startsWith("temp-sd") ? [20, 30, 40, 45, 55]
    : id.includes("secondary") ? [30, 50, 70, 85, 100]
      : id === "temp-lan" ? [30, 45, 65, 80, 95] : [25, 40, 55, 70, 85];
  return temperatureLevels[boundaries.filter(boundary => value >= boundary).length];
}
export function sharedMetricScale(ids) {
  const definitions = ids.map(id => metrics.get(id));
  if (!definitions.length || definitions.some(definition => !definition) || new Set(definitions.map(definition => definition.unit)).size !== 1) throw new Error("A shared axis needs compatible metric units.");
  return { minimum: Math.min(...definitions.map(d => d.minimum)), maximum: Math.max(...definitions.map(d => d.maximum)), unit: definitions[0].unit };
}
export function chartNumber(value, scale) {
  if (!Number.isFinite(value)) return "Unavailable";
  const factor = ["Mb/s", "MB/s"].includes(scale.unit) && scale.maximum >= 1000 ? 1000 : 1;
  const unit = factor === 1 ? scale.unit : scale.unit === "Mb/s" ? "Gb/s" : "GB/s";
  return `${(value / factor).toLocaleString("en", { maximumFractionDigits: factor === 1000 ? 3 : unit === "RPM" ? 0 : 1 })}${unit ? ` ${unit}` : ""}`;
}
export function storageDetails(id) {
  const node = topology.nodes.get(id);
  if (!node) throw new Error(`Unknown storage device: ${id}`);
  const descendants = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const candidate of topology.nodes.values()) if (!descendants.has(candidate.id) && candidate.parents.some(parent => descendants.has(parent.id))) {
      descendants.add(candidate.id); changed = true;
    }
  }
  return { node, role: linuxNodeSummary(topology, id), layers: [...descendants].filter(child => child !== id).map(child => topology.nodes.get(child)) };
}
export const demoDisks = [...topology.nodes.values()].filter(node => ["Physical HDD", "Physical NVMe"].includes(node.kind));
export const demoNics = ["bond0", "enp66s0f0", "enp66s0f1"];
export const metrics = new Map();
function metric(id, label, unit, maximum, group, extra = {}) {
  metrics.set(id, { id, label, unit, maximum, minimum: 0, group, provenance: "synthetic", ...extra });
}
metric("cpu", "CPU utilization", "%", 100, "cpu");
metric("cpu-clock", "CPU clock", "GHz", 4, "cpu");
metric("cpu-power", "CPU package power", "W", 200, "cpu");
for (let i = 0; i < 32; i += 1) metric(`thread-${i}`, `Logical CPU ${i}`, "%", 100, "cpu");
for (let i = 0; i < 16; i += 1) metric(`core-${i}`, `Core ${i}`, "%", 100, "cpu");
for (const [id, label] of [["used", "Total RAM in use"], ["apps", "Applications"], ["cache", "File cache / reclaimable"], ["kernel", "Kernel"], ["free", "Free"]]) {
  metric(`memory-${id}`, label, "GiB", 128, "memory");
}
metric("swap", "Swap used", "GiB", 119.2, "memory");
metric("gpu-util", "GPU activity", "%", 100, "gpu");
for (const engine of ["3d", "copy", "encode", "decode"]) metric(`gpu-${engine}`, { "3d": "3D / graphics", copy: "Copy engine", encode: "Video encode", decode: "Video decode" }[engine], "%", 100, "gpu");
metric("gpu-dedicated", "Dedicated GPU memory", "GiB", 8, "gpu");
metric("gpu-shared", "Shared / host GPU allocations", "GiB", 8, "gpu", { note: "Illustrative host allocations, not a measured Linux shared-memory pool or an 8 GiB limit." });
metric("gpu-power", "GPU power", "W", 250, "gpu");
for (const id of ["array", ...demoDisks.map(disk => disk.id)]) {
  metric(`disk-${id}-active`, "Disk active time", "%", 100, "storage");
  metric(`disk-${id}-read`, "Read", "MB/s", id.startsWith("nvme") ? 2500 : id === "array" ? 2200 : 240, "storage");
  metric(`disk-${id}-write`, "Write", "MB/s", id.startsWith("nvme") ? 2500 : id === "array" ? 2200 : 240, "storage");
  metric(`disk-${id}-latency`, "Response time", "ms", id.startsWith("nvme") ? 5 : 60, "storage");
  metric(`disk-${id}-queue`, "Queue depth", "", 16, "storage");
}
metric("data-used", "/data used", "TiB", 65.51, "storage");
metric("root-used", "Root filesystem used", "TiB", 1.7, "storage");
metric("cache-used", "Cache occupancy", "TiB", topology.nodes.get("dm-2").sizeBytes / 2 ** 40, "storage");
for (const id of demoNics) {
  metric(`net-${id}-rx`, "Receive", "Mb/s", 10000, "network");
  metric(`net-${id}-tx`, "Send", "Mb/s", 10000, "network");
}
const sensorLocations = {
  cpu: "CPU: internal processor sensors beneath the cooler, not an air probe. Tctl is a cooling-control reading and must not automatically be equated with Tdie or the BMC CPU channel.",
  gpu: "GPU: core temperature belongs to the GPU silicon beneath its cooler, not case air.",
  motherboard: "Motherboard: the physical location of the BMC MB Temp sensor is unknown. This badge is a board reference marker, not a located probe.",
  "lan-controller": "LAN: the badge references the onboard Intel X550 controller, schematically placed using the official motherboard layout. The BMC Onboard LAN Temp sensor's exact implementation/location is unverified; this is not an RJ45 or per-port temperature.",
  "nvme-group": "NVMe: each SSD has its own SMART temperature information. Composite temperature need not identify one physical probe; optional secondary channels need vendor interpretation. These secondary channels are illustrative. Linux-device-to-M.2-socket bindings remain unknown, so the badge stays with the two-drive group.",
  "disk-bays": "HDDs: individual drives can expose internal SMART temperatures where the drive/controller supports them. Exact internal probe positions and Linux-device-to-bay bindings remain unknown; the badge shows a group range rather than assigning temperatures to bays.",
};
export const demoSensors = [
  ["temp-cpu", "CPU Tctl", "cpu"],
  ["temp-gpu", "GPU core", "gpu"],
  ["temp-board", "Motherboard", "motherboard"],
  ["temp-lan", "LAN controller", "lan-controller"],
  ["temp-nvme0", "nvme0n1 composite · socket unbound", "nvme-group"],
  ["temp-nvme0-secondary", "nvme0n1 secondary · illustrative", "nvme-group"],
  ["temp-nvme1", "nvme1n1 composite · socket unbound", "nvme-group"],
  ["temp-nvme1-secondary", "nvme1n1 secondary · illustrative", "nvme-group"],
  ...demoDisks.filter(disk => disk.kind === "Physical HDD").map(disk => [`temp-${disk.id}`, `${disk.label} · bay unbound`, "disk-bays"]),
].map(([id, label, anchor]) => ({ id, label, anchor, location: sensorLocations[anchor] }));
for (const sensor of demoSensors) metric(sensor.id, sensor.label, "°C", 110, "temperatures", { minimum: 20 });
export const demoFans = [
  ["fan-cpu1", "CPU FAN1 · PSU side", "cpu"],
  ["fan-cpu2", "CPU FAN2 · GPU side", "cpu"],
  ["fan-hub", "FAN3 · shared six-fan speed assumption", "fan-hub"],
  ["fan-rear1", "Rear 1 · assumed constant 2000 RPM", "rear-fan-1"],
  ["fan-rear2", "Rear 2 · assumed constant 2000 RPM", "rear-fan-2"],
  ["fan-gpu", "GPU fan speed · percent, physical channels unbound", "gpu", "%"],
].map(([id, label, anchor, unit = "RPM"]) => ({ id, label, anchor, unit }));
for (const fan of demoFans) metric(fan.id, fan.label, fan.unit, fan.unit === "%" ? 100 : 2200, "fans");

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const hash = id => [...id].reduce((value, char) => (value * 31 + char.charCodeAt(0)) >>> 0, 7);
function threadValue(index, second, base) {
  const phase = index * 1.71;
  const burst = ((Math.sin(second / 19 + phase / 3) + 1) / 2) ** 5;
  const sharedLoad = (6 + base * 17) * Math.sin(second / 21) + 8 * ((Math.sin(second / 11) + 1) / 2) ** 6;
  return clamp(base * 100 + sharedLoad + 17 * Math.sin(second / 12 + phase) + 22 * burst + 6 * Math.sin(second / 3.8 + phase), 0, 100);
}
export function demoMemory(second, profile = "mixed") {
  if (!Number.isFinite(second) || second < 0 || !Object.hasOwn(demoProfiles, profile)) throw new Error("Invalid demo clock or workload.");
  const apps = { idle: 20, mixed: 43, transcode: 61, transfer: 31 }[profile] + 3 * Math.sin(second / 72);
  const cache = { idle: 25, mixed: 30, transcode: 22, transfer: 57 }[profile] + 2 * Math.sin(second / 91);
  const kernel = 7 + .7 * Math.sin(second / 49);
  return { apps, cache, kernel, free: 128 - apps - cache - kernel, used: apps + kernel };
}
export function demoValue(id, second, profile = "mixed") {
  if (!metrics.has(id)) throw new Error(`Unknown metric: ${id}`);
  if (!Number.isFinite(second) || second < 0 || !Object.hasOwn(demoProfiles, profile)) throw new Error("Invalid demo clock or workload.");
  const base = { idle: .035, mixed: .36, transcode: .75, transfer: .22 }[profile];
  const bond = linuxSnapshot.bonds.find(node => id.startsWith(`net-${node.id}-`));
  const phase = hash(bond ? id.replace(`net-${bond.id}-`, `net-${bond.activeSlave}-`) : id) % 97;
  const wave = (period = 17) => (Math.sin(second / period + phase) + 1) / 2;
  if (id.startsWith("thread-")) return threadValue(Number(id.slice(7)), second, base);
  if (id.startsWith("core-")) {
    const index = Number(id.slice(5)) * 2;
    return (threadValue(index, second, base) + threadValue(index + 1, second, base)) / 2;
  }
  if (id === "cpu") return Array.from({ length: 32 }, (_, i) => threadValue(i, second, base)).reduce((a, b) => a + b) / 32;
  if (id === "cpu-clock") return 2.45 + base * .9 + .09 * wave();
  if (id === "cpu-power") return 48 + base * 125 + 8 * wave();
  if (id.startsWith("memory-")) return demoMemory(second, profile)[id.slice(7)];
  if (id === "swap") return .7 + base + .12 * wave(75);
  if (id === "data-used") return 52.3 + .03 * Math.sin(second / 300);
  if (id === "root-used") return 1.08 + .002 * Math.sin(second / 300);
  if (id === "cache-used") return 1.15 + .12 * Math.sin(second / 600);
  if (id.startsWith("gpu-")) {
    const load = { idle: 2, mixed: 43, transcode: 78, transfer: 10 }[profile];
    if (id === "gpu-dedicated") return clamp(1.2 + load * .068 + .2 * wave(38), 0, 8);
    if (id === "gpu-shared") return .15 + load * .017 + .1 * wave(30);
    if (id === "gpu-power") return 32 + load * 1.9 + 12 * wave(30);
    const factor = { "gpu-util": .95, "gpu-3d": .8, "gpu-copy": .42, "gpu-encode": profile === "transcode" ? 1.08 : .65, "gpu-decode": .68 }[id];
    return clamp(load * factor + 17 * wave(10) - 6, 0, 100);
  }
  if (id.startsWith("disk-")) {
    const [, device, field] = id.split("-");
    const node = topology.nodes.get(device);
    const standby = node?.memberships.some(member => member.state === "spare" && member.slot === null);
    const load = standby ? .001 : { idle: .025, mixed: .35, transcode: .63, transfer: .86 }[profile];
    const active = clamp(load * (.65 + .35 * wave(13)) * 100, 0, 100);
    if (field === "active") return active;
    if (field === "latency") return device.startsWith("nvme") ? .15 + active / 150 : 3 + active * .32 + 3 * wave(7);
    if (field === "queue") return active / 12 + wave(7);
    return active / 100 * metrics.get(id).maximum * (field === "read" ? .75 : .38) * (.4 + .6 * wave(field === "read" ? 11 : 19));
  }
  if (id.startsWith("net-")) {
    const standby = topology.nodes.get(id.slice(4, -3))?.bondRole?.startsWith("Standby");
    const load = standby ? .0003 : { idle: .002, mixed: .15, transcode: .08, transfer: .72 }[profile];
    return load * 10000 * (.4 + .6 * wave(15)) * (id.endsWith("-tx") ? .48 : 1);
  }
  if (id.startsWith("temp-")) {
    if (id === "temp-cpu") return 41 + base * 43 + 2 * wave(38);
    if (id === "temp-gpu") return 39 + { idle: 2, mixed: 19, transcode: 33, transfer: 7 }[profile] + 2 * wave(40);
    if (id === "temp-board") return 35 + base * 8 + wave(50);
    if (id === "temp-lan") return 57 + 6 * wave(60);
    if (id.includes("nvme")) return (id.endsWith("secondary") ? 66 : 42) + base * 12 + 3 * wave(47);
    return 32 + base * 8 + 5 * wave(60);
  }
  if (id.startsWith("fan-")) {
    if (id === "fan-gpu") return { idle: 0, mixed: 42, transcode: 68, transfer: 27 }[profile] + (profile === "idle" ? 0 : 7 * wave(35));
    if (id.startsWith("fan-rear")) return 2000;
    return (id === "fan-hub" ? 650 : 850) + base * 900 + 35 * wave(35);
  }
  throw new Error(`No synthetic generator for ${id}`);
}

export function demoSeries(id, second, seconds = 120, profile = "mixed") {
  if (!historyWindows.includes(seconds)) throw new Error("Unsupported history window.");
  const samples = Math.min(seconds, 300);
  return Array.from({ length: samples + 1 }, (_, index) => demoValue(id, Math.max(0, second - seconds + index / samples * seconds), profile));
}
export function metricPath(values, minimum, maximum, width = 300, height = 80) {
  if (![minimum, maximum, width, height].every(Number.isFinite) || !(maximum > minimum) || width <= 0 || height <= 0 || values.length < 2) throw new Error("Invalid chart bounds.");
  let connected = false;
  return values.map((value, index) => {
    if (!Number.isFinite(value)) { connected = false; return ""; }
    const x = index / (values.length - 1) * width;
    const y = height - clamp((value - minimum) / (maximum - minimum), 0, 1) * height;
    const command = connected ? "L" : "M";
    connected = true;
    return `${command}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}
export function metricNumber(value, unit) {
  if (!Number.isFinite(value)) return "Unavailable";
  if (unit === "Mb/s" && value >= 1000) return metricNumber(value / 1000, "Gb/s");
  if (unit === "MB/s" && value >= 1000) return metricNumber(value / 1000, "GB/s");
  return `${value.toLocaleString("en", { maximumFractionDigits: unit === "RPM" ? 0 : 1 })}${unit ? ` ${unit}` : ""}`;
}

export const metricCards = [
  { id: "cpu", group: "cpu", label: "EPYC · 16C / 32T", anchor: "cpu", x: 585, y: 535, series: ["cpu"], footer: ["cpu-clock", "cpu-power"] },
  { id: "memory", group: "memory", label: "System memory · 128 GiB", anchor: "dimm-DDR4_A1", x: 1450, y: 480, series: ["memory-used"], footer: ["memory-cache"] },
  { id: "gpu", group: "gpu", label: "RTX 2070 SUPER", anchor: "gpu", x: 585, y: 130, series: ["gpu-util", "gpu-encode"], footer: ["gpu-dedicated"] },
  { id: "storage", group: "storage", label: "HDD set · /data", anchor: "disk-bays", x: -220, y: 300, series: ["disk-array-read", "disk-array-write"], footer: [], fullness: "data-used", device: "array" },
  { id: "nvme-root", group: "storage", label: "nvme0n1 · root + swap", anchor: "nvme-group", x: 1450, y: 0, series: ["disk-nvme0n1-read", "disk-nvme0n1-write"], footer: [], fullness: "root-used", device: "nvme0n1" },
  { id: "nvme", group: "storage", label: "nvme1n1 · /data cache + extents", anchor: "nvme-group", x: 1450, y: 240, series: ["disk-nvme1n1-read", "disk-nvme1n1-write"], footer: [], fullness: "cache-used", device: "nvme1n1" },
  { id: "network", group: "network", label: "bond0 · 10GbE active-backup", anchor: "network-ports", x: 585, y: -80, series: ["net-bond0-rx", "net-bond0-tx"], footer: [] },
  { id: "temperatures", group: "temperatures", label: "Component temperatures", anchor: "motherboard", x: 820, y: 660, series: ["temp-cpu", "temp-gpu"], footer: [], mobileOnly: true },
  { id: "fans", group: "fans", label: "Fan speeds · synthetic", anchor: "fan-hub", x: 440, y: 705, series: ["fan-hub"], footer: [], mobileOnly: true },
];
export const metricBadges = [
  { id: "temp-cpu", group: "temperatures", label: "CPU Tctl", anchor: "cpu", x: 991, y: 480, align: "end" },
  { id: "temp-gpu", group: "temperatures", label: "GPU", anchor: "gpu", x: 1100, y: 195 },
  { id: "temp-board", group: "temperatures", label: "Board · site?", anchor: "motherboard", x: 820, y: 610 },
  { id: "temp-lan", group: "temperatures", label: "X550", anchor: "lan-controller", x: 1310, y: 338, align: "end" },
  { id: "temp-nvme-range", ids: ["temp-nvme0", "temp-nvme1"], group: "temperatures", label: "NVMe group*", anchor: "nvme-group", x: 958, y: 332 },
  { id: "temp-hdd-range", ids: demoDisks.filter(disk => disk.kind === "Physical HDD").map(disk => `temp-${disk.id}`), group: "temperatures", label: "HDD group*", anchor: "disk-bays", x: 185, y: 105 },
  { id: "fan-cpu1", group: "fans", label: "FAN1 · PSU", anchor: "cpu", x: 1089.4, y: 536, align: "center" },
  { id: "fan-cpu2", group: "fans", label: "FAN2 · GPU", anchor: "cpu", x: 1089.4, y: 424, align: "center" },
  { id: "fan-front-bank", metricId: "fan-hub", previewBank: "hub", group: "fans", label: "Front ×3", anchor: "front-fan-1", x: 107, y: 136, align: "center" },
  { id: "fan-middle-bank", metricId: "fan-hub", previewBank: "hub", group: "fans", label: "Middle ×3", anchor: "middle-fan-1", x: 487, y: 136, align: "center" },
  { id: "fan-rear-bank", metricId: "fan-rear1", previewBank: "rear", group: "fans", label: "Rear ×2", anchor: "rear-fan-1", x: 1377, y: 610, align: "end" },
  { id: "fan-gpu", group: "fans", label: "GPU fans", anchor: "gpu", x: 1275, y: 248, align: "end" },
];

export function applyLiveSnapshot(data) {
  metrics.get("memory-apps").label = "Other / anonymous (residual)";
  for (const sensor of demoSensors) {
    if (sensor.id.startsWith("temp-nvme")) {
      sensor.label = `${sensor.id.slice(5)} · SMART ${sensor.id.endsWith("secondary") ? "sensor 1 (vendor meaning unverified)" : "composite"}`;
      sensor.location = "NVMe: each drive reports its own SMART temperature information; composite and optional sensor 1 do not establish controller/NAND probe positions. Socket assignments are provisional serial-sorted placeholders, NOT physically verified.";
      metrics.get(sensor.id).label = sensor.label;
    }
  }
  if (data.inventory?.snapshot) {
    const next = buildLinuxTopology(data.inventory.snapshot);
    topology = next;
    metricTopology = next;
    demoDisks.splice(0, demoDisks.length, ...[...next.nodes.values()].filter(node => ["Physical HDD", "Physical NVMe"].includes(node.kind)));
    demoNics.splice(0, demoNics.length, ...[...next.nodes.values()].filter(node => ["Linux network bond", "Physical 10GbE interface", "Physical network interface"].includes(node.kind)).map(node => node.id));
  }
  for (const [id, capacity] of Object.entries(data.capacities ?? {})) {
    if (metrics.has(id) && Number.isFinite(capacity) && capacity > 0) metrics.get(id).maximum = capacity;
  }
  for (const disk of demoDisks) {
    for (const [field, unit, maximum] of [["read", "MB/s", 2500], ["write", "MB/s", 2500], ["active", "%", 100], ["latency", "ms", 60], ["queue", "", 16]]) {
      const id = `disk-${disk.id}-${field}`;
      if (!metrics.has(id)) metric(id, field, unit, maximum, "storage");
    }
  }
  for (const id of demoNics) for (const direction of ["rx", "tx"]) {
    if (!metrics.has(`net-${id}-${direction}`)) metric(`net-${id}-${direction}`, direction === "rx" ? "Receive" : "Send", "Mb/s", 10000, "network");
  }
  const bindings = data.inventory?.disks ?? [];
  for (const cardId of ["nvme-root", "nvme"]) {
    const card = metricCards.find(item => item.id === cardId);
    const binding = bindings.find(item => item.kind === "nvme" && item.role === (cardId === "nvme-root" ? "root" : "cache"));
    if (!binding) {
      card.device = undefined;
      card.label = `${cardId === "nvme-root" ? "Root NVMe" : "Data/cache NVMe"} · inventory unavailable`;
      card.anchor = "nvme-group";
      continue;
    }
    card.device = binding.id;
    card.label = `${binding.id} · ${cardId === "nvme-root" ? "root + swap" : "/data cache + extents"} · provisional`;
    card.series = [`disk-${binding.id}-read`, `disk-${binding.id}-write`];
    card.anchor = binding.slot ? `drive-${binding.slot}` : "nvme-group";
  }
  const hdds = metricBadges.find(item => item.id === "temp-hdd-range");
  hdds.ids = bindings.filter(item => item.kind === "hdd").map(item => `temp-${item.id}`);
  for (const id of Object.keys(data.metrics ?? {})) {
    if (id.startsWith("temp-") && !metrics.has(id)) {
      metric(id, id, "°C", 110, "temperatures", { minimum: 20 });
      demoSensors.push({ id, label: id, anchor: id.startsWith("temp-sd") ? "disk-bays" : "nvme-group", location: id.startsWith("temp-sd") ? sensorLocations["disk-bays"] : sensorLocations["nvme-group"] });
    }
  }
}
