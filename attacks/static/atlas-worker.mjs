// Decodes and prepares one border detail level off the main thread: the 1:10m atlas takes seconds on a phone,
// and any long task there freezes a drag or pinch in progress. Replies hold only plain data and typed arrays.
import {feature as decodeTopology, geoArea, geoCentroid} from "./geo-vendor.mjs";
import {globeGeometry, prepareLand} from "./globe.mjs";
import {project} from "./model.mjs";

const FLAT = ["equal-earth", "rectangular"];

function flatPath(geometry, name) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  let path = "";
  for (const polygon of polygons) for (const ring of polygon) {
    for (let index = 0; index < ring.length; index++) {
      const [x, y] = project(ring[index][0], ring[index][1], 1000, 500, name);
      path += `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
    }
    path += "Z";
  }
  return path;
}

export async function prepareAtlas(url, level, fetcher = fetch) {
  const response = await fetcher(url, {cache: "force-cache", redirect: "error", signal: AbortSignal.timeout(30000)});
  if (!response.ok) throw new Error(`Border data unavailable (${response.status})`);
  const topology = await response.json();
  if (topology.type !== "Topology" || !topology.objects?.countries) throw new Error("Invalid border data");
  const prepared = decodeTopology(topology, topology.objects.countries).features.map(item => {
    const geometry = globeGeometry(item.geometry);
    return {item, geometry, area: geoArea(geometry) * 6371 ** 2, shape: prepareLand(geometry, level)};
  });
  // Tiny enclaves draw last so a larger neighbour cannot cover their borders.
  prepared.sort((a, b) => b.area - a.area);
  const labels = prepared.filter(value => value.area <= 3000).toReversed().map(({item, geometry, area}) => {
    const [longitude, latitude] = geoCentroid(geometry);
    return {id: item.id, name: item.properties.name, longitude, latitude, area};
  });
  const flat = Object.fromEntries(FLAT.map(name => [name, prepared.map(({item}) => flatPath(item.geometry, name))]));
  return {
    world: {features: prepared.map(({item}) => ({id: item.id, properties: {name: item.properties.name}}))},
    shapes: prepared.map(value => value.shape), labels, flat,
  };
}

export function transferables(data) {
  const buffers = new Set();
  for (const shape of data.shapes) for (const part of shape) for (const ring of part.rings) buffers.add(ring.v.buffer);
  return [...buffers];
}

if (typeof WorkerGlobalScope !== "undefined" && self instanceof WorkerGlobalScope) {
  self.onmessage = async ({data: {url, level}}) => {
    try {
      const data = await prepareAtlas(url, level);
      self.postMessage({level, data}, transferables(data));
    } catch (error) {
      self.postMessage({level, error: error.message});
    }
  };
}
