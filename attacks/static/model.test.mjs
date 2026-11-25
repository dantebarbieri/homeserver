import assert from "node:assert/strict";
import test from "node:test";
import {TYPES, OUTCOMES, SEVERITIES, REPUTATIONS, reputationGrade, severityOf, matchesFilters, facetCounts, mergeEvents, diffEvents, located, project, duration, liveTrapping, trapDuration, trapTime, ago, equalEarth, countryFlag, MAP_DEFAULTS, mapSettings, mapActivity, notDrawn, demoEvents, demoLiveEvent, demoCloseEvent, demoTrapping, isFresh, FLASH, TYPE_ORDER, SEVERITY_ORDER, slices, slicePath} from "./model.mjs";
import {constrainView, zoomView, flyPath, fitView, easeInOut, placeArrival} from "./map-view.mjs";

test("event replays deduplicate without losing nanosecond ordering", () => {
  const first = {id: "a", type: "ssh", cursor: "1795530000000000001"};
  const second = {id: "b", type: "ssh", cursor: "1795530000000000002"};
  assert.deepEqual(mergeEvents([first], [second, first]).map(item => item.id), ["b", "a"]);
  assert.equal(mergeEvents([first], [second], 1)[0].id, "b");
});
test("a poll's overlap with loaded events is news only when an event is new or came back different", () => {
  const a = {id: "a", type: "ssh", cursor: "1", keyStatus: "unregistered"}, b = {id: "b", type: "ssh", cursor: "2"};
  assert.deepEqual(diffEvents([a, b], [{...b}, {...a}]), {added: [], revised: []});
  const recognized = {...a, keyStatus: "recognized"}, c = {id: "c", type: "ssh", cursor: "3"};
  assert.deepEqual(diffEvents([a, b], [{...b}, recognized, c, {id: "d", type: "not-a-type", cursor: "4"}]), {added: [c], revised: [recognized]});
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
  id: `event-${i}`, ip: `2001:db8::${(i + 1).toString(16)}`, latitude: 0, longitude: 0, observedAt: 1000 - i,
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
  const activity = mapActivity([{id: "missing", ip: "192.0.2.1", observedAt: 2000}, ...dots(7)], MAP_DEFAULTS, 10000);
  assert.equal(activity.points.length, 7);
  assert.equal(activity.unlocated, 1);
  assert.equal(countryFlag("US"), "\u{1f1fa}\u{1f1f8}");
  for (const code of [undefined, "ZZ", "XX", "usa", "<script>"]) assert.equal(countryFlag(code), "");
});

test("the map names every source it leaves out and says nothing when it draws all of them", () => {
  assert.equal(notDrawn({}), "");
  assert.equal(notDrawn({faded: 0, farSide: 0, unlocated: 0, omitted: 0}), "");
  assert.equal(notDrawn({faded: 3, farSide: 12, unlocated: 1, omitted: 2}),
    "Sources not drawn: 3 faded · 12 on far side · 1 unlocated · 2 over the dot limit");
  assert.equal(notDrawn({farSide: 4, omitted: 1}), "Sources not drawn: 4 on far side · 1 over the dot limit");
});

test("own traffic stays off the map even in history mode without displacing external dots", () => {
  const external = dots(7);
  const own = {...dots(1)[0], id: "own", origin: "own", observedAt: 20000};
  for (const history of [true, false]) {
    const activity = mapActivity([own, ...external], MAP_DEFAULTS, 20000, history);
    assert.deepEqual(activity.points.map(({latest}) => latest.id), external.map(item => item.id));
    assert.ok(activity.points.every(({opacity}) => opacity === 1));
  }
});

test("a flood refreshes one IP before applying source limits, without merging neighbors or changing the feed", () => {
  const [first, neighbor, other] = dots(3);
  const burst = Array.from({length: 100}, (_, i) => ({...first, id: `web-${i}`, type: "web", observedAt: 1001 + i}));
  const latest = {...first, id: "ssh", type: "ssh", latitude: null, observedAt: 1101};
  const events = [neighbor, ...burst, other, first, latest];
  const settings = mapSettings({keep: 1, maxDots: 2, fadeMinutes: 1});
  const activity = mapActivity(events, settings, 1131, true);
  assert.deepEqual(activity.points.map(p => [p.ip, p.count, p.latest.type, p.latest.id, p.opacity]),
    [[first.ip, 102, "ssh", "ssh", 1], [neighbor.ip, 1, undefined, neighbor.id, .12]]);
  assert.equal(activity.points[0].place.id, "web-99");
  assert.equal(activity.omitted, 1);
  assert.equal(activity.expired, 2); // Neither neighbor is kept bright by repeat hits from the flood.
  assert.deepEqual(mapActivity(events, settings, 1131).points.map(p => p.ip), [first.ip]);
  const history = mapActivity(events, {...settings, maxDots: 3}, 1200, true);
  assert.equal(history.points.length, 3);
  assert.equal(history.points[0].count, 102);
  assert.equal(events.length, 104);
  const filtered = mapActivity(events.filter(e => e.type === "web"), settings, 1200);
  assert.deepEqual(filtered.points.map(p => [p.count, p.latest.id]), [[100, "web-99"]]);
});

test("a source counts its matching events by kind and severity for its pie and ring", () => {
  const base = {ip: "192.0.2.4", latitude: 52, longitude: 13};
  const events = [
    ...[1, 2, 3].map(i => ({...base, id: `web-${i}`, type: "web", severity: "high", observedAt: i})),
    {...base, id: "plex", type: "plex", severity: "suspicious", observedAt: 4},
  ];
  const [source] = mapActivity(events, MAP_DEFAULTS, 5).points;
  assert.deepEqual(source.types, {web: 3, plex: 1});
  assert.deepEqual(source.severities, {high: 3, suspicious: 1});
  const mixed = mapActivity(demoEvents(1000), MAP_DEFAULTS, 1000, true).points.find(p => p.ip === "192.0.2.4");
  assert.deepEqual(mixed.types, {web: 3, plex: 1});
  assert.ok(Object.keys(mixed.severities).length > 1);
});

test("slices keep one part per key in canonical order, sized by count with a visible minimum", () => {
  const order = ["web", "plex", "ssh"];
  const parts = slices({ssh: 2, web: 6, plex: 0}, order);
  assert.deepEqual(parts.map(({key, count}) => [key, count]), [["web", 6], ["ssh", 2]]);
  assert.equal(parts[0].start, 0);
  assert.equal(parts.at(-1).end, 1);
  assert.equal(parts[1].start, parts[0].end);
  assert.ok(Math.abs(parts[0].end - (.1 + .8 * 6 / 8)) < 1e-9);
  const tiny = slices({web: 999, ssh: 1}, order);
  assert.ok(tiny[1].end - tiny[1].start >= .1);
  assert.deepEqual(slices({plex: 5}, order).map(({start, end}) => [start, end]), [[0, 1]]);
  assert.deepEqual(slices({}, order), []);
  assert.deepEqual(SEVERITY_ORDER, ["critical", "high", "suspicious", "low", "info"]);
  assert.deepEqual(TYPE_ORDER, Object.keys(TYPES));
});

test("slice paths draw unit sectors and arcs clockwise from the top", () => {
  assert.equal(slicePath({start: 0, end: 1}), "M0 -1A1 1 0 1 1 0 1A1 1 0 1 1 0 -1Z");
  assert.equal(slicePath({start: 0, end: 1}, true), "M0 -1A1 1 0 1 1 0 1A1 1 0 1 1 0 -1");
  assert.equal(slicePath({start: 0, end: .25}), "M0 0L0 -1A1 1 0 0 1 1 0Z");
  assert.equal(slicePath({start: .25, end: .9}, true), `M1 0A1 1 0 1 1 ${Number(Math.cos(2 * Math.PI * .9 - Math.PI / 2).toFixed(4))} ${Number(Math.sin(2 * Math.PI * .9 - Math.PI / 2).toFixed(4))}`);
});

test("live trapping ticks between samples, switches on close, and stops on stale or failed telemetry", () => {
  const opened = {available: true, seconds: 10, connections: 2};
  assert.deepEqual(liveTrapping(opened, 5000), {seconds: 20, connections: 2});
  assert.deepEqual(liveTrapping({available: true, seconds: 0, connections: 0}, 5000), {seconds: 0, connections: 0});
  assert.equal(liveTrapping(opened, 90001), null);
  assert.equal(liveTrapping({...opened, available: false}, 1000), null);
  assert.equal(liveTrapping(null, 0), null);
});

test("trapped time reads to the second and never rounds up into a longer unit", () => {
  const cases = [[0, "0 s"], [.04, "<0.1 s"], [.3, "0.3 s"], [2, "2 s"], [9.96, "10 s"], [9.7, "9.7 s"], [10, "10 s"], [41.2, "41 s"], [59.6, "1 min"],
    [60, "1 min"], [252, "4 min 12 s"], [312.6, "5 min 13 s"], [3599.6, "1 h"], [3900, "1 h 5 min"], [7200, "2 h"], [93600, "1 d 2 h"], [86400, "1 d"]];
  for (const [seconds, text] of cases) assert.equal(trapDuration(seconds), text, String(seconds));
  for (const bad of [-1, NaN, Infinity, null, undefined]) assert.equal(trapDuration(bad), "—");
});

// Events as the collector logs them: an open and, if the client left, a close with the connection's own `time=`.
const open = (id, timestamp, extra = {}) => ({id, kind: "endlessh_open", ip: "198.51.100.7", sourcePort: 50001, timestamp, observedAt: timestamp + .5, origin: "external", ...extra});
const close = (id, timestamp, seconds, extra = {}) => ({id, kind: "endlessh_close", ip: "198.51.100.7", sourcePort: 50001, timestamp, observedAt: timestamp + .5, origin: "external",
  ...(seconds === undefined ? {} : {duration: seconds}), ...extra});
const fresh = (extra = {}) => ({available: true, connections: 1, seconds: 30, asOf: 1030, through: 1030, active: [{ip: "198.51.100.7", sourcePort: 50001, since: 1000}], activeTruncated: false, ...extra});

test("an Endlessh connection reads as ended once its close is loaded, however the close is found", () => {
  const events = [close("c", 1042.5, 42.5), open("o", 1000)];
  assert.deepEqual(trapTime(events[0], events, null, 0), {state: "ended", seconds: 42.5});
  assert.deepEqual(trapTime(events[1], events, null, 0), {state: "ended", seconds: 42.5});
  // The close wins over a published list that still shows the connection.
  assert.deepEqual(trapTime(events[1], events, fresh(), 1000), {state: "ended", seconds: 42.5});
  assert.equal(trapTime({kind: "ssh_failure", ip: "198.51.100.7"}, events, fresh(), 0), null);
  assert.equal(trapTime(close("x", 1, undefined), events, null, 0), null);
});

test("an open connection ticks from the collector's clock while the published list names it", () => {
  const events = [open("o", 1000)];
  assert.deepEqual(trapTime(events[0], events, fresh(), 0), {state: "active", seconds: 30, since: 1000});
  assert.deepEqual(trapTime(events[0], events, fresh(), 12000), {state: "active", seconds: 42, since: 1000});
  // The list is only evidence for the connection it names: same address, same port and the same start.
  for (const row of [{ip: "198.51.100.8", sourcePort: 50001, since: 1000}, {ip: "198.51.100.7", sourcePort: 50002, since: 1000},
    {ip: "198.51.100.7", sourcePort: 50001, since: 900}]) {
    assert.deepEqual(trapTime(events[0], events, fresh({active: [row]}), 0), {state: "unknown"}, JSON.stringify(row));
  }
  assert.deepEqual(trapTime(events[0], events, fresh({active: undefined}), 0), {state: "unknown"});
});

test("an open the published list has not caught up with is still held, and one it should have listed is not", () => {
  const sample = fresh({active: [], connections: 0, seconds: 0, through: 1000});
  const newer = open("new", 1005, {observedAt: 1005.5});
  assert.deepEqual(trapTime(newer, [newer], sample, 2000), {state: "active", seconds: 27, since: 1005});
  // Older than the list's horizon yet missing from it: it closed without a logged close, or the list was truncated.
  const older = open("old", 990, {observedAt: 990.5});
  assert.deepEqual(trapTime(older, [older], sample, 2000), {state: "unknown"});
  assert.deepEqual(trapTime(older, [older], {...sample, activeTruncated: true}, 2000), {state: "unknown"});
});

test("no live claim is made from stale, unavailable or own-traffic telemetry", () => {
  const events = [open("o", 1000)];
  assert.deepEqual(trapTime(events[0], events, fresh(), 90001), {state: "unknown"});
  assert.deepEqual(trapTime(events[0], events, fresh({available: false}), 0), {state: "unknown"});
  assert.deepEqual(trapTime(events[0], events, fresh({asOf: undefined}), 0), {state: "unknown"});
  assert.deepEqual(trapTime(events[0], events, null, 0), {state: "unknown"});
  // The collector does not track our own connections, so it cannot say when they ended.
  const own = [open("own", 1000, {origin: "own"})];
  assert.deepEqual(trapTime(own[0], own, fresh(), 0), {state: "unknown"});
  assert.deepEqual(trapTime(own[0], [...own, close("c", 1010, 10, {origin: "own"})], fresh(), 0), {state: "ended", seconds: 10});
});

test("a reused source port never lends one connection's end to another", () => {
  const first = open("a", 1000), second = open("b", 2000, {observedAt: 2000.5});
  const events = [close("d", 2100, 100), second, first];
  // The second open owns the later close; the first was followed by another open, so nothing says how it ended.
  assert.deepEqual(trapTime(second, events, null, 0), {state: "ended", seconds: 100});
  assert.deepEqual(trapTime(first, events, null, 0), {state: "unknown"});
  assert.deepEqual(trapTime(first, events, fresh(), 0), {state: "unknown"});
  const other = [close("e", 1500, 500, {ip: "198.51.100.9"}), open("f", 1000, {sourcePort: undefined}), first];
  assert.deepEqual(trapTime(first, other, null, 0), {state: "unknown"});
  assert.deepEqual(trapTime(other[1], other, fresh(), 0), {state: "unknown"});
});

test("demo events pair each ended Endlessh connection with its close and keep the newest one open", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  const events = demoEvents(now);
  const opens = events.filter(item => item.kind === "endlessh_open"), closes = events.filter(item => item.kind === "endlessh_close");
  assert.equal(new Set(events.map(item => item.id)).size, events.length);
  assert.equal(opens.every(item => Number.isFinite(item.sourcePort)), true);
  assert.equal(new Set(opens.map(item => `${item.ip}|${item.sourcePort}`)).size, opens.length);
  assert.equal(closes.length, 3);
  const sample = demoTrapping(events, now / 1000);
  assert.deepEqual(opens.map(item => trapTime(item, events, sample, 0).state).sort(), ["active", "ended", "ended", "ended"]);
  assert.equal(sample.connections, 1);
  assert.deepEqual(sample.active, [{ip: "192.0.2.1", sourcePort: opens.find(item => item.id === "demo-0").sourcePort, since: now / 1000}]);
  assert.equal(sample.seconds, 0);
  const live = demoLiveEvent(5, now + 5000, (values => () => values.shift() ?? 0)([0, .5, .5, .5]));
  assert.equal(live.kind, "endlessh_open");
  const ended = [...events, live, demoCloseEvent(live, 7.5)];
  const after = demoTrapping(ended, now / 1000 + 20);
  assert.equal(after.connections, 1);
  assert.deepEqual(trapTime(live, ended, after, 0), {state: "ended", seconds: 7.5});
  assert.equal(demoCloseEvent(live, 7.5).id, "demo-close-live-5");
  // Closes sort after their opens in the stream.
  const merged = mergeEvents([], ended);
  assert.equal(merged.findIndex(item => item.id === "demo-close-live-5") < merged.findIndex(item => item.id === "demo-live-5"), true);
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
  assert.equal(merged.length, 95);
});

test("severity is read from the row or derived from its kind, and filters mirror the server", () => {
  assert.deepEqual(SEVERITIES.map(([level]) => level), ["info", "low", "suspicious", "high", "critical"]);
  assert.equal(severityOf({severity: "critical", kind: "endlessh_open"}), "critical");
  assert.equal(severityOf({kind: "plex_probe"}), "suspicious");
  assert.equal(severityOf({kind: "something_new"}), "low");
  const events = demoEvents(Date.parse("2026-01-01T00:00:00Z"));
  const kinds = new Set(events.map(item => item.kind));
  for (const kind of ["plex_client", "plex_probe", "plex_reachability", "hytale_rejected", "port_scan"]) assert.equal(kinds.has(kind), true, kind);
  assert.equal(events.some(item => item.service === "Forgejo SSH"), true);
  const external = events.filter(item => item.origin !== "own");
  const atLeast = level => external.filter(item => matchesFilters(item, {severity: level}));
  assert.equal(atLeast("info").length, external.length);
  assert.equal(atLeast("suspicious").every(item => ["suspicious", "high", "critical"].includes(severityOf(item))), true);
  assert.equal(atLeast("suspicious").some(item => item.kind === "plex_probe"), true);
  assert.equal(atLeast("suspicious").some(item => item.kind === "plex_client"), false);
  assert.equal(atLeast("critical").every(item => item.kind === "ssh_accepted_unknown"), true);
  const [first] = external;
  assert.equal(matchesFilters(first, {type: `nope,${first.type}`, outcome: `${first.verdict},accepted`}), true);
  assert.equal(matchesFilters(first, {type: "nope"}), false);
  assert.equal(matchesFilters(first, {country: first.countryCode, asn: String(first.asn)}), true);
  assert.equal(matchesFilters(first, {country: "ZZ"}), false);
  const own = {...first, origin: "own"};
  assert.equal(matchesFilters(own, {}), false);
  assert.equal(matchesFilters(own, {own: "1"}), true);
  assert.equal(OUTCOMES.some(([value]) => value === first.verdict), true);
});

test("facet counts equal what selecting each option would show", () => {
  const external = demoEvents(Date.parse("2026-01-01T00:00:00Z")).filter(item => item.origin !== "own");
  const rows = external.map(item => ({type: item.type, outcome: item.verdict, severity: severityOf(item),
    reputation: reputationGrade(item), reported: !!item.reputation?.reportedAt, count: 1}));
  for (const current of [{}, {type: "ssh,plex"}, {outcome: "failure"}, {severity: "suspicious", type: "web"}, {reputation: "high,reported"}, {reputation: "clean", type: "ssh"}]) {
    const counts = facetCounts(rows, current);
    const shown = change => external.filter(item => matchesFilters(item, {...current, ...change})).length;
    for (const type of Object.keys(TYPES)) assert.equal(counts.type[type] || 0, shown({type}), `${JSON.stringify(current)} ${type}`);
    for (const [outcome] of OUTCOMES) assert.equal(counts.outcome[outcome] || 0, shown({outcome}), `${JSON.stringify(current)} ${outcome}`);
    for (const [severity] of SEVERITIES) assert.equal(counts.severity[severity], shown({severity}), `${JSON.stringify(current)} ${severity}`);
    for (const [reputation] of REPUTATIONS) assert.equal(counts.reputation[reputation] || 0, shown({reputation}), `${JSON.stringify(current)} ${reputation}`);
  }
  assert.equal(new Set(rows.map(row => row.reputation)).size, 3, "the demo covers high, medium and clean");
  assert.equal(rows.some(row => row.reported), true);
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
