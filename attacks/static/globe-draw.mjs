// Orthographic painter for the globe's land and graticule.
//
// d3-geo pushes every vertex of every polygon in view through rotate, clip, resample and project on each frame, which
// costs tens of milliseconds once detailed borders are loaded. Here geometry is prepared once as unit vectors with long
// edges already split. A frame rotates vertices by a 3×3 matrix, cuts rings at the horizon and writes only the vertices
// that can touch the viewport, as integers in a coordinate space scaled by `unit` (see `view`), which keeps number
// formatting cheap.

const TAU = 2 * Math.PI;
const RADIANS = Math.PI / 180;
// Vertices closer than NEAR px to the last written one are dropped; MARGIN px around the viewport keep strokes whole.
const NEAR = .3, MARGIN = 4;

export function unitVector(longitude, latitude) {
  const lon = longitude * RADIANS, lat = latitude * RADIANS, flat = Math.cos(lat);
  return [flat * Math.cos(lon), flat * Math.sin(lon), Math.sin(lat)];
}

// Flat xyz triples in which no great-circle edge exceeds `maxEdge` radians, so straight edges need no per-frame resampling.
function densify(points, maxEdge) {
  const count = points.length, units = new Float64Array(3 * count), steps = new Int32Array(count);
  let total = count;
  for (let i = 0; i < count; i++) {
    const [x, y, z] = unitVector(points[i][0], points[i][1]);
    units[3 * i] = x; units[3 * i + 1] = y; units[3 * i + 2] = z;
    if (i) {
      const dot = x * units[3 * i - 3] + y * units[3 * i - 2] + z * units[3 * i - 1];
      steps[i] = Math.max(1, Math.ceil(Math.acos(Math.max(-1, Math.min(1, dot))) / maxEdge));
      total += steps[i] - 1;
    }
  }
  const flat = new Float32Array(3 * total);
  let at = 0;
  for (let i = 0; i < count; i++) {
    const x = units[3 * i], y = units[3 * i + 1], z = units[3 * i + 2];
    for (let step = 1; step < steps[i]; step++) {
      const t = step / steps[i], px = units[3 * i - 3], py = units[3 * i - 2], pz = units[3 * i - 1];
      const ix = px + (x - px) * t, iy = py + (y - py) * t, iz = pz + (z - pz) * t, length = Math.hypot(ix, iy, iz) || 1;
      flat[at++] = ix / length; flat[at++] = iy / length; flat[at++] = iz / length;
    }
    flat[at++] = x; flat[at++] = y; flat[at++] = z;
  }
  return flat;
}

// A bounding cap lets most rings skip the per-vertex horizon test, or be skipped outright.
function prepareRing(v) {
  let x = 0, y = 0, z = 0;
  for (let i = 0; i < v.length; i += 3) { x += v[i]; y += v[i + 1]; z += v[i + 2]; }
  const length = Math.hypot(x, y, z);
  if (length < 1e-9) return {v, x: 1, y: 0, z: 0, sin: 1, valid: false, start: 0};
  x /= length; y /= length; z /= length;
  let cos = 1;
  for (let i = 0; i < v.length; i += 3) cos = Math.min(cos, x * v[i] + y * v[i + 1] + z * v[i + 2]);
  const radius = Math.acos(Math.max(-1, cos));
  // `start` remembers a vertex that was hidden last frame, which usually still is.
  return {v, x, y, z, sin: Math.sin(radius), valid: radius < Math.PI / 2 - .01, start: 0};
}

// `parts` are polygons wound for d3 (see globeGeometry) with a `center` [lon, lat] and an angular `radius`.
export function prepareShape(parts, maxEdge) {
  return parts.map(part => {
    const [x, y, z] = unitVector(part.center[0], part.center[1]), rings = [];
    for (const coordinates of part.coordinates) {
      const flat = densify(coordinates, maxEdge);
      // GeoJSON rings repeat their first point.
      if (flat.length >= 12) rings.push(prepareRing(flat.subarray(0, flat.length - 3)));
    }
    return {x, y, z, radius: part.radius, rings};
  });
}

export function prepareLines(lines, maxEdge) {
  return lines.map(line => densify(line, maxEdge));
}

export function createPainter() {
  // Rows of the rotation: depth toward the viewer, screen right, screen up.
  let a0 = 1, a1 = 0, a2 = 0, b0 = 0, b1 = 1, b2 = 0, c0 = 0, c1 = 0, c2 = 1;
  let unit = 1, radius = 1, centerX = 0, centerY = 0, arc = Math.PI / 2;
  let minX = -Infinity, maxX = Infinity, minY = -Infinity, maxY = Infinity, near2 = 0;
  // The path being written. Vertices outside the viewport on a shared side are collapsed to their ends, and vertices
  // within a fraction of a pixel of the last one are dropped. `mask` holds the sides shared by the collapsed vertices
  // and `outside` the sides shared by everything since `begin`.
  let text = "", firstX = 0, firstY = 0, lastX = 0, lastY = 0, lastCode = 0, mask = 0, outside = 0;
  let held = false, heldX = 0, heldY = 0, heldCode = 0;
  let limbRight = 0, limbUp = 0;
  const runs = [];

  const code = (x, y) => (x < minX ? 1 : x > maxX ? 2 : 0) | (y < minY ? 4 : y > maxY ? 8 : 0);
  const screenX = right => Math.floor(centerX + radius * right + .5) | 0;
  const screenY = up => Math.floor(centerY - radius * up + .5) | 0;

  // Sets the rotation and viewport and returns `unit`: coordinates come out as integers in 1/unit of an SVG user unit,
  // so the element that holds the paths needs `transform="scale(1/unit)"`. `pixel` is user units per CSS pixel.
  function view(options) {
    const {rotation, scale, x = 500, y = 250, pixel = 1, left = -Infinity, top = -Infinity, right = Infinity, bottom = Infinity} = options;
    const lambda = rotation[0] * RADIANS, phi = rotation[1] * RADIANS, gamma = (rotation[2] ?? 0) * RADIANS;
    const cl = Math.cos(lambda), sl = Math.sin(lambda), cp = Math.cos(phi), sp = Math.sin(phi), cg = Math.cos(gamma), sg = Math.sin(gamma);
    a0 = cp * cl; a1 = -cp * sl; a2 = -sp;
    const k0 = sp * cl, k1 = -sp * sl, k2 = cp;
    b0 = cg * sl - sg * k0; b1 = cg * cl - sg * k1; b2 = -sg * k2;
    c0 = cg * k0 + sg * sl; c1 = cg * k1 + sg * cl; c2 = cg * k2;
    unit = 10 ** Math.max(0, Math.ceil(Math.log10(5 / pixel)));
    radius = scale * unit; centerX = x * unit; centerY = y * unit; arc = options.arc ?? Math.PI / 2;
    const margin = MARGIN * pixel * unit;
    minX = left * unit - margin; maxX = right * unit + margin;
    minY = top * unit - margin; maxY = bottom * unit + margin;
    near2 = (NEAR * pixel * unit) ** 2;
    return unit;
  }

  function begin(x, y) {
    firstX = lastX = x; firstY = lastY = y;
    lastCode = mask = outside = code(x, y);
    text = ""; held = false;
  }

  function put(x, y, c) {
    const dx = x - lastX, dy = y - lastY;
    if (dx * dx + dy * dy < near2) { mask = lastCode; return; }
    text += " " + x + "," + y;
    lastX = x; lastY = y; lastCode = mask = c;
  }

  function add(x, y) {
    const c = code(x, y);
    outside &= c;
    if (mask & c) { held = true; heldX = x; heldY = y; heldCode = c; mask &= c; return; }
    if (held) {
      held = false;
      put(heldX, heldY, heldCode);
      if (mask & c) { held = true; heldX = x; heldY = y; heldCode = c; mask &= c; return; }
    }
    put(x, y, c);
  }

  // The last vertex of a run is always written.
  function finish(x, y) {
    const c = code(x, y);
    outside &= c;
    if (held && !(mask & c)) put(heldX, heldY, heldCode);
    held = false;
    text += " " + x + "," + y;
    lastX = x; lastY = y;
  }

  // Where the edge from vertex `p` to vertex `j` of `v` crosses the horizon, as a point on the unit circle. Their
  // depths are `depth` and `d`, of opposite sign.
  function crossing(v, p, j, depth, d) {
    const right0 = b0 * v[p] + b1 * v[p + 1] + b2 * v[p + 2], up0 = c0 * v[p] + c1 * v[p + 1] + c2 * v[p + 2];
    const t = depth / (depth - d);
    const x = right0 + (b0 * v[j] + b1 * v[j + 1] + b2 * v[j + 2] - right0) * t;
    const y = up0 + (c0 * v[j] + c1 * v[j + 1] + c2 * v[j + 2] - up0) * t, length = Math.sqrt(x * x + y * y) || 1;
    limbRight = x / length; limbUp = y / length;
  }

  // A ring wholly on the visible side is a plain closed outline.
  function visible(v) {
    const last = v.length - 3;
    begin(screenX(b0 * v[0] + b1 * v[1] + b2 * v[2]), screenY(c0 * v[0] + c1 * v[1] + c2 * v[2]));
    for (let j = 3; j < last; j += 3) add(screenX(b0 * v[j] + b1 * v[j + 1] + b2 * v[j + 2]), screenY(c0 * v[j] + c1 * v[j + 1] + c2 * v[j + 2]));
    finish(screenX(b0 * v[last] + b1 * v[last + 1] + b2 * v[last + 2]), screenY(c0 * v[last] + c1 * v[last + 1] + c2 * v[last + 2]));
    return outside ? "" : `M${firstX},${firstY}${text}Z`;
  }

  // A ring that crosses the horizon becomes runs of visible vertices, which `stitch` joins along the horizon.
  function straddle(entry) {
    const v = entry.v, n = v.length / 3;
    let start = entry.start;
    if (a0 * v[3 * start] + a1 * v[3 * start + 1] + a2 * v[3 * start + 2] > 0) {
      start = -1;
      for (let i = 0; i < n; i++) {
        if (a0 * v[3 * i] + a1 * v[3 * i + 1] + a2 * v[3 * i + 2] <= 0) { start = i; break; }
      }
      if (start < 0) return visible(v);
      entry.start = start;
    }
    let depth = a0 * v[3 * start] + a1 * v[3 * start + 1] + a2 * v[3 * start + 2], enter = 0;
    for (let step = 0, i = start; step < n; step++) {
      i = i + 1 === n ? 0 : i + 1;
      const j = 3 * i, d = a0 * v[j] + a1 * v[j + 1] + a2 * v[j + 2];
      if (d > 0) {
        if (depth <= 0) {
          crossing(v, i ? j - 3 : 3 * (n - 1), j, depth, d);
          begin(screenX(limbRight), screenY(limbUp));
          enter = Math.atan2(-limbUp, limbRight);
        }
        add(screenX(b0 * v[j] + b1 * v[j + 1] + b2 * v[j + 2]), screenY(c0 * v[j] + c1 * v[j + 1] + c2 * v[j + 2]));
      } else if (depth > 0) {
        crossing(v, i ? j - 3 : 3 * (n - 1), j, depth, d);
        finish(screenX(limbRight), screenY(limbUp));
        runs.push({x: firstX, y: firstY, text, enter, leave: Math.atan2(-limbUp, limbRight), next: null, gap: 0, done: false});
      }
      depth = d;
    }
    return "";
  }

  function ring(entry) {
    if (entry.valid) {
      const depth = a0 * entry.x + a1 * entry.y + a2 * entry.z;
      if (depth <= -entry.sin) return "";
      if (depth > entry.sin + 1e-7) return visible(entry.v);
    }
    return straddle(entry);
  }

  // The interior of a polygon is on the right of its rings, so the horizon between where a run leaves and where the
  // next one enters belongs to the polygon when walked clockwise on screen, which is the direction of increasing angle.
  // An exit and an entry at the same angle are a slit, such as the edge Antarctica is cut along, which is walked down
  // and back up with the polygon on both sides, so they are not joined: the entry comes first in the clockwise order.
  function stitch() {
    for (const run of runs) {
      let best = run, gap = Infinity;
      for (const other of runs) {
        let delta = other.enter - run.leave;
        if (delta < 1e-9) delta += TAU;
        if (delta < gap) { gap = delta; best = other; }
      }
      run.next = best; run.gap = gap;
    }
    const curve = Math.round(radius);
    let result = "";
    for (const first of runs) {
      if (first.done) continue;
      result += `M${first.x},${first.y}${first.text}`;
      let run = first;
      for (;;) {
        run.done = true;
        const next = run.next, target = `${next.x},${next.y}`;
        // A run that is its own successor closes where it began, so it needs no arc, which would otherwise be a circle.
        result += run.gap < TAU - 1e-9 ? `A${curve},${curve} 0 ${run.gap > Math.PI ? 1 : 0} 1 ${target}` : `L${target}`;
        if (next.done) break;
        result += `L${next.text}`;
        run = next;
      }
      result += "Z";
    }
    return result;
  }

  function polygon(rings) {
    runs.length = 0;
    let result = "";
    for (const entry of rings) result += ring(entry);
    return runs.length ? result + stitch() : result;
  }

  // The path for one country: every polygon of `parts` whose cap can reach the viewport.
  function shape(parts) {
    let result = "";
    for (const part of parts) {
      const reach = part.radius + arc + .001;
      if (reach < Math.PI && a0 * part.x + a1 * part.y + a2 * part.z < Math.cos(reach)) continue;
      result += polygon(part.rings);
    }
    return result;
  }

  // Open polylines such as the graticule: crossing the horizon ends a stroke.
  function lines(list) {
    let result = "";
    for (const v of list) {
      const n = v.length / 3, last = n - 1;
      let open = false, depth = 0;
      for (let i = 0; i < n; i++) {
        const j = 3 * i, d = a0 * v[j] + a1 * v[j + 1] + a2 * v[j + 2];
        if (d > 0) {
          const x = screenX(b0 * v[j] + b1 * v[j + 1] + b2 * v[j + 2]), y = screenY(c0 * v[j] + c1 * v[j + 1] + c2 * v[j + 2]);
          if (!i) { begin(x, y); open = true; }
          else {
            if (!open) { crossing(v, j - 3, j, depth, d); begin(screenX(limbRight), screenY(limbUp)); open = true; }
            if (i === last) {
              finish(x, y); open = false;
              if (!outside) result += `M${firstX},${firstY}${text}`;
            } else add(x, y);
          }
        } else if (open) {
          crossing(v, j - 3, j, depth, d);
          finish(screenX(limbRight), screenY(limbUp)); open = false;
          if (!outside) result += `M${firstX},${firstY}${text}`;
        }
        depth = d;
      }
    }
    return result;
  }

  return {view, shape, lines};
}
