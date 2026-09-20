#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

const ROOT = '/app/server/Tdarr/Custom';
const FLOW_ID = 'homeserver-dv5-sidecar';
const LIBRARY_ID = 'homeserver-dv5-movies';
const MODULE_PATH = `${ROOT}/dv5-sidecar.cjs`;

function flowDefinition() {
  return {
    _id: FLOW_ID,
    name: 'Homeserver - Dolby Vision 5 SDR sidecar (preserve original)',
    priority: 0,
    isUiLocked: true,
    flowPlugins: [
      {
        name: 'Input file', sourceRepo: 'Community', pluginName: 'inputFile',
        version: '1.0.0', id: 'input', position: { x: 0, y: 0 },
        fpEnabled: true, inputsDB: {},
      },
      {
        name: 'Probe: skip everything except Dolby Vision Profile 5',
        sourceRepo: 'Community', pluginName: 'customFunction', version: '1.0.0',
        id: 'classify', position: { x: 0, y: 150 }, fpEnabled: true,
        inputsDB: {
          code: `module.exports = async args => require('${MODULE_PATH}').classify(args);`,
        },
      },
      {
        name: 'Queue eligible files for the single GPU worker',
        sourceRepo: 'Community', pluginName: 'tagsWorkerType', version: '1.0.0',
        id: 'gpu-worker', position: { x: 0, y: 300 }, fpEnabled: true,
        inputsDB: { requiredWorkerType: 'GPU', requiredNodeTags: '' },
      },
      {
        name: 'Profile 5 only: validated SDR sidecar; original unchanged',
        sourceRepo: 'Community', pluginName: 'customFunction', version: '1.0.0',
        id: 'dv5-sidecar', position: { x: 0, y: 450 }, fpEnabled: true,
        inputsDB: {
          code: `module.exports = async args => require('${MODULE_PATH}')(args);`,
        },
      },
    ],
    flowEdges: [
      ['input', 'classify'],
      ['classify', 'gpu-worker'],
      ['gpu-worker', 'dv5-sidecar'],
    ].map(([source, target]) => ({
      source, sourceHandle: '1', target, targetHandle: null,
      id: `${source}-to-${target}`, animated: true, type: 'smoothstep',
    })),
  };
}

function libraryDefinition(defaults) {
  return {
    ...structuredClone(defaults),
    _id: LIBRARY_ID,
    name: 'Movies - Dolby Vision 5 compatibility (manual rollout)',
    folder: '/data/media/movies',
    cache: `${ROOT}/cache`,
    output: '.',
    flowId: FLOW_ID,
    decisionMaker: {
      ...structuredClone(defaults.decisionMaker),
      settingsFlows: true,
      settingsPlugin: false,
    },
    processLibrary: false,
    processTranscodes: false,
    processHealthChecks: false,
    folderWatching: false,
    useFsEvents: false,
    scheduledScanFindNew: false,
    scanOnStart: false,
    holdNewFiles: false,
    filterCodecsSkip: '',
    filterContainersSkip: '',
    filterResolutionsSkip: '',
    folderToFolderConversion: false,
    folderToFolderConversionDeleteSource: false,
    copyIfConditionsMet: false,
    totalHealthCheckCount: 0,
    totalTranscodeCount: 0,
    sizeDiff: 0,
    createdAt: Date.now(),
  };
}

async function connect() {
  const config = JSON.parse(await fs.readFile('/app/configs/Tdarr_Node_Config.json', 'utf8'));
  const apiKey = process.env.apiKey || config.apiKey;
  if (!apiKey) throw new Error('Tdarr API key is not configured');
  async function request(endpoint, data, method = 'POST') {
    const response = await fetch(`http://127.0.0.1:8265/api/v2/${endpoint}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey },
      body: data === undefined ? undefined : JSON.stringify(data),
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) throw new Error(`Tdarr ${endpoint}: HTTP ${response.status}`);
    const body = await response.text();
    if (!body.trim()) return null;
    return response.headers.get('content-type')?.includes('application/json') ? JSON.parse(body) : body;
  }
  const crud = (collection, mode, extra = {}) => request('cruddb', {
    data: { collection, mode, ...extra },
  });
  return { request, crud };
}

function enabledLibrarySettings() {
  return {
    name: 'Movies - Dolby Vision 5 compatibility',
    processLibrary: true,
    processTranscodes: true,
    processHealthChecks: false,
    folderWatching: true,
    useFsEvents: false,
    folderWatchScanInterval: 600,
    scannerThreadCount: 1,
    scanOnStart: true,
    scheduledScanFindNew: false,
    foldersToIgnore: 'Plex Versions',
    foldersToIgnoreCaseInsensitive: true,
    holdNewFiles: true,
    holdFor: 180,
    holdForDisplayUnit: 'minutes',
    filterCodecsSkip: '',
  };
}

function gpuWorkerLimits(node) {
  assert(node.gpuSelect === '-', 'This flow requires generic GPU worker tagging (gpuSelect="-")');
  assert(!node.allowGpuDoCpu, 'Disable GPU workers doing CPU jobs before enabling this flow');
  return { ...node.workerLimits, transcodegpu: 1 };
}

async function main() {
  const options = process.argv.slice(2);
  if (options.some(option => !['--apply', '--enable'].includes(option))
    || (options.includes('--enable') && !options.includes('--apply'))) {
    throw new Error('Usage: node install-flow.cjs [--apply [--enable]]');
  }
  const apply = options.includes('--apply');
  const enable = options.includes('--enable');
  const { crud, request } = await connect();
  const defaults = require('/app/Tdarr_Server/srcug/commonModules/jobs/libraryDefaults').default;
  assert(defaults && typeof defaults === 'object', 'Missing installed Tdarr library defaults');
  assert(Array.isArray(defaults.schedule), 'Incomplete Tdarr library defaults');
  await fs.access(MODULE_PATH);
  const [flows, libraries] = await Promise.all([
    crud('FlowsJSONDB', 'getAll'), crud('LibrarySettingsJSONDB', 'getAll'),
  ]);
  const existingFlow = flows.find(flow => flow._id === FLOW_ID);
  const existingLibrary = libraries.find(library => library._id === LIBRARY_ID);
  const desiredFlow = flowDefinition();
  if (existingFlow && existingFlow.name !== desiredFlow.name) {
    throw new Error(`Flow ID collision: ${FLOW_ID}`);
  }
  if (existingLibrary && (
    existingLibrary.flowId !== FLOW_ID || existingLibrary.folder !== '/data/media/movies'
  )) throw new Error(`Library ID collision: ${LIBRARY_ID}`);
  console.log(`${apply ? 'Applying' : 'Previewing'} flow ${FLOW_ID}`);
  console.log(existingLibrary
    ? 'Existing movie library settings will be preserved.'
    : 'New movie library will be disabled: no watchers, scans, or processing.');
  if (!apply) return;

  await fs.mkdir(`${ROOT}/backups`, { recursive: true });
  await fs.mkdir(`${ROOT}/cache`, { recursive: true });
  await fs.writeFile(path.join(ROOT, 'backups', `install-${Date.now()}.json`),
    JSON.stringify({ existingFlow, existingLibrary }, null, 2), { mode: 0o600, flag: 'wx' });
  await crud('FlowsJSONDB', existingFlow ? 'update' : 'insert', {
    docID: FLOW_ID, obj: desiredFlow,
  });
  const storedFlow = await crud('FlowsJSONDB', 'getById', { docID: FLOW_ID });
  for (const key of Object.keys(desiredFlow)) assert.deepEqual(storedFlow[key], desiredFlow[key]);
  if (!existingLibrary) {
    const library = libraryDefinition(defaults);
    await crud('LibrarySettingsJSONDB', 'insert', { docID: LIBRARY_ID, obj: library });
    const stored = await crud('LibrarySettingsJSONDB', 'getById', { docID: LIBRARY_ID });
    for (const key of Object.keys(library)) assert.deepEqual(stored[key], library[key]);
  }
  console.log('Flow and library verified via API. Existing libraries and worker limits unchanged.');
  if (enable) {
    const nodes = await request('get-nodes', undefined, 'GET');
    const entries = Object.entries(nodes);
    assert.equal(entries.length, 1, 'Enabling requires exactly one colocated node');
    const [nodeID, node] = entries[0];
    const limits = gpuWorkerLimits(node);
    const library = await crud('LibrarySettingsJSONDB', 'getById', { docID: LIBRARY_ID });
    await fs.writeFile(path.join(ROOT, 'backups', `enable-${Date.now()}.json`),
      JSON.stringify({ library, nodeID, workerLimits: node.workerLimits }, null, 2),
      { mode: 0o600, flag: 'wx' });
    await request('update-node', { data: { nodeID, nodeUpdates: { workerLimits: limits } } });
    const updatedNode = (await request('get-nodes', undefined, 'GET'))[nodeID];
    assert.deepEqual(updatedNode.workerLimits, limits);
    const persistedNode = await crud('NodeJSONDB', 'getById', { docID: node.nodeName });
    assert.deepEqual(persistedNode.workerLimits, limits);
    const settings = enabledLibrarySettings();
    await crud('LibrarySettingsJSONDB', 'update', { docID: LIBRARY_ID, obj: settings });
    const enabled = await crud('LibrarySettingsJSONDB', 'getById', { docID: LIBRARY_ID });
    for (const key of Object.keys(settings)) assert.deepEqual(enabled[key], settings[key]);
    console.log('Movies enabled: CPU classification, one GPU encode, existing CPU limits preserved.');
    console.log('Polling for new files every 10 minutes; new files held for 3 minutes.');
  }
}

module.exports = {
  flowDefinition, libraryDefinition, enabledLibrarySettings, gpuWorkerLimits,
  connect, FLOW_ID, LIBRARY_ID, ROOT,
};
if (require.main === module) {
  main().catch(error => {
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  });
}
