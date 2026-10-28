'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { reconcile } = require('./reconcile-sidecars.cjs');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'tdarr-sidecar-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const home = path.join(root, 'home'), movie = path.join(root, 'movies', 'Movie (2026)');
  await fs.mkdir(path.join(home, 'state'), { recursive: true });
  const output = path.join(movie, 'Plex Versions', 'Homeserver SDR',
    'Movie (2026) - [WEBRip-1080p][SDR][h264]-PlexSDR.mp4');
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, 'owned sidecar');
  const source = path.join(movie, 'original.mkv');
  const saved = { version: '1', source: { realpath: source, size: 10, mtimeMs: 100 }, output };
  const manifest = path.join(home, 'state', crypto.createHash('sha256').update(output).digest('hex') + '.json');
  await fs.writeFile(manifest, JSON.stringify(saved));
  return { root, home, source, output, manifest, saved };
}

test('dry run is read-only and apply archives owned stale media without deleting it', async t => {
  const f = await fixture(t);
  const dry = await reconcile({ ...f, now: () => 123 });
  assert.equal(dry.length, 1);
  assert.equal(await fs.readFile(f.output, 'utf8'), 'owned sidecar');
  const applied = await reconcile({ ...f, now: () => 123, apply: true });
  assert.equal(await fs.readFile(path.join(applied[0].archive, path.basename(f.output)), 'utf8'), 'owned sidecar');
  assert.equal((await reconcile(f)).length, 0);
  assert.equal(JSON.parse(await fs.readFile(path.join(applied[0].archive, 'manifest.json'))).reason, 'source removed or replaced');
});
test('sidecars for an unchanged source are left alone', async t => {
  const f = await fixture(t);
  await fs.writeFile(f.source, 'source');
  const stat = await fs.stat(f.source);
  f.saved.source.size = stat.size;
  f.saved.source.mtimeMs = stat.mtimeMs;
  await fs.writeFile(f.manifest, JSON.stringify(f.saved));
  assert.equal((await reconcile({ ...f, apply: true })).length, 0);
  assert.equal(await fs.readFile(f.output, 'utf8'), 'owned sidecar');
});
test('unowned paths fail closed without moving files', async t => {
  const f = await fixture(t);
  f.saved.output = path.join(f.root, 'unmanaged.mp4');
  await fs.writeFile(f.manifest, JSON.stringify(f.saved));
  await assert.rejects(reconcile({ ...f, apply: true }), /expected output/);
  assert.equal(await fs.readFile(f.output, 'utf8'), 'owned sidecar');
});
