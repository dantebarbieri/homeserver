#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { isDeepStrictEqual } = require('node:util');
const { connect, ROOT, libraryDefinition: baseLibrary } = require('./install-flow.cjs');
const { PRIVATE_ROOT, CACHE_ROOT, crf: parseCrf } = require('./hevc-offload-v1.cjs');

// assert.equal and assert.deepEqual append the compared values (a diff of whole objects) to a custom message, and a
// flow holds the Sonarr API key: failures must report the message and nothing else.
function assertSame(actual, expected, message) {
  assert(isDeepStrictEqual(actual, expected), message);
}

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
  '       node install-offload-flow.cjs --hold | --release [--mac-node NAME] [--apply]    (TV schedules off / on)',
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

// The Linux leg publishes what the Mac encoded, so a finished encode needs an unpaused node with a GPU worker, and a
// rollback to the Linux flow needs an unpaused node with a CPU worker. Both tests are strict: a node whose state
// is unknown does not count. quiet() is the opposite way round: anything but a clearly idle node counts as active.
const publisher = node => node.nodePaused === false && node.workerLimits?.transcodegpu >= 1;
const encoder = node => node.nodePaused === false && node.workerLimits?.transcodecpu >= 1;
const quiet = node => node.nodePaused === true || node.workerLimits?.transcodecpu === 0;

const validCrf = value => {
  try { parseCrf(value); return true; } catch { return false; }
};

// Saved node documents are identified by _id (the node name) and carry no nodeName field. A node that is not
// connected cannot be inspected or paused through the API, but it returns with its saved settings.
const savedName = doc => doc.nodeName ?? doc._id;

function offlineNodes(saved, connected) {
  assert(Array.isArray(saved), 'The saved node settings could not be read');
  const names = new Set(Object.values(connected || {}).map(node => node.nodeName));
  return saved.filter(doc => !names.has(savedName(doc)));
}

// Rolling back while the Mac is offline cannot pause it, so its saved settings are paused and it returns quiet.
// Whether Tdarr restores the saved or the launch-time pause state is unverified: this is a second guard next to
// startPaused in the Mac's start script, not the only one.
function offlineMacPause(nodes, saved, macName) {
  const doc = offlineNodes(saved, nodes).find(candidate => savedName(candidate) === macName);
  return doc && !quiet(doc) ? doc : undefined;
}

function checkNodes(direction, nodes, macName, saved) {
  const all = Object.values(nodes || {});
  const macs = all.filter(node => node.nodeName === macName);
  assert(macs.length <= 1, `${macName} is connected more than once`);
  const [mac] = macs;
  const others = all.filter(node => node !== mac);
  if (direction === 'adopt') {
    assert(mac, `${macName} is not connected`);
    const limits = mac.workerLimits;
    assert(limits?.transcodecpu >= 1 && limits.transcodegpu === 0 && limits.healthcheckcpu === 0
      && limits.healthcheckgpu === 0,
      `${macName} must run CPU encodes only (transcodecpu 1 or more; transcodegpu and both health check limits 0)`);
    for (const node of others) {
      assert(node.workerLimits?.transcodecpu === 0 && !node.allowGpuDoCpu,
        `Set ${node.nodeName} transcodecpu to 0 and disable GPU workers doing CPU jobs first`);
      assertSame(activeWorkers(node, 'transcodecpu').length, 0,
        `${node.nodeName} still has a running CPU encode; wait for it to finish`);
    }
    // A node that is down returns with its saved settings and would fail every file the Mac flow offers it.
    for (const doc of offlineNodes(saved, nodes)) {
      assert(doc.workerLimits?.transcodecpu === 0 && !doc.allowGpuDoCpu,
        `${savedName(doc)} is not connected, but its saved settings still allow CPU encodes; connect it and set `
        + 'transcodecpu to 0 with GPU workers doing CPU jobs disabled, or remove it in Tdarr, first');
    }
    assert(others.some(publisher),
      'A GPU worker is required to publish results: an unpaused Linux node with transcodegpu 1 or more');
    return;
  }
  assert(others.some(encoder),
    'Restore a Linux node CPU worker (an unpaused node with transcodecpu 1 or more) before rolling back');
  if (mac) {
    assert(quiet(mac), `Pause ${macName} (or set its transcodecpu to 0) before rolling back`);
    assertSame(activeWorkers(mac, 'transcodecpu').length, 0,
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
    assertSame(crf.length, 1, `${library.name} needs exactly one CRF library variable`);
    // Only an adoption feeds the value to x265; a rollback must never be blocked by it.
    if (direction === 'adopt') {
      assert(validCrf(crf[0].value),
        `${library.name} has an invalid CRF library variable (${JSON.stringify(crf[0].value)}); expected a number from 0 to 51`);
    }
    pending.push(library);
  }
  if (pending.length) {
    const rows = staged.filter(row => TV_LIBRARIES.includes(row.originalLibraryFile?.DB));
    assertSame(rows.length, 0, `${rows.length} staged TV file(s) carry the old flow; let them finish or reset them first`);
  }
  return { pending, to };
}

// Hold unchecks every schedule slot of the TV libraries so nothing new starts (running jobs finish); release
// checks every slot again. The three libraries are one group and only all-or-nothing schedules are toggled, so a
// release reopens every held library, including one that was already closed before the hold. A release is only
// allowed once the nodes match the flow the libraries use.
function schedulePlan({ mode, libraries, nodes, saved, macName }) {
  const hold = mode === 'hold';
  const targets = TV_LIBRARIES.map(id => libraries.find(l => l._id === id));
  assert(targets.every(Boolean), 'Expected exactly the three existing TV libraries');
  const filled = library => Array.isArray(library.schedule) && library.schedule.length > 0;
  const on = library => filled(library) && library.schedule.every(slot => slot.checked);
  const off = library => filled(library) && library.schedule.every(slot => !slot.checked);
  for (const library of targets) {
    assert(filled(library), `${library.name} has no schedule data`);
    assert(on(library) || off(library),
      `${library.name} has a partial schedule; --hold and --release only toggle an all-or-nothing schedule`);
  }
  const pending = targets.filter(library => (hold ? on(library) : off(library)));
  if (!hold && pending.length) {
    const uses = (library, flowId, cache) => library.flowId === flowId && library.cache === cache;
    const direction = targets.every(library => uses(library, FLOW_ID, CACHE_ROOT)) ? 'adopt'
      : targets.every(library => uses(library, SAFE_FLOW, SAFE_CACHE)) ? 'rollback' : undefined;
    assert(direction, 'The TV libraries are not all on the offload flow or all on the Linux flow; '
      + 'finish the cutover or rollback before releasing them');
    checkNodes(direction, nodes, macName, saved);
    // --rollback pauses an offline Mac's saved settings; the libraries must not reopen before that has happened.
    assert(direction === 'adopt' || !offlineMacPause(nodes, saved, macName),
      `${macName} is not connected and its saved settings are not paused; run --rollback --apply first`);
  }
  return pending.map(library => [library, library.schedule.map(slot => ({ ...slot, checked: !hold }))]);
}

function parseArgs(argv) {
  const options = { mode: 'canary', apply: false, macNode: DEFAULT_MAC_NODE };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--apply') options.apply = true;
    else if (['--adopt', '--rollback', '--hold', '--release'].includes(arg)) {
      assertSame(options.mode, 'canary', 'Use only one of --adopt, --rollback, --hold and --release');
      options.mode = arg.slice(2);
    } else if (arg === '--pools') options.pools = Number(argv[++i]);
    else if (arg === '--mac-node') options.macNode = argv[++i];
    else throw new Error(USAGE);
  }
  if (options.pools !== undefined) assertPools(options.pools);
  assert(options.macNode && !options.macNode.startsWith('--'), '--mac-node needs a node name');
  assert(!(['rollback', 'hold', 'release'].includes(options.mode) && options.pools !== undefined),
    `--pools does not apply to --${options.mode}`);
  return options;
}

// Everything a plan depends on is read in one place, so it can be read a second time just before anything is written.
async function gather({ crud, request, mode }) {
  const cutover = mode === 'adopt' || mode === 'rollback';
  const nodeState = cutover || mode === 'release';
  const [flows, libraries, variables, staged, nodes, saved] = await Promise.all([
    crud('FlowsJSONDB', 'getAll'), crud('LibrarySettingsJSONDB', 'getAll'), crud('VariablesJSONDB', 'getAll'),
    cutover ? crud('StagedJSONDB', 'getAll') : undefined,
    nodeState ? request('get-nodes', undefined, 'GET') : undefined,
    nodeState ? crud('NodeJSONDB', 'getAll') : undefined,
  ]);
  return { flows, libraries, variables, staged, nodes, saved };
}

// A pure function of the state that was read, so a second reading can be compared with the first.
function buildPlan({ mode, state, macNode, pools: requestedPools, defaults, now }) {
  const { flows, libraries, variables, staged, nodes, saved } = state;
  const plan = [];
  const put = (collection, action, docID, obj, note) => plan.push({ collection, action, docID, obj, note });
  const schedules = mode === 'hold' || mode === 'release';

  if (schedules) {
    for (const [library, schedule] of schedulePlan({ mode, libraries, nodes, saved, macName: macNode })) {
      put('LibrarySettingsJSONDB', 'update', library._id, { schedule },
        `${library.name}: ${mode === 'hold' ? 'uncheck' : 'check'} every schedule slot`);
    }
  } else if (mode === 'rollback') assert(flows.some(f => f._id === SAFE_FLOW), `Flow ${SAFE_FLOW} is required for a rollback`);
  else {
    const existing = flows.find(f => f._id === FLOW_ID);
    const notify = (existing ?? flows.find(f => f._id === SAFE_FLOW))?.flowPlugins
      ?.find(plugin => plugin.pluginName === 'notifyRadarrOrSonarr');
    assert(notify, 'Existing safe v1 Sonarr notification configuration is required');
    const currentPools = existing ? poolsOf(existing) : undefined;
    if (existing) {
      const current = flowDefinition(notify, currentPools);
      for (const key of Object.keys(current)) {
        assertSame(existing[key], current[key], 'Existing versioned flow differs; deploy a new version');
      }
    }
    const pools = requestedPools ?? currentPools ?? DEFAULT_POOLS;
    if (!existing || pools !== currentPools) {
      put('FlowsJSONDB', existing ? 'update' : 'insert', FLOW_ID, flowDefinition(notify, pools),
        `flow ${FLOW_ID} (x265 pools=${pools})`);
    }
  }

  if (mode === 'canary') {
    const existing = libraries.find(l => l._id === LIBRARY_ID);
    if (!existing) {
      put('LibrarySettingsJSONDB', 'insert', LIBRARY_ID,
        { ...libraryDefinition(defaults || libraryTemplate(libraries)), createdAt: now }, 'new disabled canary library');
    } else {
      assert(existing.folder === CANARY_FOLDER && existing.cache === CACHE_ROOT
        && [LEGACY_FLOW, FLOW_ID].includes(existing.flowId), 'Canary library ID collision');
      if (existing.flowId !== FLOW_ID) {
        for (const key of DISABLED) {
          assertSame(existing[key], false, 'Canary already enabled; installer will not repoint an active rollout');
        }
        put('LibrarySettingsJSONDB', 'update', LIBRARY_ID, { flowId: FLOW_ID }, `canary flow -> ${FLOW_ID}`);
      }
    }
    const crf = variables.filter(v => v.type === `library:${LIBRARY_ID}` && v.key === 'crf');
    assert(crf.length <= 1, 'Duplicate canary CRF variables');
    if (crf.length) assertSame(crf[0].value, '20', 'Canary CRF is not 20');
    else {
      put('VariablesJSONDB', 'insert', `${LIBRARY_ID}-crf`, {
        _id: `${LIBRARY_ID}-crf`, key: 'crf', value: '20', type: `library:${LIBRARY_ID}`, date: now,
      }, 'canary CRF 20');
    }
  } else if (!schedules) {
    const { pending, to } = cutoverPlan({ direction: mode, libraries, variables, staged });
    if (pending.length) checkNodes(mode, nodes, macNode, saved);
    // A Mac that is down cannot be paused through the API; its saved settings are what it comes back with.
    const offlineMac = mode === 'rollback' ? offlineMacPause(nodes, saved, macNode) : undefined;
    if (offlineMac) {
      put('NodeJSONDB', 'update', offlineMac._id, { nodePaused: true },
        `${macNode} is not connected: pause its saved settings so that it returns paused`);
    }
    for (const library of pending) {
      put('LibrarySettingsJSONDB', 'update', library._id, to, `${library.name}: flow ${to.flowId}, cache ${to.cache}`);
    }
  }
  return plan;
}

async function install({ crud, request, options = {}, defaults, log = console.log, io = fs }) {
  const { mode = 'canary', apply = false, macNode = DEFAULT_MAC_NODE, pools } = options;
  assert(['canary', 'adopt', 'rollback', 'hold', 'release'].includes(mode), `Unknown mode ${mode}`);
  const needsModules = mode === 'canary' || mode === 'adopt';
  const now = Date.now();
  const plan = buildPlan({ mode, state: await gather({ crud, request, mode }), macNode, pools, defaults, now });

  log(`${apply ? 'Applying' : 'Previewing'} ${mode}: ${plan.length ? `${plan.length} change(s)` : 'nothing to change'}`);
  for (const item of plan) log(`  ${item.action} ${item.note}`);
  if (needsModules && plan.length) {
    for (const file of ['hevc-offload-v1.cjs', 'hevc-safe-v1.cjs', 'dv5-sidecar.cjs']) await io.access(`${ROOT}/${file}`);
    await io.access(CACHE_ROOT); // Provisioned separately: never create or export a broader cache here.
  }
  if (!apply || !plan.length) return plan;

  // Nothing is written on the strength of an old reading: read again, plan again and require the same plan.
  const latest = await gather({ crud, request, mode });
  let again;
  try {
    again = buildPlan({ mode, state: latest, macNode, pools, defaults, now });
  } catch (error) {
    throw new Error(`State changed while the plan was being prepared (${error.message}); nothing was written; retry`,
      { cause: error });
  }
  assertSame(again, plan, 'State changed while the plan was being prepared; nothing was written; retry');

  const backup = `${ROOT}/backups/offload-flow-${Date.now()}.json`;
  await io.mkdir(`${ROOT}/backups`, { recursive: true, mode: 0o700 });
  await io.writeFile(backup, JSON.stringify({
    flows: latest.flows, libraries: latest.libraries, variables: latest.variables,
    ...(latest.saved ? { nodes: latest.saved } : {}),
  }, null, 2), { flag: 'wx', mode: 0o600 });
  log(`Backup (sensitive): ${backup}`);
  if (needsModules) await io.mkdir(PRIVATE_ROOT, { recursive: true, mode: 0o700 });
  const done = [];
  for (const item of plan) {
    try {
      await crud(item.collection, item.action, { docID: item.docID, obj: item.obj });
      const stored = await crud(item.collection, 'getById', { docID: item.docID });
      for (const key of Object.keys(item.obj)) {
        assertSame(stored[key], item.obj[key], `${item.collection} ${item.docID}: ${key} was not stored`);
      }
      done.push(item);
    } catch (error) {
      // Every command only plans what is still missing, so running it again finishes the rest.
      const notes = items => (items.length ? items.map(item => item.note).join('; ') : 'none');
      throw new Error(`${error.message}. ${done.length} of ${plan.length} change(s) were applied before this failure. `
        + `Applied: ${notes(done)}. Failed or not applied: ${notes(plan.filter(item => !done.includes(item)))}. `
        + `Run the same command again to finish what is left; the backup is ${backup}`, { cause: error });
    }
  }
  if (mode === 'hold' || mode === 'release') log('Verified via API. Flows, caches, worker limits and the Mac node are unchanged.');
  else if (plan.some(item => item.collection === 'NodeJSONDB')) {
    log(`Verified via API. Library schedules and worker limits are unchanged; ${macNode}'s saved pause state was `
      + 'changed. Check that it is still paused once it reconnects.');
  } else log('Verified via API. Library schedules, worker limits and the Mac node are unchanged.');
  return plan;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const { crud, request } = await connect();
  await install({ crud, request, options });
}

module.exports = {
  flowDefinition, libraryDefinition, libraryTemplate, poolsOf, cutoverPlan, checkNodes, parseArgs, install,
  activeWorkers, quiescent, publisher, encoder, quiet, assertSame,
  FLOW_ID, LEGACY_FLOW, SAFE_FLOW, SAFE_CACHE, LIBRARY_ID, CANARY_FOLDER, MAC_ROOT, TV_LIBRARIES, DEFAULT_POOLS,
  DEFAULT_MAC_NODE,
};
if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
