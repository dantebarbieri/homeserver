import test from "node:test";
import assert from "node:assert/strict";
import { defaults, selectedColumns, moveColumn, placeColumn, metricValue, sortRows, formatValue } from "./service-model.mjs";
import { dropIndex } from "./reorder.mjs";

test("columns can be selected and reordered without changing saved input; invalid settings are refused", () => {
  const selected = selectedColumns(defaults);
  assert.deepEqual(moveColumn(selected, "network", -1), ["cpu", "memory", "network", "disk"]);
  assert.deepEqual(defaults, ["cpu", "memory", "disk", "network"]);
  for (const invalid of [[], ["cpu", "cpu"], ["not-a-column"], {}, null]) assert.throws(() => selectedColumns(invalid));
});

test("dragging places a column at an absolute slot, clamped, without mutating or accepting unknown input", () => {
  assert.deepEqual(placeColumn(defaults, "network", 0), ["network", "cpu", "memory", "disk"]);
  assert.deepEqual(placeColumn(defaults, "cpu", 3), ["memory", "disk", "network", "cpu"]);
  assert.deepEqual(placeColumn(defaults, "memory", 99), ["cpu", "disk", "network", "memory"]);
  assert.deepEqual(placeColumn(defaults, "memory", -4), ["memory", "cpu", "disk", "network"]);
  assert.deepEqual(placeColumn(defaults, "gpu", 1), defaults);
  assert.deepEqual(defaults, ["cpu", "memory", "disk", "network"]);
  assert.throws(() => placeColumn(["cpu", "cpu"], "cpu", 0));
});

test("the drop slot counts the other items whose centres precede the dragged item", () => {
  assert.equal(dropIndex([50, 150, 250], 10), 0);
  assert.equal(dropIndex([50, 150, 250], 160), 2);
  assert.equal(dropIndex([50, 150, 250], 900), 3);
  assert.equal(dropIndex([], 5), 0);
});

test("aggregate rates require both directions; missing readings never become idle zeros", () => {
  assert.equal(metricValue({ values: { rx: 100, tx: 50 } }, "network"), 150);
  assert.equal(metricValue({ values: { diskRead: 100, diskWrite: null } }, "disk"), null);
  assert.equal(metricValue({ values: { cpu: 0 } }, "cpu"), 0);
  for (const value of [null, undefined, -1, NaN, Infinity]) assert.equal(metricValue({ values: { cpu: value } }, "cpu"), null);
});

test("sort uses numbers, keeps missing values last in either direction and is deterministic", () => {
  const rows = [{ id: "a", name: "Alpha", values: { cpu: 2 } }, { id: "b", name: "Beta", values: { cpu: 12 } },
    { id: "c", name: "Gamma", values: { cpu: null } }];
  assert.deepEqual(sortRows(rows, "cpu").map(row => row.id), ["b", "a", "c"]);
  assert.deepEqual(sortRows(rows, "cpu", 1).map(row => row.id), ["a", "b", "c"]);
  assert.equal(formatValue(125000, "bit/s"), "1.0 Mbit/s");
  assert.equal(formatValue(null, "%"), "\u2014");
});
