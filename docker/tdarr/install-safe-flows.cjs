#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const assert = require('node:assert/strict');
const { connect, ROOT } = require('./install-flow.cjs');

const FLOW_ID = 'homeserver-hevc-cpu-v1';
function flowDefinition(notify) {
  const plugin = (id, name, pluginName, inputsDB = {}) => ({
    id, name, pluginName, inputsDB, sourceRepo: 'Community', version: '1.0.0',
    fpEnabled: true, position: { x: 0, y: 120 * nodes.length },
  });
  const nodes = [];
  nodes.push(plugin('input', 'Input file', 'inputFile'));
  nodes.push(plugin('cpu', 'CPU workers only', 'tagsWorkerType', { requiredWorkerType: 'CPU', requiredNodeTags: '' }));
  nodes.push(plugin('prepare', 'Eligible SDR source and identity', 'customFunction', {
    code: `module.exports = async args => require('${ROOT}/hevc-safe-v1.cjs').prepare(args);`,
  }));
  nodes.push(plugin('begin', 'Begin command', 'ffmpegCommandStart'));
  nodes.push(plugin('encode', 'Software HEVC slow; preserve CRF', 'ffmpegCommandSetVideoEncoder', {
    outputCodec: 'hevc', hardwareEncoding: 'false', forceEncoding: 'false',
    ffmpegPreset: 'slow', ffmpegQuality: '{{{args.userVariables.library.crf}}}',
  }));
  nodes.push(plugin('threads', 'Bound x265 thread pool', 'ffmpegCommandCustomArguments', {
    outputArguments: '-x265-params pools=4',
  }));
  nodes.push(plugin('container', 'Matroska without dropping streams', 'ffmpegCommandSetContainer', {
    container: 'mkv', forceConform: 'false',
  }));
  nodes.push(plugin('execute', 'Encode', 'ffmpegCommandExecute'));
  nodes.push(plugin('commit', 'Verify complete decode and safely replace', 'customFunction', {
    code: `module.exports = async args => require('${ROOT}/hevc-safe-v1.cjs').commit(args);`,
  }));
  nodes.push({ ...structuredClone(notify), id: 'notify', position: { x: 0, y: 1080 } });
  return {
    _id: FLOW_ID, name: 'Homeserver - safe SDR HEVC CPU compression', priority: 0,
    flowPlugins: nodes,
    flowEdges: nodes.slice(0, -1).map((node, i) => ({
      source: node.id, sourceHandle: '1', target: nodes[i + 1].id, targetHandle: null,
      id: `${node.id}-to-${nodes[i + 1].id}`, animated: true, type: 'smoothstep',
    })),
  };
}

async function main() {
  assert.deepEqual(process.argv.slice(2), ['--apply'], 'Usage: node install-safe-flows.cjs --apply');
  const { crud } = await connect();
  const [flows, libraries, global] = await Promise.all([
    crud('FlowsJSONDB', 'getAll'), crud('LibrarySettingsJSONDB', 'getAll'),
    crud('SettingsGlobalJSONDB', 'getById', { docID: 'globalsettings' }),
  ]);
  const previous = flows.find(f => f._id === 'zRnXMGq83');
  const notify = previous?.flowPlugins.find(n => n.pluginName === 'notifyRadarrOrSonarr');
  assert(notify, 'Existing Sonarr notification configuration is missing');
  const targets = libraries.filter(l => ['Io-wVbVRh', 'UU_64_3Ax', 'GHlz7HL1P'].includes(l._id));
  assert.equal(targets.length, 3, 'Expected exactly the three existing TV libraries');
  assert(targets.every(l => [previous._id, FLOW_ID].includes(l.flowId)), 'A TV library uses an unexpected flow');
  await fs.access(`${ROOT}/hevc-safe-v1.cjs`);
  const backup = `${ROOT}/backups/safe-flows-${Date.now()}.json`;
  await fs.writeFile(backup, JSON.stringify({ flows, libraries, global }, null, 2), { flag: 'wx', mode: 0o600 });
  const desired = flowDefinition(notify);
  await crud('FlowsJSONDB', flows.some(f => f._id === FLOW_ID) ? 'update' : 'insert', {
    docID: FLOW_ID, obj: desired,
  });
  const stored = await crud('FlowsJSONDB', 'getById', { docID: FLOW_ID });
  for (const key of Object.keys(desired)) assert.deepEqual(stored[key], desired[key]);
  for (const library of targets) {
    const skipped = [...new Set([...(library.filterCodecsSkip || '').split(',').filter(Boolean), 'hevc', 'av1', 'vp9'])].join(',');
    const settings = {
      flowId: FLOW_ID, filterCodecsSkip: skipped, holdNewFiles: true, holdFor: 180, holdForDisplayUnit: 'minutes',
    };
    await crud('LibrarySettingsJSONDB', 'update', { docID: library._id, obj: settings });
    const readback = await crud('LibrarySettingsJSONDB', 'getById', { docID: library._id });
    for (const key of Object.keys(settings)) assert.deepEqual(readback[key], settings[key]);
    console.log(`Configured ${library.name}: safe CPU flow, efficient-codec exclusions and settling delay`);
  }
  const scheduling = { alternateLibraries: true, prioritiseLibraries: false, autoPauseIfCacheFull: true };
  await crud('SettingsGlobalJSONDB', 'update', { docID: 'globalsettings', obj: scheduling });
  const settings = await crud('SettingsGlobalJSONDB', 'getById', { docID: 'globalsettings' });
  for (const key of Object.keys(scheduling)) assert.deepEqual(settings[key], scheduling[key]);
  console.log(`Verified flow and fair scheduling. Sensitive rollback snapshot: ${backup}`);
  console.log('Existing flow is retained for in-flight jobs. CRF, preset and bit-depth policy are unchanged.');
}

module.exports = { flowDefinition, FLOW_ID };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
