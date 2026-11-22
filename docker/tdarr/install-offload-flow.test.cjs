'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  flowDefinition, poolsOf, parseArgs, install, FLOW_ID, LEGACY_FLOW, PREVIOUS_FLOW, SAFE_FLOW, SAFE_CACHE, LIBRARY_ID,
  CANARY_FOLDER, MAC_ROOT, TV_LIBRARIES, DEFAULT_POOLS,
} = require('./install-offload-flow.cjs');
const { CACHE_ROOT, PRIVATE_ROOT } = require('./hevc-offload-v2.cjs');
const { ROOT } = require('./install-flow.cjs');

const MAC = 'Studio-Native';
const slots = checked => Array.from({ length: 168 }, (_, i) => ({ _id: `slot-${i}`, checked }));
const NOTIFY = {
  id: 'notify', name: 'Notify Sonarr', pluginName: 'notifyRadarrOrSonarr', sourceRepo: 'Community',
  version: '2.0.0', fpEnabled: true, position: { x: 0, y: 1080 },
  inputsDB: { arr: 'sonarr', arr_host: 'http://sonarr:8989', arr_api_key: 'not-a-real-key' },
};
// Flow documents carry the Sonarr API key and the installer prints error.message. Node's assert.equal and
// assert.deepEqual append the compared values to a custom message, so a failure here must be a plain one-line message.
const refusal = (pattern, name) => error => {
  assert.match(error.message, pattern, name);
  assert(!error.message.includes('\n') && !error.message.includes(NOTIFY.inputsDB.arr_api_key), `${name}: ${error.message}`);
  return true;
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
// Saved node settings are identified by _id (the node name) and carry no nodeName, as Tdarr stores them.
const saved = ({ workers, nodeName, ...rest }) => ({ _id: nodeName, ...structuredClone(rest) });

function world({ flows, libraries, variables, staged = [], nodes = { a: linux(), b: mac() }, persisted, present } = {}) {
  const db = {
    FlowsJSONDB: flows ?? [{ _id: SAFE_FLOW, flowPlugins: [structuredClone(NOTIFY)] }],
    LibrarySettingsJSONDB: libraries ?? TV_LIBRARIES.map(id => tv(id)),
    VariablesJSONDB: variables ?? TV_LIBRARIES.map(crf),
    StagedJSONDB: staged,
    NodeJSONDB: persisted ?? Object.values(nodes).map(saved),
  };
  const w = { db, writes: [], logs: [], files: new Map(), calls: [], nodes };
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
    'hevc-offload-v2.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs',
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
    for (const [platform, expected] of [['darwin', `${MAC_ROOT}/hevc-offload-v2.cjs`], ['linux', `${ROOT}/hevc-offload-v2.cjs`]]) {
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
  assert.deepEqual(parseArgs(['--hold', '--apply']), { mode: 'hold', apply: true, macNode: MAC });
  assert.deepEqual(parseArgs(['--release', '--mac-node', 'Mini']), { mode: 'release', apply: false, macNode: 'Mini' });
  for (const bad of [['--adopt', '--rollback'], ['--rollback', '--pools', '6'], ['--pools'], ['--pools', '0'],
    ['--pools', 'x'], ['--mac-node'], ['--mac-node', '--apply'], ['--enable'], ['--apply', 'extra'],
    ['--hold', '--release'], ['--adopt', '--hold'], ['--release', '--rollback'],
    ['--hold', '--pools', '6'], ['--release', '--pools', '6']]) {
    assert.throws(() => parseArgs(bad), `rejects ${bad.join(' ')}`);
  }
});

test('a dry run writes nothing in any mode', async () => {
  for (const options of [{ mode: 'canary' }, { mode: 'adopt' }]) {
    const w = world();
    const plan = await w.run(options);
    assert(plan.length > 0, options.mode);
    untouched(w);
    assert.deepEqual(w.calls.filter(call => call[0] !== 'access'), [], `${options.mode} only checks that the modules and cache exist`);
  }
  const w = world({ libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })),
    nodes: { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) } });
  assert((await w.run({ mode: 'rollback' })).length > 0);
  untouched(w);
  const open = world({ libraries: TV_LIBRARIES.map(id => tv(id, { schedule: slots(true) })) });
  assert((await open.run({ mode: 'hold' })).length > 0);
  untouched(open);
  const held = world({ libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })) });
  assert((await held.run({ mode: 'release' })).length > 0);
  untouched(held);
  assert.equal(open.calls.length + held.calls.length, 0);
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
  assert(w.calls.some(call => call[0] === 'mkdir' && call[1] === `${ROOT}/backups` && call[2].mode === 0o700),
    'backups hold the Sonarr key, so only their owner may enter the directory');
  assert.deepEqual(w.calls.filter(call => call[0] === 'access').map(call => call[1]), [
    `${ROOT}/hevc-offload-v2.cjs`, `${ROOT}/hevc-safe-v1.cjs`, `${ROOT}/dv5-sidecar.cjs`, CACHE_ROOT,
  ]);
});

test('a missing module or cache aborts a dry run or an apply before any backup or write', async () => {
  for (const mode of ['canary', 'adopt']) {
    for (const apply of [false, true]) {
      for (const missing of ['hevc-offload-v2.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs', 'cache']) {
        const present = ['hevc-offload-v2.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs'].filter(file => file !== missing)
          .map(file => `${ROOT}/${file}`).concat(missing === 'cache' ? [] : [CACHE_ROOT]);
        const w = world({ present });
        await assert.rejects(w.run({ mode, apply }), /ENOENT/, `${mode} (apply ${apply}) without ${missing}`);
        assert.deepEqual([w.writes, w.backups()], [[], []], `${mode} (apply ${apply}) without ${missing}`);
      }
    }
  }
});

for (const previous of [LEGACY_FLOW, PREVIOUS_FLOW]) {
  test(`a disabled canary moves off ${previous} without changing the old flow`, async () => {
    const w = world({
      flows: [{ _id: SAFE_FLOW, flowPlugins: [structuredClone(NOTIFY)] }, { _id: previous, flowPlugins: [] }],
      libraries: [...TV_LIBRARIES.map(id => tv(id)), canary({ flowId: previous })],
      variables: [...TV_LIBRARIES.map(crf), crf(LIBRARY_ID)],
    });
    const legacy = structuredClone(w.db.FlowsJSONDB[1]);
    await w.run({ mode: 'canary', apply: true });
    assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`), [
      `FlowsJSONDB:insert:${FLOW_ID}`, `LibrarySettingsJSONDB:update:${LIBRARY_ID}`,
    ]);
    assert.deepEqual(w.writes[1].obj, { flowId: FLOW_ID });
    assert.deepEqual(w.db.FlowsJSONDB.find(flow => flow._id === previous), legacy);
  });
}

test('the installer will not repoint an active canary or accept a foreign library', async () => {
  for (const key of ['processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching', 'useFsEvents',
    'scheduledScanFindNew', 'scanOnStart']) {
    for (const flowId of [LEGACY_FLOW, PREVIOUS_FLOW]) {
      const w = world({ libraries: [...TV_LIBRARIES.map(id => tv(id)), canary({ flowId, [key]: true })], variables: TV_LIBRARIES.map(crf) });
      await assert.rejects(w.run({ mode: 'canary', apply: true }), /already enabled/, key);
      untouched(w);
    }
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
  await assert.rejects(w.run({ mode: 'canary', apply: true, pools: 4 }),
    refusal(/^Existing versioned flow differs; deploy a new version$/, 'a drifted flow'));
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
  const savedBefore = structuredClone(w.db.NodeJSONDB);
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
  assert.deepEqual(JSON.parse(w.files.get(w.backups()[0])).nodes, savedBefore, 'the backup keeps the saved node settings');
  assert(w.logs.includes(`Backup (sensitive): ${w.backups()[0]}`));
  assert.deepEqual(w.db.NodeJSONDB, savedBefore, 'adopting never writes node settings');
  w.writes.length = 0;
  w.nodes.a.workerLimits.transcodecpu = 4; // an idempotent re-run needs no node preconditions
  w.io.access = async () => { throw new Error('an idempotent re-run needs no module or cache'); };
  await w.run({ mode: 'adopt', apply: true });
  assert.deepEqual(w.writes, []);
});

test('adopting accepts a library whose transcoding is off instead of its schedule', async () => {
  const w = world({ libraries: TV_LIBRARIES.map(id => tv(id, { processTranscodes: false, schedule: slots(true) })) });
  await w.run({ mode: 'adopt', apply: true });
  assert.equal(w.writes.filter(write => write.collection === 'LibrarySettingsJSONDB').length, 3);
});

test('adopting validates the CRF the Mac will encode with, while a rollback is never blocked by it', async () => {
  const variables = value => TV_LIBRARIES.map((id, i) => (i === 1 ? { ...crf(id), value } : crf(id)));
  for (const value of ['', ' 20', '20 -preset ultrafast', '-1', '51.5', '99', 'abc', '20.', 20, null, undefined]) {
    const w = world({ variables: variables(value) });
    await assert.rejects(w.run({ mode: 'adopt', apply: true }), /TV UU_64_3Ax has an invalid CRF library variable/,
      `CRF ${JSON.stringify(value) ?? 'undefined'}`);
    untouched(w);
  }
  for (const value of ['0', '18', '20.5', '51']) {
    const w = world({ variables: variables(value) });
    await w.run({ mode: 'adopt', apply: true });
    assert.equal(w.writes.length, 4, `CRF ${value}`);
  }
  const w = world({
    libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })), variables: variables('bad'),
    nodes: { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) },
  });
  await w.run({ mode: 'rollback', apply: true });
  assert.equal(w.writes.length, 3, 'an emergency rollback does not depend on the CRF value');
});

test('adopting is refused until nothing can run the old flow or lose the Mac', async () => {
  const idleLinuxCpu = { 'quiet-quail': { workerType: 'transcodecpu', idle: true } };
  const offlineHazard = /Old-Box is not connected, but its saved settings still allow CPU encodes/;
  const down = (limits, overrides) => [saved(linux()), saved(mac()), saved(node('Old-Box', limits, overrides))];
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
    'the Mac running CPU health checks': [{ nodes: { a: linux(), b: mac({}, { healthcheckcpu: 1 }) } }, /CPU encodes only/],
    'the Mac running GPU health checks': [{ nodes: { a: linux(), b: mac({}, { healthcheckgpu: 1 }) } }, /CPU encodes only/],
    'a Mac whose worker limits are unknown': [{ nodes: { a: linux(), b: mac({ workerLimits: undefined }) } }, /CPU encodes only/],
    'a node that is down and could still run CPU encodes': [{ persisted: down({ transcodecpu: 2 }) }, offlineHazard],
    'a paused node that is down with CPU workers': [{ persisted: down({ transcodecpu: 2 }, { nodePaused: true }) }, offlineHazard],
    'a node that is down and lets GPU workers do CPU jobs': [{ persisted: down({}, { allowGpuDoCpu: true }) }, offlineHazard],
    'a node that is down with unknown worker limits': [{ persisted: down({}, { workerLimits: undefined }) }, offlineHazard],
    'Linux CPU workers still allowed': [{ nodes: { a: linux({}, { transcodecpu: 4 }), b: mac() } }, /Set HomeServer transcodecpu to 0/],
    'Linux GPU workers allowed to do CPU jobs': [{ nodes: { a: linux({ allowGpuDoCpu: true }), b: mac() } }, /Set HomeServer transcodecpu to 0/],
    'a running Linux CPU encode': [{ nodes: { a: linux({ workers: { 'busy-bee': { workerType: 'transcodecpu', idle: false } } }), b: mac() } }, /running CPU encode/],
    'no Linux GPU worker to publish': [{ nodes: { a: linux({}, { transcodegpu: 0 }), b: mac() } }, /GPU worker is required/],
    'a paused Linux GPU worker cannot publish': [{ nodes: { a: linux({ nodePaused: true }), b: mac() } }, /GPU worker is required/],
    'a Linux node of unknown pause state cannot publish': [{ nodes: { a: linux({ nodePaused: undefined }), b: mac() } }, /GPU worker is required/],
  };
  for (const [name, [setup, message]] of Object.entries(cases)) {
    const w = world(setup);
    await assert.rejects(w.run({ mode: 'adopt', apply: true }), refusal(message, name));
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
  const stale = [saved(linux({}, { transcodecpu: 4 })), saved(mac({}, { transcodegpu: 1 }))];
  for (const [name, persisted] of Object.entries({
    'a node that is down but cannot encode': down({}),
    'a connected node is judged by its live settings, not by its saved copy': stale,
  })) {
    const ok = world({ persisted });
    await ok.run({ mode: 'adopt', apply: true });
    assert.equal(ok.writes.length, 4, name);
    assert(ok.writes.every(write => write.collection !== 'NodeJSONDB'), name);
  }
});

test('rolling back restores the Linux flow and cache once Linux can encode and the Mac is quiet', async () => {
  const adopted = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }));
  const restored = { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) };
  const refused = {
    'no Linux CPU worker': { a: linux(), b: mac({ nodePaused: true }) },
    'a paused Linux CPU worker': { a: linux({ nodePaused: true }, { transcodecpu: 4 }), b: mac({ nodePaused: true }) },
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

test('holding unchecks only the schedules that are open and needs nothing from the nodes', async () => {
  const w = world({ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 1 ? {} : { schedule: slots(true) })) });
  w.request = async () => { throw new Error('holding must not depend on any node'); };
  const crud = w.crud;
  w.crud = async (collection, mode, extra) => {
    assert(!['NodeJSONDB', 'StagedJSONDB'].includes(collection), `holding must not read ${collection}`);
    return crud(collection, mode, extra);
  };
  const before = structuredClone(w.db);
  await w.run({ mode: 'hold', apply: true });
  assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`),
    [TV_LIBRARIES[0], TV_LIBRARIES[2]].map(id => `LibrarySettingsJSONDB:update:${id}`));
  for (const write of w.writes) assert.deepEqual(Object.keys(write.obj), ['schedule']);
  for (const id of TV_LIBRARIES) {
    assert.deepEqual(w.library(id), { ...before.LibrarySettingsJSONDB.find(row => row._id === id), schedule: slots(false) });
  }
  assert.deepEqual([w.db.FlowsJSONDB, w.db.VariablesJSONDB], [before.FlowsJSONDB, before.VariablesJSONDB]);
  assert.equal(w.backups().length, 1);
  assert.deepEqual(w.calls.filter(call => call[0] === 'access'), [], 'holding needs no module or cache');
  assert(!w.calls.some(call => call[0] === 'mkdir' && call[1] === PRIVATE_ROOT), 'holding creates no private state');
  assert(w.logs.at(-1).startsWith('Verified via API. Flows, caches, worker limits'), w.logs.at(-1));
  assert(w.logs.some(line => line.includes(': uncheck every schedule slot')), 'the preview names the change');
  w.writes.length = 0;
  await w.run({ mode: 'hold', apply: true });
  assert.deepEqual(w.writes, [], 'a second hold changes nothing');
  assert.equal(w.calls.filter(call => call[0] === 'writeFile').length, 1, 'and takes no second backup');
});

test('releasing checks only the held libraries, on nodes that match their flow', async () => {
  const offload = () => TV_LIBRARIES.map((id, i) => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT, ...(i === 1 ? { schedule: slots(true) } : {}) }));
  const w = world({ libraries: offload() });
  const before = structuredClone(w.db.LibrarySettingsJSONDB);
  await w.run({ mode: 'release', apply: true });
  assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`),
    [TV_LIBRARIES[0], TV_LIBRARIES[2]].map(id => `LibrarySettingsJSONDB:update:${id}`));
  for (const id of TV_LIBRARIES) {
    assert.deepEqual(w.library(id), { ...before.find(row => row._id === id), schedule: slots(true) });
  }
  assert.deepEqual(w.calls.filter(call => call[0] === 'access'), [], 'releasing needs no module or cache');
  assert(w.logs.some(line => line.includes(': check every schedule slot')), 'the preview names the change');
  assert(w.logs.at(-1).startsWith('Verified via API. Flows, caches, worker limits'), w.logs.at(-1));
  assert.equal(w.backups().length, 1);
  w.writes.length = 0;
  w.nodes.a.workerLimits.transcodecpu = 4; // nothing left to release, so an idempotent re-run needs no node preconditions
  await w.run({ mode: 'release', apply: true });
  assert.deepEqual(w.writes, []);
  const linuxFlow = world({ nodes: { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) } });
  await linuxFlow.run({ mode: 'release', apply: true });
  assert.equal(linuxFlow.writes.length, 3, 'libraries on the Linux flow release once Linux can encode and the Mac is quiet');
});

test('releasing is refused until the nodes and the libraries agree', async () => {
  const offload = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }));
  const onLinux = () => TV_LIBRARIES.map(id => tv(id));
  const quietMac = mac({ nodePaused: true });
  const cases = {
    'offload flow with Linux CPU workers still allowed': [offload(), { a: linux({}, { transcodecpu: 4 }), b: mac() }, /Set HomeServer transcodecpu to 0/],
    'offload flow with the Mac missing': [offload(), { a: linux() }, /not connected/],
    'offload flow with no Linux GPU worker': [offload(), { a: linux({}, { transcodegpu: 0 }), b: mac() }, /GPU worker is required/],
    'offload flow with the only Linux GPU worker paused': [offload(), { a: linux({ nodePaused: true }), b: mac() }, /GPU worker is required/],
    'offload flow with a running Linux CPU encode': [offload(), { a: linux({ workers: { w: { workerType: 'transcodecpu', idle: false } } }), b: mac() }, /running CPU encode/],
    'Linux flow with no Linux CPU worker': [onLinux(), { a: linux(), b: quietMac }, /Restore a Linux node CPU worker/],
    'Linux flow with the only Linux CPU worker paused': [onLinux(), { a: linux({ nodePaused: true }, { transcodecpu: 4 }), b: quietMac }, /Restore a Linux node CPU worker/],
    'Linux flow with an active Mac': [onLinux(), { a: linux({}, { transcodecpu: 4 }), b: mac() }, /Pause Studio-Native/],
    'one library still on the Linux flow': [offload().map((library, i) => (i === 0 ? tv(library._id) : library)), { a: linux(), b: mac() }, /finish the cutover or rollback/],
    'a library on another flow': [offload().map((library, i) => (i === 0 ? { ...library, flowId: 'zRnXMGq83' } : library)), { a: linux(), b: mac() }, /finish the cutover or rollback/],
    'a library on the offload flow with the Linux cache': [offload().map((library, i) => (i === 0 ? { ...library, cache: SAFE_CACHE } : library)), { a: linux(), b: mac() }, /finish the cutover or rollback/],
    'a library on the Linux flow with the Mac cache': [onLinux().map((library, i) => (i === 0 ? { ...library, cache: CACHE_ROOT } : library)), { a: linux({}, { transcodecpu: 4 }), b: quietMac }, /finish the cutover or rollback/],
  };
  for (const [name, [libraries, nodes, message]] of Object.entries(cases)) {
    const w = world({ libraries, nodes });
    await assert.rejects(w.run({ mode: 'release', apply: true }), message, name);
    untouched(w);
  }
});

test('release reopens all three TV libraries, including one that was already closed before the hold', async () => {
  const w = world({
    libraries: TV_LIBRARIES.map((id, i) => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT, schedule: slots(i !== 1) })),
  });
  await w.run({ mode: 'hold', apply: true });
  assert.deepEqual(w.writes.map(write => write.docID), [TV_LIBRARIES[0], TV_LIBRARIES[2]],
    'a hold leaves the library that was already closed alone');
  w.writes.length = 0;
  await w.run({ mode: 'release', apply: true });
  assert.deepEqual(w.writes.map(write => write.docID), TV_LIBRARIES,
    'a release cannot tell that library from the held ones, so it reopens all three');
  for (const id of TV_LIBRARIES) assert.deepEqual(w.library(id).schedule, slots(true));
});

test('hold and release refuse a schedule they could not restore exactly', async () => {
  const partial = { schedule: slots(false).map((slot, i) => ({ ...slot, checked: i === 0 })) };
  const refused = [['a partial schedule', partial, /partial schedule/], ['no schedule data', { schedule: undefined }, /no schedule data/],
    ['an empty schedule', { schedule: [] }, /no schedule data/]];
  for (const mode of ['hold', 'release']) {
    for (const [name, overrides, message] of refused) {
      const w = world({ libraries: TV_LIBRARIES.map((id, i) => tv(id, i === 2 ? overrides : { schedule: slots(mode === 'release' ? false : true) })) });
      await assert.rejects(w.run({ mode, apply: true }), message, `${mode} with ${name}`);
      untouched(w);
    }
    const w = world({ libraries: TV_LIBRARIES.slice(1).map(id => tv(id)) });
    await assert.rejects(w.run({ mode, apply: true }), /three existing TV libraries/, mode);
    untouched(w);
  }
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
  await assert.rejects(w.run({ mode: 'adopt', apply: true }),
    refusal(/^LibrarySettingsJSONDB \S+: flowId was not stored\. 1 of 4 change\(s\) were applied before this failure\. /, 'a library'));
});

test('a flow that Tdarr stores differently is reported without printing it', async () => {
  const w = world();
  const crud = w.crud;
  w.crud = async (collection, mode, extra) => {
    const result = await crud(collection, mode, extra);
    if (collection === 'FlowsJSONDB' && mode === 'insert') {
      w.db.FlowsJSONDB.find(flow => flow._id === FLOW_ID).flowPlugins.find(plugin => plugin.id === 'notify').name = 'edited';
    }
    return result;
  };
  await assert.rejects(w.run({ mode: 'canary', apply: true }),
    refusal(new RegExp(`^FlowsJSONDB ${FLOW_ID}: flowPlugins was not stored\\. 0 of 3 change\\(s\\) were applied before this failure\\. `), 'a flow'));
});

// Changes the stored state between the first reading (the preview) and the second one (just before writing).
function changeBetweenReadings(w, change) {
  const crud = w.crud;
  let reads = 0;
  w.crud = async (collection, mode, extra) => {
    if (collection === 'FlowsJSONDB' && mode === 'getAll' && ++reads === 2) change();
    return crud(collection, mode, extra);
  };
}
const changed = reason => new RegExp(`^State changed while the plan was being prepared \\(.*${reason}.*\\); nothing was written; retry$`);
const differs = /^State changed while the plan was being prepared; nothing was written; retry$/;

test('nothing is written when the state changes between the preview and the write', async () => {
  const busyCpu = { 'busy-bee': { workerType: 'transcodecpu', idle: false } };
  const cases = {
    'a library opens its schedule': [w => { w.library(TV_LIBRARIES[1]).schedule = slots(true); }, changed('is still processing')],
    'a Linux CPU encode starts': [w => { w.nodes.a.workers = busyCpu; }, changed('still has a running CPU encode')],
    'a Linux CPU worker is switched back on': [w => { w.nodes.a.workerLimits.transcodecpu = 4; }, changed('Set HomeServer transcodecpu to 0')],
    'the Mac disconnects': [w => { delete w.nodes.b; }, changed('Studio-Native is not connected')],
    'the only Linux GPU worker is paused': [w => { w.nodes.a.nodePaused = true; }, changed('GPU worker is required')],
    'a TV file is staged': [w => { w.db.StagedJSONDB.push({ _id: 'row', originalLibraryFile: { DB: TV_LIBRARIES[0] } }); }, changed('staged TV file')],
    'a CRF variable is edited': [w => { w.db.VariablesJSONDB.find(row => row._id === `${TV_LIBRARIES[2]}-crf`).value = 'abc'; }, changed('invalid CRF')],
    'a node that is down is saved with CPU workers': [w => { w.db.NodeJSONDB.push(saved(node('Old-Box', { transcodecpu: 2 }))); }, changed('Old-Box is not connected')],
    'someone else moves a library': [w => Object.assign(w.library(TV_LIBRARIES[0]), { flowId: FLOW_ID, cache: CACHE_ROOT }), differs],
    'someone else installs the flow': [w => { w.db.FlowsJSONDB.push(flowDefinition(NOTIFY, 5)); }, differs],
  };
  for (const [name, [change, message]] of Object.entries(cases)) {
    const w = world();
    changeBetweenReadings(w, () => change(w));
    await assert.rejects(w.run({ mode: 'adopt', apply: true }), refusal(message, name));
    untouched(w);
  }
  const rollbackCases = {
    'the Mac starts an encode': [w => { w.nodes.b.workers = busyCpu; }, changed('still has a running CPU encode')],
    'the Mac is resumed': [w => { w.nodes.b.nodePaused = false; }, changed('Pause Studio-Native')],
    'the only Linux CPU worker is paused': [w => { w.nodes.a.nodePaused = true; }, changed('Restore a Linux node CPU worker')],
    'a TV file is staged': [w => { w.db.StagedJSONDB.push({ _id: 'row', originalLibraryFile: { DB: TV_LIBRARIES[0] } }); }, changed('staged TV file')],
  };
  for (const [name, [change, message]] of Object.entries(rollbackCases)) {
    const w = world({ libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })),
      nodes: { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) } });
    changeBetweenReadings(w, () => change(w));
    await assert.rejects(w.run({ mode: 'rollback', apply: true }), refusal(message, `rollback: ${name}`));
    untouched(w);
  }
  const held = world({ libraries: TV_LIBRARIES.map(id => tv(id, { schedule: slots(true) })) });
  changeBetweenReadings(held, () => { held.library(TV_LIBRARIES[0]).schedule = slots(false); });
  await assert.rejects(held.run({ mode: 'hold', apply: true }), refusal(differs, 'hold'));
  untouched(held);
  const open = world({ libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })) });
  changeBetweenReadings(open, () => { open.nodes.b.workerLimits.transcodegpu = 1; });
  await assert.rejects(open.run({ mode: 'release', apply: true }), refusal(changed('CPU encodes only'), 'release'));
  untouched(open);
  const canaryWorld = world();
  changeBetweenReadings(canaryWorld, () => canaryWorld.db.LibrarySettingsJSONDB.push(canary()));
  await assert.rejects(canaryWorld.run({ mode: 'canary', apply: true }), refusal(differs, 'canary'));
  untouched(canaryWorld);
});

test('a failure part-way through an apply says what was written and what is left, and a re-run finishes', async () => {
  const w = world();
  const crud = w.crud;
  let failing = true;
  w.crud = async (collection, mode, extra) => {
    if (failing && collection === 'LibrarySettingsJSONDB' && mode === 'update' && extra.docID === TV_LIBRARIES[1]) {
      throw new Error('Tdarr cruddb: HTTP 500');
    }
    return crud(collection, mode, extra);
  };
  await assert.rejects(w.run({ mode: 'adopt', apply: true }), error => {
    const [backup] = w.backups();
    assert.match(error.message, /^Tdarr cruddb: HTTP 500\. 2 of 4 change\(s\) were applied before this failure\. /);
    assert.match(error.message, new RegExp(`Applied: flow ${FLOW_ID} \\(x265 pools=9\\); TV ${TV_LIBRARIES[0]}: flow ${FLOW_ID}, cache `));
    assert.match(error.message, new RegExp(`Failed or not applied: TV ${TV_LIBRARIES[1]}: .*; TV ${TV_LIBRARIES[2]}: [^;]*\\. Run the same command again`));
    assert(error.message.endsWith(`the backup is ${backup}`), error.message);
    assert.equal(error.cause.message, 'Tdarr cruddb: HTTP 500');
    return true;
  });
  assert.deepEqual(w.writes.map(write => write.docID), [FLOW_ID, TV_LIBRARIES[0]], 'nothing after the failure was attempted');
  failing = false;
  w.writes.length = 0;
  await w.run({ mode: 'adopt', apply: true });
  assert.deepEqual(w.writes.map(write => write.docID), [TV_LIBRARIES[1], TV_LIBRARIES[2]], 'a re-run only does what is left');
  for (const id of TV_LIBRARIES) assert.deepEqual([w.library(id).flowId, w.library(id).cache], [FLOW_ID, CACHE_ROOT]);
  const failure = world({ libraries: TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT })),
    nodes: { a: linux({}, { transcodecpu: 4 }), b: mac({ nodePaused: true }) } });
  const failingCrud = failure.crud;
  failure.crud = async (collection, mode, extra) => {
    if (collection === 'LibrarySettingsJSONDB' && mode === 'update') throw new Error('Tdarr cruddb: HTTP 500');
    return failingCrud(collection, mode, extra);
  };
  await assert.rejects(failure.run({ mode: 'rollback', apply: true }), /^.*HTTP 500\. 0 of 3 change\(s\) were applied before this failure\. Applied: none\./);
});

test('rolling back while the Mac is offline pauses its saved settings first, so that it returns paused', async () => {
  const adopted = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }));
  const live = { a: linux({}, { transcodecpu: 4 }) };
  const w = world({ libraries: adopted(), nodes: live, persisted: [saved(live.a), saved(mac())] });
  const before = structuredClone(w.db.NodeJSONDB);
  await w.run({ mode: 'rollback' });
  untouched(w);
  assert.equal(w.logs[0], 'Previewing rollback: 4 change(s)');
  assert.equal(w.logs[1], '  update Studio-Native is not connected: pause its saved settings so that it returns paused');
  w.logs.length = 0;
  await w.run({ mode: 'rollback', apply: true });
  assert.deepEqual(w.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`), [
    'NodeJSONDB:update:Studio-Native', ...TV_LIBRARIES.map(id => `LibrarySettingsJSONDB:update:${id}`),
  ], 'the Mac is paused before any library moves back');
  assert.deepEqual(w.writes[0].obj, { nodePaused: true });
  assert.deepEqual(w.db.NodeJSONDB, before.map(doc => (doc._id === MAC ? { ...doc, nodePaused: true } : doc)),
    'only the pause flag of the Mac changes; its limits stay');
  assert.deepEqual(JSON.parse(w.files.get(w.backups()[0])).nodes, before, 'the backup keeps the saved node settings');
  assert(w.logs.at(-1).includes(`${MAC}'s saved pause state was changed`), w.logs.at(-1));
  w.writes.length = 0;
  await w.run({ mode: 'rollback', apply: true });
  assert.deepEqual(w.writes, [], 'once it is paused a second rollback has nothing left to do');

  const pauseOnly = world({ nodes: live, persisted: [saved(live.a), saved(mac())] });
  await pauseOnly.run({ mode: 'rollback', apply: true });
  assert.deepEqual(pauseOnly.writes.map(write => `${write.collection}:${write.mode}:${write.docID}`), ['NodeJSONDB:update:Studio-Native'],
    'libraries that are already on the Linux flow still get the pause');

  const noPause = {
    'its saved settings are already paused': [saved(live.a), saved(mac({ nodePaused: true }))],
    'its saved settings allow no CPU workers': [saved(live.a), saved(mac({}, { transcodecpu: 0 }))],
    'no saved settings exist for it': [saved(live.a)],
    'only another node that is down has saved settings': [saved(live.a), saved(node('Old-Box', { transcodecpu: 2 }))],
  };
  for (const [name, persisted] of Object.entries(noPause)) {
    const quietWorld = world({ libraries: adopted(), nodes: live, persisted });
    await quietWorld.run({ mode: 'rollback', apply: true });
    assert.deepEqual(quietWorld.writes.map(write => write.collection), Array(3).fill('LibrarySettingsJSONDB'), name);
  }
  const crowded = world({ libraries: adopted(), nodes: live,
    persisted: [saved(live.a), saved(node('Old-Box', { transcodecpu: 2 })), saved(mac())] });
  const crowdedBefore = structuredClone(crowded.db.NodeJSONDB);
  await crowded.run({ mode: 'rollback', apply: true });
  assert.deepEqual(crowded.writes.filter(write => write.collection === 'NodeJSONDB').map(write => write.docID), [MAC],
    'only the Mac is paused, never another node that is down');
  assert.deepEqual(crowded.db.NodeJSONDB, crowdedBefore.map(doc => (doc._id === MAC ? { ...doc, nodePaused: true } : doc)));
  const connected = world({ libraries: adopted(), nodes: { ...live, b: mac({ nodePaused: true }) },
    persisted: [saved(live.a), saved(mac())] });
  await connected.run({ mode: 'rollback', apply: true });
  assert.deepEqual(connected.writes.map(write => write.collection), Array(3).fill('LibrarySettingsJSONDB'),
    'a connected Mac is paused by the nodes check, never through its saved copy');

  const unstored = world({ libraries: adopted(), nodes: live, persisted: [saved(live.a), saved(mac())] });
  const crud = unstored.crud;
  unstored.crud = async (collection, mode, extra) => (collection === 'NodeJSONDB' && mode === 'update' ? undefined : crud(collection, mode, extra));
  await assert.rejects(unstored.run({ mode: 'rollback', apply: true }),
    /nodePaused was not stored\. 0 of 4 change\(s\) were applied before this failure/);
  for (const id of TV_LIBRARIES) assert.equal(unstored.library(id).flowId, FLOW_ID, 'no library moves when the pause was not stored');
});

test('a release is refused while a node that is down could still run the wrong jobs', async () => {
  const onLinux = () => TV_LIBRARIES.map(id => tv(id));
  const offload = () => TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }));
  const live = { a: linux({}, { transcodecpu: 4 }) };
  const active = world({ libraries: onLinux(), nodes: live, persisted: [saved(live.a), saved(mac())] });
  await assert.rejects(active.run({ mode: 'release', apply: true }),
    /Studio-Native is not connected and its saved settings are not paused; run --rollback --apply first/);
  untouched(active);
  for (const doc of [mac({ nodePaused: true }), mac({}, { transcodecpu: 0 })]) {
    const w = world({ libraries: onLinux(), nodes: live, persisted: [saved(live.a), saved(doc)] });
    await w.run({ mode: 'release', apply: true });
    assert.equal(w.writes.length, 3, 'a Mac that returns paused does not hold the libraries back');
  }
  const hazard = world({ libraries: offload(), persisted: [saved(linux()), saved(mac()), saved(node('Old-Box', { transcodecpu: 2 }))] });
  await assert.rejects(hazard.run({ mode: 'release', apply: true }), /Old-Box is not connected, but its saved settings still allow CPU encodes/);
  untouched(hazard);
});

test('a node list that cannot be read stops adopt and rollback before anything is written', async () => {
  for (const unreadable of [undefined, null, {}]) {
    for (const [mode, libraries] of [['adopt', undefined], ['rollback', TV_LIBRARIES.map(id => tv(id, { flowId: FLOW_ID, cache: CACHE_ROOT }))]]) {
      const w = world({ libraries, nodes: { a: linux({}, { transcodecpu: mode === 'rollback' ? 4 : 0 }), b: mac({ nodePaused: mode === 'rollback' }) } });
      const crud = w.crud;
      w.crud = async (collection, action, extra) => (collection === 'NodeJSONDB' ? unreadable : crud(collection, action, extra));
      await assert.rejects(w.run({ mode, apply: true }), /saved node settings could not be read/, `${mode}: ${JSON.stringify(unreadable)}`);
      untouched(w);
    }
  }
});
