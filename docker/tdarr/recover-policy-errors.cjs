#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { connect, ROOT } = require('./install-flow.cjs');
const { LEGACY } = require('./hevc-safe-v1.cjs');

function recoveryStatus(report, codec) {
  if (/New file size not within limits[^\n]+upperBound is 95%/.test(report)) return 'Not required';
  if (/New file size not within limits[^\n]+lowerBound is 30%/.test(report) && LEGACY.has(codec)) return 'Queued';
  return null;
}

async function main() {
  const options = process.argv.slice(2);
  assert(options.length === 0 || (options.length === 1 && options[0] === '--apply'),
    'Usage: node recover-policy-errors.cjs [--apply]');
  const { DatabaseSync } = require('node:sqlite');
  const db = new DatabaseSync('/app/server/Tdarr/DB2/SQL/database.db', { readOnly: true });
  const rows = db.prepare(`SELECT id,json_data FROM filejsondb
    WHERE transcode_decision_maker='Transcode error' AND db IN ('Io-wVbVRh','UU_64_3Ax','GHlz7HL1P')`).all();
  db.close();
  const changes = [];
  for (const row of rows) {
    const file = JSON.parse(row.json_data);
    if (!/^[\w-]+$/.test(file.footprintId)) continue;
    const dir = path.join('/app/server/Tdarr/DB2/JobReports', file.footprintId);
    let names;
    try { names = await fs.readdir(dir); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    const reports = names.filter(n => n.includes('()transcode()')).sort((a, b) =>
      Number(b.split('()').at(-1).replace('.txt', '')) - Number(a.split('()').at(-1).replace('.txt', '')));
    if (!reports.length) continue;
    const report = await fs.readFile(path.join(dir, reports[0]), 'utf8');
    const next = recoveryStatus(report, file.video_codec_name);
    if (!next) continue;
    try { await fs.access(file._id); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    changes.push({ id: file._id, next });
  }
  const { crud } = await connect();
  if (options.includes('--apply')) {
    await fs.writeFile(`${ROOT}/backups/policy-errors-${Date.now()}.json`,
      JSON.stringify(rows.filter(row => changes.some(c => c.id === row.id))), { flag: 'wx', mode: 0o600 });
    for (const change of changes) {
      const current = await crud('FileJSONDB', 'getById', { docID: change.id });
      assert.equal(current.TranscodeDecisionMaker, 'Transcode error', 'File status changed; stopping recovery');
      await crud('FileJSONDB', 'update', { docID: change.id, obj: { TranscodeDecisionMaker: change.next } });
      const stored = await crud('FileJSONDB', 'getById', { docID: change.id });
      assert.equal(stored.TranscodeDecisionMaker, change.next);
    }
  }
  console.log(JSON.stringify({ apply: options.includes('--apply'), policySkips: changes.filter(c => c.next === 'Not required').length,
    requeuedForSafeValidation: changes.filter(c => c.next === 'Queued').length, otherErrorsPreserved: rows.length - changes.length }));
}

module.exports = { recoveryStatus };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
