#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { ROOT } = require('./install-flow.cjs');
const { internals: { inside } } = require('./dv5-sidecar.cjs');

async function reconcile({ io = fs, apply = false, root = '/data/media', home = ROOT, now = Date.now } = {}) {
  const state = path.join(home, 'state');
  const results = [];
  for (const name of await io.readdir(state)) {
    if (!/^[a-f0-9]{64}\.json$/.test(name)) continue;
    const raw = await io.readFile(path.join(state, name), 'utf8');
    const saved = JSON.parse(raw);
    assert.equal(saved.version, '1', 'Unknown sidecar manifest version');
    assert(inside(path.join(root, 'movies'), saved.source.realpath), 'Manifest source escapes movie library');
    const expected = path.join(path.dirname(saved.source.realpath), 'Plex Versions', 'Homeserver SDR',
      path.basename(path.dirname(saved.source.realpath)) + ' - [WEBRip-1080p][SDR][h264]-PlexSDR.mp4');
    assert.equal(saved.output, expected, 'Manifest does not own the expected output');
    assert.equal(name, crypto.createHash('sha256').update(saved.output).digest('hex') + '.json', 'Manifest name mismatch');
    let output, source;
    try { output = await io.lstat(saved.output); }
    catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    assert(output.isFile() && !output.isSymbolicLink(), 'Output is not a regular file');
    assert.equal(await io.realpath(saved.output), saved.output, 'Output path is redirected');
    try { source = await io.stat(saved.source.realpath); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (source && source.size === saved.source.size && source.mtimeMs === saved.source.mtimeMs) continue;
    const archive = path.join(root, '.tdarr-sidecar-archive', `${now()}-${name.slice(0, 12)}`);
    if (apply) {
      const archiveRoot = path.join(root, '.tdarr-sidecar-archive');
      await io.mkdir(archiveRoot, { recursive: true });
      assert.equal(await io.realpath(archiveRoot), archiveRoot, 'Archive path is redirected');
      await io.mkdir(archive);
      await io.writeFile(path.join(archive, 'manifest.json'), JSON.stringify({
        ...saved, archivedAt: new Date(now()).toISOString(), reason: 'source removed or replaced',
        outputSize: output.size, outputMtimeMs: output.mtimeMs,
      }), { flag: 'wx', mode: 0o600 });
      const current = await io.lstat(saved.output);
      assert(current.ino === output.ino && current.size === output.size && current.mtimeMs === output.mtimeMs,
        'Sidecar changed during reconciliation');
      await io.rename(saved.output, path.join(archive, path.basename(saved.output)));
    }
    results.push({ output: saved.output, archive, applied: apply });
  }
  return results;
}

module.exports = { reconcile };
if (require.main === module) {
  const options = process.argv.slice(2);
  assert(options.length === 0 || (options.length === 1 && options[0] === '--apply'), 'Usage: node reconcile-sidecars.cjs [--apply]');
  reconcile({ apply: options.includes('--apply') }).then(results => console.log(JSON.stringify(results, null, 2)))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
