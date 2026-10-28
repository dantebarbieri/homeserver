#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { connect, ROOT } = require('./install-flow.cjs');
const LEASE = `${ROOT}/update-lease.json`;
const busy = nodes => Object.values(nodes).some(node => Object.values(node.workers || {}).some(worker => !worker.idle));

async function prepare({ request, io = fs }) {
  const nodes = await request('get-nodes', undefined, 'GET');
  if (busy(nodes)) return 75;
  assert.equal(Object.keys(nodes).length, 1, 'Expected one connected node; refusing an unverified update');
  const [id, node] = Object.entries(nodes)[0];
  assert.equal(typeof node.nodePaused, 'boolean', 'Node pause state is unknown');
  await io.writeFile(LEASE, JSON.stringify({ nodeName: node.nodeName, paused: node.nodePaused }), { flag: 'wx', mode: 0o600 });
  try {
    await request('update-node', { data: { nodeID: id, nodeUpdates: { nodePaused: true } } });
    const paused = await request('get-nodes', undefined, 'GET');
    assert.equal(paused[id]?.nodePaused, true, 'Node pause was not acknowledged');
    if (busy(paused)) {
      await release({ request, io });
      return 75;
    }
    return 0;
  } catch (error) {
    try { await release({ request, io }); }
    catch (restore) { throw new AggregateError([error, restore], `Tdarr update pause requires recovery: ${LEASE}`); }
    throw error;
  }
}

async function release({ request, io = fs }) {
  let lease;
  try { lease = JSON.parse(await io.readFile(LEASE, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  const nodes = await request('get-nodes', undefined, 'GET');
  const entry = Object.entries(nodes).find(([, node]) => node.nodeName === lease.nodeName);
  assert(entry, 'Tdarr node has not reconnected; update pause is retained for recovery');
  const [id] = entry;
  await request('update-node', { data: { nodeID: id, nodeUpdates: { nodePaused: lease.paused } } });
  const verified = await request('get-nodes', undefined, 'GET');
  assert.equal(verified[id]?.nodePaused, lease.paused, 'Original pause state was not restored');
  await io.unlink(LEASE);
}

async function main() {
  const [mode] = process.argv.slice(2);
  assert(['prepare', 'release'].includes(mode), 'Usage: node maintenance.cjs prepare|release');
  const api = await connect();
  if (mode === 'prepare') {
    const code = await prepare(api);
    if (code === 75) console.error('Tdarr has active workers; deferring its recreation without interrupting jobs.');
    process.exitCode = code;
  } else await release(api);
}

module.exports = { prepare, release, busy };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
