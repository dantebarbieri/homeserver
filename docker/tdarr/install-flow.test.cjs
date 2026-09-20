'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  flowDefinition, libraryDefinition, enabledLibrarySettings, gpuWorkerLimits,
  FLOW_ID, LIBRARY_ID,
} = require('./install-flow.cjs');

test('flow has no original replacement or compression branch', () => {
  const flow = flowDefinition();
  assert.equal(flow._id, FLOW_ID);
  assert.deepEqual(flow.flowPlugins.map(node => node.pluginName),
    ['inputFile', 'customFunction', 'tagsWorkerType', 'customFunction']);
  assert.match(flow.flowPlugins[1].inputsDB.code, /dv5-sidecar\.cjs/);
  assert.match(flow.flowPlugins[1].inputsDB.code, /\.classify\(args\)/);
  assert.equal(flow.flowPlugins[2].inputsDB.requiredWorkerType, 'GPU');
  assert.equal(flow.flowEdges.length, 3);
  assert.equal(flow.flowEdges[0].target, flow.flowPlugins[1].id);
  assert.ok(flow.flowEdges.every(edge => edge.sourceHandle === '1'));
  assert.equal(flow.flowEdges[1].target, 'gpu-worker');
  assert.equal(flow.flowEdges[2].target, 'dv5-sidecar');
});

test('new library retains defaults but cannot start a backlog or replace sources', () => {
  const defaults = {
    schedule: [true, false],
    decisionMaker: { settingsFlows: false, settingsPlugin: true, unrelated: 'keep' },
    unrelated: { value: 1 },
    filterCodecsSkip: 'hevc',
  };
  const library = libraryDefinition(defaults);
  assert.equal(library._id, LIBRARY_ID);
  assert.equal(library.flowId, FLOW_ID);
  assert.equal(library.folder, '/data/media/movies');
  for (const key of [
    'processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching',
    'useFsEvents', 'scheduledScanFindNew', 'scanOnStart', 'holdNewFiles',
    'folderToFolderConversion', 'folderToFolderConversionDeleteSource', 'copyIfConditionsMet',
  ]) assert.equal(library[key], false, key);
  assert.equal(library.filterCodecsSkip, '');
  assert.equal(library.decisionMaker.unrelated, 'keep');
  assert.equal(library.decisionMaker.settingsFlows, true);
  assert.equal(library.decisionMaker.settingsPlugin, false);
  library.schedule.push(true);
  library.unrelated.value = 2;
  assert.deepEqual(defaults.schedule, [true, false]);
  assert.equal(defaults.unrelated.value, 1);
});

test('explicit enablement watches originals with a settling delay and no health-check backlog', () => {
  const settings = enabledLibrarySettings();
  assert.equal(settings.processLibrary, true);
  assert.equal(settings.processTranscodes, true);
  assert.equal(settings.processHealthChecks, false);
  assert.equal(settings.folderWatching, true);
  assert.equal(settings.foldersToIgnore, 'Plex Versions');
  assert.equal(settings.holdNewFiles, true);
  assert.ok(settings.holdFor >= 120);
  assert.equal(settings.folderWatchScanInterval, 600);
});

test('single GPU limit preserves CPU limits and rejects incompatible routing', () => {
  const node = {
    gpuSelect: '-', allowGpuDoCpu: false,
    workerLimits: { transcodecpu: 4, healthcheckcpu: 4, transcodegpu: 0, healthcheckgpu: 0 },
  };
  assert.deepEqual(gpuWorkerLimits(node), { ...node.workerLimits, transcodegpu: 1 });
  assert.equal(node.workerLimits.transcodegpu, 0);
  assert.throws(() => gpuWorkerLimits({ ...node, gpuSelect: 'nvenc' }), /generic GPU/);
  assert.throws(() => gpuWorkerLimits({ ...node, allowGpuDoCpu: true }), /CPU jobs/);
});
