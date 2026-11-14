'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { prepare, release } = require('./maintenance.cjs');

function fixture(...names) {
  let lease;
  let serial = 0;
  const nodes = {};
  const gone = {};
  const add = nodeName => { nodes[`id-${serial++}`] = { nodeName, nodePaused: false, workers: {}, ...gone[nodeName] }; };
  (names.length ? names : ['HomeServer']).forEach(add);
  const calls = [];
  const io = {
    writeFile: async (_, content, options) => {
      if (lease && options.flag === 'wx') throw Object.assign(new Error('lease exists'), { code: 'EEXIST' });
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
    if (endpoint === 'get-nodes') return structuredClone(nodes);
    if (endpoint === 'update-node') Object.assign(nodes[data.data.nodeID], data.data.nodeUpdates);
    else throw new Error(endpoint);
  };
  const byName = name => Object.values(nodes).find(node => node.nodeName === name);
  return {
    io, request, nodes, calls, byName, add,
    get node() { return Object.values(nodes)[0]; },
    idOf: name => Object.keys(nodes).find(id => nodes[id].nodeName === name),
    // A node that reconnects gets a new ID but keeps its persisted settings.
    drop(name) { gone[name] = byName(name); delete nodes[this.idOf(name)]; },
    reconnect(name) { add(name); },
    leased: () => Boolean(lease),
    lease: () => JSON.parse(lease),
    seed: value => { lease = typeof value === 'string' ? value : JSON.stringify(value); },
    pausedStates: () => Object.fromEntries(Object.values(nodes).map(node => [node.nodeName, node.nodePaused])),
  };
}
const pair = () => fixture('HomeServer', 'Studio-Native');

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
test('a busy worker on any node defers without changing any pause state', async () => {
  for (const busyNode of ['HomeServer', 'Studio-Native']) {
    const f = pair();
    f.byName('Studio-Native').nodePaused = true;
    f.byName(busyNode).workers.job = { idle: false };
    assert.equal(await prepare(f), 75, busyNode);
    assert.deepEqual(f.pausedStates(), { HomeServer: false, 'Studio-Native': true });
    assert.equal(f.leased(), false);
    assert(!f.calls.includes('update-node'));
  }
});
test('an idle update pauses every node and restores each node to its own original state', async () => {
  for (const [server, studio] of [[false, false], [true, false], [false, true], [true, true]]) {
    const f = pair();
    f.byName('HomeServer').nodePaused = server;
    f.byName('Studio-Native').nodePaused = studio;
    assert.equal(await prepare(f), 0);
    assert.deepEqual(f.pausedStates(), { HomeServer: true, 'Studio-Native': true });
    assert.deepEqual(f.lease(), { nodes: [
      { nodeName: 'HomeServer', paused: server }, { nodeName: 'Studio-Native', paused: studio },
    ] });
    await release(f);
    assert.deepEqual(f.pausedStates(), { HomeServer: server, 'Studio-Native': studio });
    assert.equal(f.leased(), false);
  }
});
test('a job that starts on another node while pausing causes deferral and restores every node', async () => {
  const f = pair(), request = f.request;
  f.byName('Studio-Native').nodePaused = true;
  let raced = false;
  f.request = async (...args) => {
    const result = await request(...args);
    if (args[0] === 'update-node' && !raced) {
      raced = true;
      f.byName('Studio-Native').workers.raced = { idle: false };
    }
    return result;
  };
  assert.equal(await prepare(f), 75);
  assert.deepEqual(f.pausedStates(), { HomeServer: false, 'Studio-Native': true });
  assert.equal(f.leased(), false);
});
test('a node that connects during the pause is not trusted and nothing stays paused', async () => {
  const f = pair(), request = f.request;
  let joined = false;
  f.request = async (...args) => {
    const result = await request(...args);
    if (args[0] === 'update-node' && !joined) {
      joined = true;
      f.add('Late-Node');
    }
    return result;
  };
  assert.equal(await prepare(f), 75);
  assert.deepEqual(f.pausedStates(), { HomeServer: false, 'Studio-Native': false, 'Late-Node': false });
  assert.equal(f.leased(), false);
});
test('a failure part-way through pausing restores the nodes that were already paused', async () => {
  const f = pair(), request = f.request;
  f.byName('HomeServer').nodePaused = true;
  let updates = 0;
  f.request = async (...args) => {
    if (args[0] === 'update-node' && ++updates === 2) throw new Error('update refused');
    return request(...args);
  };
  await assert.rejects(prepare(f), /update refused/);
  assert.deepEqual(f.pausedStates(), { HomeServer: true, 'Studio-Native': false });
  assert.equal(f.leased(), false);
});
test('a pause the server acknowledges for only some nodes fails and restores them all', async () => {
  const f = pair(), request = f.request;
  const studio = f.idOf('Studio-Native');
  f.request = async (...args) => {
    if (args[0] === 'update-node' && args[1].data.nodeID === studio && args[1].data.nodeUpdates.nodePaused) return undefined;
    return request(...args);
  };
  await assert.rejects(prepare(f), /not acknowledged/);
  assert.deepEqual(f.pausedStates(), { HomeServer: false, 'Studio-Native': false });
  assert.equal(f.leased(), false);
});
test('an update that cannot identify the nodes it must wait for is refused', async () => {
  const duplicate = fixture('Studio-Native', 'Studio-Native');
  await assert.rejects(prepare(duplicate), /not unique/);
  const unknown = pair();
  unknown.byName('Studio-Native').nodePaused = undefined;
  await assert.rejects(prepare(unknown), /pause state is unknown/);
  const none = fixture();
  none.drop('HomeServer');
  await assert.rejects(prepare(none), /No connected/);
  for (const f of [duplicate, unknown, none]) {
    assert.equal(f.leased(), false);
    assert(!f.calls.includes('update-node'));
  }
});
test('a second update cannot take over a lease that is still held', async () => {
  const f = pair();
  const held = { nodes: [{ nodeName: 'HomeServer', paused: false }] };
  f.seed(held);
  await assert.rejects(prepare(f), { code: 'EEXIST' });
  assert.deepEqual(f.lease(), held);
  assert.deepEqual(f.pausedStates(), { HomeServer: false, 'Studio-Native': false });
  assert(!f.calls.includes('update-node'));
});
test('a node that returns later is restored from the retained lease', async () => {
  const f = pair();
  f.byName('HomeServer').nodePaused = true;
  assert.equal(await prepare(f), 0);
  f.drop('Studio-Native');
  await assert.rejects(release(f), /Studio-Native have not reconnected/);
  assert.deepEqual(f.lease(), { nodes: [{ nodeName: 'Studio-Native', paused: false }] });
  assert.deepEqual(f.pausedStates(), { HomeServer: true });
  f.reconnect('Studio-Native');
  assert.equal(f.byName('Studio-Native').nodePaused, true, 'the pause outlives the reconnection');
  await release(f);
  assert.deepEqual(f.pausedStates(), { HomeServer: true, 'Studio-Native': false });
  assert.equal(f.leased(), false);
});
test('a restore the server does not honour keeps that node in the lease', async () => {
  const f = pair(), request = f.request;
  assert.equal(await prepare(f), 0);
  const studio = f.idOf('Studio-Native');
  f.request = async (...args) => {
    if (args[0] === 'update-node' && args[1].data.nodeID === studio) return undefined;
    return request(...args);
  };
  await assert.rejects(release(f), /not restored for Studio-Native/);
  assert.deepEqual(f.pausedStates(), { HomeServer: false, 'Studio-Native': true });
  assert.deepEqual(f.lease(), { nodes: [{ nodeName: 'Studio-Native', paused: false }] });
});
test('a lease written for a single node by the first release of this script is still restored', async () => {
  const f = fixture();
  f.node.nodePaused = true;
  f.seed({ nodeName: 'HomeServer', paused: false });
  await release(f);
  assert.equal(f.node.nodePaused, false);
  assert.equal(f.leased(), false);
});
test('release does not guess between nodes that share a name', async () => {
  const f = fixture('Studio-Native', 'Studio-Native');
  const held = { nodes: [{ nodeName: 'Studio-Native', paused: false }] };
  f.seed(held);
  for (const node of Object.values(f.nodes)) node.nodePaused = true;
  await assert.rejects(release(f), /Studio-Native have not reconnected/);
  assert(!f.calls.includes('update-node'));
  assert.deepEqual(f.lease(), held);
});
test('a malformed lease is kept for inspection instead of guessed at', async () => {
  const f = pair();
  for (const lease of ['{"nodes":[{"nodeName":1,"paused":false}]}', '{"nodes":{}}', '{"nodes":[{"nodeName":"HomeServer"}]}']) {
    f.seed(lease);
    f.byName('HomeServer').nodePaused = true;
    await assert.rejects(release(f), /malformed/, lease);
    assert.equal(f.byName('HomeServer').nodePaused, true);
    assert(f.leased());
  }
});
