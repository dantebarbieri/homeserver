#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { connect, ROOT } = require('./install-flow.cjs');
const { LIBRARY_ID, FLOW_ID, CANARY_FOLDER } = require('./install-studio-flow.cjs');

function exclusions(libraries, current = {}) {
  assert(current && typeof current === 'object' && !Array.isArray(current), 'Invalid current library exclusions');
  const canary = libraries.find(l => l._id === LIBRARY_ID);
  assert(canary?.flowId === FLOW_ID && canary.folder === CANARY_FOLDER, 'Expected isolated native canary library');
  assert(libraries.every(l => typeof l._id === 'string' && l._id)
    && new Set(libraries.map(l => l._id)).size === libraries.length, 'Invalid library inventory');
  return Object.fromEntries([...Object.entries(current), ...libraries.map(l => [l._id, l._id !== LIBRARY_ID])]);
}

function pausedNativeNode(node) {
  assert(node.nodePaused === true, 'Keep the native node paused before setting library restrictions');
  const tags = (node.nodeTags || '').split(',').map(s => s.trim());
  assert(tags.includes('studio-native') && !tags.includes('homeserver-storage'), 'Expected native-only node tags');
  assert(Object.entries(node.workerLimits || {}).every(([key, value]) => Number.isInteger(value)
    && value >= 0 && value <= (key === 'transcodecpu' ? 1 : 0)), 'Expected at most one CPU worker and no GPU/health workers');
  assert(node.allowGpuDoCpu === false, 'Disable GPU workers doing CPU jobs on the native node');
}

const inventory = libraries => libraries.map(l => l._id).sort();

async function restrict({ crud, request, nodeName, apply = false, io = fs, log = console.log }) {
  assert(typeof nodeName === 'string' && nodeName.length > 0, 'Specify the exact native node name');
  const [libraries, nodes] = await Promise.all([
    crud('LibrarySettingsJSONDB', 'getAll'), request('get-nodes', undefined, 'GET'),
  ]);
  const matches = Object.entries(nodes).filter(([, n]) => n.nodeName === nodeName);
  assert.equal(matches.length, 1, 'Expected exactly one connected node with that name');
  const [nodeID, node] = matches[0];
  pausedNativeNode(node);
  const desired = exclusions(libraries, node.librariesToNotProcess);
  log(JSON.stringify({ nodeName, nodeID, apply, librariesToNotProcess: desired }));
  log('Denylist only: future libraries default allowed. Keep the node paused until verified; freeze library additions during the canary.');
  if (!apply) return desired;

  const persisted = await crud('NodeJSONDB', 'getById', { docID: nodeName });
  assert(persisted, 'Missing persisted node settings');
  assert.equal(persisted.nodePaused, true, 'Persisted node must also be paused');
  const canary = libraries.find(l => l._id === LIBRARY_ID);
  assert.equal(canary.processLibrary, false, 'Set restrictions before canary activation');
  assert.equal(canary.processTranscodes, false, 'Set restrictions before canary activation');
  await io.mkdir(`${ROOT}/backups`, { recursive: true, mode: 0o700 });
  const backup = `${ROOT}/backups/studio-node-restrictions-${crypto.randomUUID()}.json`;
  await io.writeFile(backup, JSON.stringify({ nodeID, nodeName, libraries, node: persisted }, null, 2),
    { flag: 'wx', mode: 0o600 });
  const latest = (await request('get-nodes', undefined, 'GET'))[nodeID];
  assert(latest && latest.nodeName === nodeName, 'Node identity changed before update');
  pausedNativeNode(latest);
  for (const key of ['nodePaused', 'workerLimits', 'nodeTags', 'librariesToNotProcess']) {
    assert.deepEqual(latest[key], node[key], `Node ${key} changed before update`);
  }
  assert.deepEqual(inventory(await crud('LibrarySettingsJSONDB', 'getAll')), inventory(libraries),
    'Library inventory changed; leave the node paused and retry');
  await request('update-node', { data: { nodeID, nodeUpdates: { librariesToNotProcess: desired } } });
  const [updatedNodes, stored, updatedLibraries] = await Promise.all([
    request('get-nodes', undefined, 'GET'), crud('NodeJSONDB', 'getById', { docID: nodeName }),
    crud('LibrarySettingsJSONDB', 'getAll'),
  ]);
  assert.deepEqual(inventory(updatedLibraries), inventory(libraries),
    'A library was added during the update; keep the node paused and regenerate exclusions');
  const updated = updatedNodes[nodeID];
  assert(updated, 'Node disconnected; keep it paused and verify before any canary');
  assert.deepEqual(updated.librariesToNotProcess, desired, 'Live exclusions were not applied');
  assert.deepEqual(stored.librariesToNotProcess, desired, 'Persisted exclusions were not applied');
  for (const key of ['nodePaused', 'workerLimits', 'nodeTags']) {
    assert.deepEqual(updated[key], node[key], `Live ${key} changed`);
    assert.deepEqual(stored[key], persisted[key], `Persisted ${key} changed`);
  }
  log(`Verified current-library exclusions live and persisted. Node remains paused. Sensitive backup: ${backup}`);
  return desired;
}

async function main() {
  const options = process.argv.slice(2);
  assert(options[0] === '--node-name' && options[1]
    && (options.length === 2 || (options.length === 3 && options[2] === '--apply')),
  'Usage: node restrict-studio-node.cjs --node-name <exact-name> [--apply]');
  const { crud, request } = await connect();
  await restrict({ crud, request, nodeName: options[1], apply: options.includes('--apply') });
}

module.exports = { exclusions, pausedNativeNode, restrict };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
