'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { parseArgs, configure, WORKER_TYPES } = require('./configure-offload-nodes.cjs');
const { FLOW_ID, SAFE_FLOW, SAFE_CACHE, TV_LIBRARIES } = require('./install-offload-flow.cjs');
const { CACHE_ROOT } = require('./hevc-offload-v1.cjs');
const { ROOT } = require('./install-flow.cjs');

const MAC = 'Studio-Native';
const slots = checked => Array.from({ length: 168 }, (_, i) => ({ _id: `slot-${i}`, checked }));
const tv = (id, overrides = {}) => ({
  _id: id, name: `TV ${id}`, flowId: SAFE_FLOW, cache: SAFE_CACHE, processTranscodes: true,
  schedule: slots(true), ...overrides,
});
const adopted = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }));
const held = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT, schedule: slots(false) }));
const node = (nodeName, limits, overrides = {}) => ({
  nodeName, nodePaused: false, allowGpuDoCpu: false, gpuSelect: '-', nodeTags: 'mapped', librariesToNotProcess: {},
  workers: {}, workerLimits: { healthcheckcpu: 0, healthcheckgpu: 0, transcodecpu: 0, transcodegpu: 0, ...limits },
  ...overrides,
});
const linux = (overrides, limits) => node('HomeServer', { healthcheckcpu: 4, transcodecpu: 4, transcodegpu: 1, ...limits }, overrides);
const mac = (overrides, limits) => node(MAC, { transcodecpu: 1 }, { nodeTags: 'mapped,studio-native', nodePaused: true, ...overrides, ...(limits && { workerLimits: { healthcheckcpu: 0, healthcheckgpu: 0, transcodecpu: 1, transcodegpu: 0, ...limits } }) });
const busy = type => ({ job: { workerType: type, idle: false } });
const idle = type => ({ job: { workerType: type, idle: true } });
// A job that finished on one node and waits in staging for a worker of the other node to continue it.
const waiting = (library = TV_LIBRARIES[0], id = 'file') => ({
  _id: `staged-${id}`, status: 'processing', originalLibraryFile: { _id: `/data/media/${id}.mkv`, DB: library },
});
// Tdarr keeps a node's saved settings under _id = the node's name, and the document has no nodeName field.
const persistedDoc = ({ workers, nodeName, ...rest }) => ({ _id: nodeName, ...structuredClone(rest) });

function world({ nodes, libraries, staged } = {}) {
  const w = { updates: [], files: new Map(), calls: [], logs: [], gets: 0 };
  w.nodes = nodes ?? { a: linux(), b: mac() };
  w.libraries = libraries ?? adopted();
  w.staged = staged ?? [];
  w.stored = Object.fromEntries(Object.values(w.nodes).map(connected => [connected.nodeName, persistedDoc(connected)]));
  w.crud = async (collection, mode, { docID } = {}) => {
    if (collection === 'LibrarySettingsJSONDB' && mode === 'getAll') return structuredClone(w.libraries);
    if (collection === 'StagedJSONDB' && mode === 'getAll') return structuredClone(w.staged);
    if (collection === 'NodeJSONDB' && mode === 'getById') return structuredClone(w.stored[docID]);
    throw new Error(`${collection} ${mode}`);
  };
  w.apply = ({ nodeID, nodeUpdates }) => {
    Object.assign(w.nodes[nodeID], structuredClone(nodeUpdates));
    Object.assign(w.stored[w.nodes[nodeID].nodeName], structuredClone(nodeUpdates));
  };
  w.request = async (endpoint, data) => {
    w.calls.push(endpoint);
    if (endpoint === 'get-nodes') { w.gets++; return structuredClone(w.nodes); }
    if (endpoint === 'update-node') { w.updates.push(data.data); w.apply(data.data); return undefined; }
    throw new Error(endpoint);
  };
  w.io = {
    mkdir: async (path, options) => { w.calls.push(['mkdir', path, options]); },
    writeFile: async (path, content, options) => { w.calls.push(['writeFile', path, options]); w.files.set(path, content); },
  };
  w.run = options => configure({
    crud: w.crud, request: w.request, io: w.io, log: line => w.logs.push(line), options: { sets: {}, ...options },
  });
  return w;
}
const untouched = w => assert.deepEqual([w.updates, [...w.files.keys()]], [[], []]);

test('argument parsing accepts one change set and refuses malformed or contradictory requests', () => {
  assert.deepEqual(parseArgs(['--node-name', 'HomeServer', '--set', 'transcodecpu=0', '--set', 'transcodegpu=2', '--pause', '--apply']),
    { apply: true, sets: { transcodecpu: 0, transcodegpu: 2 }, macNode: MAC, nodeName: 'HomeServer', pause: true });
  assert.equal(parseArgs(['--node-name', MAC, '--resume', '--mac-node', 'Other']).macNode, 'Other');
  assert.equal(parseArgs(['--node-name', MAC, '--resume']).pause, false);
  const refused = [
    [], ['--apply'], ['--node-name', MAC], ['--node-name'], ['--node-name', '--resume'], ['--node-name', '--pause', '--resume'],
    ['--node-name', MAC, '--pause', '--resume'], ['--node-name', MAC, '--set'], ['--node-name', MAC, '--set', 'transcodecpu'],
    ['--node-name', MAC, '--set', 'transcodecpu='], ['--node-name', MAC, '--set', 'transcodecpu=-1'],
    ['--node-name', MAC, '--set', 'transcodecpu=33'], ['--node-name', MAC, '--set', 'transcodecpu=1.5'],
    ['--node-name', MAC, '--set', 'transcodecpu=1=2'], ['--node-name', MAC, '--set', 'cpu=1'],
    ['--node-name', MAC, '--set', 'transcodecpu=1', '--set', 'transcodecpu=2'],
    ['--node-name', MAC, '--resume', '--mac-node'], ['--node-name', MAC, '--resume', '--surprise'],
  ];
  for (const argv of refused) assert.throws(() => parseArgs(argv), undefined, JSON.stringify(argv));
  assert.deepEqual(WORKER_TYPES, ['healthcheckcpu', 'healthcheckgpu', 'transcodecpu', 'transcodegpu']);
});

test('a dry run reports the change and writes nothing', async () => {
  const w = world();
  const updates = await w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0 }, apply: false });
  assert.deepEqual(updates, { workerLimits: { healthcheckcpu: 4, healthcheckgpu: 0, transcodecpu: 0, transcodegpu: 1 } });
  untouched(w);
  assert(!w.calls.includes('update-node'));
  assert.equal(w.nodes.a.workerLimits.transcodecpu, 4);
});

test('applying changes only what was asked, with a private backup and verified readback', async () => {
  const w = world({ nodes: { a: linux({ workers: idle('transcodecpu') }), b: mac() } });
  const before = structuredClone(w.nodes.a);
  const storedBefore = persistedDoc(before);
  assert(!('nodeName' in storedBefore) && storedBefore._id === 'HomeServer', 'the saved document is keyed by _id');
  await w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0, transcodegpu: 2 }, apply: true });
  assert.deepEqual(w.updates, [{ nodeID: 'a', nodeUpdates: {
    workerLimits: { healthcheckcpu: 4, healthcheckgpu: 0, transcodecpu: 0, transcodegpu: 2 },
  } }]);
  const limits = { ...before.workerLimits, transcodecpu: 0, transcodegpu: 2 };
  assert.deepEqual(w.nodes.a, { ...before, workerLimits: limits });
  assert.deepEqual(w.stored.HomeServer, { ...storedBefore, workerLimits: limits });
  assert.deepEqual(w.nodes.b, mac(), 'other nodes are untouched');
  const [path] = [...w.files.keys()];
  assert.match(path, new RegExp(`^${ROOT}/backups/offload-node-[0-9a-f-]{36}\\.json$`));
  assert.deepEqual(JSON.parse(w.files.get(path)), { nodeID: 'a', nodeName: 'HomeServer', node: storedBefore });
  assert(w.calls.some(call => call[0] === 'writeFile' && call[2].flag === 'wx' && call[2].mode === 0o600));
  assert(w.calls.some(call => call[0] === 'mkdir' && call[1] === `${ROOT}/backups` && call[2].mode === 0o700));

  await w.run({ nodeName: MAC, pause: false, sets: { transcodecpu: 3 }, apply: true });
  assert.deepEqual(w.nodes.b.workerLimits, { healthcheckcpu: 0, healthcheckgpu: 0, transcodecpu: 3, transcodegpu: 0 });
  assert.equal(w.nodes.b.nodePaused, false);
  assert.equal(w.stored[MAC].nodePaused, false);
  assert.equal(w.nodes.b.nodeTags, 'mapped,studio-native');
});

test('asking for the current state changes nothing', async () => {
  const w = world();
  await w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 4 }, apply: true });
  await w.run({ nodeName: MAC, pause: true, apply: true });
  untouched(w);
  assert(w.logs.every(line => /nothing to change|"updates":\{\}/.test(line)));
});

test('a limit is never lowered under a running worker of that type', async () => {
  for (const type of ['transcodecpu', 'transcodegpu', 'healthcheckcpu']) {
    const w = world({ nodes: { a: linux({ workers: busy(type) }), b: mac() } });
    await assert.rejects(w.run({ nodeName: 'HomeServer', sets: { [type]: 0 }, apply: true }), new RegExp(`running ${type} worker`), type);
    untouched(w);
  }
  const w = world({ libraries: held(), nodes: { a: linux({ workers: busy('transcodecpu') }), b: mac() } });
  await w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 6, transcodegpu: 0, healthcheckcpu: 2 }, apply: true });
  assert.equal(w.nodes.a.workerLimits.transcodecpu, 6, 'raising a limit or lowering another type is allowed');
  const unchanged = world({ nodes: { a: linux({ workers: busy('transcodecpu') }), b: mac() } });
  await unchanged.run({ nodeName: 'HomeServer', sets: { transcodecpu: 4 }, apply: true });
  untouched(unchanged);
});

test('the node must be identified exactly and report complete settings', async () => {
  for (const nodes of [{ a: linux() }, { a: linux(), b: linux(), c: mac() }]) {
    const w = world({ nodes });
    await assert.rejects(w.run({ nodeName: nodes.b ? 'HomeServer' : MAC, pause: true, apply: true }), /exactly one connected node/);
    untouched(w);
  }
  for (const bad of [{ workerLimits: undefined }, { workerLimits: { transcodecpu: 1 } }, { nodePaused: undefined }]) {
    const w = world({ nodes: { a: linux(bad), b: mac() } });
    await assert.rejects(w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 1 }, apply: true }), /incomplete worker limits|unknown pause state/);
    untouched(w);
  }
});

test('the Mac may only be active as a CPU encoder, and a pause is always allowed', async () => {
  for (const type of ['transcodegpu', 'healthcheckcpu', 'healthcheckgpu']) {
    const sets = { [type]: 2 };
    const w = world();
    await assert.rejects(w.run({ nodeName: MAC, pause: false, sets, apply: true }), /CPU encodes only/, type);
    untouched(w);
    const stayPaused = world();
    await assert.rejects(stayPaused.run({ nodeName: MAC, sets, apply: true }), /CPU encodes only/, `paused ${type}`);
    untouched(stayPaused);
    const linuxNode = world();
    await linuxNode.run({ nodeName: 'HomeServer', sets, apply: true });
    assert.equal(linuxNode.updates.length, 1, `${type}: only the Mac is limited to CPU work`);
    assert.equal(linuxNode.nodes.a.workerLimits[type], 2);
  }
  const misconfigured = world({ nodes: { a: linux(), b: mac({ nodePaused: false }, { transcodegpu: 1, healthcheckcpu: 2 }) } });
  await assert.rejects(misconfigured.run({ nodeName: MAC, sets: { transcodecpu: 2 }, apply: true }), /CPU encodes only/);
  await misconfigured.run({ nodeName: MAC, pause: true, apply: true });
  assert.equal(misconfigured.nodes.b.nodePaused, true);
  await misconfigured.run({ nodeName: MAC, sets: { transcodegpu: 0, healthcheckcpu: 0 }, apply: true });
  assert.deepEqual(misconfigured.nodes.b.workerLimits, { healthcheckcpu: 0, healthcheckgpu: 0, transcodecpu: 1, transcodegpu: 0 });
});

test('the Mac does not become active while a TV library could hand it the Linux-only flow', async () => {
  const open = (flowId, cache, overrides) => TV_LIBRARIES.map((id, i) => tv(id, i === 1 ? { flowId, cache, ...overrides } : { flowId: FLOW_ID, cache: CACHE_ROOT }));
  const refused = {
    'old flow, schedule open': open(SAFE_FLOW, SAFE_CACHE),
    'half-moved library': open(FLOW_ID, SAFE_CACHE),
    'unknown flow': open('zRnXMGq83', SAFE_CACHE),
    'no schedule data': open(SAFE_FLOW, SAFE_CACHE, { schedule: undefined }),
  };
  for (const [name, libraries] of Object.entries(refused)) {
    for (const request of [{ pause: false }, { pause: false, sets: { transcodecpu: 2 } }]) {
      const w = world({ libraries });
      await assert.rejects(w.run({ nodeName: MAC, apply: true, ...request }), /run install-offload-flow\.cjs --adopt/, name);
      untouched(w);
    }
    const prepared = world({ libraries });
    await prepared.run({ nodeName: MAC, sets: { transcodecpu: 2 }, apply: true });
    assert.equal(prepared.nodes.b.workerLimits.transcodecpu, 2, `${name}: a paused Mac can be prepared`);
    const linuxNode = world({ libraries });
    await linuxNode.run({ nodeName: 'HomeServer', pause: true, apply: true });
    assert.equal(linuxNode.nodes.a.nodePaused, true, `${name}: the guard only protects the Mac`);
  }
  for (const libraries of [adopted(), open(SAFE_FLOW, SAFE_CACHE, { schedule: slots(false) }), open(SAFE_FLOW, SAFE_CACHE, { processTranscodes: false })]) {
    const w = world({ libraries });
    await w.run({ nodeName: MAC, pause: false, apply: true });
    assert.equal(w.nodes.b.nodePaused, false);
  }
  const idleMac = world({ libraries: open(SAFE_FLOW, SAFE_CACHE), nodes: { a: linux(), b: mac({ nodePaused: false }, { transcodecpu: 2 }) } });
  await idleMac.run({ nodeName: MAC, sets: { transcodecpu: 0 }, apply: true });
  assert.equal(idleMac.nodes.b.workerLimits.transcodecpu, 0, 'removing the workers needs no adoption');
  await assert.rejects(world({ libraries: adopted().slice(1) }).run({ nodeName: MAC, pause: false, apply: true }), /three existing TV libraries/);
});

test('a Linux node does not start or enlarge CPU encoding while a library on the offload flow can start jobs', async () => {
  const refused = {
    'raising the CPU limit': [linux({}, { transcodecpu: 0 }), { sets: { transcodecpu: 2 } }],
    'resuming a node that has CPU workers': [linux({ nodePaused: true }), { pause: false }],
    'resuming and raising together': [linux({ nodePaused: true }, { transcodecpu: 0 }), { pause: false, sets: { transcodecpu: 2 } }],
    'enlarging a node that already has them': [linux(), { sets: { transcodecpu: 6 } }],
  };
  for (const [name, [home, request]] of Object.entries(refused)) {
    const w = world({ nodes: { a: home, b: mac() } });
    await assert.rejects(w.run({ nodeName: 'HomeServer', apply: true, ...request }), /runs the Mac offload flow/, name);
    untouched(w);
  }
  const canary = tv('homeserver-hevc-studio-canary-v1', { flowId: FLOW_ID, cache: CACHE_ROOT });
  const open = world({ libraries: [...held(), canary], nodes: { a: linux({}, { transcodecpu: 0 }), b: mac() } });
  await assert.rejects(open.run({ nodeName: 'HomeServer', sets: { transcodecpu: 2 }, apply: true }), /TV homeserver-hevc-studio-canary-v1 runs the Mac offload flow/,
    'one enabled library is enough, whatever it is');
  untouched(open);

  const quietLibraries = {
    'every schedule held': held(),
    'transcoding off': TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT, processTranscodes: false })),
    'still on the Linux flow': TV_LIBRARIES.map(id => tv(id)),
  };
  for (const [name, libraries] of Object.entries(quietLibraries)) {
    const w = world({ libraries, nodes: { a: linux({ nodePaused: true }, { transcodecpu: 0 }), b: mac() } });
    await w.run({ nodeName: 'HomeServer', pause: false, sets: { transcodecpu: 2 }, apply: true });
    assert.equal(w.nodes.a.workerLimits.transcodecpu, 2, name);
    assert.equal(w.nodes.a.nodePaused, false, name);
  }

  // Fixing a node that is already in that state is never blocked, and neither is a request that changes nothing.
  const hazard = world();
  await hazard.run({ nodeName: 'HomeServer', sets: { transcodecpu: 4 }, apply: true });
  await hazard.run({ nodeName: 'HomeServer', sets: { transcodegpu: 2 }, apply: true });
  await hazard.run({ nodeName: 'HomeServer', sets: { transcodecpu: 2 }, apply: true });
  await hazard.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0 }, apply: true });
  await hazard.run({ nodeName: 'HomeServer', pause: true, apply: true });
  assert.deepEqual([hazard.nodes.a.workerLimits.transcodecpu, hazard.nodes.a.workerLimits.transcodegpu, hazard.nodes.a.nodePaused], [0, 2, true]);
});

test('the only Linux GPU worker is not paused or removed while the Mac may still be encoding', async () => {
  const removals = { pausing: { pause: true }, 'removing its GPU worker': { sets: { transcodegpu: 0 } } };
  const backup = (overrides, limits) => node('Backup', { transcodegpu: 1, ...limits }, overrides);
  const refused = {
    'an active Mac': { a: linux(), b: mac({ nodePaused: false }) },
    'a paused Mac with a running encode': { a: linux(), b: mac({ workers: busy('transcodecpu') }) },
    'a Mac whose pause state is unknown': { a: linux(), b: mac({ nodePaused: undefined }) },
    'a second Linux node that is paused': { a: linux(), b: mac({ nodePaused: false }), c: backup({ nodePaused: true }) },
    'a second Linux node without a GPU worker': { a: linux(), b: mac({ nodePaused: false }), c: backup({}, { transcodegpu: 0 }) },
    'a Mac with a GPU worker of its own, which is no publisher': {
      a: linux(), b: mac({ nodePaused: false }, { transcodegpu: 1, transcodecpu: 2 }),
    },
  };
  for (const [name, nodes] of Object.entries(refused)) {
    for (const [change, request] of Object.entries(removals)) {
      const w = world({ nodes });
      await assert.rejects(w.run({ nodeName: 'HomeServer', apply: true, ...request }), /only unpaused Linux node with a GPU worker/, `${change} with ${name}`);
      untouched(w);
    }
  }
  const allowed = {
    'a paused idle Mac': { a: linux(), b: mac() },
    'a Mac with no CPU workers': { a: linux(), b: mac({ nodePaused: false }, { transcodecpu: 0 }) },
    'no Mac connected': { a: linux() },
    'another Linux node that can publish': { a: linux(), b: mac({ nodePaused: false }), c: backup() },
  };
  for (const [name, nodes] of Object.entries(allowed)) {
    for (const [change, request] of Object.entries(removals)) {
      const w = world({ nodes: structuredClone(nodes) });
      await w.run({ nodeName: 'HomeServer', apply: true, ...request });
      assert.equal(w.updates.length, 1, `${change} with ${name}`);
    }
  }
  const active = world({ nodes: { a: linux(), b: mac({ nodePaused: false }) } });
  await active.run({ nodeName: 'HomeServer', sets: { transcodegpu: 2, healthcheckcpu: 2 }, apply: true });
  assert.equal(active.nodes.a.workerLimits.transcodegpu, 2, 'only removing the publisher is refused');
  const notPublishing = world({ nodes: { a: linux({ nodePaused: true }), b: mac({ nodePaused: false }) } });
  await notPublishing.run({ nodeName: 'HomeServer', sets: { healthcheckcpu: 2 }, apply: true });
  assert.equal(notPublishing.nodes.a.workerLimits.healthcheckcpu, 2, 'a node that publishes nothing is not what the rule protects');
});

test('the only Linux GPU worker stays while a job that the Mac finished is waiting in staging for it', async () => {
  // get-nodes lists busy workers only, so a job waiting between the two nodes can be seen in staging alone.
  const removals = { pausing: { pause: true }, 'removing its GPU worker': { sets: { transcodegpu: 0 } } };
  const backup = overrides => node('Backup', { transcodegpu: 1 }, overrides);
  const message = /only unpaused Linux node with a GPU worker to publish Studio-Native's encodes; 2 staged job\(s\) of the offload flow are waiting/;
  const quietMacs = {
    'a paused idle Mac': { a: linux(), b: mac() },
    'a Mac with no CPU workers': { a: linux(), b: mac({ nodePaused: false }, { transcodecpu: 0 }) },
    'no Mac connected': { a: linux() },
  };
  const rows = [waiting(TV_LIBRARIES[1], 'one'), waiting(TV_LIBRARIES[2], 'two')];
  for (const [name, nodes] of Object.entries(quietMacs)) {
    for (const [change, request] of Object.entries(removals)) {
      const w = world({ nodes: structuredClone(nodes), staged: rows });
      await assert.rejects(w.run({ nodeName: 'HomeServer', apply: true, ...request }), message, `${change} with ${name}`);
      untouched(w);
      const empty = world({ nodes: structuredClone(nodes) });
      await empty.run({ nodeName: 'HomeServer', apply: true, ...request });
      assert.equal(empty.updates.length, 1, `${change} with ${name}: nothing is waiting`);
    }
  }

  const unrelated = {
    'another Linux node can publish': world({ nodes: { a: linux(), b: mac(), c: backup() }, staged: rows }),
    'the rows belong to libraries of other flows': world({
      libraries: [tv(TV_LIBRARIES[0]), ...adopted().slice(1)],
      staged: [waiting('homeserver-dv5-movies', 'dv5'), waiting(TV_LIBRARIES[0], 'old-flow')],
    }),
    'no library uses the offload flow': world({ libraries: TV_LIBRARIES.map(id => tv(id)), staged: rows }),
  };
  for (const [name, w] of Object.entries(unrelated)) {
    await w.run({ nodeName: 'HomeServer', pause: true, apply: true });
    assert.equal(w.updates.length, 1, name);
  }

  // A row that names no library cannot be told apart from an offload job.
  const nameless = world({ staged: [{ ...waiting(), originalLibraryFile: {} }, { _id: 'bare' }] });
  await assert.rejects(nameless.run({ nodeName: 'HomeServer', pause: true, apply: true }), /2 staged job\(s\) of the offload flow/);
  untouched(nameless);

  // Everything else is unaffected, including changes that keep the node a publisher.
  const others = world({ staged: rows });
  await others.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0, healthcheckcpu: 2, transcodegpu: 2 }, apply: true });
  await others.run({ nodeName: MAC, sets: { transcodecpu: 2 }, pause: false, apply: true });
  await others.run({ nodeName: MAC, pause: true, apply: true });
  assert.deepEqual(others.updates.map(({ nodeID }) => nodeID), ['a', 'b', 'b']);
  assert.equal(others.nodes.b.nodePaused, true);
});

test('staging that cannot be read stops only the change that depends on it', async () => {
  for (const unreadable of [null, {}, 'oops']) {
    const stuck = world();
    stuck.staged = unreadable;
    await assert.rejects(stuck.run({ nodeName: 'HomeServer', pause: true, apply: true }), /The staged jobs could not be read/);
    untouched(stuck);
    const unrelated = world();
    unrelated.staged = unreadable;
    await unrelated.run({ nodeName: 'HomeServer', sets: { healthcheckcpu: 2 }, apply: true });
    assert.equal(unrelated.updates.length, 1);
    const noOffload = world({ libraries: TV_LIBRARIES.map(id => tv(id)) });
    noOffload.staged = unreadable;
    await noOffload.run({ nodeName: 'HomeServer', pause: true, apply: true });
    assert.equal(noOffload.updates.length, 1, 'nothing can be waiting for a flow that no library uses');
  }
});

test('the Mac does not become active without an unpaused Linux GPU worker to publish its encodes', async () => {
  const refused = {
    'no Linux node at all': { b: mac() },
    'a Linux node without a GPU worker': { a: linux({}, { transcodegpu: 0 }), b: mac() },
    'a paused Linux node': { a: linux({ nodePaused: true }), b: mac() },
  };
  for (const [name, nodes] of Object.entries(refused)) {
    for (const request of [{ pause: false }, { pause: false, sets: { transcodecpu: 2 } }]) {
      const w = world({ nodes });
      await assert.rejects(w.run({ nodeName: MAC, apply: true, ...request }), /GPU worker to publish/, name);
      untouched(w);
    }
    const prepared = world({ nodes });
    await prepared.run({ nodeName: MAC, sets: { transcodecpu: 2 }, apply: true });
    assert.equal(prepared.nodes.b.workerLimits.transcodecpu, 2, `${name}: a paused Mac can be prepared`);
    const stopped = world({ nodes: { ...nodes, b: mac({ nodePaused: false }, { transcodecpu: 2 }) } });
    await stopped.run({ nodeName: MAC, pause: true, apply: true });
    assert.equal(stopped.nodes.b.nodePaused, true, `${name}: a pause is always allowed`);
  }
  const second = world({ nodes: { a: linux({ nodePaused: true }), b: mac(), c: node('Backup', { transcodegpu: 1 }) } });
  await second.run({ nodeName: MAC, pause: false, apply: true });
  assert.equal(second.nodes.b.nodePaused, false, 'any Linux node can publish');
});

test('state that changes between planning and applying is not overwritten', async () => {
  const races = {
    'a job starts': [() => ({ a: linux({ workers: busy('transcodecpu') }), b: mac() }), /running transcodecpu worker/],
    'someone resizes the pools': [() => ({ a: linux({}, { transcodegpu: 3 }), b: mac() }), /changed before the update/],
    'the node reconnects': [() => ({ z: linux(), b: mac() }), /reconnected/],
    'the node vanishes': [() => ({ b: mac() }), /exactly one connected node/],
  };
  for (const [name, [after, message]] of Object.entries(races)) {
    const w = world();
    const request = w.request;
    w.request = async (endpoint, data) => {
      if (endpoint === 'get-nodes' && w.gets === 1) w.nodes = after();
      return request(endpoint, data);
    };
    await assert.rejects(w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0 }, apply: true }), message, name);
    assert.deepEqual(w.updates, [], name);
  }
});

test('the other nodes and the libraries are checked again right before the update', async () => {
  const races = {
    'the Mac resumes before the only Linux GPU worker is paused': [
      () => world(), { nodeName: 'HomeServer', pause: true }, w => { w.nodes.b.nodePaused = false; },
      /only unpaused Linux node with a GPU worker/],
    'the Linux GPU worker is paused before the Mac resumes': [
      () => world(), { nodeName: MAC, pause: false }, w => { w.nodes.a.nodePaused = true; }, /GPU worker to publish/],
    'a library reopens before Linux starts encoding': [
      () => world({ libraries: held(), nodes: { a: linux({}, { transcodecpu: 0 }), b: mac() } }),
      { nodeName: 'HomeServer', sets: { transcodecpu: 2 } }, w => { w.libraries = adopted(); }, /runs the Mac offload flow/],
    'a finished encode starts waiting before the only Linux GPU worker is paused': [
      () => world(), { nodeName: 'HomeServer', pause: true }, w => { w.staged = [waiting()]; },
      /1 staged job\(s\) of the offload flow are waiting/],
  };
  for (const [name, [build, request, change, message]] of Object.entries(races)) {
    const w = build();
    const original = w.request;
    w.request = async (endpoint, data) => {
      if (endpoint === 'get-nodes' && w.gets === 1) change(w);
      return original(endpoint, data);
    };
    await assert.rejects(w.run({ apply: true, ...request }), message, name);
    assert.deepEqual(w.updates, [], name);
  }
});

test('a concurrent change to a setting we are not touching is preserved, not overwritten', async () => {
  const w = world();
  const request = w.request;
  w.request = async (endpoint, data) => {
    if (endpoint === 'get-nodes' && w.gets === 1) w.nodes.a.nodePaused = true;
    return request(endpoint, data);
  };
  await w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0 }, apply: true });
  assert.deepEqual(Object.keys(w.updates[0].nodeUpdates), ['workerLimits']);
  assert.equal(w.nodes.a.nodePaused, true);
});

test('a setting that Tdarr does not store, or changes behind our back, is detected', async () => {
  const both = { sets: { transcodecpu: 0 }, pause: true };
  const cases = {
    'live limits not applied': [w => { w.apply = () => {}; }, /Live workerLimits was not applied/],
    'persisted limits not applied': [w => { w.apply = ({ nodeID, nodeUpdates }) => Object.assign(w.nodes[nodeID], nodeUpdates); }, /Persisted workerLimits was not applied/],
    'live tags rewritten': [w => { const apply = w.apply; w.apply = update => { apply(update); w.nodes[update.nodeID].nodeTags = ''; }; }, /Live nodeTags changed/],
    'persisted exclusions rewritten': [w => { const apply = w.apply; w.apply = update => { apply(update); w.stored.HomeServer.librariesToNotProcess = { x: true }; }; }, /Persisted librariesToNotProcess changed/],
    'pause flipped': [w => { const apply = w.apply; w.apply = update => { apply(update); w.nodes[update.nodeID].nodePaused = true; }; }, /Live nodePaused changed/],
    'cpu fallback enabled': [w => { const apply = w.apply; w.apply = update => { apply(update); w.nodes[update.nodeID].allowGpuDoCpu = true; }; }, /Live allowGpuDoCpu changed/],
    'gpu selection rewritten': [w => { const apply = w.apply; w.apply = update => { apply(update); w.stored.HomeServer.gpuSelect = '0'; }; }, /Persisted gpuSelect changed/],
    'live pause not applied': [w => { w.apply = ({ nodeID, nodeUpdates: { nodePaused, ...rest } }) => { Object.assign(w.nodes[nodeID], rest); Object.assign(w.stored.HomeServer, rest); }; }, /Live nodePaused was not applied/, both],
    'persisted pause not applied': [w => { const apply = w.apply; w.apply = update => { apply(update); w.stored.HomeServer.nodePaused = false; }; }, /Persisted nodePaused was not applied/, both],
    'limits rewritten by a pause': [w => { const apply = w.apply; w.apply = update => { apply(update); w.nodes[update.nodeID].workerLimits = { ...w.nodes[update.nodeID].workerLimits, transcodecpu: 9 }; }; }, /Live workerLimits changed/, { pause: true }],
    'node gone after the update': [w => { const apply = w.apply; w.apply = update => { apply(update); delete w.nodes[update.nodeID]; }; }, /disconnected after the update/],
  };
  for (const [name, [tamper, message, request = { sets: { transcodecpu: 0 } }]] of Object.entries(cases)) {
    const w = world();
    tamper(w);
    await assert.rejects(w.run({ nodeName: 'HomeServer', apply: true, ...request }), message, name);
  }
});

test('nothing is written without a persisted copy of the node to back up', async () => {
  const w = world();
  w.stored = {};
  await assert.rejects(w.run({ nodeName: 'HomeServer', sets: { transcodecpu: 0 }, apply: true }), /Missing persisted node settings/);
  untouched(w);
});

test('the Mac is not activated if a library goes back to the Linux-only flow before the update', async () => {
  const w = world();
  const crud = w.crud;
  let reads = 0;
  w.crud = async (collection, mode, extra) => {
    if (collection === 'LibrarySettingsJSONDB' && ++reads === 2) w.libraries = [tv(TV_LIBRARIES[0]), ...adopted().slice(1)];
    return crud(collection, mode, extra);
  };
  await assert.rejects(w.run({ nodeName: MAC, pause: false, apply: true }), /run install-offload-flow\.cjs --adopt/);
  assert.deepEqual(w.updates, []);
});
