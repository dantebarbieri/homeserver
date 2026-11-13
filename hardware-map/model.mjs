import { boardId, connectorById, hardwareCategories, inspectionConnections, provenanceLabels } from "./board.mjs";

export const storageKey = "homeserver.hardware-map.v1";
export const confidenceValues = ["unknown", "inferred", "confirmed"];
export const occupancyValues = ["unverified", "occupied", "free", "blocked"];
export const maxImportBytes = 256 * 1024;
const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);

export const fanMotionStages = [
  { id: "stopped", label: "Stopped", example: 0, ceiling: 0, period: 0, bladeOpacity: 1, rings: 0, segments: 0, sweep: 0 },
  { id: "slow", label: "Slow", example: .12, ceiling: .2, period: 10, bladeOpacity: 1, rings: 0, segments: 0, sweep: 0 },
  { id: "medium", label: "Medium", example: .35, ceiling: .45, period: 2.2, bladeOpacity: .85, impressions: 12, discOpacity: .05, rings: 1, segments: 12, sweep: 12 },
  { id: "fast", label: "Fast", example: .6, ceiling: .7, period: 1.25, bladeOpacity: .65, impressions: 18, discOpacity: .12, rings: 1, segments: 18, sweep: 8 },
  { id: "very-fast", label: "Very fast", example: .82, ceiling: .9, period: .9, bladeOpacity: .45, impressions: 24, discOpacity: .2, rings: 1, segments: 24, sweep: 6 },
  { id: "max", label: "Maximum", example: 1, ceiling: 1, period: .75, bladeOpacity: .28, impressions: 36, discOpacity: .3, rings: 1, segments: 36, sweep: 4 },
];

// Fraction of rated maximum RPM, not PWM duty. Null means unavailable, never stopped.
export function fanMotionForSpeed(fraction) {
  if (!Number.isFinite(fraction) || fraction < 0) return null;
  return fanMotionStages.find(stage => fraction <= stage.ceiling) ?? fanMotionStages.at(-1);
}

function raidMemberStatus(member) {
  const flags = member.state.split(",").map(flag => flag.trim());
  const faulty = flags.includes("faulty");
  const inSync = !faulty && flags.includes("in_sync");
  const standby = !faulty && flags.includes("spare") && member.slot === null;
  const label = faulty ? `FAULTY · ${member.state}`
    : standby ? "HOT SPARE (standby)"
      : inSync ? `Array member · ${member.state} · array slot ${member.slot ?? "unassigned"}`
        : `${member.slot === null ? "Unassigned RAID device" : "Assigned RAID member"} · ${member.state} · array slot ${member.slot ?? "unassigned"} · not in sync`;
  return { inSync, standby, label };
}

export function buildLinuxTopology(snapshot) {
  if (snapshot.schemaVersion !== 1 || !Number.isFinite(Date.parse(snapshot.capturedAt))) throw new Error("Invalid Linux snapshot version or capture time.");
  const nodes = new Map();
  for (const node of snapshot.nodes) {
    if (!node.id || nodes.has(node.id)) throw new Error(`Duplicate or missing Linux node: ${node.id}`);
    nodes.set(node.id, { ...node, parents: [...(node.parents ?? [])], memberships: [] });
  }
  const requireNode = id => {
    if (!nodes.has(id)) throw new Error(`Unknown Linux node: ${id}`);
    return nodes.get(id);
  };
  for (const raid of snapshot.raids) {
    const array = requireNode(raid.id);
    array.raid = raid;
    for (const member of raid.members) {
      const status = raidMemberStatus(member);
      const partition = requireNode(member.id);
      const membership = { ...member, array: raid.id };
      partition.memberships.push(membership);
      for (const parent of partition.parents) {
        const disk = requireNode(parent.id);
        if (disk.kind === "Physical HDD" || disk.kind === "Physical NVMe") disk.memberships.push(membership);
      }
      array.parents.push({
        id: member.id,
        relation: status.standby ? "Hot spare · standby, not active stripes" : status.label,
        standby: status.standby,
      });
    }
  }
  for (const bond of snapshot.bonds) {
    const node = requireNode(bond.id);
    node.summary = `${bond.mode} · active link ${bond.activeSlave}`;
    for (const id of bond.members) {
      const nic = requireNode(id);
      nic.bondRole = `${id === bond.activeSlave ? "Active" : "Standby"} link in ${bond.id}`;
      node.parents.push({ id, relation: nic.bondRole });
    }
  }
  for (const node of nodes.values()) {
    for (const parent of node.parents) requireNode(parent.id);
  }
  const visited = new Set(), visiting = new Set();
  function visit(id) {
    if (visiting.has(id)) throw new Error(`Cyclic Linux topology at ${id}`);
    if (visited.has(id)) return;
    visiting.add(id);
    for (const parent of nodes.get(id).parents) visit(parent.id);
    visiting.delete(id);
    visited.add(id);
  }
  for (const id of nodes.keys()) visit(id);
  for (const association of snapshot.associations) for (const id of association.nodes) requireNode(id);
  return { snapshot, nodes };
}

export function linuxNodeSummary(topology, id) {
  const node = topology.nodes.get(id);
  if (!node) throw new Error(`Unknown Linux node: ${id}`);
  if (node.raid) {
    const active = node.raid.members.filter(member => raidMemberStatus(member).inSync).length;
    const spares = node.raid.members.filter(member => raidMemberStatus(member).standby).length;
    return `${node.raid.level} · ${active}/${node.raid.raidDisks} in sync · ${spares} hot spare · ${node.raid.state} · ${node.raid.syncAction} · degraded ${node.raid.degraded}`;
  }
  if (node.memberships.length) return node.memberships.map(member =>
    `${raidMemberStatus(member).label} · /dev/${member.array}`,
  ).join("; ");
  return [node.bondRole, node.summary ?? node.kind].filter(Boolean).join(" · ");
}

export function matchesHardware(part, category, query = "") {
  const categories = Object.entries(hardwareCategories)
    .filter(([, ids]) => ids.includes(part.componentId ?? part.id))
    .map(([name]) => name);
  return (category === "*" || categories.includes(category)) &&
    `${part.id} ${part.label} ${part.model ?? ""} ${categories.join(" ")}`
      .toLowerCase().includes(query.trim().toLowerCase());
}

export function emptyDocument() {
  return { schemaVersion: 1, boardId, connections: {} };
}

export function emptyConnection() {
  return { target: "", confidence: "unknown", occupancy: "unverified", provenance: "unverified", evidence: "", note: "", updatedAt: null };
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
      provenance: entry.provenance === undefined ? "user-annotation" : entry.provenance,
      evidence: text(entry.evidence, `${id} evidence`, 600),
      note: text(entry.note, `${id} note`, 2000),
      updatedAt: entry.updatedAt,
    };
    if (!occupancyValues.includes(connection.occupancy)) throw new Error(`${id} has an invalid occupancy state.`);
    if (typeof connection.provenance !== "string" || !Object.hasOwn(provenanceLabels, connection.provenance)) {
      throw new Error(`${id} has an invalid evidence source.`);
    }
    if (connection.occupancy !== "unverified" && connection.confidence === "unknown") {
      throw new Error(`${id}: occupied/free/blocked claims need inferred or confirmed confidence and evidence.`);
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

export function withInspectionDefaults(document) {
  const validated = validateDocument(document);
  return validateDocument({
    ...validated,
    connections: { ...inspectionConnections, ...validated.connections },
  });
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

export function occupancyCounts(document) {
  const counts = { occupied: 0, free: 0, blocked: 0, unverified: 0 };
  for (const id of connectorById.keys()) {
    counts[document.connections[id]?.occupancy ?? "unverified"] += 1;
  }
  return counts;
}

export function fanAvailability(document) {
  const counts = { free: 0, occupied: 0, unverified: 0 };
  for (const [id, connector] of connectorById) {
    if (connector.category !== "Fans") continue;
    const connection = document.connections[id] ?? emptyConnection();
    const occupancy = connection.confidence === "confirmed" && ["free", "occupied"].includes(connection.occupancy)
      ? connection.occupancy : "unverified";
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
