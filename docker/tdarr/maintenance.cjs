#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { connect, ROOT } = require('./install-flow.cjs');
const LEASE = `${ROOT}/update-lease.json`;
const busy = nodes => Object.values(nodes).some(node => Object.values(node.workers || {}).some(worker => !worker.idle));
// A job that finished one leg (the Mac's encode, say) waits in staging for the next worker, and
// for those seconds no worker looks busy. Pausing the nodes then would leave it unclaimed until
// Tdarr discards it, wasting the finished leg. Staging empties by itself within minutes.
const staged = async crud => {
  const rows = await crud('StagedJSONDB', 'getAll');
  assert(Array.isArray(rows), 'Staged Tdarr jobs are unreadable; refusing an unverified update');
  return rows.length > 0;
};
const setPause = (request, nodeID, nodePaused) => request('update-node', { data: { nodeID, nodeUpdates: { nodePaused } } });

// Every connected node is paused, including mapped nodes on other machines: a worker that is
// idle now could otherwise start a job while the server is being recreated. A disconnected node
// has no server-side worker to wait for; its pause state is restored when it comes back.
async function prepare({ request, crud, io = fs }) {
  const nodes = await request('get-nodes', undefined, 'GET');
  if (busy(nodes) || await staged(crud)) return 75;
  const connected = Object.entries(nodes);
  assert(connected.length > 0, 'No connected Tdarr node; refusing an unverified update');
  const names = connected.map(([, node]) => node.nodeName);
  assert(names.every(name => typeof name === 'string' && name) && new Set(names).size === names.length,
    'Tdarr node names are not unique; refusing an unverified update');
  assert(connected.every(([, node]) => typeof node.nodePaused === 'boolean'), 'Node pause state is unknown');
  const leased = connected.map(([, node]) => ({ nodeName: node.nodeName, paused: node.nodePaused }));
  await io.writeFile(LEASE, JSON.stringify({ nodes: leased }), { flag: 'wx', mode: 0o600 });
  try {
    for (const [id] of connected) await setPause(request, id, true);
    const paused = await request('get-nodes', undefined, 'GET');
    for (const [id] of connected) assert.equal(paused[id]?.nodePaused, true, 'Node pause was not acknowledged');
    if (busy(paused) || Object.keys(paused).some(id => !(id in nodes)) || await staged(crud)) {
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

// Restores whatever it can and keeps the rest of the lease for a later retry.
async function release({ request, io = fs }) {
  let lease;
  try { lease = JSON.parse(await io.readFile(LEASE, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  const saved = lease.nodes ?? [lease]; // The first release of this script leased one node as {nodeName, paused}.
  assert(Array.isArray(saved) && saved.every(entry => typeof entry?.nodeName === 'string' && typeof entry.paused === 'boolean'),
    `Update lease is malformed; inspect ${LEASE}`);
  const nodes = await request('get-nodes', undefined, 'GET');
  const ids = new Map();
  for (const { nodeName } of saved) {
    const matches = Object.keys(nodes).filter(id => nodes[id].nodeName === nodeName);
    if (matches.length === 1) ids.set(nodeName, matches[0]);
  }
  for (const entry of saved) {
    if (ids.has(entry.nodeName)) await setPause(request, ids.get(entry.nodeName), entry.paused);
  }
  const verified = ids.size ? await request('get-nodes', undefined, 'GET') : nodes;
  const remaining = saved.filter(entry => !(ids.has(entry.nodeName)
    && verified[ids.get(entry.nodeName)]?.nodePaused === entry.paused));
  if (remaining.length) {
    if (remaining.length < saved.length) await io.writeFile(LEASE, JSON.stringify({ nodes: remaining }), { flag: 'w', mode: 0o600 });
    const absent = remaining.filter(entry => !ids.has(entry.nodeName)).map(entry => entry.nodeName);
    assert.equal(absent.length, 0, `Tdarr node(s) ${absent.join(', ')} have not reconnected (or share a name); update pause is retained for recovery`);
    assert.fail(`Original pause state was not restored for ${remaining.map(entry => entry.nodeName).join(', ')}`);
  }
  await io.unlink(LEASE);
}

async function main() {
  const [mode] = process.argv.slice(2);
  assert(['prepare', 'release'].includes(mode), 'Usage: node maintenance.cjs prepare|release');
  const api = await connect();
  if (mode === 'prepare') {
    const code = await prepare(api);
    if (code === 75) console.error('Tdarr has active or staged jobs; deferring its recreation without interrupting them.');
    process.exitCode = code;
  } else await release(api);
}

module.exports = { prepare, release, busy };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
