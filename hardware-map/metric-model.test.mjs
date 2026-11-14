import test from "node:test";
import assert from "node:assert/strict";
import { metrics, demoProfiles, demoValue, demoMemory, demoSeries, metricPath, metricNumber, sharedMetricScale, windowMetricScale, chartNumber, temperatureLevel, temperatureProfile, temperatureStops, temperatureAverage, performanceContext, storageDetails, placeMetricCards, rayBoxEdge } from "./metric-model.mjs";

test("motherboard-centered rays hit the case boundary through the actual component", () => {
  const box = { x: 100, y: 100, width: 900, height: 600 }, origin = { x: 700, y: 400 };
  for (const [through, expected] of [
    [{ x: 800, y: 400 }, { x: 1000, y: 400, edge: "right" }],
    [{ x: 600, y: 400 }, { x: 100, y: 400, edge: "left" }],
    [{ x: 700, y: 300 }, { x: 700, y: 100, edge: "top" }],
    [{ x: 700, y: 500 }, { x: 700, y: 700, edge: "bottom" }],
    [{ x: 750, y: 300 }, { x: 850, y: 100, edge: "top" }],
    [origin, { x: 700, y: 100, edge: "top" }],
  ]) assert.deepEqual(rayBoxEdge(origin, through, box), expected);
});

test("radial cards slide along their edge without reversing ray order or covering reserved objects", () => {
  const viewport = { width: 1200, height: 900 }, enclosure = { x: 100, y: 200, width: 800, height: 400 };
  const origin = { x: 500, y: 400 }, reserved = [{ x: 450, y: 20, width: 200, height: 170 }];
  const cards = [400, 500, 600].map((x, i) => ({ id: String(i), width: 206, height: 160, anchor: { x, y: 300 } }));
  const original = structuredClone({ cards, reserved });
  const placed = placeMetricCards(cards, viewport, enclosure, origin, reserved);
  for (const [index, card] of placed.entries()) {
    assert.equal(card.edge, "top");
    assert.equal(card.y, 30);
    assert.ok(card.x >= 10 && card.x + card.width <= viewport.width - 10);
    assert.ok(card.x + card.width <= reserved[0].x - 10 || card.x >= reserved[0].x + reserved[0].width + 10);
    if (index) assert.ok(card.x >= placed[index - 1].x + placed[index - 1].width + 10);
  }
  assert.deepEqual(placeMetricCards([...cards].reverse(), viewport, enclosure, origin, reserved).reverse(), placed);
  assert.deepEqual({ cards, reserved }, original);
  assert.deepEqual(placeMetricCards([], viewport, enclosure, origin, reserved), []);
});

test("crowded shared ray targets remain finite and within the viewport", () => {
  const cards = Array.from({ length: 4 }, (_, i) => ({ id: String(i), width: 100, height: 90, anchor: { x: 150, y: 150 } }));
  const placed = placeMetricCards(cards, { width: 300, height: 500 }, { x: 30, y: 200, width: 240, height: 200 }, { x: 150, y: 300 }, []);
  assert.equal(placed.length, 4);
  for (const card of placed) {
    assert.ok(card.x >= 10 && card.x + card.width <= 290);
    assert.ok(card.y >= 10 && card.y + card.height <= 490);
  }
});

test("avoiding a reserved card takes priority over avoiding hardware when perimeter space is limited", () => {
  const hardware = { x: 0, y: 0, width: 700, height: 300 }, fixed = { x: 800, y: 10, width: 190, height: 210 };
  const [placed] = placeMetricCards(
    [{ id: "gpu", width: 200, height: 200, anchor: { x: 800, y: 200 } }],
    { width: 1000, height: 800 }, { x: 100, y: 150, width: 800, height: 500 },
    { x: 600, y: 350 }, [hardware, fixed], [fixed]);
  assert.ok(placed.x + placed.width <= fixed.x - 10);
});

test("cards on adjacent case edges share crowded corners without overlapping", () => {
  const cards = [
    { id: "gpu", width: 200, height: 300, anchor: { x: 730, y: 200 } },
    { id: "memory", width: 200, height: 280, anchor: { x: 730, y: 500 } },
    { id: "network", width: 200, height: 140, anchor: { x: 850, y: 350 } },
  ];
  const placed = placeMetricCards(cards, { width: 1000, height: 700 },
    { x: 40, y: 40, width: 920, height: 620 }, { x: 700, y: 350 },
    [{ x: 0, y: 0, width: 780, height: 700 }]);
  for (const [index, a] of placed.entries()) for (const b of placed.slice(index + 1)) {
    assert.ok(a.x + a.width <= b.x - 10 || b.x + b.width <= a.x - 10 ||
      a.y + a.height <= b.y - 10 || b.y + b.height <= a.y - 10);
  }
});

test("separately bound NVMe cards and the GPU fan out without crossed leaders", () => {
  const cards = [
    { id: "gpu", width: 176, height: 355, anchor: { x: 838, y: 425 } },
    { id: "nvme-root", width: 176, height: 232, anchor: { x: 783, y: 442 } },
    { id: "nvme", width: 176, height: 232, anchor: { x: 727, y: 442 } },
  ];
  const placed = placeMetricCards(cards, { width: 1117, height: 1153 },
    { x: 27, y: 301, width: 1059, height: 562 }, { x: 818, y: 527 },
    [{ x: 640, y: 300, width: 400, height: 80 }]);
  const end = card => rayBoxEdge({ x: card.x + card.width / 2, y: card.y + card.height / 2 }, card.anchor, card);
  const cross = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  for (const [index, a] of placed.entries()) for (const b of placed.slice(index + 1)) {
    assert.ok(cross(a.anchor, end(a), b.anchor) * cross(a.anchor, end(a), end(b)) >= 0 ||
      cross(b.anchor, end(b), a.anchor) * cross(b.anchor, end(b), end(a)) >= 0);
  }
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
