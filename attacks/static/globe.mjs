import {geoArea, geoCentroid, geoDistance, geoGraticule10, geoOrthographic, geoPath, versor} from "./geo-vendor.mjs";

const FALLBACK_LONGITUDE = -97.7421638889;
const VIEW_LATITUDE = 30.4291555556;
const HORIZON = Math.PI / 2 - 1e-6;

export function activityLongitude(points) {
  const edges = [], degrees = 180 / Math.PI;
  const focus = VIEW_LATITUDE / degrees;
  let count = 0, previous = 0;
  for (const {longitude, latitude} of points) {
    const sine = Math.sin(latitude / degrees) * Math.sin(focus);
    const cosine = Math.cos(latitude / degrees) * Math.cos(focus);
    // Solve the spherical horizon at the fixed viewing latitude.
    const limit = (Math.cos(HORIZON) - sine) / cosine;
    if (limit < -1) { count++; continue; }
    if (limit >= 1) continue;
    const halfWidth = Math.acos(limit) * degrees;
    const start = (longitude - halfWidth + 360) % 360;
    const end = (longitude + halfWidth + 360) % 360;
    if (start >= end) count++;
    edges.push([start, 1], [end, -1]);
  }
  if (!edges.length) return FALLBACK_LONGITUDE;
  edges.sort((a, b) => a[0] - b[0]);
  const intervals = [];
  for (let i = 0; i < edges.length;) {
    const angle = edges[i][0];
    if (angle > previous) intervals.push({start: previous, end: angle, count});
    do { count += edges[i++][1]; } while (i < edges.length && edges[i][0] === angle);
    previous = angle;
  }
  if (previous < 360) intervals.push({start: previous, end: 360, count});
  if (edges[0][0] > 0 && intervals[0].count === intervals.at(-1).count) {
    intervals[0].start = intervals.pop().start - 360;
  }
  // Among equally busy views, prefer the widest safe range to avoid limb crowding.
  const best = intervals.reduce((best, interval) => interval.count > best.count
    || (interval.count === best.count && interval.end - interval.start > best.end - best.start) ? interval : best);
  return ((best.start + best.end) / 2 + 540) % 360 - 180;
}

const wrap = degrees => ((degrees % 360) + 540) % 360 - 180;

// Turn between two views with north kept up: longitude takes the short way round and any roll unwinds.
export function turnPath(from, to) {
  const [longitude, latitude, roll = 0] = from, [targetLongitude, targetLatitude, targetRoll = 0] = to;
  const spin = wrap(targetLongitude - longitude), unroll = wrap(targetRoll - roll);
  const angle = geoDistance([-longitude, -latitude], [-targetLongitude, -targetLatitude]) * 180 / Math.PI;
  return {angle, at: t => [longitude + spin * t, latitude + (targetLatitude - latitude) * t, roll + unroll * t]};
}

// Frame a burst together when it fits within `spread` radians; otherwise face the newest (first) point.
export function followCenter(points, spread) {
  const coordinates = points.map(({longitude, latitude}) => [longitude, latitude]);
  if (coordinates.length > 1) {
    const center = geoCentroid({type: "MultiPoint", coordinates});
    if (center.every(Number.isFinite) && coordinates.every(point => geoDistance(center, point) <= spread)) return center;
  }
  return coordinates[0];
}

export function detailLevel(zoom) {
  return zoom >= 6 ? "10m" : zoom >= 2.5 ? "50m" : "110m";
}

export function globeGeometry(geometry) {
  const rewind = coordinates => geoArea({type: "Polygon", coordinates}) > 2 * Math.PI
    ? coordinates.map(ring => ring.toReversed()) : coordinates;
  // Natural Earth countries are smaller than a hemisphere; D3 uses clockwise exteriors.
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return {type: "GeometryCollection", geometries: polygons.map(coordinates => {
    const part = {type: "Polygon", coordinates: rewind(coordinates)};
    part.center = geoCentroid(part);
    part.radius = 0;
    for (const ring of part.coordinates) for (const point of ring)
      part.radius = Math.max(part.radius, geoDistance(part.center, point));
    return part;
  })};
}

export function createGlobe() {
  const initial = [-FALLBACK_LONGITUDE, -VIEW_LATITUDE, 0];
  const projection = geoOrthographic().translate([500, 250]).scale(235).rotate(initial).clipAngle(90);
  const path = geoPath(projection), grid = geoGraticule10();
  let visibleArc = Math.PI / 2, reach = Math.PI / 2;
  function drag(from, to) {
    const a = projection.invert(from), b = projection.invert(to);
    if (![...a, ...b].every(Number.isFinite)) return;
    const rotation = versor.rotation(versor.multiply(versor(projection.rotate()),
      versor.delta(versor.cartesian(a), versor.cartesian(b))));
    if (rotation.every(Number.isFinite)) projection.rotate(rotation);
  }
  return {
    drag,
    reset: (points = []) => projection.rotate([-activityLongitude(points), -VIEW_LATITUDE, 0]),
    rotation: () => projection.rotate(),
    rotate: rotation => { projection.rotate(rotation); },
    // Angular radius of the largest globe cap the viewport shows in full.
    reach: () => reach,
    resize: (width, height, zoom) => {
      projection.scale(Math.min(width, height) * .47).precision(.3 / zoom);
      projection.clipExtent([[500 - width / zoom / 2, 250 - height / zoom / 2],
        [500 + width / zoom / 2, 250 + height / zoom / 2]]);
      visibleArc = Math.asin(Math.min(1, Math.hypot(width, height) / 2 / zoom / projection.scale()));
      reach = Math.asin(Math.min(1, Math.min(width, height) / 2 / zoom / projection.scale()));
    },
    path: geometry => {
      const center = projection.invert([500, 250]);
      // Cull entire island polygons before projecting their detailed coastlines.
      const visible = geometry.type === "GeometryCollection" ? {...geometry,
        geometries: geometry.geometries.filter(part => geoDistance(center, part.center) <= part.radius + visibleArc + .001)} : geometry;
      return path(visible) || "";
    },
    grid: () => path(grid),
    sphere: () => {
      const r = projection.scale();
      return `M${500 - r},250a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0Z`;
    },
    position: (longitude, latitude) => {
      const location = [longitude, latitude], [x, y] = projection(location);
      const angle = geoDistance(projection.invert([500, 250]), location);
      return {x, y, angle, visible: angle < HORIZON};
    },
  };
}
