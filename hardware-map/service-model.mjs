export const columns = [
  { id: "cpu", label: "CPU", unit: "%", note: "Share of all host logical CPUs. One busy thread on 32 threads is 3.125%." },
  { id: "memory", label: "Memory", unit: "bytes", note: "Container working set (usage minus inactive file cache). Process rows use RSS; shared pages mean children need not sum to the container." },
  { id: "memoryPercent", label: "Memory %", unit: "%", note: "Share of host RAM, not the container limit." },
  { id: "disk", label: "Disk", unit: "B/s", note: "Read + write block-device throughput, not drive busy %. RAID/LVM parent layers are excluded. Process I/O is kernel-accounted bytes and may differ because of buffering/writeback." },
  { id: "diskRead", label: "Disk read", unit: "B/s", note: "Storage reads per second; not logical application read() traffic." },
  { id: "diskWrite", label: "Disk write", unit: "B/s", note: "Storage writes per second; buffering can delay attribution." },
  { id: "network", label: "Network", unit: "bit/s", note: "Receive + send on Docker namespace interfaces, excluding tunnel duplicates. Not uplink utilization; shared namespaces are counted only on their owner." },
  { id: "rx", label: "Receive", unit: "bit/s", note: "Inbound Docker network namespace throughput. Not attributable to individual processes without extra instrumentation." },
  { id: "tx", label: "Send", unit: "bit/s", note: "Outbound Docker network namespace throughput. Traffic between containers is not Internet traffic." },
  { id: "gpu", label: "GPU compute", unit: "%", note: "NVIDIA per-process SM activity, summed within the container; not a host GPU reading or a generic 3D engine." },
  { id: "gpuEncode", label: "GPU encode", unit: "%", note: "NVIDIA per-process video encoder activity, when supported." },
  { id: "gpuDecode", label: "GPU decode", unit: "%", note: "NVIDIA per-process video decoder activity, when supported." },
  { id: "vram", label: "GPU memory", unit: "bytes", note: "NVIDIA per-process framebuffer allocation. Unavailable is not zero." },
];
export const defaults = ["cpu", "memory", "disk", "network"];
export const preferenceKey = "chasex.services.columns.v1";
const known = new Set(columns.map(column => column.id));

export function selectedColumns(value) {
  if (!Array.isArray(value) || !value.length || value.some(id => !known.has(id)) || new Set(value).size !== value.length) {
    throw new Error("Saved service columns are invalid");
  }
  return [...value];
}

export function moveColumn(value, id, offset) {
  const result = selectedColumns(value), index = result.indexOf(id), target = index + offset;
  if (index >= 0 && target >= 0 && target < result.length) [result[index], result[target]] = [result[target], result[index]];
  return result;
}

export function placeColumn(value, id, index) {
  const result = selectedColumns(value), from = result.indexOf(id);
  if (from < 0) return result;
  result.splice(from, 1);
  result.splice(Math.max(0, Math.min(result.length, index)), 0, id);
  return result;
}

export function metricValue(row, id) {
  const values = row.values ?? {};
  const pair = id === "disk" ? ["diskRead", "diskWrite"] : id === "network" ? ["rx", "tx"] : null;
  const valid = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  if (pair) return pair.every(key => valid(values[key])) ? values[pair[0]] + values[pair[1]] : null;
  return valid(values[id]) ? values[id] : null;
}

export function sortRows(rows, id, direction = -1) {
  return [...rows].sort((a, b) => {
    if (id === "name") return direction * a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
    const left = metricValue(a, id), right = metricValue(b, id);
    if (left === null || right === null) return left === right ? a.name.localeCompare(b.name) : left === null ? 1 : -1;
    return direction * (left - right) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
  });
}

export function formatValue(value, unit) {
  if (value === null || !Number.isFinite(value)) return "\u2014";
  if (unit === "%") return `${value.toFixed(1)}%`;
  if (unit === "bit/s") {
    value *= 8;
    const index = value >= 1e9 ? 3 : value >= 1e6 ? 2 : value >= 1e3 ? 1 : 0;
    return `${(value / 1000 ** index).toFixed(index ? 1 : 0)} ${["bit/s", "kbit/s", "Mbit/s", "Gbit/s"][index]}`;
  }
  const index = value >= 1024 ** 3 ? 3 : value >= 1024 ** 2 ? 2 : value >= 1024 ? 1 : 0;
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${["B", "KiB", "MiB", "GiB"][index]}${unit === "B/s" ? "/s" : ""}`;
}
