import test from "node:test";
import assert from "node:assert/strict";
import { LiveData, historyValues } from "./live-data.mjs";

test("live zero remains valid while missing, failed and stale readings never become demo values", async () => {
  let now = 100000;
  let fail = false;
  const source = new LiveData({ enabled: true, clock: () => now, fetcher: async () => {
    if (fail) throw new Error("Offline");
    return { ok: true, json: async () => ({ version: 1, mode: "live", capturedAt: new Date(now).toISOString(), intervalSeconds: 5, metrics: { cpu: 0 } }) };
  } });
  await source.poll();
  assert.equal(source.value("cpu"), 0);
  assert.equal(source.value("gpu-3d"), null);
  now += 21000;
  assert.equal(source.value("cpu"), null);
  await source.poll();
  assert.equal(source.value("cpu"), 0);
  fail = true;
  await source.poll();
  assert.equal(source.value("cpu"), null);
  assert.equal(source.error, "Offline");
});

test("sparse real history preserves uncollected intervals instead of connecting or zero-filling them", () => {
  assert.deepEqual(historyValues([{ timestamp: 60, value: 0 }, { timestamp: 90, value: 42 }, { timestamp: 105, value: null }], 120, 60, 15), [0, null, 42, null, null]);
  assert.deepEqual(historyValues([], 120, 60, 15), [null, null, null, null, null]);
});

test("history requests include only server-advertised channels and failures clear old curves", async () => {
  let now = 100000, fail = false, requested;
  const source = new LiveData({ enabled: true, clock: () => now, fetcher: async url => {
    requested = url;
    return { ok: !fail, status: 502, json: async () => ({ capturedAt: new Date(now).toISOString(), seconds: 60, step: 15, series: { cpu: [{ timestamp: 100, value: 20 }] } }) };
  } });
  source.snapshot = { capturedAt: new Date(now).toISOString(), intervalSeconds: 5, channelKeys: { cpu: "cpu" } };
  await source.requestHistory([{ ids: ["cpu", "unsupported"], seconds: 60 }]);
  assert.ok(requested.includes("ids=cpu"));
  assert.ok(!requested.includes("unsupported"));
  assert.equal(source.series("cpu", 60).at(-1), 20);
  now += 16000;
  fail = true;
  await source.requestHistory([{ ids: ["cpu"], seconds: 60 }]);
  assert.deepEqual(source.series("cpu", 60), [null, null]);
  assert.match(source.historyError, /502/);
});

test("multiple history windows stay serialized even when subscribers request again during updates", async () => {
  let active = 0, maximum = 0, requests = 0;
  const now = 100000;
  const source = new LiveData({ enabled: true, clock: () => now, fetcher: async () => {
    active++;
    maximum = Math.max(maximum, active);
    requests++;
    await new Promise(resolve => setTimeout(resolve, 1));
    active--;
    return { ok: true, json: async () => ({ capturedAt: new Date(now).toISOString(), step: 15, series: {} }) };
  } });
  source.snapshot = { capturedAt: new Date(now).toISOString(), intervalSeconds: 5, channelKeys: { cpu: "cpu" } };
  const records = [60, 120, 300, 900, 7200].map(seconds => ({ ids: ["cpu"], seconds }));
  source.subscribe(() => { void source.requestHistory(records); });
  await source.requestHistory(records);
  assert.equal(requests, 5);
  assert.equal(maximum, 1);
});

test("live inventory replaces provisional NVMe card bindings without depending on controller numbering", async () => {
  const { linuxSnapshot } = await import("./linux-snapshot.mjs");
  const { applyLiveSnapshot, metricCards, metricBadges, metrics } = await import("./metric-model.mjs?live-inventory-test");
  const snapshot = JSON.parse(JSON.stringify(linuxSnapshot).replaceAll("nvme0n1", "nvme9n1"));
  const data = {
    inventory: { snapshot, disks: [
      { id: "nvme9n1", kind: "nvme", role: "root", slot: "M2_2" },
      { id: "nvme1n1", kind: "nvme", role: "cache", slot: "M2_1" },
      { id: "sda", kind: "hdd", slot: "cage-1-bay-1" },
    ] },
    capacities: { "memory-used": 123.5 },
    metrics: { "temp-nvme9": 43, "temp-nvme9-secondary": null },
  };
  applyLiveSnapshot(data);
  const card = metricCards.find(item => item.id === "nvme-root");
  assert.equal(card.anchor, "drive-M2_2");
  assert.equal(card.device, "nvme9n1");
  assert.deepEqual(card.series, ["disk-nvme9n1-read", "disk-nvme9n1-write"]);
  assert.ok(metrics.has("disk-nvme9n1-read"));
  assert.ok(metrics.has("temp-nvme9"));
  assert.equal(metrics.get("memory-used").maximum, 123.5);
  assert.deepEqual(metricBadges.find(item => item.id === "temp-hdd-range").ids, ["temp-sda"]);
  applyLiveSnapshot({ inventory: { ...data.inventory, disks: [] } });
  assert.equal(card.device, undefined);
  assert.equal(card.anchor, "nvme-group");
  assert.match(card.label, /unavailable/);
});
