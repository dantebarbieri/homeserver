import { linuxSnapshot } from "./linux-snapshot.mjs";
import { buildLinuxTopology } from "./model.mjs";

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
const topology = buildLinuxTopology(linuxSnapshot);
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
for (const [id, label] of [["used", "In use · apps + kernel"], ["apps", "Applications"], ["cache", "File cache / reclaimable"], ["kernel", "Kernel"], ["free", "Free"]]) {
  metric(`memory-${id}`, label, "GiB", 128, "memory");
}
metric("swap", "Swap used", "GiB", 119.2, "memory");
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
for (const id of demoNics) {
  metric(`net-${id}-rx`, "Receive", "Mb/s", 10000, "network");
  metric(`net-${id}-tx`, "Send", "Mb/s", 10000, "network");
}
export const demoSensors = [
  ["temp-cpu", "CPU Tctl", "cpu"],
  ["temp-gpu", "GPU core", "gpu"],
  ["temp-board", "Motherboard", "motherboard"],
  ["temp-lan", "LAN controller", "network-ports"],
  ["temp-nvme0", "nvme0n1 composite · socket unbound", "nvme-group"],
  ["temp-nvme0-secondary", "nvme0n1 secondary · illustrative", "nvme-group"],
  ["temp-nvme1", "nvme1n1 composite · socket unbound", "nvme-group"],
  ["temp-nvme1-secondary", "nvme1n1 secondary · illustrative", "nvme-group"],
  ...demoDisks.filter(disk => disk.kind === "Physical HDD").map(disk => [`temp-${disk.id}`, `${disk.label} · bay unbound`, "disk-bays"]),
].map(([id, label, anchor]) => ({ id, label, anchor }));
for (const sensor of demoSensors) metric(sensor.id, sensor.label, "°C", 110, "temperatures", { minimum: 20 });
export const demoFans = [
  ["fan-cpu1", "CPU FAN1", "cpu"],
  ["fan-cpu2", "CPU FAN2", "cpu"],
  ["fan-hub", "FAN3 hub · one tach", "fan-hub"],
  ["fan-rear1", "Rear 1 · invented, no tach", "rear-fan-1"],
  ["fan-rear2", "Rear 2 · invented, no tach", "rear-fan-2"],
].map(([id, label, anchor]) => ({ id, label, anchor }));
for (const fan of demoFans) metric(fan.id, fan.label, "RPM", 2200, "fans");

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
  if (id.startsWith("gpu-")) {
    const load = { idle: 2, mixed: 43, transcode: 78, transfer: 10 }[profile];
    if (id === "gpu-dedicated") return clamp(1.2 + load * .068 + .2 * wave(38), 0, 8);
    if (id === "gpu-shared") return .15 + load * .017 + .1 * wave(30);
    if (id === "gpu-power") return 32 + load * 1.9 + 12 * wave(30);
    const factor = { "gpu-3d": .8, "gpu-copy": .42, "gpu-encode": profile === "transcode" ? 1.08 : .65, "gpu-decode": .68 }[id];
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
    if (id.startsWith("fan-rear")) return 1950 + 8 * wave(70);
    return (id === "fan-hub" ? 650 : 850) + base * 900 + 35 * wave(35);
  }
  throw new Error(`No synthetic generator for ${id}`);
}

export function demoSeries(id, second, seconds = 120, profile = "mixed") {
  if (![60, 120, 300].includes(seconds)) throw new Error("Unsupported history window.");
  return Array.from({ length: seconds + 1 }, (_, index) => demoValue(id, Math.max(0, second - seconds + index), profile));
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
  { id: "memory", group: "memory", label: "System memory · 128 GiB", anchor: "dimm-DDR4_A1", x: 585, y: 330, series: ["memory-used"], footer: ["memory-cache"] },
  { id: "gpu", group: "gpu", label: "RTX 2070 SUPER", anchor: "gpu", x: 585, y: 130, series: ["gpu-3d", "gpu-encode"], footer: ["gpu-dedicated"] },
  { id: "storage", group: "storage", label: "HDD set · /data", anchor: "disk-bays", x: 180, y: 705, series: ["disk-array-read", "disk-array-write"], footer: ["data-used"] },
  { id: "nvme", group: "storage", label: "nvme1n1 · socket unbound", anchor: "nvme-group", x: 850, y: 270, series: ["disk-nvme1n1-read", "disk-nvme1n1-write"], footer: ["disk-nvme1n1-active"] },
  { id: "network", group: "network", label: "bond0 · 10GbE active-backup", anchor: "network-ports", x: 1100, y: 270, series: ["net-bond0-rx", "net-bond0-tx"], footer: [] },
  { id: "temperatures", group: "temperatures", label: "Component temperatures", anchor: "motherboard", x: 820, y: 660, series: ["temp-cpu", "temp-gpu"], footer: [], mobileOnly: true },
  { id: "fans", group: "fans", label: "Fan speeds · synthetic", anchor: "fan-hub", x: 440, y: 705, series: ["fan-hub"], footer: [], mobileOnly: true },
];
export const metricBadges = [
  { id: "temp-cpu", group: "temperatures", label: "CPU", anchor: "cpu", x: 1040, y: 550 },
  { id: "temp-gpu", group: "temperatures", label: "GPU", anchor: "gpu", x: 1100, y: 195 },
  { id: "temp-board", group: "temperatures", label: "Board", anchor: "motherboard", x: 820, y: 610 },
  { id: "temp-lan", group: "temperatures", label: "LAN", anchor: "network-ports", x: 1220, y: 500 },
  { id: "temp-nvme-range", ids: ["temp-nvme0", "temp-nvme1"], group: "temperatures", label: "NVMe group*", anchor: "nvme-group", x: 820, y: 100 },
  { id: "temp-hdd-range", ids: demoDisks.filter(disk => disk.kind === "Physical HDD").map(disk => `temp-${disk.id}`), group: "temperatures", label: "HDD group*", anchor: "disk-bays", x: 185, y: 105 },
  { id: "fan-cpu1", group: "fans", label: "FAN1", anchor: "cpu", x: 985, y: 590 },
  { id: "fan-cpu2", group: "fans", label: "FAN2", anchor: "cpu", x: 1120, y: 590 },
  { id: "fan-hub", group: "fans", label: "Hub", anchor: "fan-hub", x: 580, y: 420 },
  { id: "fan-rear1", group: "fans", label: "Rear*", anchor: "rear-fan-1", x: 1260, y: 630 },
];
