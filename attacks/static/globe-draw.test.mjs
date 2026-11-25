import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {geoContains, geoDistance, geoGraticule10, geoOrthographic, geoPath} from "d3-geo";
import {MAP_FILES} from "./atlas.mjs";
import {feature} from "./geo-vendor.mjs";
import {createGlobe, globeGeometry, prepareGrid, prepareLand} from "./globe.mjs";
import {createPainter, prepareShape} from "./globe-draw.mjs";

const TAU = 2 * Math.PI, RADIANS = Math.PI / 180;
// The zoom range in which each border detail is drawn (see detailLevel).
const ZOOMS = {"110m": [1, 2.5], "50m": [2.5, 6], "10m": [6, 128]};
// Areas are compared with d3 only where its fine precision does not also subdivide the horizon, which would make it fill more than its own 2° chords.
const AREA_ZOOMS = {"110m": [1, 2.5], "50m": [1, 6], "10m": [1, 3]};
// d3 interpolates the horizon in chords of 2°, which cut slightly more off a country than the exact arcs drawn here.
const CHORD = 2 * RADIANS;

function generator(seed) {
  return () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const atlases = new Map();
async function atlas(level) {
  if (!atlases.has(level)) {
    const topology = JSON.parse(await readFile(new URL(MAP_FILES[level].slice(1), import.meta.url), "utf8"));
    atlases.set(level, feature(topology, topology.objects.countries).features.filter(item => item.geometry).map(item => {
      const geometry = globeGeometry(item.geometry);
      return {id: item.id, parts: geometry.geometries, shape: prepareLand(geometry, level)};
    }));
  }
  return atlases.get(level);
}

// A viewport as the map computes it for `globe.resize`, aimed at a random vertex so that borders are in view at high zoom.
function randomView(level, countries, random, zooms = ZOOMS[level]) {
  const between = (low, high) => low + (high - low) * random();
  const [low, high] = zooms, zoom = Math.exp(between(Math.log(low), Math.log(high)));
  const boxWidth = between(320, 1600), boxHeight = between(320, 1000);
  const width = Math.max(1000, 500 * boxWidth / boxHeight), height = Math.max(500, 1000 * boxHeight / boxWidth);
  const country = countries[Math.floor(random() * countries.length)];
  const part = country.parts[Math.floor(random() * country.parts.length)];
  const ring = part.coordinates[0], vertex = ring[Math.floor(random() * ring.length)];
  const rotation = [-vertex[0], -vertex[1], random() < .3 ? between(-40, 40) : 0];
  if (random() < .15) rotation[1] = between(-90, 90);
  const scale = Math.min(width, height) * .47;
  return {zoom, boxWidth, width, height, rotation, scale, pixel: width / zoom / boxWidth,
    left: 500 - width / zoom / 2, right: 500 + width / zoom / 2, top: 250 - height / zoom / 2, bottom: 250 + height / zoom / 2};
}

function reference(view, extent = true, precision = .3 / view.zoom) {
  const projection = geoOrthographic().translate([500, 250]).scale(view.scale).rotate(view.rotation).clipAngle(90).precision(precision);
  return extent ? projection.clipExtent([[view.left, view.top], [view.right, view.bottom]]) : projection;
}

// Reads back the path data: arcs along the horizon become points on it, as chords when `chords` is set.
function flatten(path, unit, view, chords = false) {
  const tokens = path.match(/[MLAZ]|-?\d*\.?\d+(?:e[-+]?\d+)?/gi) ?? [], polylines = [];
  const center = 500 * unit, middle = 250 * unit, radius = view.scale * unit;
  let current = null, command = "", i = 0;
  const next = () => Number(tokens[i++]);
  while (i < tokens.length) {
    if (/^[MLAZ]$/.test(tokens[i])) { command = tokens[i++]; continue; }
    if (command === "M") { current = [[next(), next()]]; polylines.push(current); command = "L"; }
    else if (command === "L") current.push([next(), next()]);
    else if (command === "A") {
      i += 3;
      const large = next(), sweep = next(), x = next(), y = next(), [x0, y0] = current.at(-1);
      const start = Math.atan2(y0 - middle, x0 - center), delta = (((Math.atan2(y - middle, x - center) - start) % TAU) + TAU) % TAU;
      assert.equal(sweep, 1, "horizon arcs run clockwise");
      assert.ok(Boolean(large) === delta > Math.PI || Math.abs(delta - Math.PI) < 1e-3, "large-arc flag matches the arc");
      const steps = chords ? Math.floor((delta - 1e-9) / CHORD) : Math.max(1, Math.ceil(delta / .002));
      for (let step = 1; step <= steps; step++) {
        const angle = start + (chords ? step * CHORD : delta * step / steps);
        if (chords || step < steps) current.push([center + radius * Math.cos(angle), middle + radius * Math.sin(angle)]);
      }
      current.push([x, y]);
    } else throw new Error(`Unexpected ${tokens[i - 1]} in path`);
  }
  return polylines.map(points => points.map(([x, y]) => [x / unit, y / unit]));
}

function winding(polylines, x, y) {
  let count = 0;
  for (const points of polylines) {
    for (let k = 0, n = points.length; k < n; k++) {
      const [x0, y0] = points[k], [x1, y1] = points[k + 1 === n ? 0 : k + 1];
      const side = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0);
      if (y0 <= y) { if (y1 > y && side > 0) count++; }
      else if (y1 <= y && side < 0) count--;
    }
  }
  return count;
}

function distanceTo(points, x, y, closed) {
  let best = Infinity;
  for (let k = 0, n = points.length; k < (closed ? n : n - 1); k++) {
    const [x0, y0] = points[k], [x1, y1] = points[(k + 1) % n], dx = x1 - x0, dy = y1 - y0, length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / length)) : 0;
    best = Math.min(best, Math.hypot(x - x0 - t * dx, y - y0 - t * dy));
  }
  return best;
}

function area(polylines) {
  let sum = 0, perimeter = 0;
  for (const points of polylines) {
    for (let k = 0, n = points.length; k < n; k++) {
      const [x0, y0] = points[k], [x1, y1] = points[(k + 1) % n];
      sum += x0 * y1 - x1 * y0; perimeter += Math.hypot(x1 - x0, y1 - y0);
    }
  }
  return {area: Math.abs(sum / 2), perimeter};
}

// A sample must be painted as exact spherical containment says, unless it is within a pixel of a border, where either side is a tie.
function assertFill(label, polylines, parts, projection, points, view) {
  let samples = 0, limb = 0;
  for (const [x, y] of points) {
    const radius = Math.hypot(x - 500, y - 250);
    if (radius >= view.scale * .995) continue;
    samples++; limb += radius > view.scale * .9;
    const location = projection.invert([x, y]);
    const expected = parts.some(part => geoDistance(part.center, location) <= part.radius + 1e-6 && geoContains(part, location));
    if (expected === (winding(polylines, x, y) !== 0)) continue;
    const nearest = Math.min(...polylines.map(line => distanceTo(line, x, y, true))) / view.pixel;
    assert.ok(nearest <= .75, `${label}: ${expected ? "land" : "sea"} painted wrongly ${nearest.toFixed(2)} px from a border at ${x.toFixed(2)},${y.toFixed(2)} in ${JSON.stringify(view)}`);
  }
  return {samples, limb};
}

test("land fills are exactly the countries, including across the horizon and the viewport edge", async () => {
  const counts = {"110m": 14, "50m": 14, "10m": 5};
  for (const level of ["110m", "50m", "10m"]) {
    const countries = await atlas(level), random = generator(7);
    let samples = 0, limb = 0;
    for (let trial = 0; trial < counts[level]; trial++) {
      const view = randomView(level, countries, random), projection = reference(view);
      const globe = createGlobe();
      globe.rotate(view.rotation);
      globe.resize(view.width, view.height, view.zoom, view.boxWidth);
      const unit = globe.aim();
      const polylines = flatten(countries.map(country => globe.shape(country.shape)).join(""), unit, view);
      const center = projection.invert([500, 250]);
      const near = countries.flatMap(country => country.parts)
        .filter(part => geoDistance(center, part.center) <= part.radius + Math.asin(Math.min(1, Math.hypot(view.width, view.height) / 2 / view.zoom / view.scale)) + .001);
      const between = (low, high) => low + (high - low) * random();
      const points = [];
      for (let k = 0; k < 150; k++) points.push([between(view.left, view.right), between(view.top, view.bottom)]);
      // The horizon is where arcs are stitched, so it is sampled on its own where the viewport reaches it.
      for (let k = 0; k < 100; k++) {
        const angle = between(0, TAU), r = view.scale * between(.9, .999);
        points.push([500 + r * Math.cos(angle), 250 + r * Math.sin(angle)]);
      }
      // Points a few pixels either side of a drawn border are where a wrong turn shows.
      const edges = polylines.flat();
      for (let k = 0; k < 100 && edges.length; k++) {
        const [x, y] = edges[Math.floor(random() * edges.length)];
        points.push([x + between(-3, 3) * view.pixel, y + between(-3, 3) * view.pixel]);
      }
      const inView = points.filter(([x, y]) => x >= view.left && x <= view.right && y >= view.top && y <= view.bottom);
      const checked = assertFill(`${level} trial ${trial}`, polylines, near, projection, inView, view);
      samples += checked.samples; limb += checked.limb;
    }
    // Only the wider views reach the horizon; at 10m the viewport is a small patch around the center.
    assert.ok(samples > counts[level] * 100 && (limb > 0 || level === "10m"), `${level} sampled ${samples} points, ${limb} near the horizon`);
  }
});

test("Antarctica's slit and the pole are filled exactly when the pole is just in or out of view", async () => {
  // Antarctica is cut along the antimeridian, so its rings leave and re-enter the horizon at identical angles.
  // d3's own fill loses a fifth of the main polygon in the second view at 10m, so exact containment is the reference.
  const views = [
    {rotation: [50.92790927909277, 0.32744201626016434, 0], scale: 235, pixel: .157},
    {rotation: [-173.03033030330306, -1.7175691761517555, 0], scale: 470, pixel: .7368880261798231},
    {rotation: [-103.99603996039963, -1.3651606260162623, 0], scale: 235, pixel: .9485362142477806},
  ];
  const random = generator(11), between = (low, high) => low + (high - low) * random();
  for (const level of ["110m", "50m", "10m"]) {
    const [antarctica] = (await atlas(level)).filter(country => country.id === "ATA");
    assert.ok(antarctica, `${level} has Antarctica`);
    for (const view of views) {
      const painter = createPainter(), projection = reference({...view, zoom: 1}, false);
      const unit = painter.view({rotation: view.rotation, scale: view.scale, pixel: view.pixel, arc: Math.PI});
      const polylines = flatten(painter.shape(antarctica.shape), unit, view), edges = polylines.flat();
      let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
      for (const [x, y] of edges) { left = Math.min(left, x); top = Math.min(top, y); right = Math.max(right, x); bottom = Math.max(bottom, y); }
      // Most of the sphere is not Antarctica, so the samples are drawn from the box around what is painted.
      const points = [];
      for (let k = 0; k < 1200; k++) points.push([between(left, right), between(top, bottom)]);
      for (let k = 0; k < 300; k++) {
        const [x, y] = edges[Math.floor(random() * edges.length)];
        points.push([x + between(-3, 3) * view.pixel, y + between(-3, 3) * view.pixel]);
      }
      const {samples} = assertFill(`${level} at ${view.rotation}`, polylines, antarctica.parts, projection, points, view);
      assert.ok(edges.length > 0 && samples > 500, `${level} at ${view.rotation}: ${samples} samples`);
    }
  }
});

test("every polygon keeps the area d3 gives it as the globe turns", async () => {
  for (const [level, trials] of [["110m", 6], ["50m", 6], ["10m", 3]]) {
    const countries = await atlas(level), random = generator(5), painter = createPainter();
    for (let trial = 0; trial < trials; trial++) {
      const view = randomView(level, countries, random, AREA_ZOOMS[level]), projection = reference(view, false);
      const unit = painter.view({rotation: view.rotation, scale: view.scale, pixel: view.pixel, arc: Math.PI});
      const center = projection.invert([500, 250]);
      // Antarctica's slit is where d3 itself goes wrong, so it has its own exact test.
      for (const country of countries.filter(country => country.id !== "ATA")) country.parts.forEach((part, index) => {
        if (geoDistance(center, part.center) > part.radius + Math.PI / 2 + .01) return;
        const expected = geoPath(projection).area(part);
        const {area: actual, perimeter} = area(flatten(painter.shape([country.shape[index]]), unit, view, true));
        const shift = Math.abs(actual - expected) / Math.max(perimeter, 1) / view.pixel;
        assert.ok(shift <= .1 || Math.abs(actual - expected) <= 1, `${level} ${country.id} part ${index}: area ${actual.toFixed(1)}, d3 ${expected.toFixed(1)}`);
      });
    }
  }
});

test("graticule strokes follow d3's and stop at the horizon", () => {
  const painter = createPainter(), grid = geoGraticule10();
  for (const [level, trials, seed] of [["110m", 6, 3], ["50m", 5, 4], ["10m", 4, 9]]) {
    const lines = prepareGrid(level), random = generator(seed);
    for (let trial = 0; trial < trials; trial++) {
      const between = (low, high) => low + (high - low) * random();
      const [low, high] = ZOOMS[level], zoom = Math.exp(between(Math.log(low), Math.log(high)));
      const boxWidth = between(320, 1600), boxHeight = between(320, 1000);
      const width = Math.max(1000, 500 * boxWidth / boxHeight), height = Math.max(500, 1000 * boxHeight / boxWidth);
      const scale = Math.min(width, height) * .47, rotation = [between(-180, 180), between(-90, 90), 0];
      const view = {zoom, boxWidth, width, height, rotation, scale, pixel: width / zoom / boxWidth,
        left: 500 - width / zoom / 2, right: 500 + width / zoom / 2, top: 250 - height / zoom / 2, bottom: 250 + height / zoom / 2};
      const unit = painter.view({rotation, scale, pixel: view.pixel, left: view.left, top: view.top, right: view.right, bottom: view.bottom});
      const mine = flatten(painter.lines(lines), unit, view);
      // d3 checks only one midpoint per subdivision, so a fine precision stands in for the exact curve.
      const exact = flatten(geoPath(reference(view, true, .01))(grid) ?? "", 1, view);
      const inset = 2 * view.pixel;
      for (const [from, to, label] of [[mine, exact, "painted line missing from d3"], [exact, mine, "d3 line missing from painter"]]) {
        for (const points of from) for (let k = 0; k + 1 < points.length; k++) {
          const [x0, y0] = points[k], [x1, y1] = points[k + 1], count = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / (3 * view.pixel)));
          for (let q = 0; q <= count; q++) {
            const x = x0 + (x1 - x0) * q / count, y = y0 + (y1 - y0) * q / count;
            // d3 drops a line that only grazes the viewport edge.
            if (x < view.left + inset || x > view.right - inset || y < view.top + inset || y > view.bottom - inset) continue;
            const nearest = Math.min(...to.map(other => distanceTo(other, x, y, false))) / view.pixel;
            assert.ok(nearest <= 1, `${level} trial ${trial}: ${label}, ${nearest.toFixed(2)} px away at ${x.toFixed(2)},${y.toFixed(2)}`);
          }
        }
      }
    }
  }
});

test("prepared edges are split along great circles and the closing vertex is dropped", () => {
  const maxEdge = 2.5 * RADIANS;
  const square = {type: "Polygon", coordinates: [[[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]], center: [20, 20], radius: .6};
  const [part] = prepareShape([square], maxEdge), vertices = part.rings[0].v;
  assert.ok(vertices.length / 3 >= 64 && vertices.length / 3 < 80);
  for (let i = 0; i < vertices.length; i += 3) {
    const j = (i + 3) % vertices.length;
    const dot = vertices[i] * vertices[j] + vertices[i + 1] * vertices[j + 1] + vertices[i + 2] * vertices[j + 2];
    assert.ok(Math.acos(Math.min(1, dot)) <= maxEdge + 1e-6, "no edge is longer than the limit, including the one that closes the ring");
  }
  // Latitude 40 is reached by a great circle bulging poleward of the straight chord on a map, so the midpoint is not on the parallel.
  const middle = vertices.slice(3 * 16 + 3 * 8, 3 * 16 + 3 * 8 + 3);
  assert.ok(Math.abs(Math.asin(middle[2]) / RADIANS - 40) > .1);
  assert.deepEqual(prepareShape([{...square, coordinates: [[[0, 0], [1, 1], [0, 0]]]}], maxEdge)[0].rings, []);
});

test("the painter's coordinate unit follows how many plane units a screen pixel covers", () => {
  const painter = createPainter(), view = pixel => painter.view({rotation: [0, 0, 0], scale: 235, pixel});
  assert.equal(view(6), 1);
  assert.equal(view(5), 1);
  assert.equal(view(.9), 10);
  assert.equal(view(.0078), 1000);
  assert.equal(view(.0001), 100000);
});
