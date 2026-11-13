#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { connect, ROOT, libraryDefinition: baseLibrary } = require('./install-flow.cjs');
const { PRIVATE_ROOT, CACHE_ROOT } = require('./hevc-studio-v1.cjs');

const FLOW_ID = 'homeserver-hevc-studio-v1';
const LIBRARY_ID = 'homeserver-hevc-studio-canary-v1';
const CANARY_FOLDER = '/data/media/tdarr-studio-canary';
const MAC_MODULE = '/var/lib/studio-worker/tdarr/Custom/hevc-studio-v1.cjs';

function flowDefinition(notify) {
  const nodes = [];
  const plugin = (id, name, pluginName, inputsDB = {}) => {
    nodes.push({
      id, name, pluginName, inputsDB, sourceRepo: 'Community', version: '1.0.0', fpEnabled: true,
      position: { x: 0, y: nodes.length * 140 },
    });
  };
  plugin('input', 'Input file', 'inputFile');
  plugin('storage-prepare', 'Linux storage CPU only', 'tagsWorkerType',
    { requiredWorkerType: 'CPU', requiredNodeTags: 'homeserver-storage' });
  plugin('prepare', 'Linux-private source contract', 'customFunction',
    { code: `module.exports = async args => require('${ROOT}/hevc-studio-v1.cjs').prepare(args);` });
  plugin('studio', 'Native Studio CPU only', 'tagsWorkerType',
    { requiredWorkerType: 'CPU', requiredNodeTags: 'studio-native' });
  plugin('encode', 'Software x265 slow; preserve library CRF', 'customFunction',
    { code: `module.exports = async args => require('${MAC_MODULE}').encode(args);` });
  plugin('storage-commit', 'Return to Linux storage CPU', 'tagsWorkerType',
    { requiredWorkerType: 'CPU', requiredNodeTags: 'homeserver-storage' });
  plugin('commit', 'Private copy, strict decode and safe publication', 'customFunction',
    { code: `module.exports = async args => require('${ROOT}/hevc-studio-v1.cjs').commit(args);` });
  nodes.push({ ...structuredClone(notify), id: 'notify', position: { x: 0, y: nodes.length * 140 } });
  return {
    _id: FLOW_ID, name: 'Homeserver - native Studio SDR HEVC v1 (canary)', priority: 0, isUiLocked: true,
    flowPlugins: nodes,
    flowEdges: nodes.slice(0, -1).map((node, i) => ({
      source: node.id, sourceHandle: '1', target: nodes[i + 1].id, targetHandle: null,
      id: `${node.id}-to-${nodes[i + 1].id}`, animated: true, type: 'smoothstep',
    })),
  };
}

function libraryDefinition(defaults) {
  return {
    ...baseLibrary(defaults), _id: LIBRARY_ID, name: 'Studio native HEVC - isolated manual canary',
    folder: CANARY_FOLDER, cache: CACHE_ROOT, flowId: FLOW_ID,
    holdNewFiles: true, holdFor: 180, holdForDisplayUnit: 'minutes',
    filterCodecsSkip: 'hevc,av1,vp9',
  };
}

async function install({ crud, defaults, apply = false, log = console.log, io = fs }) {
  const [flows, libraries, variables] = await Promise.all([
    crud('FlowsJSONDB', 'getAll'), crud('LibrarySettingsJSONDB', 'getAll'), crud('VariablesJSONDB', 'getAll'),
  ]);
  const notify = flows.find(f => f._id === 'homeserver-hevc-cpu-v1')?.flowPlugins
    .find(n => n.pluginName === 'notifyRadarrOrSonarr');
  assert(notify, 'Existing safe v1 Sonarr notification configuration is required');
  const desired = flowDefinition(notify);
  const existingFlow = flows.find(f => f._id === FLOW_ID);
  if (existingFlow) for (const key of Object.keys(desired)) {
    assert.deepEqual(existingFlow[key], desired[key], 'Existing versioned flow differs; deploy a new version');
  }
  const existingLibrary = libraries.find(l => l._id === LIBRARY_ID);
  if (existingLibrary) {
    assert(existingLibrary.flowId === FLOW_ID && existingLibrary.folder === CANARY_FOLDER
      && existingLibrary.cache === CACHE_ROOT, 'Canary library ID collision');
    for (const key of ['processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching',
      'useFsEvents', 'scheduledScanFindNew', 'scanOnStart']) assert.equal(existingLibrary[key], false,
      'Canary already enabled; installer will not modify an active rollout');
  }
  const existingCrf = variables.filter(v => v.type === `library:${LIBRARY_ID}` && v.key === 'crf');
  assert(existingCrf.length <= 1, 'Duplicate canary CRF variables');
  if (existingCrf.length) assert.equal(existingCrf[0].value, '20', 'Canary CRF is not 20');
  log(`${apply ? 'Installing' : 'Previewing'} NEW disabled canary only; existing libraries and workers unchanged.`);
  if (!apply) return;
  await io.access(`${ROOT}/hevc-studio-v1.cjs`);
  await io.access(`${ROOT}/hevc-safe-v1.cjs`);
  await io.access(`${ROOT}/dv5-sidecar.cjs`);
  await io.mkdir(`${ROOT}/backups`, { recursive: true, mode: 0o700 });
  await io.writeFile(`${ROOT}/backups/studio-flow-${Date.now()}.json`,
    JSON.stringify({ flows, libraries, variables }, null, 2), { flag: 'wx', mode: 0o600 });
  await io.mkdir(PRIVATE_ROOT, { recursive: true, mode: 0o700 });
  await io.access(CACHE_ROOT); // Provisioned separately: never create or export a broader cache here.
  const insert = async (collection, docID, obj) => {
    await crud(collection, 'insert', { docID, obj });
    const stored = await crud(collection, 'getById', { docID });
    for (const key of Object.keys(obj)) assert.deepEqual(stored[key], obj[key]);
  };
  if (!existingFlow) await insert('FlowsJSONDB', FLOW_ID, desired);
  if (!existingLibrary) await insert('LibrarySettingsJSONDB', LIBRARY_ID, libraryDefinition(defaults));
  if (!existingCrf.length) await insert('VariablesJSONDB', `${LIBRARY_ID}-crf`, {
    _id: `${LIBRARY_ID}-crf`, key: 'crf', value: '20', type: `library:${LIBRARY_ID}`, date: Date.now(),
  });
  log('Verified disabled canary and CRF 20. No scans, activation, real-library repointing or worker changes.');
}

async function main() {
  const options = process.argv.slice(2);
  assert(options.length === 0 || (options.length === 1 && options[0] === '--apply'),
    'Usage: node install-studio-flow.cjs [--apply] (canary only; no enable mode)');
  const { crud } = await connect();
  const defaults = require('/app/Tdarr_Server/srcug/commonModules/jobs/libraryDefaults').default;
  await install({ crud, defaults, apply: options.includes('--apply') });
}

module.exports = { flowDefinition, libraryDefinition, install, FLOW_ID, LIBRARY_ID, CANARY_FOLDER, MAC_MODULE };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
