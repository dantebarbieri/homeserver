import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { connectorById, connectors, driveCages, inspectionConnections, psuPorts } from "./board.mjs";
import { caseFanIds, driveBayId, driveIds, driveInfo, flaggedProvenance, psuSocketLinks, relationsFor, rearFanIds } from "./relations.mjs";

const source = readFileSync(new URL("./app.mjs", import.meta.url), "utf8");
const staticParts = [...source.matchAll(/hardwarePart\("([^"]+)"/g)].map(match => match[1]);
const partIds = new Set([...staticParts, ...driveIds, ...caseFanIds, ...rearFanIds]);
const partTargets = links => links.filter(link => link.kind === "part").map(link => link.id);

function neighbors(id) {
  return id === "psu"
    ? psuPorts.flatMap(port => partTargets(psuSocketLinks(port.id)))
    : relationsFor(id).flatMap(group => partTargets(group.links));
}

test("every relation resolves to a real part or connector and has readable text", () => {
  for (const id of partIds) {
    for (const { title, links } of relationsFor(id)) {
      assert.ok(title && links.length, `${id} has an empty group`);
      for (const link of links) {
        assert.notEqual(link.id, id, `${id} links to itself`);
        assert.ok(link.kind === "part" ? partIds.has(link.id) : connectorById.has(link.id), `${id} → ${link.id}`);
      }
    }
  }
  for (const port of psuPorts) {
    for (const link of psuSocketLinks(port.id)) {
      assert.ok(link.kind === "part" ? partIds.has(link.id) : connectorById.has(link.id), `${port.id} → ${link.id}`);
    }
  }
});

test("part-to-part relations are reciprocal except for the disk-bay aggregate", () => {
  for (const id of partIds) {
    if (id === "disk-bays") continue;
    for (const target of neighbors(id)) {
      assert.ok(neighbors(target).includes(id), `${id} → ${target} has no way back`);
    }
  }
  assert.ok(neighbors("disk-bays").length > 0);
});

test("drive siblings, power and controller follow the cage routing", () => {
  for (const cage of driveCages) {
    for (const bay of [1, 2, 3, 4]) {
      const id = driveBayId(cage.number, bay);
      const groups = relationsFor(id);
      const siblings = groups.find(group => group.title === `Other drives in cage ${cage.number}`).links.map(link => link.id);
      assert.deepEqual(siblings, [1, 2, 3, 4].filter(other => other !== bay).map(other => driveBayId(cage.number, other)));
      const power = groups.find(group => group.title === "Powered by").links[0];
      assert.match(power.detail, new RegExp(`^${psuPorts.find(port => port.targetId === `cage-${cage.number}`).id} `));
      assert.equal(groups.some(group => group.title === "Controller"), cage.number === 1);
      assert.equal(driveInfo(id).lead, cage.leads[bay - 1]);
    }
  }
  assert.equal(driveInfo(driveBayId(1, 5)), null);
});

test("fan hub lists exactly the six case fans without claiming hub ports", () => {
  const fans = relationsFor("fan-hub").find(group => group.title === "Fans on this hub").links;
  assert.deepEqual(fans.map(link => link.id), caseFanIds);
  assert.equal(fans.filter(link => link.detail === "Single tach return").length, 1);
  assert.ok(fans.every(link => !/port \d/i.test(link.detail)));
  for (const id of caseFanIds) {
    assert.ok(!neighbors(id).includes("psu"), "case fans are powered through the hub, not directly");
    assert.equal(relationsFor(id).find(group => group.title === "Other fans on this hub").links.length, 5);
  }
});

test("PSU sockets link only to what they feed", () => {
  const byId = Object.fromEntries(psuPorts.map(port => [port.id, psuSocketLinks(port.id).map(link => link.id)]));
  assert.deepEqual(byId.MB18, ["ATXPWR1"]);
  assert.deepEqual(byId.MB10, ["ATXPWR1"]);
  assert.deepEqual(byId.C1, ["gpu"]);
  assert.deepEqual(byId.C2, ["ATX12V1"]);
  assert.deepEqual(byId.S1, ["fan-hub"]);
  assert.deepEqual(byId.S2, [1, 2, 3, 4].map(bay => driveBayId(3, bay)));
  assert.deepEqual(byId.S4, [1, 2, 3, 4].map(bay => driveBayId(1, bay)));
  assert.deepEqual(byId.S5, [1, 2, 3, 4].map(bay => driveBayId(2, bay)));
  assert.deepEqual(byId.S6, rearFanIds);
  for (const port of psuPorts) assert.equal(byId[port.id].length === 0, !port.targetId, `${port.id} empty state`);
  assert.deepEqual(relationsFor("psu"), []);
});

test("site-visible hardware text never attributes facts to the user", () => {
  const attribution = /user[- ]?(reported|confirmed)|user (confirms|reports|accepts)|\(user|tentative/i;
  const linkText = links => links.flatMap(link => [link.detail, link.short]);
  const visible = [
    ...connectors.map(connector => connector.detail),
    ...Object.values(inspectionConnections).map(connection => connection.target),
    ...psuPorts.map(port => port.target),
    ...psuPorts.flatMap(port => linkText(psuSocketLinks(port.id))),
    ...[...partIds].flatMap(id => relationsFor(id).flatMap(group => [group.title, ...linkText(group.links)])),
    ...[...source.matchAll(/connectionNote: [`"]([^`"]+)/g)].map(match => match[1]),
  ].filter(Boolean);
  for (const text of visible) assert.doesNotMatch(text, attribution);
  assert.ok(!flaggedProvenance.has("user-reported") && !flaggedProvenance.has("user-confirmed"));
  assert.doesNotMatch(source, /title:[^\n]*provenance/, "link tooltips must not carry provenance");
});
