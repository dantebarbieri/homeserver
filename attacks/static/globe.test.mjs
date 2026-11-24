import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {activityLongitude, createGlobe, globeGeometry, detailLevel} from "./globe.mjs";
import {feature, geoArea, geoCentroid} from "./geo-vendor.mjs";
import {MAP_FILES} from "./atlas.mjs";

test("globe dragging keeps a grabbed geographic location under the pointer", () => {
  const globe = createGlobe();
  for (const [width, height] of [[1000, 500], [1000, 1500]]) {
    globe.reset([{longitude: 12, latitude: 18}]); globe.resize(width, height, 1);
    const before = globe.position(12, 18);
    globe.drag([before.x, before.y], [before.x + 70, before.y + 30]);
    const after = globe.position(12, 18);
    assert.ok(Math.abs(after.x - before.x - 70) < .001);
    assert.ok(Math.abs(after.y - before.y - 30) < .001);
    assert.equal(after.visible, true);
    assert.equal(globe.position(-168, -18).visible, false);
  }
});

test("country winding and horizon clipping do not paint the back hemisphere", () => {
  const globe = createGlobe();
  globe.reset([{longitude: 12, latitude: 18}]);
  const country = globeGeometry({type: "Polygon", coordinates: [[[5, 10], [20, 10], [20, 25], [5, 25], [5, 10]]]});
  const far = globeGeometry({type: "Polygon", coordinates: [[[160, -10], [175, -10], [175, 10], [160, 10], [160, -10]]]});
  assert.ok(geoArea(country) < 1);
  assert.ok(globe.path(country).length > 20);
  assert.equal(globe.path(far), "");
  const point = globe.position(12, 18);
  globe.drag([point.x, point.y], [520, 265]);
  // The same anchor adjustment is used when pinch zoom changes the SVG viewBox.
  const moved = globe.position(12, 18);
  globe.drag([moved.x, moved.y], [510, 257.5]);
  assert.ok(Math.abs(globe.position(12, 18).x - 510) < .001);
});

test("activity reset removes roll and faces the busiest hemisphere across the date line", () => {
  const points = [170, 175, -178, -172, 0, 0].map(longitude => ({longitude, latitude: 0}));
  const globe = createGlobe();
  globe.drag([500, 250], [560, 300]);
  globe.reset(points);
  assert.ok(Math.abs(Math.abs(activityLongitude(points)) - 180) < 10);
  assert.equal(points.filter(point => globe.position(point.longitude, point.latitude).visible).length, 4);
  const [longitude, tilt, roll] = globe.rotation();
  assert.ok(Number.isFinite(longitude));
  assert.ok(Math.abs(tilt + (30 + 25 / 60 + 44.96 / 3600)) < 1e-8);
  assert.equal(roll, 0);
  const north = globe.position(0, 90), south = globe.position(0, -90);
  assert.ok(Math.abs(north.x - 500) < 1e-8 && north.y < 250);
  assert.ok(Math.abs(south.x - 500) < 1e-8 && south.y > 250);
  assert.equal(north.visible, true);
  assert.equal(south.visible, false);
});

test("activity centering handles the prime meridian, dense sources and an empty map", () => {
  assert.ok(Math.abs(activityLongitude([{longitude: -10, latitude: 0}, {longitude: 10, latitude: 0}])) < 1e-8);
  const dense = Array.from({length: 8}, () => ({longitude: -100, latitude: 45}));
  const points = [...dense, {longitude: 80, latitude: -45}, {longitude: 90, latitude: -45}];
  const globe = createGlobe();
  globe.reset(points);
  assert.equal(points.filter(point => globe.position(point.longitude, point.latitude).visible).length, 9);
  globe.reset([]);
  assert.ok(Math.abs(globe.rotation()[0] - (97 + 44 / 60 + 31.79 / 3600)) < 1e-8);
  const latitude = 30 + 25 / 60 + 44.96 / 3600;
  assert.ok(Math.abs(globe.rotation()[1] + latitude) < 1e-8);
  assert.equal(globe.rotation()[2], 0);
  for (const view of [globe, createGlobe()]) {
    const center = view.position(-(97 + 44 / 60 + 31.79 / 3600), latitude);
    assert.ok(Math.abs(center.x - 500) < 1e-8 && Math.abs(center.y - 250) < 1e-8);
  }
});

test("reset maximizes visible dots at the northern tilt, including polar visibility", () => {
  const cases = [
    [0, 180].map(longitude => ({longitude, latitude: 0})),
    [0, 60, 120, 180, -120, -60].map(longitude => ({longitude, latitude: 30})),
    [{longitude: 25, latitude: 89.9999}, {longitude: -25, latitude: 89.9999},
      {longitude: 100, latitude: -40}, {longitude: 0, latitude: 90}, {longitude: 0, latitude: -90}],
    [{longitude: 0, latitude: 90}, {longitude: -120, latitude: -90}],
    [{longitude: 0, latitude: -80}],
  ];
  for (const points of cases) {
    const globe = createGlobe();
    globe.reset(points);
    const count = points.filter(point => globe.position(point.longitude, point.latitude).visible).length;
    const radians = Math.PI / 180;
    const focus = (30 + 25 / 60 + 44.96 / 3600) * radians;
    let best = 0;
    for (let longitude = -180; longitude < 180; longitude += .25)
      best = Math.max(best, points.filter(point =>
        Math.sin(point.latitude * radians) * Math.sin(focus)
        + Math.cos(point.latitude * radians) * Math.cos(focus) * Math.cos((point.longitude - longitude) * radians) > Math.sin(1e-6)).length);
    assert.equal(count, best);
  }
});

test("progressive atlas adds real tiny territories and preserves them at close zoom", async () => {
  assert.equal(detailLevel(1), "110m");
  assert.equal(detailLevel(3), "50m");
  assert.equal(detailLevel(8), "10m");
  const read = async level => {
    const topology = JSON.parse(await readFile(new URL(MAP_FILES[level].slice(1), import.meta.url), "utf8"));
    return feature(topology, topology.objects.countries).features;
  };
  const coarse = await read("110m"), medium = await read("50m"), detailed = await read("10m");
  assert.ok(medium.length > coarse.length && detailed.length > medium.length);
  for (const id of ["SGP", "MCO", "VAT", "SMR", "HKG"]) {
    const item = detailed.find(item => item.id === id);
    assert.ok(item, `Missing ${id}`);
    const geometry = globeGeometry(item.geometry), center = geoCentroid(geometry);
    assert.ok(geoArea(geometry) > 0 && geoArea(geometry) < .01, `${id} must be a real small polygon`);
    const globe = createGlobe();
    for (let turn = 0; turn < 16 && !globe.position(...center).visible; turn++) globe.drag([500, 250], [400, 250]);
    const point = globe.position(...center);
    assert.ok(point.visible);
    globe.drag([point.x, point.y], [500, 250]);
    globe.resize(1000, 500, 128);
    const outline = globe.path(geometry);
    assert.ok(outline.length > 10 && !outline.includes("NaN"), `${id} must survive close-zoom clipping`);
  }
});
