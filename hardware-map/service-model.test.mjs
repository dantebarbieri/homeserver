import test from "node:test";
import assert from "node:assert/strict";
import { defaults, selectedColumns, moveColumn, metricValue, sortRows, formatValue } from "./service-model.mjs";

test("columns can be selected and reordered without changing saved input; invalid settings are refused", () => {
  const selected = selectedColumns(defaults);
  assert.deepEqual(moveColumn(selected, "network", -1), ["cpu", "memory", "network", "disk"]);
  assert.deepEqual(defaults, ["cpu", "memory", "disk", "network"]);
  for (const invalid of [[], ["cpu", "cpu"], ["not-a-column"], {}, null]) assert.throws(() => selectedColumns(invalid));
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
