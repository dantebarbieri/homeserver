#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { connect, ROOT, libraryDefinition: baseLibrary } = require('./install-flow.cjs');
const { PRIVATE_ROOT, CACHE_ROOT } = require('./hevc-offload-v1.cjs');

const FLOW_ID = 'homeserver-hevc-offload-v1';
const LEGACY_FLOW = 'homeserver-hevc-studio-v1';
const SAFE_FLOW = 'homeserver-hevc-cpu-v1';
const SAFE_CACHE = '/temp';
const LIBRARY_ID = 'homeserver-hevc-studio-canary-v1';
const CANARY_FOLDER = '/data/media/tdarr-studio-canary';
const MAC_ROOT = '/var/lib/studio-worker/tdarr/Custom';
const TV_LIBRARIES = ['Io-wVbVRh', 'UU_64_3Ax', 'GHlz7HL1P'];
const DEFAULT_POOLS = 9;
const DEFAULT_MAC_NODE = 'Studio-Native';
const DISABLED = ['processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching',
  'useFsEvents', 'scheduledScanFindNew', 'scanOnStart'];
const USAGE = [
  'Usage: node install-offload-flow.cjs [--pools N] [--apply]                       (flow + disabled canary)',
  '       node install-offload-flow.cjs --adopt [--pools N] [--mac-node NAME] [--apply]  (TV libraries -> Mac)',
  '       node install-offload-flow.cjs --rollback [--mac-node NAME] [--apply]           (TV libraries -> Linux)',
].join('\n');

// The same flow runs on both nodes: the platform picks which copy of the module a step loads.
const step = fn => `module.exports = async args => require(process.platform === 'darwin' ? '${MAC_ROOT}/hevc-offload-v1.cjs' : '${ROOT}/hevc-offload-v1.cjs').${fn}(args);`;

function assertPools(pools) {
  assert(Number.isInteger(pools) && pools >= 1 && pools <= 64, 'pools must be an integer from 1 to 64');
}

function flowDefinition(notify, pools = DEFAULT_POOLS) {
  assertPools(pools);
  const nodes = [];
  const plugin = (id, name, pluginName, inputsDB = {}) => {
    nodes.push({
      id, name, pluginName, inputsDB, sourceRepo: 'Community', version: '1.0.0', fpEnabled: true,
      position: { x: 0, y: 120 * nodes.length },
    });
  };
  plugin('input', 'Input file', 'inputFile');
  plugin('cpu', 'CPU workers only (the Mac Studio encodes)', 'tagsWorkerType',
    { requiredWorkerType: 'CPU', requiredNodeTags: '' });
  plugin('prepare', 'Mac: eligible SDR source and identity', 'customFunction', { code: step('prepare') });
  plugin('begin', 'Begin command', 'ffmpegCommandStart');
  plugin('encode', 'Software HEVC slow; preserve CRF', 'ffmpegCommandSetVideoEncoder', {
    outputCodec: 'hevc', hardwareEncoding: 'false', forceEncoding: 'false',
    ffmpegPreset: 'slow', ffmpegQuality: '{{{args.userVariables.library.crf}}}',
  });
  plugin('threads', 'Bound x265 thread pool', 'ffmpegCommandCustomArguments',
    { outputArguments: `-x265-params pools=${pools}` });
  plugin('container', 'Matroska without dropping streams', 'ffmpegCommandSetContainer',
    { container: 'mkv', forceConform: 'false' });
  plugin('execute', 'Encode', 'ffmpegCommandExecute');
  plugin('finish', 'Mac: check the result and hand it over', 'customFunction', { code: step('finish') });
  plugin('gpu', 'GPU workers only (the Linux server publishes)', 'tagsWorkerType',
    { requiredWorkerType: 'GPU', requiredNodeTags: '' });
  plugin('commit', 'Linux: private copy, strict decode and safe publication', 'customFunction',
    { code: step('commit') });
  nodes.push({ ...structuredClone(notify), id: 'notify', position: { x: 0, y: 120 * nodes.length } });
  return {
    _id: FLOW_ID, name: 'Homeserver - SDR HEVC encoded on the Mac Studio', priority: 0, isUiLocked: true,
    flowPlugins: nodes,
    flowEdges: nodes.slice(0, -1).map((node, i) => ({
      source: node.id, sourceHandle: '1', target: nodes[i + 1].id, targetHandle: null,
      id: `${node.id}-to-${nodes[i + 1].id}`, animated: true, type: 'smoothstep',
    })),
  };
}

function poolsOf(flow) {
  const args = flow?.flowPlugins?.find(plugin => plugin.id === 'threads')?.inputsDB?.outputArguments;
  const match = /^-x265-params pools=(\d{1,2})$/.exec(args ?? '');
  assert(match, 'Existing offload flow has an unrecognised thread pool setting; deploy a new version');
  return Number(match[1]);
}

function libraryTemplate(libraries) {
  const template = libraries.find(l => l._id === TV_LIBRARIES[0]);
  assert(template && Array.isArray(template.schedule) && template.decisionMaker
    && typeof template.decisionMaker === 'object', 'Expected the existing TV library to use as a template');
  return template;
}

function libraryDefinition(defaults) {
  return {
    ...baseLibrary(defaults), _id: LIBRARY_ID, name: 'Studio native HEVC - isolated manual canary',
    folder: CANARY_FOLDER, cache: CACHE_ROOT, flowId: FLOW_ID,
    foldersToIgnore: '', foldersToIgnoreCaseInsensitive: false,
    holdNewFiles: true, holdFor: 180, holdForDisplayUnit: 'minutes',
    filterCodecsSkip: 'hevc,av1,vp9',
    // A template may carry a paused schedule; the canary must always be allowed to run.
    schedule: defaults.schedule.map(slot => ({ ...slot, checked: true })),
  };
}

const activeWorkers = (node, type) => Object.values(node.workers || {})
  .filter(worker => worker.workerType === type && !worker.idle);

// A library nothing can pick files from: transcoding is off, or no schedule slot is checked.
const quiescent = library => library.processTranscodes === false
  || (Array.isArray(library.schedule) && !library.schedule.some(slot => slot.checked));

function checkNodes(direction, nodes, macName) {
  const all = Object.values(nodes || {});
  const macs = all.filter(node => node.nodeName === macName);
  assert(macs.length <= 1, `${macName} is connected more than once`);
  const [mac] = macs;
  const others = all.filter(node => node !== mac);
  if (direction === 'adopt') {
    assert(mac, `${macName} is not connected`);
    assert(mac.workerLimits?.transcodecpu >= 1 && mac.workerLimits?.transcodegpu === 0,
      `${macName} must run CPU encodes only (transcodecpu 1 or more, transcodegpu 0)`);
    for (const node of others) {
      assert(node.workerLimits?.transcodecpu === 0 && !node.allowGpuDoCpu,
        `Set ${node.nodeName} transcodecpu to 0 and disable GPU workers doing CPU jobs first`);
      assert.equal(activeWorkers(node, 'transcodecpu').length, 0,
        `${node.nodeName} still has a running CPU encode; wait for it to finish`);
    }
    assert(others.some(node => node.workerLimits?.transcodegpu >= 1),
      'A Linux node with a GPU worker is required to publish results');
    return;
  }
  assert(others.some(node => node.workerLimits?.transcodecpu >= 1),
    'Restore a Linux node CPU worker limit (transcodecpu) before rolling back');
  if (mac) {
    assert(mac.nodePaused === true || mac.workerLimits?.transcodecpu === 0,
      `Pause ${macName} (or set its transcodecpu to 0) before rolling back`);
    assert.equal(activeWorkers(mac, 'transcodecpu').length, 0,
      `${macName} still has a running CPU encode; wait for it to finish`);
  }
}

// Returns the TV libraries that still need to move, after proving that moving them is safe.
function cutoverPlan({ direction, libraries, variables, staged }) {
  const from = direction === 'adopt'
    ? { flowId: SAFE_FLOW, cache: SAFE_CACHE } : { flowId: FLOW_ID, cache: CACHE_ROOT };
  const to = direction === 'adopt'
    ? { flowId: FLOW_ID, cache: CACHE_ROOT } : { flowId: SAFE_FLOW, cache: SAFE_CACHE };
  const targets = TV_LIBRARIES.map(id => libraries.find(l => l._id === id));
  assert(targets.every(Boolean), 'Expected exactly the three existing TV libraries');
  const pending = [];
  for (const library of targets) {
    const matches = state => library.flowId === state.flowId && library.cache === state.cache;
    if (matches(to)) continue;
    assert(matches(from), `${library.name} uses an unexpected flow or cache (${library.flowId}, ${library.cache}); `
      + `expected ${from.flowId} with ${from.cache}`);
    const quiet = quiescent(library);
    assert(quiet, `${library.name} is still processing: turn off transcoding or uncheck its whole schedule first`);
    const crf = variables.filter(v => v.type === `library:${library._id}` && v.key === 'crf');
    assert.equal(crf.length, 1, `${library.name} needs exactly one CRF library variable`);
    pending.push(library);
  }
  if (pending.length) {
    const rows = staged.filter(row => TV_LIBRARIES.includes(row.originalLibraryFile?.DB));
    assert.equal(rows.length, 0, `${rows.length} staged TV file(s) carry the old flow; let them finish or reset them first`);
  }
  return { pending, to };
}

function parseArgs(argv) {
  const options = { mode: 'canary', apply: false, macNode: DEFAULT_MAC_NODE };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--apply') options.apply = true;
    else if (arg === '--adopt' || arg === '--rollback') {
      assert.equal(options.mode, 'canary', 'Use only one of --adopt and --rollback');
      options.mode = arg.slice(2);
    } else if (arg === '--pools') options.pools = Number(argv[++i]);
    else if (arg === '--mac-node') options.macNode = argv[++i];
    else throw new Error(USAGE);
  }
  if (options.pools !== undefined) assertPools(options.pools);
  assert(options.macNode && !options.macNode.startsWith('--'), '--mac-node needs a node name');
  assert(!(options.mode === 'rollback' && options.pools !== undefined), '--pools does not apply to --rollback');
  return options;
}

async function install({ crud, request, options = {}, defaults, log = console.log, io = fs }) {
  const { mode = 'canary', apply = false, macNode = DEFAULT_MAC_NODE } = options;
  assert(['canary', 'adopt', 'rollback'].includes(mode), `Unknown mode ${mode}`);
  const [flows, libraries, variables] = await Promise.all([
    crud('FlowsJSONDB', 'getAll'), crud('LibrarySettingsJSONDB', 'getAll'), crud('VariablesJSONDB', 'getAll'),
  ]);
  const plan = [];
  const put = (collection, action, docID, obj, note) => plan.push({ collection, action, docID, obj, note });

  if (mode === 'rollback') assert(flows.some(f => f._id === SAFE_FLOW), `Flow ${SAFE_FLOW} is required for a rollback`);
  else {
    const existing = flows.find(f => f._id === FLOW_ID);
    const notify = (existing ?? flows.find(f => f._id === SAFE_FLOW))?.flowPlugins
      ?.find(plugin => plugin.pluginName === 'notifyRadarrOrSonarr');
    assert(notify, 'Existing safe v1 Sonarr notification configuration is required');
    const currentPools = existing ? poolsOf(existing) : undefined;
    if (existing) {
      const current = flowDefinition(notify, currentPools);
      for (const key of Object.keys(current)) {
        assert.deepEqual(existing[key], current[key], 'Existing versioned flow differs; deploy a new version');
      }
    }
    const pools = options.pools ?? currentPools ?? DEFAULT_POOLS;
    if (!existing || pools !== currentPools) {
      put('FlowsJSONDB', existing ? 'update' : 'insert', FLOW_ID, flowDefinition(notify, pools),
        `flow ${FLOW_ID} (x265 pools=${pools})`);
    }
  }

  if (mode === 'canary') {
    const existing = libraries.find(l => l._id === LIBRARY_ID);
    if (!existing) {
      put('LibrarySettingsJSONDB', 'insert', LIBRARY_ID, libraryDefinition(defaults || libraryTemplate(libraries)),
        'new disabled canary library');
    } else {
      assert(existing.folder === CANARY_FOLDER && existing.cache === CACHE_ROOT
        && [LEGACY_FLOW, FLOW_ID].includes(existing.flowId), 'Canary library ID collision');
      if (existing.flowId !== FLOW_ID) {
        for (const key of DISABLED) {
          assert.equal(existing[key], false, 'Canary already enabled; installer will not repoint an active rollout');
        }
        put('LibrarySettingsJSONDB', 'update', LIBRARY_ID, { flowId: FLOW_ID }, `canary flow -> ${FLOW_ID}`);
      }
    }
    const crf = variables.filter(v => v.type === `library:${LIBRARY_ID}` && v.key === 'crf');
    assert(crf.length <= 1, 'Duplicate canary CRF variables');
    if (crf.length) assert.equal(crf[0].value, '20', 'Canary CRF is not 20');
    else {
      put('VariablesJSONDB', 'insert', `${LIBRARY_ID}-crf`, {
        _id: `${LIBRARY_ID}-crf`, key: 'crf', value: '20', type: `library:${LIBRARY_ID}`, date: Date.now(),
      }, 'canary CRF 20');
    }
  } else {
    const [staged, nodes] = await Promise.all([
      crud('StagedJSONDB', 'getAll'), request('get-nodes', undefined, 'GET'),
    ]);
    const { pending, to } = cutoverPlan({ direction: mode, libraries, variables, staged });
    if (pending.length) checkNodes(mode, nodes, macNode);
    for (const library of pending) {
      put('LibrarySettingsJSONDB', 'update', library._id, to, `${library.name}: flow ${to.flowId}, cache ${to.cache}`);
    }
  }

  log(`${apply ? 'Applying' : 'Previewing'} ${mode}: ${plan.length ? `${plan.length} change(s)` : 'nothing to change'}`);
  for (const item of plan) log(`  ${item.action} ${item.note}`);
  if (!apply || !plan.length) return plan;

  if (mode !== 'rollback') {
    for (const file of ['hevc-offload-v1.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs']) await io.access(`${ROOT}/${file}`);
    await io.access(CACHE_ROOT); // Provisioned separately: never create or export a broader cache here.
  }
  await io.mkdir(`${ROOT}/backups`, { recursive: true, mode: 0o700 });
  await io.writeFile(`${ROOT}/backups/offload-flow-${Date.now()}.json`,
    JSON.stringify({ flows, libraries, variables }, null, 2), { flag: 'wx', mode: 0o600 });
  if (mode !== 'rollback') await io.mkdir(PRIVATE_ROOT, { recursive: true, mode: 0o700 });
  for (const { collection, action, docID, obj } of plan) {
    await crud(collection, action, { docID, obj });
    const stored = await crud(collection, 'getById', { docID });
    for (const key of Object.keys(obj)) assert.deepEqual(stored[key], obj[key], `${collection} ${docID}: ${key} was not stored`);
  }
  log('Verified via API. Library schedules, worker limits and the Mac node are unchanged.');
  return plan;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const { crud, request } = await connect();
  await install({ crud, request, options });
}

module.exports = {
  flowDefinition, libraryDefinition, libraryTemplate, poolsOf, cutoverPlan, checkNodes, parseArgs, install,
  activeWorkers, quiescent,
  FLOW_ID, LEGACY_FLOW, SAFE_FLOW, SAFE_CACHE, LIBRARY_ID, CANARY_FOLDER, MAC_ROOT, TV_LIBRARIES, DEFAULT_POOLS,
  DEFAULT_MAC_NODE,
};
if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
