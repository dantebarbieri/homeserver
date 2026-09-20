'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { flowDefinition, libraryDefinition, FLOW_ID, LIBRARY_ID } = require('./install-flow.cjs');

test('flow has no original replacement or compression branch', () => {
  const flow = flowDefinition();
  assert.equal(flow._id, FLOW_ID);
  assert.deepEqual(flow.flowPlugins.map(node => node.pluginName), ['inputFile', 'customFunction']);
  assert.match(flow.flowPlugins[1].inputsDB.code, /dv5-sidecar\.cjs/);
  assert.equal(flow.flowEdges.length, 1);
  assert.equal(flow.flowEdges[0].target, flow.flowPlugins[1].id);
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
