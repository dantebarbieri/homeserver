import test from "node:test";
import assert from "node:assert/strict";
import { ageText, sourceGroups, healthOf, announceAfter } from "./status.mjs";
import { placePopover } from "./popover.mjs";

const now = Date.parse("2026-11-14T12:00:00Z");
const live = extra => ({ mode: "live", stale: false, error: "", historyError: "", snapshotIssues: [],
  snapshot: { capturedAt: "2026-11-14T11:59:57Z", intervalSeconds: 5, sources: { cpu: { status: "ok" } } }, ...extra });

test("ages read naturally at each scale", () => {
  assert.equal(ageText(3400), "3 s");
  assert.equal(ageText(5 * 60000), "5 min");
  assert.equal(ageText(3 * 3600000), "3 h");
  assert.equal(ageText(-50), "0 s");
});

test("demo mode is labelled and never reports sources", () => {
  const health = healthOf({ mode: "demo" }, now);
  assert.equal(health.level, "demo");
  assert.deepEqual([health.items, health.sources], [[], []]);
});

test("a healthy live snapshot is quiet", () => {
  const health = healthOf(live(), now);
  assert.deepEqual([health.level, health.label, health.items.length], ["ok", "Live", 0]);
  assert.match(health.note, /Snapshot 3 s old · refreshed every 5 s/);
});

test("waiting for the first snapshot is not an error", () => {
  assert.equal(healthOf({ mode: "live", stale: true, error: "", snapshot: null }, now).level, "connecting");
});

test("collector notices become separate titled items", () => {
  const health = healthOf(live({ snapshotIssues: ["cache: kernel reports needs_check; cached metadata requires operator attention",
    "An unstructured note: with a colon"], historyError: "120s: ChasEx API returned HTTP 502" }), now);
  assert.equal(health.level, "warn");
  assert.equal(health.label, "3 issues");
  assert.deepEqual(health.items.map(item => [item.severity, item.title]),
    [["error", "cache"], ["warn", "Collector notice"], ["warn", "Chart history unavailable"]]);
  assert.equal(health.items[1].detail, "An unstructured note: with a colon");
});

test("an outage shows one cause and hides notices from the old snapshot", () => {
  const failed = healthOf(live({ stale: true, error: "ChasEx API returned HTTP 503", snapshotIssues: ["cpu: unavailable"] }), now);
  assert.deepEqual([failed.level, failed.label, failed.items.length], ["down", "No live data", 1]);
  assert.match(failed.items[0].detail, /HTTP 503.*hidden rather than shown out of date/);
  assert.deepEqual(failed.sources, []);
  const frozen = healthOf(live({ stale: true, snapshot: { capturedAt: "2026-11-14T11:58:00Z", intervalSeconds: 5 } }), now);
  assert.equal(frozen.items[0].title, "Collector has stopped updating");
  assert.match(frozen.note, /Last snapshot 2 min ago/);
});

test("per-disk SMART sources collapse without exposing identifiers", () => {
  const groups = sourceGroups({ "smart:wwn:0xAAA": { status: "ok" }, "smart:wwn:0xBBB": { status: "unavailable" },
    bmc: { status: "ok" }, "rear-fans": { status: "assumed", note: "constant" }, mystery: { status: "pending" } });
  assert.deepEqual(groups.map(group => [group.label, group.state, group.text]), [
    ["mystery", "failing", "pending"], ["SMART", "failing", "1 of 2 unavailable"],
    ["BMC sensors", "ok", "OK"], ["Rear fans", "assumed", "assumed"]]);
  assert.ok(!JSON.stringify(groups).includes("wwn"));
});

test("announcements wait long enough to ignore one failed poll", () => {
  assert.ok(announceAfter > 5000);
});

test("menus stay inside the viewport and flip above when there is no room", () => {
  const viewport = { width: 375, height: 800 };
  const below = placePopover({ left: 300, right: 360, top: 60, bottom: 100 }, { width: 280, height: 300 }, viewport);
  assert.deepEqual([below.left, below.top], [80, 106]);
  const clamped = placePopover({ left: 10, right: 60, top: 60, bottom: 100 }, { width: 280, height: 300 }, viewport);
  assert.equal(clamped.left, 8);
  const above = placePopover({ left: 300, right: 360, top: 700, bottom: 740 }, { width: 280, height: 300 }, viewport);
  assert.equal(above.top, 700 - 6 - 300);
  const start = placePopover({ left: 40, right: 100, top: 60, bottom: 100 }, { width: 200, height: 100 }, viewport, { align: "start" });
  assert.equal(start.left, 40);
});
