import test from "node:test";
import assert from "node:assert/strict";
import { connectors, connectorById, inspectionConnections, observedReadings, syntheticReadings } from "./board.mjs";
import { emptyDocument, emptyConnection, validateDocument, parseDocument, updateConnection, serializeDocument, loadDocument, saveDocument, withInspectionDefaults, connectionCounts, fanAvailability, interpolateAir, readingFor, storageKey, maxImportBytes } from "./model.mjs";

const now = "2026-11-12T21:30:00.000Z";
const annotation = { target: "CPU cooler via splitter", confidence: "confirmed", occupancy: "occupied", evidence: "Cable physically traced; example test evidence", note: "Both branches checked" };

test("board connectors are unique and a blank annotation document has no assigned connections", () => {
  assert.equal(connectorById.size, connectors.length);
  const counts = connectionCounts(emptyDocument());
  assert.deepEqual(counts, { confirmed: 0, inferred: 0, unknown: connectors.length });
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

test("inspection defaults preserve photo confirmation, user reports, uncertainty and unresolved slots", () => {
  const document = withInspectionDefaults(emptyDocument());
  for (const id of ["M2_1", "M2_2", "SATA_0_3", "SATA_4_7"]) {
    assert.equal(document.connections[id].confidence, "confirmed");
    assert.equal(document.connections[id].provenance, "photo-confirmed");
    assert.equal(document.connections[id].occupancy, "occupied");
  }
  for (const id of ["FAN1", "FAN2", "DDR4_A1", "DDR4_B1", "DDR4_G1", "DDR4_H1", "USB3_3_4", "LAN1", "LAN2", "IPMI_LAN1"]) {
    assert.equal(document.connections[id].provenance, "user-reported");
    assert.equal(document.connections[id].confidence, "inferred");
    assert.equal(document.connections[id].occupancy, "occupied");
  }
  for (const id of ["PCIE1", "PCIE2", "FAN3", "FAN4", "FAN5", "FAN6", "FAN7"]) {
    assert.equal(document.connections[id].confidence, "unknown");
    assert.equal(document.connections[id].occupancy, "unverified");
  }
  assert.equal(document.connections.GFX_12V1.provenance, "photo-uncertain");
  assert.equal(document.connections.GFX_12V1.confidence, "inferred");
  assert.deepEqual(fanAvailability(document), { free: 0, occupied: 0, unverified: 7 });
  assert.deepEqual(parseDocument(serializeDocument(document)), document);
});

test("adding inspection defaults never overwrites existing user annotations, including explicit unknowns", () => {
  let document = updateConnection(emptyDocument(), "FAN1", annotation, now);
  document = updateConnection(document, "M2_1", emptyConnection(), now);
  const combined = withInspectionDefaults(document);
  assert.deepEqual(combined.connections.FAN1, document.connections.FAN1);
  assert.deepEqual(combined.connections.M2_1, document.connections.M2_1);
  assert.equal(combined.connections.M2_2.provenance, "photo-confirmed");
  assert.equal(inspectionConnections.FAN1.provenance, "user-reported");
  assert.equal(inspectionConnections.M2_1.confidence, "confirmed");
  assert.deepEqual(withInspectionDefaults(combined), combined);
  assert.throws(() => withInspectionDefaults({ ...emptyDocument(), connections: null }), /object/);
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
  assert.equal(readingFor(observedReadings, "FAN3"), null);
  assert.equal(readingFor(observedReadings, "FAN1").provenance, "snapshot");
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
