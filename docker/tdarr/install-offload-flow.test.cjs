'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  flowDefinition, poolsOf, parseArgs, install, FLOW_ID, LEGACY_FLOW, SAFE_FLOW, SAFE_CACHE, LIBRARY_ID,
  CANARY_FOLDER, MAC_ROOT, TV_LIBRARIES, DEFAULT_POOLS,
} = require('./install-offload-flow.cjs');
const { CACHE_ROOT, PRIVATE_ROOT } = require('./hevc-offload-v1.cjs');
const { ROOT } = require('./install-flow.cjs');

const MAC = 'Studio-Native';
const slots = checked => Array.from({ length: 168 }, (_, i) => ({ _id: `slot-${i}`, checked }));
const NOTIFY = {
  id: 'notify', name: 'Notify Sonarr', pluginName: 'notifyRadarrOrSonarr', sourceRepo: 'Community',
  version: '2.0.0', fpEnabled: true, position: { x: 0, y: 1080 },
  inputsDB: { arr: 'sonarr', arr_host: 'http://sonarr:8989', arr_api_key: 'not-a-real-key' },
};
const tv = (id, overrides = {}) => ({
  _id: id, name: `TV ${id}`, folder: `/data/media/${id}`, flowId: SAFE_FLOW, cache: SAFE_CACHE,
  processLibrary: true, processTranscodes: true, processHealthChecks: true, folderWatching: true,
  useFsEvents: false, scheduledScanFindNew: false, scanOnStart: false, filterCodecsSkip: 'hevc',
  schedule: slots(false), decisionMaker: { settingsFlows: true, settingsPlugin: false }, ...overrides,
});
const crf = id => ({ _id: `${id}-crf`, key: 'crf', value: '20', type: `library:${id}`, date: 1 });
const node = (nodeName, limits, overrides = {}) => ({
  nodeName, nodePaused: false, allowGpuDoCpu: false, workers: {},
  workerLimits: { healthcheckcpu: 0, healthcheckgpu: 0, transcodecpu: 0, transcodegpu: 0, ...limits }, ...overrides,
});
const linux = (overrides, limits) => node('HomeServer', { healthcheckcpu: 4, transcodegpu: 1, ...limits }, overrides);
const mac = (overrides, limits) => node(MAC, { transcodecpu: 2, ...limits }, overrides);

function world({ flows, libraries, variables, staged = [], nodes, present } = {}) {
  const db = {
    FlowsJSONDB: flows ?? [{ _id: SAFE_FLOW, flowPlugins: [structuredClone(NOTIFY)] }],
    LibrarySettingsJSONDB: libraries ?? TV_LIBRARIES.map(id => tv(id)),
    VariablesJSONDB: variables ?? TV_LIBRARIES.map(crf),
    StagedJSONDB: staged,
  };
  const w = { db, writes: [], logs: [], files: new Map(), calls: [], nodes: nodes ?? { a: linux(), b: mac() } };
  w.crud = async (collection, mode, { docID, obj } = {}) => {
    const rows = db[collection];
    if (mode === 'getAll') return structuredClone(rows);
    if (mode === 'getById') return structuredClone(rows.find(row => row._id === docID));
    w.writes.push({ collection, mode, docID, obj: structuredClone(obj) });
    if (mode === 'insert') {
      assert(!rows.some(row => row._id === docID), `duplicate ${docID}`);
      rows.push(structuredClone(obj));
    } else if (mode === 'update') Object.assign(rows.find(row => row._id === docID), structuredClone(obj));
    else throw new Error(mode);
  };
  w.request = async endpoint => {
    assert.equal(endpoint, 'get-nodes');
    return structuredClone(w.nodes);
  };
  const available = new Set(present ?? [
    'hevc-offload-v1.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs',
  ].map(file => `${ROOT}/${file}`).concat(CACHE_ROOT));
  w.io = {
    access: async path => {
      w.calls.push(['access', path]);
      if (!available.has(path)) throw Object.assign(new Error(`ENOENT ${path}`), { code: 'ENOENT' });
    },
    mkdir: async (path, options) => { w.calls.push(['mkdir', path, options]); },
    writeFile: async (path, content, options) => { w.calls.push(['writeFile', path, options]); w.files.set(path, content); },
  };
  w.run = (options, extra = {}) => install({
    crud: w.crud, request: w.request, io: w.io, log: line => w.logs.push(line), options, ...extra,
  });
  w.backups = () => [...w.files.keys()].filter(path => path.startsWith(`${ROOT}/backups/offload-flow-`));
  w.library = id => db.LibrarySettingsJSONDB.find(row => row._id === id);
  return w;
}
const untouched = w => assert.deepEqual([w.writes, w.backups()], [[], []]);
const canary = overrides => tv(LIBRARY_ID, {
  name: 'Studio native HEVC - isolated manual canary', folder: CANARY_FOLDER, cache: CACHE_ROOT, flowId: LEGACY_FLOW,
  processLibrary: false, processTranscodes: false, processHealthChecks: false, folderWatching: false,
  schedule: slots(true), ...overrides,
});

test('the flow encodes on a CPU worker, publishes from a GPU worker and needs no Pro-only node tags', () => {
  const flow = flowDefinition(NOTIFY, 7);
  const ids = flow.flowPlugins.map(plugin => plugin.id);
  assert.deepEqual(ids, ['input', 'cpu', 'prepare', 'begin', 'encode', 'threads', 'container', 'execute',
    'finish', 'gpu', 'commit', 'notify']);
  assert.deepEqual(flow.flowEdges.map(edge => edge.id), ids.slice(0, -1).map((id, i) => `${id}-to-${ids[i + 1]}`));
  const byId = Object.fromEntries(flow.flowPlugins.map(plugin => [plugin.id, plugin]));
  assert.deepEqual(byId.cpu.inputsDB, { requiredWorkerType: 'CPU', requiredNodeTags: '' });
  assert.deepEqual(byId.gpu.inputsDB, { requiredWorkerType: 'GPU', requiredNodeTags: '' });
  assert.deepEqual(byId.encode.inputsDB, {
    outputCodec: 'hevc', hardwareEncoding: 'false', forceEncoding: 'false', ffmpegPreset: 'slow',
    ffmpegQuality: '{{{args.userVariables.library.crf}}}',
  });
  assert.equal(byId.threads.inputsDB.outputArguments, '-x265-params pools=7');
  assert.deepEqual(byId.container.inputsDB, { container: 'mkv', forceConform: 'false' });
  assert.deepEqual(byId.notify, { ...NOTIFY, position: { x: 0, y: 1320 } });
  assert.notEqual(byId.notify.inputsDB, NOTIFY.inputsDB);
  assert.equal(flow.isUiLocked, true);
  assert.equal(poolsOf(flow), 7);
  assert.equal(poolsOf(flowDefinition(NOTIFY)), DEFAULT_POOLS);
  for (const pools of [0, 65, 1.5, '9', NaN]) assert.throws(() => flowDefinition(NOTIFY, pools), /pools/);
});

test('each custom step loads the module copy that belongs to the node it runs on', async () => {
  const flow = flowDefinition(NOTIFY);
  for (const fn of ['prepare', 'finish', 'commit']) {
    const { code } = flow.flowPlugins.find(plugin => plugin.id === fn).inputsDB;
    for (const [platform, expected] of [['darwin', `${MAC_ROOT}/hevc-offload-v1.cjs`], ['linux', `${ROOT}/hevc-offload-v1.cjs`]]) {
      const loaded = [];
      const sandbox = { exports: undefined };
      new Function('module', 'require', 'process', code)(sandbox, path => {
        loaded.push(path);
        return { [fn]: async args => `${fn}:${args}` };
      }, { platform });
      assert.equal(await sandbox.exports('job'), `${fn}:job`);
      assert.deepEqual(loaded, [expected]);
    }
  }
});

test('an offload flow with an unrecognised thread setting is refused', () => {
  const flow = flowDefinition(NOTIFY);
  flow.flowPlugins.find(plugin => plugin.id === 'threads').inputsDB.outputArguments = '-x265-params pools=4 --no-asm';
  assert.throws(() => poolsOf(flow), /unrecognised/);
  assert.throws(() => poolsOf(undefined), /unrecognised/);
});

test('argument parsing accepts one mode and bounded pools', () => {
  assert.deepEqual(parseArgs([]), { mode: 'canary', apply: false, macNode: MAC });
  assert.deepEqual(parseArgs(['--adopt', '--pools', '6', '--mac-node', 'Mini', '--apply']),
    { mode: 'adopt', apply: true, macNode: 'Mini', pools: 6 });
  assert.equal(parseArgs(['--rollback']).mode, 'rollback');
  for (const bad of [['--adopt', '--rollback'], ['--rollback', '--pools', '6'], ['--pools'], ['--pools', '0'],
    ['--pools', 'x'], ['--mac-node'], ['--mac-node', '--apply'], ['--enable'], ['--apply', 'extra']]) {
    assert.throws(() => parseArgs(bad), `rejects ${bad.join(' ')}`);
  }
});

test('a dry run writes nothing in any mode', async () => {
  for (const options of [{ mode: 'canary' }, { mode: 'adopt' }]) {
    const w = world();
    const plan = await w.run(options);
    assert(plan.length > 0, options.mode);
    untouched(w);
    assert.equal(w.calls.length, 0);
  }
  const w = world({ libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })),
    nodes: { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) } });
  assert((await w.run({ mode: 'rollback' })).length > 0);
  untouched(w);
});

test('canary install creates the flow, a runnable disabled canary and CRF 20 without touching TV libraries', async () => {
  const w = world();
  const before = structuredClone(w.db);
  await w.run({ mode: 'canary', apply: true });
  assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`), [
    `FlowsJSONDB:insert:${FLOW_ID}`, `LibrarySettingsJSONDB:insert:${LIBRARY_ID}`, `VariablesJSONDB:insert:${LIBRARY_ID}-crf`,
  ]);
  const created = w.library(LIBRARY_ID);
  assert.deepEqual([created.folder, created.cache, created.flowId], [CANARY_FOLDER, CACHE_ROOT, FLOW_ID]);
  for (const key of ['processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching', 'useFsEvents',
    'scheduledScanFindNew', 'scanOnStart']) assert.equal(created[key], false, key);
  assert.equal(created.schedule.length, 168);
  assert(created.schedule.every(slot => slot.checked), 'a paused template schedule is not inherited');
  assert.equal(poolsOf(w.db.FlowsJSONDB.find(flow => flow._id === FLOW_ID)), DEFAULT_POOLS);
  assert.deepEqual(w.db.VariablesJSONDB.filter(row => row.type === `library:${LIBRARY_ID}`).map(row => row.value), ['20']);
  for (const id of TV_LIBRARIES) assert.deepEqual(w.library(id), before.LibrarySettingsJSONDB.find(row => row._id === id));
  const [backup] = w.backups();
  assert.deepEqual(JSON.parse(w.files.get(backup)), {
    flows: before.FlowsJSONDB, libraries: before.LibrarySettingsJSONDB, variables: before.VariablesJSONDB,
  });
  assert(w.calls.some(call => call[0] === 'writeFile' && call[2].flag === 'wx' && call[2].mode === 0o600));
  assert(w.calls.some(call => call[0] === 'mkdir' && call[1] === PRIVATE_ROOT && call[2].mode === 0o700));
  assert.deepEqual(w.calls.filter(call => call[0] === 'access').map(call => call[1]), [
    `${ROOT}/hevc-offload-v1.cjs`, `${ROOT}/hevc-safe-v1.cjs`, `${ROOT}/dv5-sidecar.cjs`, CACHE_ROOT,
  ]);
});

test('a missing module or cache aborts before any backup or write', async () => {
  for (const missing of ['hevc-offload-v1.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs', 'cache']) {
    const present = ['hevc-offload-v1.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs'].filter(file => file !== missing)
      .map(file => `${ROOT}/${file}`).concat(missing === 'cache' ? [] : [CACHE_ROOT]);
    const w = world({ present });
    await assert.rejects(w.run({ mode: 'canary', apply: true }), /ENOENT/, missing);
    assert.deepEqual([w.writes, w.backups()], [[], []], missing);
  }
});

test('an existing canary moves off the legacy flow and nothing else changes', async () => {
  const w = world({
    flows: [{ _id: SAFE_FLOW, flowPlugins: [structuredClone(NOTIFY)] }, { _id: LEGACY_FLOW, flowPlugins: [] }],
    libraries: [...TV_LIBRARIES.map(id => tv(id)), canary()],
    variables: [...TV_LIBRARIES.map(crf), crf(LIBRARY_ID)],
  });
  const legacy = structuredClone(w.db.FlowsJSONDB[1]);
  await w.run({ mode: 'canary', apply: true });
  assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`), [
    `FlowsJSONDB:insert:${FLOW_ID}`, `LibrarySettingsJSONDB:update:${LIBRARY_ID}`,
  ]);
  assert.deepEqual(w.writes[1].obj, { flowId: FLOW_ID });
  assert.deepEqual(w.db.FlowsJSONDB.find(flow => flow._id === LEGACY_FLOW), legacy);
});

test('the installer will not repoint an active canary or accept a foreign library', async () => {
  for (const key of ['processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching', 'useFsEvents',
    'scheduledScanFindNew', 'scanOnStart']) {
    const w = world({ libraries: [...TV_LIBRARIES.map(id => tv(id)), canary({ [key]: true })], variables: TV_LIBRARIES.map(crf) });
    await assert.rejects(w.run({ mode: 'canary', apply: true }), /already enabled/, key);
    untouched(w);
  }
  for (const overrides of [{ folder: '/data/media/tv' }, { cache: '/temp' }, { flowId: SAFE_FLOW }]) {
    const w = world({ libraries: [...TV_LIBRARIES.map(id => tv(id)), canary(overrides)] });
    await assert.rejects(w.run({ mode: 'canary', apply: true }), /collision/, JSON.stringify(overrides));
    untouched(w);
  }
  const w = world({ variables: [...TV_LIBRARIES.map(crf), { ...crf(LIBRARY_ID), value: '18' }] });
  await assert.rejects(w.run({ mode: 'canary', apply: true }), /CRF is not 20/);
  untouched(w);
});

test('a canary is only created from a TV library that has a schedule and decision settings to copy', async () => {
  for (const overrides of [{ schedule: undefined }, { schedule: {} }, { decisionMaker: undefined }, { decisionMaker: 'flows' }]) {
    const w = world({ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 0 ? overrides : {})) });
    await assert.rejects(w.run({ mode: 'canary', apply: true }), /use as a template/, JSON.stringify(overrides));
    untouched(w);
  }
});

test('only the thread pool may change in place; any other drift needs a new version', async () => {
  const w = world();
  await w.run({ mode: 'canary', apply: true, pools: 6 });
  const stored = () => w.db.FlowsJSONDB.find(flow => flow._id === FLOW_ID);
  assert.equal(poolsOf(stored()), 6);
  w.writes.length = 0;
  w.db.LibrarySettingsJSONDB.find(row => row._id === LIBRARY_ID).processTranscodes = true; // an active canary may stay active
  await w.run({ mode: 'canary', apply: true });
  assert.deepEqual(w.writes, [], 'no --pools keeps the stored value');
  await w.run({ mode: 'canary', apply: true, pools: 8 });
  assert.deepEqual(w.writes.map(write => `${write.mode}:${write.docID}`), [`update:${FLOW_ID}`]);
  assert.deepEqual(stored(), flowDefinition(NOTIFY, 8));
  stored().flowPlugins.find(plugin => plugin.id === 'encode').inputsDB.ffmpegPreset = 'medium';
  w.writes.length = 0;
  await assert.rejects(w.run({ mode: 'canary', apply: true, pools: 4 }), /deploy a new version/);
  assert.deepEqual(w.writes, []);
});

test('an installed flow keeps its own notification settings when the safe flow changes later', async () => {
  const w = world();
  await w.run({ mode: 'canary', apply: true });
  w.db.FlowsJSONDB.find(flow => flow._id === SAFE_FLOW).flowPlugins[0].inputsDB.arr_api_key = 'rotated';
  w.writes.length = 0;
  await w.run({ mode: 'canary', apply: true, pools: 5 });
  const stored = w.db.FlowsJSONDB.find(flow => flow._id === FLOW_ID);
  assert.equal(stored.flowPlugins.find(plugin => plugin.id === 'notify').inputsDB.arr_api_key, 'not-a-real-key');
  assert.equal(poolsOf(stored), 5);
  await assert.rejects(world({ flows: [] }).run({ mode: 'canary', apply: true }), /notification configuration/);
});

test('adopting moves only the TV flow and cache, installs the flow and leaves schedules gated', async () => {
  const w = world();
  const before = structuredClone(w.db.LibrarySettingsJSONDB);
  await w.run({ mode: 'adopt', apply: true, pools: 8 });
  assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`), [
    `FlowsJSONDB:insert:${FLOW_ID}`, ...TV_LIBRARIES.map(id => `LibrarySettingsJSONDB:update:${id}`),
  ]);
  for (const write of w.writes.slice(1)) assert.deepEqual(write.obj, { flowId: FLOW_ID, cache: CACHE_ROOT });
  for (const id of TV_LIBRARIES) {
    const expected = { ...before.find(row => row._id === id), flowId: FLOW_ID, cache: CACHE_ROOT };
    assert.deepEqual(w.library(id), expected);
  }
  assert.equal(w.library(LIBRARY_ID), undefined, 'adopting never creates the canary');
  assert.equal(poolsOf(w.db.FlowsJSONDB.find(flow => flow._id === FLOW_ID)), 8);
  assert.equal(w.backups().length, 1);
  w.writes.length = 0;
  w.nodes.a.workerLimits.transcodecpu = 4; // an idempotent re-run needs no node preconditions
  await w.run({ mode: 'adopt', apply: true });
  assert.deepEqual(w.writes, []);
});

test('adopting accepts a library whose transcoding is off instead of its schedule', async () => {
  const w = world({ libraries: TV_LIBRARIES.map(id => tv(id, { processTranscodes: false, schedule: slots(true) })) });
  await w.run({ mode: 'adopt', apply: true });
  assert.equal(w.writes.filter(write => write.collection === 'LibrarySettingsJSONDB').length, 3);
});

test('adopting is refused until nothing can run the old flow or lose the Mac', async () => {
  const idleLinuxCpu = { 'quiet-quail': { workerType: 'transcodecpu', idle: true } };
  const cases = {
    'a library that is still processing': [{ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 1 ? { schedule: slots(true) } : {})) }, /still processing/],
    'a library with no schedule data': [{ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 2 ? { schedule: undefined } : {})) }, /still processing/],
    'a library on another flow': [{ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 0 ? { flowId: 'zRnXMGq83' } : {})) }, /unexpected flow or cache/],
    'a library half-moved': [{ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 0 ? { cache: CACHE_ROOT } : {})) }, /unexpected flow or cache/],
    'a missing library': [{ libraries: TV_LIBRARIES.slice(1).map(id => tv(id)) }, /three existing TV libraries/],
    'a missing CRF variable': [{ variables: TV_LIBRARIES.slice(1).map(crf) }, /exactly one CRF/],
    'a duplicate CRF variable': [{ variables: [...TV_LIBRARIES.map(crf), { ...crf(TV_LIBRARIES[0]), _id: 'dup' }] }, /exactly one CRF/],
    'a staged TV file': [{ staged: [{ _id: 'row', originalLibraryFile: { DB: TV_LIBRARIES[2] } }] }, /1 staged TV file/],
    'the Mac missing': [{ nodes: { a: linux() } }, /not connected/],
    'the Mac doing GPU work': [{ nodes: { a: linux(), b: mac({}, { transcodegpu: 1 }) } }, /CPU encodes only/],
    'the Mac with no CPU workers': [{ nodes: { a: linux(), b: mac({}, { transcodecpu: 0 }) } }, /CPU encodes only/],
    'the Mac connected twice': [{ nodes: { a: linux(), b: mac(), c: mac() } }, /more than once/],
    'Linux CPU workers still allowed': [{ nodes: { a: linux({}, { transcodecpu: 4 }), b: mac() } }, /Set HomeServer transcodecpu to 0/],
    'Linux GPU workers allowed to do CPU jobs': [{ nodes: { a: linux({ allowGpuDoCpu: true }), b: mac() } }, /Set HomeServer transcodecpu to 0/],
    'a running Linux CPU encode': [{ nodes: { a: linux({ workers: { 'busy-bee': { workerType: 'transcodecpu', idle: false } } }), b: mac() } }, /running CPU encode/],
    'no Linux GPU worker to publish': [{ nodes: { a: linux({}, { transcodegpu: 0 }), b: mac() } }, /GPU worker is required/],
  };
  for (const [name, [setup, message]] of Object.entries(cases)) {
    const w = world(setup);
    await assert.rejects(w.run({ mode: 'adopt', apply: true }), message, name);
    untouched(w);
  }
  const otherWork = {
    ...idleLinuxCpu,
    feeder: { workerType: 'transcodegpu', idle: false },
    'health-check': { workerType: 'healthcheckcpu', idle: false },
  };
  const w = world({ nodes: { a: linux({ workers: otherWork }), b: mac() },
    staged: [{ _id: 'row', originalLibraryFile: { DB: 'homeserver-dv5-movies' } }] });
  await w.run({ mode: 'adopt', apply: true });
  assert.equal(w.writes.length, 4, 'idle CPU workers, busy GPU or health-check workers and other libraries do not block adoption');
});

test('rolling back restores the Linux flow and cache once Linux can encode and the Mac is quiet', async () => {
  const adopted = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }));
  const restored = { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) };
  const refused = {
    'no Linux CPU worker': { a: linux(), b: mac({ nodePaused: true }) },
    'an active Mac': { a: linux({}, { transcodecpu: 4 }), b: mac() },
    'a busy Mac': { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true, workers: { w: { workerType: 'transcodecpu', idle: false } } }) },
  };
  for (const [name, nodes] of Object.entries(refused)) {
    const w = world({ libraries: adopted(), nodes });
    await assert.rejects(w.run({ mode: 'rollback', apply: true }), /Restore|Pause|running CPU encode/, name);
    untouched(w);
  }
  for (const nodes of [restored, { a: linux({}, { transcodecpu: 4 }) }, { a: linux({}, { transcodecpu: 4 }), b: mac({}, { transcodecpu: 0 }) }]) {
    const w = world({ libraries: adopted(), nodes });
    await w.run({ mode: 'rollback', apply: true });
    assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}`), Array(3).fill('LibrarySettingsJSONDB:update'));
    for (const id of TV_LIBRARIES) assert.deepEqual([w.library(id).flowId, w.library(id).cache], [SAFE_FLOW, SAFE_CACHE]);
    assert.equal(w.calls.filter(call => call[0] === 'access').length, 0, 'a rollback needs no module or cache');
  }
  await assert.rejects(world({ libraries: adopted(), flows: [], nodes: restored }).run({ mode: 'rollback', apply: true }), /required for a rollback/);
  const w = world({ libraries: adopted(), nodes: restored, staged: [{ _id: 'row', originalLibraryFile: { DB: TV_LIBRARIES[0] } }] });
  await assert.rejects(w.run({ mode: 'rollback', apply: true }), /staged TV file/);
});

test('a write that Tdarr does not store is detected', async () => {
  const w = world();
  const crud = w.crud;
  w.crud = async (collection, mode, extra) => {
    if (collection === 'LibrarySettingsJSONDB' && mode === 'update') {
      w.writes.push({ collection, mode, docID: extra.docID, obj: extra.obj });
      return undefined;
    }
    return crud(collection, mode, extra);
  };
  await assert.rejects(w.run({ mode: 'adopt', apply: true }), /flowId was not stored/);
});
