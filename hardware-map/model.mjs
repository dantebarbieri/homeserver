import { boardId, connectorById } from "./board.mjs";

export const storageKey = "homeserver.hardware-map.v1";
export const confidenceValues = ["unknown", "inferred", "confirmed"];
export const occupancyValues = ["unverified", "occupied", "free"];
export const maxImportBytes = 256 * 1024;
const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);

export function emptyDocument() {
  return { schemaVersion: 1, boardId, connections: {} };
}

export function emptyConnection() {
  return { target: "", confidence: "unknown", occupancy: "unverified", evidence: "", note: "", updatedAt: null };
}

function text(value, field, limit) {
  if (typeof value !== "string" || value.length > limit) {
    throw new Error(`${field} must be text of at most ${limit} characters.`);
  }
  return value.trim();
}

export function validateDocument(input) {
  if (!isRecord(input) || input.schemaVersion !== 1 || input.boardId !== boardId) {
    throw new Error("Expected a version 1 ROMED8-2T hardware-map export.");
  }
  if (!isRecord(input.connections)) throw new Error("The connections field must be an object.");
  const result = emptyDocument();
  for (const [id, entry] of Object.entries(input.connections)) {
    if (!connectorById.has(id)) throw new Error(`Unknown connector: ${id}`);
    if (!isRecord(entry) || !confidenceValues.includes(entry.confidence)) {
      throw new Error(`Invalid confidence for ${id}.`);
    }
    const connection = {
      target: text(entry.target, `${id} connection`, 200),
      confidence: entry.confidence,
      occupancy: entry.occupancy ?? (entry.confidence !== "unknown" && entry.target ? "occupied" : "unverified"),
      evidence: text(entry.evidence, `${id} evidence`, 600),
      note: text(entry.note, `${id} note`, 2000),
      updatedAt: entry.updatedAt,
    };
    if (!occupancyValues.includes(connection.occupancy)) throw new Error(`${id} has an invalid occupancy state.`);
    if (connection.occupancy !== "unverified" && connection.confidence === "unknown") {
      throw new Error(`${id}: occupied/free claims need inferred or confirmed confidence and evidence.`);
    }
    if (connection.occupancy === "free" && connection.target) {
      throw new Error(`${id}: a free connector cannot also have a connected target.`);
    }
    if (connection.confidence !== "unknown" &&
        (!connection.evidence || (connection.occupancy !== "free" && !connection.target))) {
      throw new Error(`${id}: confirmed or inferred connections need a target and evidence.`);
    }
    if (connection.updatedAt !== null &&
        (typeof connection.updatedAt !== "string" ||
         !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(connection.updatedAt) ||
         !Number.isFinite(Date.parse(connection.updatedAt)) ||
         new Date(connection.updatedAt).toISOString() !== connection.updatedAt)) {
      throw new Error(`${id} has an invalid timestamp.`);
    }
    result.connections[id] = connection;
  }
  return result;
}

export function parseDocument(raw) {
  if (typeof raw !== "string" || new TextEncoder().encode(raw).length > maxImportBytes) {
    throw new Error("Import must be a JSON file smaller than 256 KiB.");
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("The selected file is not valid JSON.");
  }
  return validateDocument(parsed);
}

export function updateConnection(document, id, fields, now = new Date().toISOString()) {
  if (!connectorById.has(id)) throw new Error(`Unknown connector: ${id}`);
  return validateDocument({
    ...document,
    connections: { ...document.connections, [id]: { ...fields, updatedAt: now } },
  });
}

export function serializeDocument(document) {
  return JSON.stringify(validateDocument(document), null, 2) + "\n";
}

export function saveDocument(storage, document) {
  storage.setItem(storageKey, serializeDocument(document));
}

export function loadDocument(storage) {
  const raw = storage.getItem(storageKey);
  return raw === null ? emptyDocument() : parseDocument(raw);
}

export function connectionCounts(document) {
  const counts = { confirmed: 0, inferred: 0, unknown: connectorById.size };
  for (const entry of Object.values(document.connections)) {
    if (entry.confidence !== "unknown") {
      counts[entry.confidence] += 1;
      counts.unknown -= 1;
    }
  }
  return counts;
}

export function readingFor(readings, id) {
  return readings.find(reading => reading.id === id) ?? null;
}

export function fanAvailability(document) {
  const counts = { free: 0, occupied: 0, unverified: 0 };
  for (const [id, connector] of connectorById) {
    if (connector.category !== "Fans") continue;
    const connection = document.connections[id] ?? emptyConnection();
    const occupancy = connection.confidence === "confirmed" ? connection.occupancy : "unverified";
    counts[occupancy] += 1;
  }
  return counts;
}

// One-dimensional, piecewise LERP between air probes only; never extrapolate.
export function interpolateAir(readings, position, provenance) {
  if (!Number.isFinite(position) || position < 0 || position > 1) return null;
  const probes = readings.filter(reading =>
    reading.kind === "air" && reading.unit === "°C" &&
    reading.provenance === provenance && reading.stale !== true &&
    Number.isFinite(reading.value) && Number.isFinite(reading.position) &&
    reading.position >= 0 && reading.position <= 1,
  ).sort((a, b) => a.position - b.position);
  if (probes.length < 2 || probes.some((probe, i) => i > 0 && probe.position === probes[i - 1].position)) {
    return null;
  }
  for (let i = 1; i < probes.length; i += 1) {
    const left = probes[i - 1];
    const right = probes[i];
    if (position >= left.position && position <= right.position) {
      const ratio = (position - left.position) / (right.position - left.position);
      return left.value + (right.value - left.value) * ratio;
    }
  }
  return null;
}
