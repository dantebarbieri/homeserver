// Older collectors mix permanent documentation into issues. Only these exact
// notes are hidden; unknown messages and collection failures remain visible.
const legacyContextNotes = new Set([
  "Disk placement is provisional/serial-sorted, never physically confirmed.",
  "memory-apps is residual other/anonymous memory, not per-process RSS.",
  "Rear fan 2000 RPM values are ASSUMPTIONS, not measured; FAN3 is one shared six-fan hub reading.",
  "Optional NVMe secondary is SMART temperature sensor 1; vendor-specific physical meaning is unverified.",
  "GPU 3D/copy/shared memory remain unavailable (no supported source).",
  "CPU package power is an energy-counter-derived interval average, not instantaneous or whole-server power.",
  "Cache occupancy is resident cached blocks, not filesystem fullness; a full cache can be normal.",
]);

export function historyValues(points, end, seconds, step) {
  const count = Math.min(300, Math.ceil(seconds / Math.max(1, step)));
  const values = Array(count + 1).fill(null);
  for (const point of points ?? []) {
    if (!Number.isFinite(point.timestamp) || !Number.isFinite(point.value)) continue;
    const index = Math.round((point.timestamp - (end - seconds)) / seconds * count);
    if (index >= 0 && index <= count) values[index] = point.value;
  }
  return values;
}

export class LiveData {
  constructor({ enabled, fetcher = (...args) => globalThis.fetch(...args), clock = () => Date.now() }) {
    this.mode = enabled ? "live" : "demo";
    this.fetcher = fetcher;
    this.clock = clock;
    this.snapshot = null;
    this.error = "";
    this.historyError = "";
    this.listeners = new Set();
    this.histories = new Map();
    this.requests = new Map();
    this.historyErrors = new Map();
    this.historyBatch = false;
    this.generation = 0;
    this.timer = null;
  }
  get stale() {
    return this.mode === "live" && (Boolean(this.error) || !this.snapshot ||
      this.clock() - Date.parse(this.snapshot.capturedAt) > Math.max(20000, this.snapshot.intervalSeconds * 3000));
  }
  get snapshotIssues() {
    return (this.snapshot?.issues ?? []).filter(issue => !legacyContextNotes.has(issue));
  }
  get issues() {
    return [...this.snapshotIssues, this.error, this.historyError].filter(Boolean);
  }
  value(id) {
    const value = this.snapshot?.metrics[id];
    return !this.stale && Number.isFinite(value) ? value : null;
  }
  series(id, seconds) {
    const history = this.histories.get(seconds);
    if (!history) return [null, null];
    return historyValues(history.series[id], history.end, seconds, history.step);
  }
  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  emit() { for (const listener of this.listeners) listener(this.snapshot); }
  async json(path) {
    const response = await this.fetcher(path, { cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(10000) });
    if (!response.ok) {
      // The server explains failures in a small JSON body; proxies may not.
      const reason = await response.json().then(body => typeof body?.error === "string" ? body.error.slice(0, 160) : "", () => "");
      throw new Error(`ChasEx API returned HTTP ${response.status}${reason ? ` (${reason})` : ""}`);
    }
    return response.json();
  }
  async poll() {
    try {
      const snapshot = await this.json("./api/snapshot");
      if (snapshot.version !== 1 || snapshot.mode !== "live" || !snapshot.metrics ||
          !Number.isFinite(Date.parse(snapshot.capturedAt))) throw new Error("Unrecognized live snapshot");
      if (JSON.stringify(this.snapshot?.channelKeys) !== JSON.stringify(snapshot.channelKeys)) {
        this.generation++;
        this.histories.clear();
        this.requests.clear();
        this.historyErrors.clear();
        this.historyError = "";
      }
      this.snapshot = snapshot;
      this.error = "";
    } catch (error) {
      this.error = error.message;
    }
    this.emit();
  }
  async requestHistory(records) {
    if (this.mode !== "live" || !this.snapshot || this.stale || this.historyBatch) return;
    const windows = new Map();
    for (const record of records) {
      if (!windows.has(record.seconds)) windows.set(record.seconds, new Set());
      for (const id of record.ids) if (Object.hasOwn(this.snapshot.channelKeys ?? {}, id)) windows.get(record.seconds).add(id);
    }
    this.historyBatch = true;
    const generation = this.generation;
    try {
      for (const [seconds, set] of windows) {
        const ids = [...set].sort();
        if (!ids.length) continue;
        const key = `${seconds}:${ids.join(",")}`;
        const previous = this.requests.get(seconds);
        if (previous?.pending || previous?.key === key && this.clock() - previous.at < 15000) continue;
        this.requests.set(seconds, { key, at: this.clock(), pending: true });
        try {
          const history = await this.json(`./api/history?${new URLSearchParams({ ids: ids.join(","), seconds: String(seconds) })}`);
          if (generation !== this.generation) break;
          const end = Date.parse(history.capturedAt) / 1000;
          if (!history.series || !Number.isFinite(end) || !Number.isFinite(history.step)) throw new Error("Unrecognized history response");
          this.histories.set(seconds, { ...history, end });
          if (history.issues?.length) this.historyErrors.set(seconds, history.issues.join("; "));
          else this.historyErrors.delete(seconds);
        } catch (error) {
          if (generation !== this.generation) break;
          this.historyErrors.set(seconds, error.message);
          this.histories.delete(seconds);
        } finally {
          if (generation === this.generation) {
            this.requests.set(seconds, { key, at: this.clock(), pending: false });
            this.historyError = [...this.historyErrors].map(([window, issue]) => `${window}s: ${issue}`).join("; ");
          }
          this.emit();
        }
      }
    } finally {
      this.historyBatch = false;
    }
  }
  start() {
    if (this.mode !== "live") return;
    const tick = async () => {
      await this.poll();
      this.timer = setTimeout(tick, 5000);
    };
    void tick();
  }
  destroy() { clearTimeout(this.timer); this.listeners.clear(); }
}
