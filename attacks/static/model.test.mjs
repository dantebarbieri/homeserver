import assert from "node:assert/strict";
import test from "node:test";
import {TYPES, mergeEvents, located, project, duration, liveTrapping, ago, equalEarth, countryFlag, MAP_DEFAULTS, mapSettings, mapActivity, demoEvents, demoLiveEvent, isFresh, FLASH} from "./model.mjs";
import {constrainView, zoomView, flyPath, fitView, easeInOut, placeArrival} from "./map-view.mjs";

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

test("time ago reads in the largest whole unit and never goes negative", () => {
  const now = 10_000_000;
  assert.equal(ago(now - 5, now), "5s ago");
  assert.equal(ago(now + 3, now), "0s ago");
  assert.equal(ago(now - 59.9, now), "59s ago");
  assert.equal(ago(now - 15 * 60, now), "15m ago");
  assert.equal(ago(now - 3 * 3600 - 59, now), "3h ago");
  assert.equal(ago(now - 2 * 86400, now), "2d ago");
  assert.equal(ago(undefined, now), "");
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

test("own traffic stays off the map even in history mode without displacing external dots", () => {
  const external = dots(7);
  const own = {...dots(1)[0], id: "own", origin: "own", observedAt: 20000};
  for (const history of [true, false]) {
    const activity = mapActivity([own, ...external], MAP_DEFAULTS, 20000, history);
    assert.deepEqual(activity.points.map(({item}) => item.id), external.map(item => item.id));
    assert.ok(activity.points.every(({opacity}) => opacity === 1));
  }
});

test("live trapping ticks between samples, switches on close, and stops on stale or failed telemetry", () => {
  const opened = {available: true, seconds: 10, connections: 2};
  assert.deepEqual(liveTrapping(opened, 5000), {seconds: 20, connections: 2});
  assert.deepEqual(liveTrapping({available: true, seconds: 0, connections: 0}, 5000), {seconds: 0, connections: 0});
  assert.equal(liveTrapping(opened, 90001), null);
  assert.equal(liveTrapping({...opened, available: false}, 1000), null);
  assert.equal(liveTrapping(null, 0), null);
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

test("same-city summaries stay separated and keep their offsets as the globe moves or neighbors expire", () => {
  const bounds = {width: 950, height: 480};
  for (const [x, y] of [[475, 240], [945, 5]]) {
    const cards = [];
    for (const h of [115, 120, 110]) {
      const card = placeArrival(x, y, 260, h, bounds, cards);
      assert.ok(card.left >= 8 && card.top >= 8 && card.left + card.width <= 942 && card.top + h <= 472);
      assert.ok(cards.every(p => p.top + p.height <= card.top || card.top + h <= p.top ||
        p.left + p.width <= card.left || card.left + card.width <= p.left));
      cards.push(card);
    }
    const last = cards.at(-1);
    const held = placeArrival(x, y, 260, last.height, bounds, [], last);
    assert.deepEqual(held, last);
    const moved = placeArrival(x + 1, y - 2, 260, last.height, bounds, [], held);
    assert.ok(Math.abs(moved.left - held.left) <= 1 && Math.abs(moved.top - held.top) <= 2);
  }
});

test("follow flights land exactly, pull back on long hops and frame new dots", () => {
  const close = (a, b, tolerance = 1e-6) => assert.ok(Math.abs(a - b) < tolerance, `${a} != ${b}`);
  const from = {x: 100, y: 100, width: 100}, to = {x: 900, y: 400, width: 100};
  const path = flyPath(from, to);
  for (const key of ["x", "y", "width"]) { close(path.at(0)[key], from[key]); close(path.at(.999999)[key], to[key], 1e-3); }
  assert.deepEqual(path.at(1), to);
  assert.ok(path.at(.5).width > 3 * from.width);
  const zoomIn = flyPath({x: 500, y: 250, width: 1000}, {x: 500, y: 250, width: 125});
  const widths = [0, .25, .5, .75, 1].map(t => zoomIn.at(t).width);
  assert.ok(widths.every((width, index) => !index || width < widths[index - 1]));
  close(widths.at(-1), 125);
  assert.equal(easeInOut(0), 0); assert.equal(easeInOut(.5), .5); assert.equal(easeInOut(1), 1);

  const spread = fitView([{x: 200, y: 200}, {x: 300, y: 260}], 3, 1000, 500);
  assert.deepEqual([spread.x, spread.y], [250, 230]);
  assert.ok(spread.zoom <= 3 && spread.width >= 100 / .6 - 1e-9);
  const single = fitView([{x: 820, y: 120}], 3, 1000, 500);
  assert.equal(single.zoom, 3);
  assert.deepEqual([single.x, single.y], [820, 120]);
  const wide = fitView([{x: 10, y: 10}, {x: 990, y: 490}], 3, 1000, 500);
  assert.equal(wide.zoom, 1);
});
