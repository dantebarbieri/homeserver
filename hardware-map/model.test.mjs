import test from "node:test";
import assert from "node:assert/strict";
import { connectors, connectorById, landscapeBounds, inspectionConnections, observedReadings, syntheticReadings } from "./board.mjs";
import { emptyDocument, emptyConnection, validateDocument, parseDocument, updateConnection, serializeDocument, loadDocument, saveDocument, withInspectionDefaults, connectionCounts, occupancyCounts, fanAvailability, matchesHardware, fanMotionStages, fanMotionForSpeed, buildLinuxTopology, linuxNodeSummary, interpolateAir, readingFor, storageKey, maxImportBytes } from "./model.mjs";
import { linuxSnapshot } from "./linux-snapshot.mjs";

const now = "2026-11-12T21:30:00.000Z";
const annotation = { target: "CPU cooler via splitter", confidence: "confirmed", occupancy: "occupied", evidence: "Cable physically traced; example test evidence", note: "Both branches checked" };

test("board connectors are unique and a blank annotation document has no assigned connections", () => {
  assert.equal(connectorById.size, connectors.length);
  const counts = connectionCounts(emptyDocument());
  assert.deepEqual(counts, { confirmed: 0, inferred: 0, unknown: connectors.length });
});

test("hardware filters include off-board parts, overlapping categories and model search", () => {
  const fan = { id: "middle-fan-3", componentId: "case-fans", label: "Middle fan 3", model: "Noctua NF-P12 redux-1700 PWM" };
  const hub = { id: "fan-hub", componentId: "fan-hub", label: "Thermalright hub" };
  const drive = { id: "drive-M2_1", componentId: null, label: "M2_1", model: "Samsung 990 EVO" };
  assert.ok(matchesHardware(fan, "Cooling", " REDUX "));
  assert.ok(matchesHardware(fan, "*", "middle-fan-3"));
  assert.ok(matchesHardware(fan, "*", "cooling"));
  assert.equal(matchesHardware(fan, "Storage", "redux"), false);
  assert.equal(matchesHardware(fan, "Cooling", "Samsung"), false);
  assert.ok(matchesHardware(hub, "Cooling"));
  assert.ok(matchesHardware(hub, "Power"));
  assert.ok(matchesHardware({ id: "psu", label: "HX1000i" }, "Power"));
  assert.ok(matchesHardware({ id: "chassis", label: "Rosewill" }, "Chassis"));
  assert.ok(matchesHardware({ id: "disk-bays", componentId: "disks", label: "12 HDDs" }, "Storage"));
  assert.ok(matchesHardware(drive, "Storage", "990 EVO"));
  assert.equal(matchesHardware(drive, "Memory"), false);
  assert.equal(matchesHardware(fan, "Fans"), false, "connector categories are separate from hardware categories");
  assert.ok(matchesHardware({ id: "network-ports", componentId: "rear-io", label: "Network ports" }, "Networking"));
});

test("fan animation distinguishes unavailable speed from stopped and selects proportional speed bands", () => {
  for (const speed of [null, undefined, NaN, Infinity, -1, "0"]) assert.equal(fanMotionForSpeed(speed), null);
  assert.equal(fanMotionForSpeed(0).id, "stopped");
  assert.equal(fanMotionForSpeed(.001).id, "slow");
  assert.equal(fanMotionForSpeed(.2).id, "slow");
  assert.equal(fanMotionForSpeed(.201).id, "medium");
  assert.equal(fanMotionForSpeed(.45).id, "medium");
  assert.equal(fanMotionForSpeed(.451).id, "fast");
  assert.equal(fanMotionForSpeed(.7).id, "fast");
  assert.equal(fanMotionForSpeed(.701).id, "very-fast");
  assert.equal(fanMotionForSpeed(.9).id, "very-fast");
  assert.equal(fanMotionForSpeed(.901).id, "max");
  assert.equal(fanMotionForSpeed(1).id, "max");
  assert.equal(fanMotionForSpeed(1.2).id, "max");
  const moving = fanMotionStages.filter(stage => stage.period > 0);
  for (let i = 1; i < moving.length; i += 1) {
    assert.ok(moving[i].period < moving[i - 1].period, "higher bands must rotate faster");
    assert.ok(moving[i].rings * moving[i].segments > moving[i - 1].rings * moving[i - 1].segments, "higher bands must add speed lines");
  }
  const multiples = moving.filter(stage => stage.impressions);
  for (let i = 1; i < multiples.length; i += 1) {
    assert.ok(multiples[i].impressions > multiples[i - 1].impressions, "higher bands must subdivide the blade impressions");
    assert.equal(multiples[i].impressions % 6, 0, "impressions must be evenly distributed full repetitions");
    assert.ok(multiples[i].discOpacity > multiples[i - 1].discOpacity, "higher bands blend toward a disc");
  }
});

test("replacing a Linux snapshot moves spare and bond roles without changing physical annotations or the old snapshot", () => {
  const original = structuredClone(linuxSnapshot);
  const topology = buildLinuxTopology(linuxSnapshot);
  assert.match(linuxNodeSummary(topology, "sde"), /HOT SPARE/);
  assert.match(linuxNodeSummary(topology, "sde1"), /HOT SPARE/);
  const refreshed = structuredClone(linuxSnapshot);
  const oldSpare = refreshed.raids[0].members.find(member => member.state === "spare");
  const newSpare = refreshed.raids[0].members.find(member => member.id === "sda1");
  oldSpare.state = "in_sync";
  oldSpare.slot = newSpare.slot;
  newSpare.state = "spare";
  newSpare.slot = null;
  refreshed.bonds[0].activeSlave = "enp66s0f0";
  const next = buildLinuxTopology(refreshed);
  assert.match(linuxNodeSummary(next, "sda"), /HOT SPARE/);
  assert.doesNotMatch(linuxNodeSummary(next, "sde"), /HOT SPARE/);
  assert.match(linuxNodeSummary(next, "md0"), /11\/11 in sync · 1 hot spare/);
  assert.match(linuxNodeSummary(next, "enp66s0f0"), /Active link/);
  assert.match(linuxNodeSummary(next, "enp66s0f1"), /Standby link/);
  assert.match(linuxNodeSummary(topology, "sde"), /HOT SPARE/);
  assert.deepEqual(linuxSnapshot, original, "deriving roles must not mutate supplied snapshot observations");
  const standby = next.nodes.get("md0").parents.find(parent => parent.id === "sda1");
  assert.equal(standby.standby, true);
  assert.match(standby.relation, /not active stripes/);
});

test("Linux topology keeps partitions, aliases, cache and ordinary NVMe backing distinct", () => {
  const topology = buildLinuxTopology(linuxSnapshot);
  assert.ok(topology.nodes.get("dm-5").aliases.includes("/dev/dm-5"));
  assert.ok(topology.nodes.get("dm-5").aliases.includes("/dev/vg_redundant/lv_data"));
  assert.ok(topology.nodes.get("dm-2").parents.some(parent => parent.id === "nvme1n1p1"));
  assert.ok(topology.nodes.get("dm-4").parents.some(parent => parent.id === "nvme1n1p1"), "NVMe also backs ordinary data, not only cache");
  assert.ok(topology.nodes.get("dm-4").parents.some(parent => parent.id === "md0"));
  assert.equal(topology.nodes.get("data-filesystem").parents[0].id, "dm-5");
  for (const target of ["M2_1", "M2_2", "LAN1", "LAN2"]) {
    assert.equal(linuxSnapshot.associations.find(entry => entry.targets.includes(target)).nodes.filter(id => id !== "bond0").length, 2, "do not invent a one-to-one physical port/socket binding");
  }
});

test("a spare assigned to a recovery slot is not presented as an idle hot spare", () => {
  const snapshot = structuredClone(linuxSnapshot);
  const raid = snapshot.raids[0];
  raid.syncAction = "recover";
  raid.degraded = 1;
  const failed = raid.members.find(member => member.id === "sda1");
  const replacement = raid.members.find(member => member.state === "spare");
  replacement.slot = failed.slot;
  failed.slot = null;
  failed.state = "faulty";
  raid.members.find(member => member.id === "sdb1").state = "in_sync,writemostly";
  const topology = buildLinuxTopology(snapshot);
  assert.doesNotMatch(linuxNodeSummary(topology, "sde"), /HOT SPARE/);
  assert.match(linuxNodeSummary(topology, "sde"), /not in sync/);
  assert.match(linuxNodeSummary(topology, "sda"), /FAULTY/);
  assert.match(linuxNodeSummary(topology, "md0"), /10\/11 in sync · 0 hot spare.*recover.*degraded 1/);
  assert.equal(topology.nodes.get("md0").parents.find(parent => parent.id === "sde1").standby, false);
});

test("Linux topology rejects duplicate identities, missing references and cyclic dependencies", () => {
  const duplicate = structuredClone(linuxSnapshot);
  duplicate.nodes.push(duplicate.nodes[0]);
  assert.throws(() => buildLinuxTopology(duplicate), /Duplicate/);
  const missing = structuredClone(linuxSnapshot);
  missing.nodes.find(node => node.id === "sda1").parents[0].id = "missing";
  assert.throws(() => buildLinuxTopology(missing), /Unknown Linux node/);
  const cyclic = structuredClone(linuxSnapshot);
  cyclic.nodes.find(node => node.id === "nvme0n1").parents = [{ id: "nvme0n1p1", relation: "invalid" }];
  assert.throws(() => buildLinuxTopology(cyclic), /Cyclic/);
});

test("landscape projection rotates connector order without mutating manual geometry or pin functions", () => {
  const original = structuredClone(connectors);
  const board = landscapeBounds({ x: 65, y: 10, width: 675, height: 910 });
  const cpu = landscapeBounds(connectorById.get("CPU1"));
  const rear = landscapeBounds(connectorById.get("LAN1"));
  const upperSlot = landscapeBounds(connectorById.get("PCIE7"));
  const lowerSlot = landscapeBounds(connectorById.get("PCIE1"));
  assert.ok(rear.x > cpu.x, "rear I/O must be on the chassis right");
  assert.ok(upperSlot.y > lowerSlot.y, "manual slot order must rotate, not be renumbered");
  for (const id of ["FAN1", "FAN2", "FAN3", "FAN4", "FAN5", "FAN6", "FAN7"]) {
    const header = landscapeBounds(connectorById.get(id));
    assert.ok(header.x >= board.x && header.x + header.width <= board.x + board.width);
    assert.ok(header.y >= board.y && header.y + header.height <= board.y + board.height);
  }
  const fan1 = landscapeBounds(connectorById.get("FAN1"));
  const fan3 = landscapeBounds(connectorById.get("FAN3"));
  assert.ok(fan1.y > fan3.y, "fan upper-cluster order must rotate with the board");
  const socket = connectorById.get("M2_1");
  const drive = landscapeBounds({ x: socket.x + 25, y: 513, width: 40, height: 236 });
  assert.ok(drive.height > drive.width);
  assert.ok(upperSlot.width > upperSlot.height, "drive and PCIe axes must remain perpendicular");
  assert.deepEqual(connectors, original);
});

test("a connection edit preserves other connectors and retains evidence on export/import", () => {
  const first = updateConnection(emptyDocument(), "FAN1", annotation, now);
  const second = updateConnection(first, "FAN2", { ...annotation, confidence: "inferred" }, now);
  const restored = parseDocument(serializeDocument(second));
  assert.deepEqual(restored, second);
  assert.equal(restored.connections.FAN1.updatedAt, now);
  assert.deepEqual(connectionCounts(restored), { confirmed: 1, inferred: 1, unknown: connectors.length - 2 });
  assert.equal(first.connections.FAN2, undefined);
});

test("occupancy counts distinguish empty, connected, blocked and unverified independently of confidence", () => {
  assert.deepEqual(occupancyCounts(emptyDocument()), { occupied: 0, free: 0, blocked: 0, unverified: connectors.length });
  let document = updateConnection(emptyDocument(), "FAN1", annotation, now);
  document = updateConnection(document, "FAN2", { ...annotation, target: "", confidence: "inferred", occupancy: "free" }, now);
  document = updateConnection(document, "PCIE3", { ...annotation, confidence: "inferred", occupancy: "blocked" }, now);
  assert.deepEqual(occupancyCounts(document), { occupied: 1, free: 1, blocked: 1, unverified: connectors.length - 3 });
  document = updateConnection(document, "FAN2", { ...document.connections.FAN2, confidence: "confirmed" }, now);
  assert.deepEqual(occupancyCounts(document), { occupied: 1, free: 1, blocked: 1, unverified: connectors.length - 3 });
});

test("inspection defaults distinguish confirmed occupied and confirmed free fan headers", () => {
  const document = withInspectionDefaults(emptyDocument());
  for (const id of ["CPU1", "M2_1", "M2_2", "SATA_0_3", "SATA_4_7", "FAN1", "FAN2", "ATXPWR1", "ATX12V1", "PANEL1"]) {
    assert.equal(document.connections[id].confidence, "confirmed");
    assert.equal(document.connections[id].provenance, "photo-confirmed");
    assert.equal(document.connections[id].occupancy, "occupied");
  }
  for (const id of ["DDR4_A1", "DDR4_B1", "DDR4_G1", "DDR4_H1", "USB3_3_4", "LAN1", "LAN2", "IPMI_LAN1"]) {
    assert.equal(document.connections[id].provenance, "user-confirmed");
    assert.equal(document.connections[id].confidence, "confirmed");
    assert.equal(document.connections[id].occupancy, "occupied");
  }
  assert.equal(document.connections.FAN3.confidence, "confirmed");
  assert.equal(document.connections.FAN3.occupancy, "occupied");
  assert.equal(document.connections.FAN3.provenance, "user-confirmed");
  for (const id of ["FAN4", "FAN5", "FAN6", "FAN7", "DDR4_C1", "DDR4_D1", "DDR4_E1", "DDR4_F1", "GFX_12V1", "TR1", "TR2", "REAR_OTHER"]) {
    assert.equal(document.connections[id].confidence, "confirmed");
    assert.equal(document.connections[id].occupancy, "free");
    assert.equal(document.connections[id].provenance, "user-confirmed");
  }
  assert.equal(document.connections.ATX12V2.provenance, "photo-confirmed");
  assert.equal(document.connections.ATX12V2.occupancy, "free");
  assert.deepEqual(fanAvailability(document), { free: 4, occupied: 3, unverified: 0 });
  assert.deepEqual(parseDocument(serializeDocument(document)), document);
});

test("adding inspection defaults never overwrites existing user annotations, including explicit unknowns", () => {
  let document = updateConnection(emptyDocument(), "FAN1", annotation, now);
  document = updateConnection(document, "M2_1", emptyConnection(), now);
  document = updateConnection(document, "FAN3", {
    ...emptyConnection(), confidence: "confirmed", occupancy: "free", provenance: "photo-confirmed",
    evidence: "Earlier empty-header photo; preserved local annotation predates the replacement.",
  }, now);
  document = updateConnection(document, "PCIE3", {
    ...annotation, target: "Earlier GPU-in-PCIE3 annotation",
  }, now);
  const combined = withInspectionDefaults(document);
  assert.deepEqual(combined.connections.FAN1, document.connections.FAN1);
  assert.deepEqual(combined.connections.M2_1, document.connections.M2_1);
  assert.deepEqual(combined.connections.FAN3, document.connections.FAN3);
  assert.deepEqual(combined.connections.PCIE3, document.connections.PCIE3);
  assert.equal(inspectionConnections.PCIE3.occupancy, "blocked");
  assert.equal(inspectionConnections.FAN3.occupancy, "occupied");
  assert.equal(combined.connections.M2_2.provenance, "photo-confirmed");
  assert.equal(inspectionConnections.FAN1.provenance, "photo-confirmed");
  assert.equal(inspectionConnections.M2_1.confidence, "confirmed");
  assert.deepEqual(withInspectionDefaults(combined), combined);
  assert.throws(() => withInspectionDefaults({ ...emptyDocument(), connections: null }), /object/);
});

test("physical slot blockage stays distinct from a GPU electrical connection and survives export", () => {
  const document = withInspectionDefaults(emptyDocument());
  for (const id of ["PCIE1"]) {
    assert.equal(document.connections[id].occupancy, "occupied");
    assert.equal(document.connections[id].confidence, "confirmed");
    assert.equal(document.connections[id].provenance, "user-confirmed");
  }
  assert.equal(document.connections.PCIE2.occupancy, "blocked");
  assert.equal(document.connections.PCIE2.confidence, "confirmed");
  assert.equal(document.connections.PCIE3.occupancy, "blocked");
  assert.equal(document.connections.PCIE3.confidence, "confirmed");
  assert.equal(document.connections.PCIE4.occupancy, "occupied");
  assert.equal(document.connections.PCIE4.confidence, "confirmed");
  assert.equal(document.connections.PCIE4.provenance, "user-confirmed");
  for (const id of ["PCIE5", "PCIE6", "PCIE7"]) {
    assert.equal(document.connections[id].occupancy, "free");
    assert.equal(document.connections[id].provenance, "user-confirmed");
    assert.equal(document.connections[id].confidence, "confirmed");
  }
  assert.deepEqual(parseDocument(serializeDocument(document)), document);
  const blocked = updateConnection(emptyDocument(), "FAN5", { ...annotation, occupancy: "blocked" }, now);
  assert.deepEqual(fanAvailability(blocked), { free: 0, occupied: 0, unverified: 7 });
  assert.throws(() => updateConnection(emptyDocument(), "PCIE2", { ...emptyConnection(), occupancy: "blocked" }, now), /evidence/);
});

test("confirmed and inferred claims cannot be saved without both target and evidence", () => {
  for (const confidence of ["confirmed", "inferred"]) {
    assert.throws(() => updateConnection(emptyDocument(), "FAN1", { ...annotation, confidence, evidence: " " }, now), /evidence/);
    assert.throws(() => updateConnection(emptyDocument(), "FAN1", { ...annotation, confidence, target: "" }, now), /target/);
  }
  assert.doesNotThrow(() => updateConnection(emptyDocument(), "FAN1", emptyConnection(), now));
});

test("fan shopping counts only confirmed free/occupied headers, never tach readings or inferred claims", () => {
  assert.deepEqual(fanAvailability(emptyDocument()), { free: 0, occupied: 0, unverified: 7 });
  let document = updateConnection(emptyDocument(), "FAN1", annotation, now);
  document = updateConnection(document, "FAN2", { ...annotation, occupancy: "free", target: "" }, now);
  document = updateConnection(document, "FAN3", { ...annotation, confidence: "inferred", occupancy: "free", target: "" }, now);
  assert.deepEqual(fanAvailability(document), { free: 1, occupied: 1, unverified: 5 });
  assert.throws(() => updateConnection(document, "FAN4", { ...emptyConnection(), occupancy: "free" }, now), /evidence/);
  assert.throws(() => updateConnection(document, "FAN4", { ...annotation, occupancy: "free" }, now), /target/);
  assert.throws(() => updateConnection(document, "FAN4", { ...annotation, occupancy: "maybe" }, now), /occupancy/);
});

test("imports reject incompatible versions, boards, connector identities and malformed fields", () => {
  assert.throws(() => validateDocument({ ...emptyDocument(), schemaVersion: 2 }), /version 1/);
  assert.throws(() => validateDocument({ ...emptyDocument(), boardId: "other-board" }), /ROMED8/);
  assert.throws(() => validateDocument({ ...emptyDocument(), connections: [] }), /object/);
  for (const id of ["NOT_A_HEADER", "__proto__", "constructor"]) {
    assert.throws(() => parseDocument(`{"schemaVersion":1,"boardId":"asrock-rack-romed8-2t","connections":{"${id}":{}}}`), /Unknown connector/);
  }
  for (const bad of [null, [], { ...annotation, note: {} }, { ...annotation, target: "x".repeat(201) }, { ...annotation, confidence: "probably" }]) {
    assert.throws(() => validateDocument({ ...emptyDocument(), connections: { FAN1: bad } }));
  }
  for (const provenance of ["automatic-photo-proof", ["user-reported"], {}, null, 0]) {
    assert.throws(() => updateConnection(emptyDocument(), "FAN1", { ...annotation, provenance }, now), /evidence source/);
  }
});

test("imports bound byte size and reject invalid JSON and impossible timestamps", () => {
  assert.throws(() => parseDocument("{"), /valid JSON/);
  assert.throws(() => parseDocument("x".repeat(maxImportBytes + 1)), /256 KiB/);
  assert.throws(() => parseDocument("é".repeat(maxImportBytes)), /256 KiB/);
  for (const timestamp of ["yesterday", "2026-02-31T21:30:00.000Z", "2026-11-12", 0]) {
    assert.throws(() => updateConnection(emptyDocument(), "FAN1", annotation, timestamp), /timestamp/);
  }
});

test("plain text notes round-trip without being interpreted as markup", () => {
  const note = '<img src=x onerror="alert(1)"> & cable note';
  const document = updateConnection(emptyDocument(), "FAN1", { ...annotation, note }, now);
  assert.equal(parseDocument(serializeDocument(document)).connections.FAN1.note, note);
});

test("browser persistence restores notes and surfaces storage/corruption failures", () => {
  const store = new Map();
  const storage = { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) };
  assert.deepEqual(loadDocument(storage), emptyDocument());
  const document = updateConnection(emptyDocument(), "FAN1", annotation, now);
  saveDocument(storage, document);
  assert.deepEqual(loadDocument(storage), document);
  store.set(storageKey, "invalid saved data");
  assert.throws(() => loadDocument(storage), /valid JSON/);
  assert.equal(store.get(storageKey), "invalid saved data");
  assert.throws(() => saveDocument({ setItem() { throw new Error("Quota exceeded"); } }, document), /Quota/);
});

test("observed component readings never produce an air estimate or imply a missing RPM of zero", () => {
  assert.equal(interpolateAir(observedReadings, 0.5, "snapshot"), null);
  assert.equal(readingFor(observedReadings, "FAN4"), null);
  assert.equal(readingFor(observedReadings, "FAN3").provenance, "snapshot");
  assert.equal(readingFor(observedReadings, "FAN1").provenance, "snapshot");
  assert.equal(readingFor(observedReadings, "rear-fans"), null);
  assert.equal(readingFor(observedReadings, "case-fans"), null);
  for (const bank of ["front", "middle"]) {
    for (let number = 1; number <= 3; number += 1) {
      assert.equal(readingFor(observedReadings, `${bank}-fan-${number}`), null);
    }
  }
});

test("synthetic air LERP has exact endpoints, midpoint and piecewise behavior", () => {
  assert.equal(interpolateAir(syntheticReadings, 0, "synthetic"), 24);
  assert.equal(interpolateAir(syntheticReadings, 0.5, "synthetic"), 31.5);
  assert.equal(interpolateAir(syntheticReadings, 1, "synthetic"), 39);
  const mid = { kind: "air", unit: "°C", position: 0.5, value: 25, provenance: "synthetic" };
  assert.equal(interpolateAir([...syntheticReadings, mid], 0.25, "synthetic"), 24.5);
  assert.equal(interpolateAir([...syntheticReadings, mid], 0.75, "synthetic"), 32);
  assert.equal(interpolateAir(syntheticReadings, 0.5, "snapshot"), null);
});

test("air interpolation rejects extrapolation, duplicate locations, stale and invalid probes", () => {
  const probe = { kind: "air", unit: "°C", position: 0.25, value: 20, provenance: "synthetic" };
  const pair = [probe, { ...probe, position: 0.75, value: 30 }];
  assert.equal(interpolateAir(pair, 0.1, "synthetic"), null);
  assert.equal(interpolateAir(pair, 0.9, "synthetic"), null);
  assert.equal(interpolateAir(pair, 0.5, "synthetic"), 25);
  for (const invalid of [-1, 2, NaN, Infinity, "0.5"]) {
    assert.equal(interpolateAir(pair, invalid, "synthetic"), null);
  }
  assert.equal(interpolateAir([probe, { ...probe, value: 30 }], 0.25, "synthetic"), null);
  for (const change of [{ stale: true }, { value: NaN }, { position: 2 }, { provenance: "snapshot" }, { kind: "component" }, { unit: "RPM" }]) {
    assert.equal(interpolateAir([probe, { ...pair[1], ...change }], 0.5, "synthetic"), null);
  }
});
