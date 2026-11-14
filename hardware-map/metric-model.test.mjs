import test from "node:test";
import assert from "node:assert/strict";
import { metrics, metricCardRows, demoProfiles, demoValue, demoMemory, demoSeries, metricPath, metricNumber, sharedMetricScale, windowMetricScale, chartNumber, temperatureLevel, temperatureProfile, temperatureStops, temperatureAverage, performanceContext, storageDetails, placeMetricCard, placeMetricRow } from "./metric-model.mjs";

test("card rows keep the requested order and align unequal card heights at the correct edge", () => {
  const viewport = { width: 1200, height: 900 };
  for (const [edge, ids] of Object.entries(metricCardRows)) {
    const cards = ids.map((id, index) => ({ id, width: 206, height: 160 + index * 30 }));
    const placed = placeMetricRow(cards, viewport, [], edge);
    assert.deepEqual(placed.map(card => card.id), edge === "top" ? ["nvme-root", "gpu", "network"] : ["nvme", "cpu", "memory"]);
    for (let index = 0; index < placed.length; index++) {
      const card = placed[index];
      assert.ok(card.x >= 10 && card.x + card.width <= viewport.width - 10);
      assert.ok(card.y >= (edge === "top" ? 10 : viewport.height / 2));
      assert.ok(card.y + card.height <= (edge === "top" ? viewport.height / 2 : viewport.height - 10));
      if (index) {
        assert.ok(card.x >= placed[index - 1].x + placed[index - 1].width + 10);
        assert.equal(edge === "top" ? card.y : card.y + card.height,
          edge === "top" ? placed[0].y : placed[0].y + placed[0].height);
      }
    }
  }
});

test("row placement avoids reserved hardware or custom cards without reordering or mutating them", () => {
  const viewport = { width: 1200, height: 900 }, reserved = [{ x: 900, y: 10, width: 280, height: 300 }];
  const cards = metricCardRows.top.map(id => ({ id, width: 206, height: 200 }));
  const original = structuredClone({ cards, reserved });
  const placed = placeMetricRow(cards, viewport, reserved, "top");
  assert.ok(placed.at(-1).x + placed.at(-1).width <= reserved[0].x - 10);
  assert.deepEqual({ cards, reserved }, original);
  assert.deepEqual(placeMetricRow([], viewport, reserved, "bottom"), []);
});

test("automatic callouts find clear background beyond nearby candidates without covering hardware", () => {
  const card = { x: 700, y: 80, width: 206, height: 234 };
  const board = { x: 250, y: 0, width: 700, height: 700 };
  const position = placeMetricCard(card, { width: 1200, height: 700 }, [board]);
  assert.ok(position.x + card.width <= board.x - 10 || position.x >= board.x + board.width + 10);
  assert.ok(position.y >= 10 && position.y + card.height <= 690);
});

test("automatic callouts preserve clear preferences and avoid other cards", () => {
  const viewport = { width: 1000, height: 800 }, card = { x: 100, y: 100, width: 206, height: 234 };
  assert.deepEqual(placeMetricCard(card, viewport, []), { x: 100, y: 100 });
  const next = placeMetricCard(card, viewport, [card]);
  assert.ok(next.x >= card.x + card.width + 10 || next.y >= card.y + card.height + 10);
  assert.deepEqual(placeMetricCard(card, viewport, [card]), next);
});

test("synthetic channels are deterministic and remain inside their declared graph ranges", () => {
  for (const profile of Object.keys(demoProfiles)) {
    for (const second of [0, 60, 300, 900]) {
      for (const [id, definition] of metrics) {
        const value = demoValue(id, second, profile);
        assert.ok(Number.isFinite(value), id);
        assert.ok(value >= definition.minimum && value <= definition.maximum, `${id}: ${value}`);
        assert.equal(demoValue(id, second, profile), value);
        assert.equal(definition.provenance, "synthetic");
      }
    }
  }
});

test("overall CPU agrees with both core and logical-CPU views", () => {
  for (const profile of Object.keys(demoProfiles)) {
    for (const second of [0, 37, 300]) {
      const mean = values => values.reduce((total, value) => total + value, 0) / values.length;
      const threads = Array.from({ length: 32 }, (_, i) => demoValue(`thread-${i}`, second, profile));
      const cores = Array.from({ length: 16 }, (_, i) => demoValue(`core-${i}`, second, profile));
      assert.equal(demoValue("cpu", second, profile), mean(threads));
      assert.ok(Math.abs(mean(cores) - mean(threads)) < 1e-10);
      cores.forEach((value, i) => assert.equal(value, mean(threads.slice(i * 2, i * 2 + 2))));
    }
  }
});

test("memory composition partitions capacity without double-counting cache", () => {
  for (const profile of Object.keys(demoProfiles)) {
    for (const second of [0, 300, 900]) {
      const memory = demoMemory(second, profile);
      assert.ok(Math.abs(memory.apps + memory.cache + memory.kernel + memory.free - 128) < 1e-10);
      assert.equal(memory.used, memory.apps + memory.kernel);
      assert.equal(demoValue("memory-used", second, profile), memory.used);
    }
  }
});

test("synthetic active-backup traffic matches the active NIC rather than adding both links", () => {
  for (const direction of ["rx", "tx"]) {
    for (const second of [0, 60, 300]) {
      const active = demoValue(`net-enp66s0f1-${direction}`, second, "transfer");
      assert.equal(demoValue(`net-bond0-${direction}`, second, "transfer"), active);
      assert.ok(demoValue(`net-enp66s0f0-${direction}`, second, "transfer") < active);
      assert.ok(demoValue("disk-sde-active", second, "transfer") <= .1);
    }
  }
});

test("history windows keep their exact endpoints and regenerate for the selected scenario", () => {
  for (const seconds of [60, 120, 300]) {
    const values = demoSeries("cpu", 400, seconds, "transcode");
    assert.equal(values.length, seconds + 1);
    assert.equal(values[0], demoValue("cpu", 400 - seconds, "transcode"));
    assert.equal(values.at(-1), demoValue("cpu", 400, "transcode"));
  }
  assert.notDeepEqual(demoSeries("cpu", 300, 60, "idle"), demoSeries("cpu", 300, 60, "transcode"));
});

test("multi-hour histories retain full lookback with a bounded render cost", () => {
  for (const seconds of [900, 1800, 3600, 7200, 21600, 86400]) {
    const series = demoSeries("temp-cpu", 86400, seconds);
    assert.equal(series.length, 301);
    assert.equal(series[0], demoValue("temp-cpu", 86400 - seconds));
    assert.equal(series.at(-1), demoValue("temp-cpu", 86400));
    assert.equal(series[150], demoValue("temp-cpu", 86400 - seconds / 2));
  }
});

test("overlaid traffic series use one shared domain and consistent units", () => {
  const scale = sharedMetricScale(["net-bond0-rx", "net-bond0-tx"]);
  assert.deepEqual(scale, { minimum: 0, maximum: 10000, unit: "Mb/s" });
  assert.equal(chartNumber(1500, scale), "1.5 Gb/s");
  assert.equal(chartNumber(700, scale), "0.7 Gb/s");
  assert.equal(chartNumber(null, scale), "Unavailable");
  assert.throws(() => sharedMetricScale(["cpu", "temp-cpu"]));
  assert.throws(() => sharedMetricScale([]));
});

test("temperature bands distinguish component contexts and missing sensors", () => {
  assert.deepEqual([10, 30, 45, 60, 75, 90].map(value => temperatureLevel("temp-cpu", value).label),
    ["Cold", "Cool", "Moderate", "Warm", "Hot", "Dangerous"]);
  assert.equal(temperatureLevel("temp-sda", 44).label, "Warm");
  assert.equal(temperatureLevel("temp-sda", 45).label, "Hot");
  assert.equal(temperatureLevel("temp-gpu", 45).label, "Moderate");
  assert.equal(temperatureLevel("temp-cpu", null).label, "Unavailable");
});

test("temperature trace colors change exactly at kind-specific thresholds", () => {
  const hdd = temperatureStops("temp-sda", 40, 60);
  const crossing = hdd.filter(stop => stop.offset === .75);
  assert.deepEqual(crossing.map(stop => stop.color), [temperatureLevel("temp-sda", 45).color, temperatureLevel("temp-sda", 44.9).color]);
  assert.equal(hdd[0].color, temperatureLevel("temp-sda", 60).color);
  assert.equal(hdd.at(-1).color, temperatureLevel("temp-sda", 40).color);
  assert.ok(hdd.every((stop, index) => stop.offset >= 0 && stop.offset <= 1 && (!index || stop.offset >= hdd[index - 1].offset)));
  assert.notDeepEqual(temperatureProfile("temp-sda").boundaries, temperatureProfile("temp-cpu").boundaries);
  assert.notDeepEqual(temperatureProfile("temp-nvme0").boundaries, temperatureProfile("temp-nvme0-secondary").boundaries);
  assert.deepEqual(temperatureProfile("temp-hdd-average"), temperatureProfile("temp-sda"));
  assert.throws(() => temperatureStops("temp-cpu", 20, 20));
});

test("HDD means exclude missing sensors, report coverage and preserve a measured zero", () => {
  assert.deepEqual(temperatureAverage([40, 50, null, NaN]), { value: 45, count: 2, total: 4 });
  assert.deepEqual(temperatureAverage([0, null]), { value: 0, count: 1, total: 2 });
  assert.deepEqual(temperatureAverage([null, undefined]), { value: null, count: 0, total: 2 });
  assert.deepEqual(temperatureAverage([]), { value: null, count: 0, total: 0 });
});

test("component graph contexts preserve device bindings and never guess unbound slots", () => {
  assert.ok(performanceContext("cpu").series.flat().includes("temp-cpu"));
  assert.ok(performanceContext("cpu").series.flat().includes("fan-cpu2"));
  assert.ok(performanceContext("gpu").series.flat().includes("temp-gpu"));
  assert.equal(performanceContext("drive-M2_1").unbound, true);
  const nvme = performanceContext("drive-M2_1", "nvme7n1");
  assert.equal(nvme.disk, "nvme7n1");
  assert.ok(nvme.series.flat().includes("temp-nvme7-secondary"));
  assert.ok(performanceContext("drive-cage-1-bay-1", "sdz").series.flat().includes("temp-sdz"));
  assert.equal(performanceContext("rear-fan-2").sensor, "fan-rear2");
  assert.equal(performanceContext("front-fan-1").sensor, "fan-hub");
  assert.equal(performanceContext("motherboard").sensor, "temp-board");
  assert.equal(performanceContext("psu"), null);
});

test("adaptive axes include both traffic series, the selected window and the latest value", () => {
  const ids = ["net-bond0-rx", "net-bond0-tx"];
  const scale = windowMetricScale(ids, [[.003, .005, null], [.008, .015, NaN]], [.002, .02]);
  assert.equal(scale.minimum, 0);
  assert.equal(scale.maximum, .025);
  assert.equal(chartNumber(.005, scale), "5 kb/s");
  assert.equal(chartNumber(.02, scale), "20 kb/s");
  assert.ok(windowMetricScale(ids, [[.003, 1500], [.008, .015]]).maximum > 1500);
  assert.ok(windowMetricScale(ids, [[.003, .005], [.008, .015]]).maximum < 1);
  assert.equal(windowMetricScale(ids, [[0, 0], [0, 0]]).maximum, 1);
  assert.equal(windowMetricScale(ids, [[null], [NaN]]).adaptive, false);
  assert.equal(windowMetricScale(ids, [[1], [2]], [], "fixed").maximum, 10000);
  assert.throws(() => windowMetricScale(ids, [[1], [2]], [], "invalid"));
});

test("capacity and percentage axes remain truthful while temperatures and latency gain readable ranges", () => {
  for (const id of ["cpu", "gpu-util", "gpu-dedicated", "memory-used", "data-used", "cache-used"]) {
    const scale = windowMetricScale([id], [[1, 2]]);
    assert.equal(scale.minimum, metrics.get(id).minimum);
    assert.equal(scale.maximum, metrics.get(id).maximum);
    assert.equal(scale.adaptive, false);
  }
  const temp = windowMetricScale(["temp-cpu"], [[48, 53]]);
  assert.ok(temp.minimum < 48 && temp.minimum > 0);
  assert.ok(temp.maximum > 53 && temp.maximum < 80);
  const latency = windowMetricScale(["disk-sda-latency"], [[.05, .1]]);
  assert.equal(chartNumber(.05, latency), "50 µs");
  const throughput = windowMetricScale(["disk-sda-read"], [[.00001, .0001]]);
  assert.equal(chartNumber(.0001, throughput), "100 B/s");
  assert.equal(chartNumber(0, throughput), "0 B/s");
});

test("readouts select readable units independently of the shared graph ceiling", () => {
  assert.equal(metricNumber(.002, "Gb/s"), "2 Mb/s");
  assert.equal(metricNumber(.002, "GB/s"), "2 MB/s");
  assert.equal(metricNumber(.002, "Mb/s"), "2 kb/s");
  assert.equal(metricNumber(.0002, "MB/s"), "200 B/s");
  assert.equal(metricNumber(2500, "Mb/s"), "2.5 Gb/s");
  assert.equal(metricNumber(.5, "TiB"), "512 GiB");
  assert.equal(metricNumber(.0009765625, "GiB"), "1 MiB");
  assert.equal(metricNumber(.05, "ms"), "50 µs");
  assert.equal(metricNumber(0, "MB/s"), "0 B/s");
  assert.equal(metricNumber(null, "Gb/s"), "Unavailable");
  assert.equal(chartNumber(2, sharedMetricScale(["net-bond0-rx", "net-bond0-tx"])), "0.002 Gb/s");
});

test("storage details trace root, swap, cache and ordinary extents without losing RAID roles", () => {
  const root = storageDetails("nvme0n1").layers.map(node => node.id);
  assert.ok(root.includes("homeserver-vg") && root.includes("dm-0") && root.includes("dm-1"));
  assert.ok(!root.includes("vg_redundant"));
  const cache = storageDetails("nvme1n1").layers.map(node => node.id);
  for (const id of ["vg_redundant", "dm-2", "dm-3", "dm-4", "dm-5", "data-filesystem"]) assert.ok(cache.includes(id), id);
  assert.ok(!cache.includes("homeserver-vg"));
  assert.match(storageDetails("sde").role, /HOT SPARE/);
  assert.match(storageDetails("sda").role, /Array member/);
  assert.throws(() => storageDetails("unknown"));
  for (const profile of Object.keys(demoProfiles)) for (const second of [0, 300, 86400]) {
    assert.equal(demoValue("fan-rear1", second, profile), 2000);
    assert.equal(demoValue("fan-rear2", second, profile), 2000);
  }
});

test("chart gaps remain unavailable, zero stays valid, and invalid bounds are rejected", () => {
  const path = metricPath([0, null, 50, undefined, NaN, Infinity, 100], 0, 100);
  assert.equal((path.match(/M/g) ?? []).length, 3);
  assert.ok(path.startsWith("M0.0,80.0"));
  assert.ok(path.endsWith("M300.0,0.0"));
  assert.ok(!path.includes("L"));
  assert.equal(metricPath([0, 50, 100], 0, 100), "M0.0,80.0 L150.0,40.0 L300.0,0.0");
  assert.equal(metricNumber(null, "%"), "Unavailable");
  assert.equal(metricNumber(0, "%"), "0 %");
  assert.equal(metricNumber(1500, "Mb/s"), "1.5 Gb/s");
  assert.equal(metricNumber(1500, "MB/s"), "1.5 GB/s");
  for (const maximum of [0, NaN, Infinity]) assert.throws(() => metricPath([1, 2], 0, maximum));
  assert.throws(() => demoValue("not-a-channel", 300));
  assert.throws(() => demoValue("cpu", -1));
  assert.throws(() => demoMemory(300, "not-a-profile"));
  assert.throws(() => demoMemory(NaN));
  assert.throws(() => demoSeries("cpu", 300, 30));
});
