import assert from "node:assert/strict";
import test from "node:test";
import {TYPES, mergeEvents, located, project, duration, equalEarth, countryFlag, MAP_DEFAULTS, mapSettings, mapActivity, demoEvents, demoLiveEvent, isFresh, FLASH} from "./model.mjs";
import {constrainView, zoomView} from "./map-view.mjs";

test("event replays deduplicate without losing nanosecond ordering", () => {
  const first = {id: "a", type: "ssh", cursor: "1795530000000000001"};
  const second = {id: "b", type: "ssh", cursor: "1795530000000000002"};
  assert.deepEqual(mergeEvents([first], [second, first]).map(item => item.id), ["b", "a"]);
  assert.equal(mergeEvents([first], [second], 1)[0].id, "b");
});
test("Equal Earth matches the PROJ reference example and preserves relative area", () => {
  const [x, y] = equalEarth(122, 47);
  assert.equal(x.toFixed(2), "1.55");
  assert.equal(y.toFixed(2), "0.89");
  const area = latitude => {
    const epsilon = .00001;
    const center = equalEarth(10, latitude);
    const east = equalEarth(10 + epsilon, latitude);
    const north = equalEarth(10, latitude + epsilon);
    return Math.abs((east[0] - center[0]) * (north[1] - center[1])
      - (north[0] - center[0]) * (east[1] - center[1])) / Math.cos(latitude * Math.PI / 180);
  };
  for (const latitude of [30, 60, 80]) assert.ok(Math.abs(area(latitude) / area(0) - 1) < .00001);
  for (const longitude of [-180, 0, 180]) for (const latitude of [-90, 0, 90])
    assert.ok(project(longitude, latitude, 1000, 500).every(Number.isFinite));
});
test("missing and invalid locations never invent map coordinates", () => {
  assert.equal(located({latitude: null, longitude: 0}), false);
  assert.equal(located({latitude: 91, longitude: 0}), false);
  assert.equal(located({latitude: 0, longitude: 0}), true);
  assert.deepEqual(project(0, 0, 760, 380), [380, 190]);
  assert.equal(duration(null), "—");
});

const dots = count => Array.from({length: count}, (_, i) => ({
  id: `event-${i}`, latitude: 0, longitude: 0, observedAt: 1000 - i,
}));

test("seven dots hold; the eighth fades from displacement time and disappears after 30 minutes", () => {
  const seven = dots(7), eight = dots(8);
  assert.ok(mapActivity(seven, MAP_DEFAULTS, 10000).points.every(point => point.opacity === 1));
  assert.equal(mapActivity(eight, MAP_DEFAULTS, 1000).points.length, 8);
  assert.equal(mapActivity(eight, MAP_DEFAULTS, 1900).points.at(-1).opacity, .5);
  const after = mapActivity(eight, MAP_DEFAULTS, 2800);
  assert.equal(after.points.length, 7);
  assert.equal(after.expired, 1);
  assert.ok(after.points.every(point => point.opacity === 1));
});

test("bursts and optional history remain bounded without removing stream events", () => {
  const events = dots(1000), settings = mapSettings({keep: 7, fadeMinutes: 30, maxDots: 20});
  const activity = mapActivity(events, settings, 1000);
  assert.equal(activity.points.length, 20);
  assert.equal(activity.omitted, 980);
  assert.equal(events.length, 1000);
  assert.equal(mapActivity(events, settings, 10000, true).points.length, 20);
  assert.equal(mapActivity(events, {...settings, keep: 0}, 10000).points.length, 0);
  for (const input of [{...settings, keep: 21}, {...settings, maxDots: 1001}, {...settings, fadeMinutes: 0}, {...settings, keep: null}])
    assert.throws(() => mapSettings(input));
});

test("unlocated events do not displace held dots and unknown countries never invent flags", () => {
  assert.equal(mapActivity([{id: "missing", observedAt: 2000}, ...dots(7)], MAP_DEFAULTS, 10000).points.length, 7);
  assert.equal(countryFlag("US"), "\u{1f1fa}\u{1f1f8}");
  for (const code of [undefined, "ZZ", "XX", "usa", "<script>"]) assert.equal(countryFlag(code), "");
});

test("simulated arrivals are unique, located, documentation-range addresses that merge newest first", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  let seed = 7;
  const random = () => (seed = (seed * 48271) % 2147483647) / 2147483647;
  const arrivals = Array.from({length: 60}, (_, i) => demoLiveEvent(i + 1, now + i, random));
  assert.equal(new Set(arrivals.map(item => item.id)).size, 60);
  assert.equal(new Set(arrivals.map(item => item.type)).size > 3, true);
  for (const item of arrivals) {
    assert.equal(located(item), true);
    assert.match(item.ip, /^(192\.0\.2|198\.51\.100|203\.0\.113)\.\d+$/);
    assert.equal(Boolean(TYPES[item.type]), true);
    assert.equal(item.source, "synthetic");
  }
  const merged = mergeEvents(demoEvents(now), arrivals);
  assert.equal(merged[0].id, "demo-live-60");
  assert.equal(merged.length, 92);
});

test("only genuinely fresh events flash", () => {
  assert.equal(isFresh({observedAt: 990}, 60, 1000), true);
  assert.equal(isFresh({observedAt: 900}, 60, 1000), false);
  assert.equal(isFresh({}, 60, 1000), false);
  assert.equal(FLASH.seconds < 10 && FLASH.maxConcurrent > 0, true);
});

test("map zoom anchors the selected region and clamps panning at every viewport shape", () => {
  for (const [width, height] of [[1200, 600], [390, 600], [844, 300]]) {
    const initial = constrainView({zoom: 1, x: 500, y: 250}, width, height);
    const center = zoomView(initial, 4, {x: width / 2, y: height / 2}, width, height);
    assert.equal(center.zoom, 4);
    assert.equal(center.x, 500);
    assert.equal(center.y, 250);
    const edge = constrainView({...center, x: -100000, y: 100000}, width, height);
    assert.ok(edge.x >= 0 && edge.x <= 1000 && edge.y >= 0 && edge.y <= 500);
    assert.equal(constrainView({...center, zoom: 1000}, width, height).zoom, 128);
    assert.equal(constrainView({...center, zoom: .001}, width, height).zoom, 1);
  }
  const zoomed = constrainView({zoom: 4, x: 500, y: 250}, 1000, 500);
  const changed = zoomView(zoomed, 2, {x: 700, y: 300}, 1000, 500);
  assert.equal(zoomed.x + .2 * zoomed.width, changed.x + .2 * changed.width);
  assert.equal(zoomed.y + .1 * zoomed.height, changed.y + .1 * changed.height);
});
