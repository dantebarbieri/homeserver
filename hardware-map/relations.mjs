import { components, driveCages, psuPorts } from "./board.mjs";

export const driveBayId = (cage, bay) => `drive-cage-${cage}-bay-${bay}`;
export const caseFanId = (region, number) => `${region}-fan-${number}`;
export const rearFanId = number => `rear-fan-${number}`;

const baysPerCage = [1, 2, 3, 4];
export const driveIds = driveCages.flatMap(cage => baysPerCage.map(bay => driveBayId(cage.number, bay)));
export const caseFanIds = ["front", "middle"].flatMap(region => [1, 2, 3].map(number => caseFanId(region, number)));
export const rearFanIds = [1, 2].map(rearFanId);
// Only genuinely uncertain sources are marked on the site; user-supplied facts are shown plainly.
export const flaggedProvenance = new Set(["photo-inferred", "photo-uncertain", "unverified"]);

const tachFanId = components.find(component => component.id === "case-fans").tachPartId;
const driveRoutes = new Map(driveCages.flatMap(cage => baysPerCage.map(bay => [
  driveBayId(cage.number, bay), { cage: cage.number, bay, lead: cage.leads[bay - 1], route: cage.route, connectorId: cage.connectorId },
])));

export function driveInfo(partId) {
  return driveRoutes.get(partId) ?? null;
}

const part = (id, extra = {}) => ({ kind: "part", id, ...extra });
const connector = (id, extra = {}) => ({ kind: "connector", id, ...extra });
const cageDrives = (cage, provenance, exclude = null) => baysPerCage
  .map(bay => driveBayId(cage, bay))
  .filter(id => id !== exclude)
  .map(id => part(id, { detail: `lead ${driveInfo(id).lead}`, short: `Bay ${driveInfo(id).bay}`, provenance }));

function psuLink(targetId) {
  const port = psuPorts.find(entry => entry.targetId === targetId);
  return port && part("psu", { detail: `${port.id} · ${port.target}`, provenance: port.provenance });
}

function group(title, links) {
  const present = links.filter(Boolean);
  return present.length ? { title, links: present } : null;
}

function driveRelations(id) {
  const { cage, bay } = driveInfo(id);
  return [
    group("Powered by", [psuLink(`cage-${cage}`)]),
    cage === 1 ? group("Controller", [part("hba", { detail: "SAS 9300-8i · breakout lead " + driveInfo(id).lead, provenance: "user-confirmed" })]) : null,
    group(`Other drives in cage ${cage}`, cageDrives(cage, "user-confirmed", driveBayId(cage, bay))),
  ];
}

function caseFanRelations(id) {
  return [
    group("Fan hub", [part("fan-hub", { detail: "FAN3 · PWM + one tach return", provenance: "user-confirmed" })]),
    group("Other fans on this hub", caseFanIds.filter(peer => peer !== id).map(peer => part(peer, {
      detail: peer === tachFanId ? "Single tach return" : "Hub port not traced", provenance: "user-confirmed",
    }))),
  ];
}

const builders = {
  hba: () => [group("Drives on this HBA", cageDrives(1, "user-confirmed"))],
  gpu: () => [group("Powered by", [psuLink("gpu")])],
  "fan-hub": () => [
    group("Powered by", [psuLink("fan-hub")]),
    group("Fans on this hub", caseFanIds.map(id => part(id, {
      detail: id === tachFanId ? "Single tach return" : "Hub port not traced", provenance: "user-confirmed",
    }))),
  ],
  "disk-bays": () => driveCages.map(cage => group(`Cage ${cage.number} · ${cage.route}`, [
    ...cageDrives(cage.number, "user-confirmed"),
    psuLink(`cage-${cage.number}`),
    cage.number === 1 ? part("hba", { detail: "SAS 9300-8i", provenance: "user-confirmed" }) : null,
  ])),
};

/** Part-to-part relations for the selected scene part; connectors are linked separately from the scene's connector ids. */
export function relationsFor(partId) {
  let groups = [];
  if (driveRoutes.has(partId)) groups = driveRelations(partId);
  else if (caseFanIds.includes(partId)) groups = caseFanRelations(partId);
  else if (rearFanIds.includes(partId)) {
    groups = [
      group("Powered by", [psuLink("rear-fans")]),
      group("Other fan on this harness", rearFanIds.filter(peer => peer !== partId).map(peer => part(peer, { detail: "Shared Molex harness", provenance: "user-confirmed" }))),
    ];
  } else if (builders[partId]) groups = builders[partId]();
  return groups.filter(Boolean);
}

/** What a populated PSU socket feeds. Empty sockets return nothing. */
export function psuSocketLinks(portId) {
  const port = psuPorts.find(entry => entry.id === portId);
  if (!port?.targetId) return [];
  const provenance = port.provenance;
  const cage = /^cage-(\d)$/.exec(port.targetId);
  if (cage) return cageDrives(Number(cage[1]), provenance).map(link => ({ ...link, detail: undefined }));
  if (port.targetId === "rear-fans") return rearFanIds.map((id, index) => part(id, { short: `Rear fan ${index + 1}`, provenance }));
  if (port.targetId === "fan-hub" || port.targetId === "gpu") return [part(port.targetId, { provenance })];
  return [connector(port.targetId, { provenance })];
}
