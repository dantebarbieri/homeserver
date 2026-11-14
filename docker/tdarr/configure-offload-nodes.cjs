#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { connect, ROOT } = require('./install-flow.cjs');
const { CACHE_ROOT } = require('./hevc-offload-v1.cjs');
const { activeWorkers, quiescent, FLOW_ID, TV_LIBRARIES, DEFAULT_MAC_NODE } = require('./install-offload-flow.cjs');

const WORKER_TYPES = ['healthcheckcpu', 'healthcheckgpu', 'transcodecpu', 'transcodegpu'];
// Settings this tool never changes; they must read back exactly as they were.
const KEPT = ['nodeTags', 'allowGpuDoCpu', 'librariesToNotProcess', 'gpuSelect'];
const USAGE = 'Usage: node configure-offload-nodes.cjs --node-name <name> [--set <type>=<0-32>]... '
  + `[--pause | --resume] [--mac-node <name>] [--apply]\n  types: ${WORKER_TYPES.join(', ')}`;

function parseArgs(argv) {
  const options = { apply: false, sets: {}, macNode: DEFAULT_MAC_NODE };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--apply') options.apply = true;
    else if (arg === '--node-name') options.nodeName = argv[++i];
    else if (arg === '--mac-node') options.macNode = argv[++i];
    else if (arg === '--pause' || arg === '--resume') {
      assert.equal(options.pause, undefined, 'Use only one of --pause and --resume');
      options.pause = arg === '--pause';
    } else if (arg === '--set') {
      const [type, value, ...extra] = String(argv[++i]).split('=');
      assert(WORKER_TYPES.includes(type) && extra.length === 0 && /^\d{1,2}$/.test(value) && Number(value) <= 32,
        `--set needs <type>=<0-32>; ${USAGE}`);
      assert(!(type in options.sets), `${type} was set twice`);
      options.sets[type] = Number(value);
    } else throw new Error(USAGE);
  }
  assert(options.nodeName && !options.nodeName.startsWith('--'), '--node-name needs a node name');
  assert(options.macNode && !options.macNode.startsWith('--'), '--mac-node needs a node name');
  assert(Object.keys(options.sets).length || options.pause !== undefined, `Nothing to change; ${USAGE}`);
  return options;
}

// Without Tdarr Pro no node setting keeps a worker away from a library, so the only protection for
// the Mac is that it never becomes active while a library could hand it the Linux-only flow.
function checkMacActivation(libraries) {
  const targets = TV_LIBRARIES.map(id => libraries.find(l => l._id === id));
  assert(targets.every(Boolean), 'Expected exactly the three existing TV libraries');
  for (const library of targets) {
    assert((library.flowId === FLOW_ID && library.cache === CACHE_ROOT) || quiescent(library),
      `${library.name} still uses the Linux-only flow ${library.flowId}; run install-offload-flow.cjs --adopt `
      + 'before the Mac can take jobs');
  }
}

function plan({ node, libraries, sets, pause, isMac }) {
  const limits = node.workerLimits;
  assert(limits && WORKER_TYPES.every(type => Number.isInteger(limits[type])),
    `${node.nodeName} reports incomplete worker limits`);
  const nextLimits = { ...limits, ...sets };
  for (const type of WORKER_TYPES) {
    // What Tdarr does to a running job when its worker is removed is unverified, so never find out.
    if (nextLimits[type] < limits[type]) {
      assert.equal(activeWorkers(node, type).length, 0,
        `${node.nodeName} has a running ${type} worker; wait for it to finish before lowering that limit`);
    }
  }
  const nextPaused = pause ?? node.nodePaused;
  assert.equal(typeof nextPaused, 'boolean', `${node.nodeName} reports an unknown pause state`);
  if (isMac) {
    const others = WORKER_TYPES.filter(type => type !== 'transcodecpu');
    const cpuOnly = `${node.nodeName} must run CPU encodes only: transcodegpu and both health check limits must be 0`;
    assert(others.every(type => !sets[type]), cpuOnly);
    if (!nextPaused) {
      assert(others.every(type => nextLimits[type] === 0), cpuOnly);
      if (nextLimits.transcodecpu >= 1) checkMacActivation(libraries);
    }
  }
  const updates = {};
  if (WORKER_TYPES.some(type => nextLimits[type] !== limits[type])) updates.workerLimits = nextLimits;
  if (nextPaused !== node.nodePaused) updates.nodePaused = nextPaused;
  return updates;
}

async function configure({ crud, request, options, io = fs, log = console.log }) {
  const { nodeName, sets = {}, pause, apply = false, macNode = DEFAULT_MAC_NODE } = options;
  assert(typeof nodeName === 'string' && nodeName.length > 0, 'Specify the exact node name');
  const find = nodes => {
    const matches = Object.entries(nodes || {}).filter(([, n]) => n.nodeName === nodeName);
    assert.equal(matches.length, 1, 'Expected exactly one connected node with that name');
    return matches[0];
  };
  const decide = (node, libraries) => plan({ node, libraries, sets, pause, isMac: nodeName === macNode });

  const [libraries, nodes] = await Promise.all([
    crud('LibrarySettingsJSONDB', 'getAll'), request('get-nodes', undefined, 'GET'),
  ]);
  const [nodeID, node] = find(nodes);
  const updates = decide(node, libraries);
  log(JSON.stringify({ nodeName, nodeID, apply, updates }));
  if (!Object.keys(updates).length) {
    log('Already as requested; nothing to change.');
    return updates;
  }
  if (!apply) return updates;

  const persisted = await crud('NodeJSONDB', 'getById', { docID: nodeName });
  assert(persisted, 'Missing persisted node settings');
  await io.mkdir(`${ROOT}/backups`, { recursive: true, mode: 0o700 });
  const backup = `${ROOT}/backups/offload-node-${crypto.randomUUID()}.json`;
  await io.writeFile(backup, JSON.stringify({ nodeID, nodeName, node: persisted }, null, 2),
    { flag: 'wx', mode: 0o600 });
  const [latestNodes, latestLibraries] = await Promise.all([
    request('get-nodes', undefined, 'GET'), crud('LibrarySettingsJSONDB', 'getAll'),
  ]);
  const [latestID, latest] = find(latestNodes);
  assert.equal(latestID, nodeID, 'Node reconnected before the update; retry');
  assert.deepEqual(decide(latest, latestLibraries), updates, 'Node or library state changed before the update; retry');

  await request('update-node', { data: { nodeID, nodeUpdates: updates } });
  const [liveNodes, stored] = await Promise.all([
    request('get-nodes', undefined, 'GET'), crud('NodeJSONDB', 'getById', { docID: nodeName }),
  ]);
  const live = liveNodes?.[nodeID];
  assert(live && stored, 'Node disconnected after the update; verify its settings before relying on it');
  for (const [key, value] of Object.entries(updates)) {
    assert.deepEqual(live[key], value, `Live ${key} was not applied`);
    assert.deepEqual(stored[key], value, `Persisted ${key} was not applied`);
  }
  for (const key of [...KEPT, ...['nodePaused', 'workerLimits'].filter(k => !(k in updates))]) {
    assert.deepEqual(live[key], latest[key], `Live ${key} changed unexpectedly`);
    assert.deepEqual(stored[key], persisted[key], `Persisted ${key} changed unexpectedly`);
  }
  log(`Verified live and persisted node settings. Sensitive backup: ${backup}`);
  return updates;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const { crud, request } = await connect();
  await configure({ crud, request, options });
}

module.exports = { parseArgs, plan, checkMacActivation, configure, WORKER_TYPES };
if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
