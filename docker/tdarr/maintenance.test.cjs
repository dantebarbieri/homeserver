'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { prepare, release } = require('./maintenance.cjs');

function fixture() {
  let lease;
  const node = { nodeName: 'HomeServer', nodePaused: false, workers: {} };
  const calls = [];
  const io = {
    writeFile: async (_, content) => {
      if (lease) throw Object.assign(new Error('lease exists'), { code: 'EEXIST' });
      lease = content;
    },
    readFile: async () => {
      if (!lease) throw Object.assign(new Error('missing'), { code: 'ENOENT' });
      return lease;
    },
    unlink: async () => { lease = undefined; },
  };
  const request = async (endpoint, data) => {
    calls.push(endpoint);
    if (endpoint === 'get-nodes') return { current: structuredClone(node) };
    if (endpoint === 'update-node') Object.assign(node, data.data.nodeUpdates);
    else throw new Error(endpoint);
  };
  return { io, request, node, calls, leased: () => Boolean(lease) };
}

test('busy workers defer without changing pause state', async () => {
  const f = fixture(); f.node.workers.job = { idle: false };
  assert.equal(await prepare(f), 75);
  assert.equal(f.node.nodePaused, false);
  assert.equal(f.leased(), false);
});
test('idle update pauses scheduling and restores the original state', async () => {
  for (const paused of [false, true]) {
    const f = fixture(); f.node.nodePaused = paused;
    assert.equal(await prepare(f), 0);
    assert.equal(f.node.nodePaused, true);
    assert.equal(f.leased(), true);
    await release(f);
    assert.equal(f.node.nodePaused, paused);
    assert.equal(f.leased(), false);
  }
});
test('a job racing the pause causes deferral, not a restart', async () => {
  const f = fixture(), request = f.request;
  f.request = async (...args) => {
    const result = await request(...args);
    if (args[0] === 'update-node' && args[1].data.nodeUpdates.nodePaused) f.node.workers.raced = { idle: false };
    return result;
  };
  assert.equal(await prepare(f), 75);
  assert.equal(f.node.nodePaused, false);
  assert.equal(f.leased(), false);
});
test('a disconnected node fails closed and cannot erase the recovery lease', async () => {
  const f = fixture();
  await prepare(f);
  f.request = async () => ({});
  await assert.rejects(release(f), /reconnected/);
  assert.equal(f.leased(), true);
});
