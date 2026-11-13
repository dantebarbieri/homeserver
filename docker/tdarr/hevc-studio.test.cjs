'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { prepare, encode, commit, encodeArgs, privateCopy, MAC_FFMPEG } = require('./hevc-studio-v1.cjs');
const { fingerprint } = require('./hevc-safe-v1.cjs');
const { flowDefinition, libraryDefinition, libraryTemplate, install, FLOW_ID, LIBRARY_ID, CANARY_FOLDER } = require('./install-studio-flow.cjs');
const { exclusions, restrict } = require('./restrict-studio-node.cjs');
const linux = { skip: process.platform !== 'linux' };
const notify = { pluginName: 'notifyRadarrOrSonarr', inputsDB: { arr: 'sonarr' } };

function probe(codec = 'h264') {
  return {
    format: { duration: '120', tags: { title: 'Episode' } },
    chapters: [{ start_time: '0', end_time: '120', tags: { title: 'Chapter' } }],
    streams: [
      { codec_type: 'video', codec_name: codec, width: 1920, height: 1080, pix_fmt: 'yuv420p10le',
        avg_frame_rate: '24000/1001', disposition: { default: 1 } },
      { codec_type: 'audio', codec_name: 'aac', channels: 2, sample_rate: '48000', tags: { language: 'eng' } },
      { codec_type: 'subtitle', codec_name: 'subrip', disposition: { forced: 1 }, tags: { title: 'Forced' } },
    ],
  };
}

async function fixture(t) {
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'tdarr-studio-test-')));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const media = path.join(root, 'media'), cacheRoot = path.join(root, 'cache'), privateRoot = path.join(root, 'private');
  for (const dir of [media, cacheRoot, privateRoot]) await fs.mkdir(dir, { mode: 0o700 });
  const source = path.join(media, 'source.mkv'), token = crypto.randomUUID(), id = crypto.randomUUID();
  await fs.writeFile(source, Buffer.alloc(1000, 1));
  const work = path.join(cacheRoot, token), output = path.join(work, 'result.mkv');
  await fs.mkdir(work);
  await fs.writeFile(output, Buffer.alloc(500, 2));
  const state = path.join(privateRoot, crypto.createHash('sha256').update(id).digest('hex'));
  await fs.mkdir(state, { mode: 0o700 });
  const manifest = { version: 1, jobId: id, libraryId: 'canary', root: media, token, crf: '20',
    saved: { source, fingerprint: fingerprint(await fs.stat(source)), probe: probe() } };
  await fs.writeFile(path.join(state, 'manifest.json'), JSON.stringify(manifest), { mode: 0o600 });
  const logs = [], calls = [];
  const args = {
    inputFileObj: { _id: output }, originalLibraryFile: { _id: source },
    job: { jobId: id }, librarySettings: { _id: 'canary', folder: media },
    variables: { homeserverStudio: { token, jobId: id, source, probe: probe(), crf: '20' } },
    workerType: 'transcodecpu', nodeTags: 'homeserver-storage', jobLog: line => logs.push(line),
  };
  const run = async (binary, argv) => {
    calls.push({ binary, argv });
    return { stdout: binary.endsWith('ffprobe') ? JSON.stringify(probe('hevc'))
      : 'out_time_us=120000000\nprogress=end\n' };
  };
  return { root, media, cacheRoot, privateRoot, source, token, work, output, state, manifest,
    args, logs, calls, injected: { privateRoot, cacheRoot, run } };
}

test('software quality arguments preserve library CRF, bit depth, streams, chapters and dispositions', () => {
  for (const quality of ['18', '20', '21.5']) {
    const argv = encodeArgs('/source', '/result.mkv', probe(), quality);
    const value = flag => argv[argv.indexOf(flag) + 1];
    assert.equal(value('-c:v:0'), 'libx265');
    assert.equal(value('-preset:v:0'), 'slow');
    assert.equal(value('-crf:v:0'), quality);
    assert.equal(value('-x265-params:v:0'), 'pools=4');
    assert.equal(value('-pix_fmt:v:0'), 'yuv420p10le');
    assert.equal(value('-fps_mode:v:0'), 'passthrough');
    assert.equal(value('-c'), 'copy');
    for (const flag of ['-map', '-map_metadata', '-map_chapters']) assert.equal(value(flag), '0');
    assert.equal(value('-disposition:1'), '0');
    assert.equal(value('-disposition:2'), 'forced');
    assert(argv.includes('-n'));
    assert(!argv.some(v => /videotoolbox|cuda|nvenc|scale|tonemap/.test(v)));
  }
  for (const quality of [undefined, '', '-1', '52', '20 -preset fast']) {
    assert.throws(() => encodeArgs('/source', '/result', probe(), quality), /CRF/);
  }
  const p = probe();
  p.streams.unshift({ codec_type: 'video', codec_name: 'mjpeg', disposition: { attached_pic: 1 } });
  assert(encodeArgs('/source', '/result', p, '20').includes('-c:v:1'));
});

test('canary flow gates both Linux steps and Mac encode; benign skip cannot notify or publish', () => {
  const flow = flowDefinition(notify);
  assert.deepEqual(flow.flowPlugins.filter(p => p.pluginName === 'tagsWorkerType').map(p => p.inputsDB), [
    { requiredWorkerType: 'CPU', requiredNodeTags: 'homeserver-storage' },
    { requiredWorkerType: 'CPU', requiredNodeTags: 'studio-native' },
    { requiredWorkerType: 'CPU', requiredNodeTags: 'homeserver-storage' },
  ]);
  assert(flow.flowEdges.every(e => e.sourceHandle === '1'));
  assert(!flow.flowPlugins.some(p => ['replaceOriginalFile', 'ffmpegCommandExecute'].includes(p.pluginName)));
  assert.match(flow.flowPlugins.find(p => p.id === 'encode').inputsDB.code, /\/var\/lib\/studio-worker\/tdarr\/Custom/);
  const library = libraryDefinition({ decisionMaker: {}, schedule: [] });
  assert.equal(library.folder, CANARY_FOLDER);
  assert.equal(library.flowId, FLOW_ID);
  for (const key of ['processLibrary', 'processTranscodes', 'processHealthChecks', 'folderWatching',
    'useFsEvents', 'scheduledScanFindNew', 'scanOnStart']) assert.equal(library[key], false);
});

test('Linux prepare captures a private authoritative contract and retains per-library CRF', linux, async t => {
  const f = await fixture(t);
  await fs.rm(f.state, { recursive: true });
  const source = await fs.open(f.source, 'r+');
  await source.truncate(101 * 1024 ** 2);
  await source.close();
  await fs.utimes(f.source, new Date(0), new Date(0));
  f.args.inputFileObj = f.args.originalLibraryFile;
  f.args.userVariables = { library: { crf: '18' } };
  const injected = { ...f.injected, run: async () => ({ stdout: JSON.stringify(probe()) }) };
  const result = await prepare(f.args, injected);
  assert.equal(result.outputNumber, 1);
  const saved = JSON.parse(await fs.readFile(path.join(f.state, 'manifest.json'), 'utf8'));
  assert.equal(saved.crf, '18');
  assert.equal(saved.saved.source, f.source);
  assert.equal((await fs.stat(f.state)).mode & 0o077, 0);
  assert.equal((await fs.stat(path.join(f.state, 'manifest.json'))).mode & 0o077, 0);
  assert(!f.args.variables.homeserverSafeHevc);
  assert.equal(f.args.variables.homeserverStudio.crf, '18');
  await assert.rejects(prepare(f.args, injected), /EEXIST/);
});

test('runtime guards reject a wrong worker, platform, binary and missing CRF', linux, async t => {
  const f = await fixture(t);
  await assert.rejects(commit({ ...f.args, nodeTags: 'studio-native' }, f.injected), /homeserver-storage/);
  await assert.rejects(commit(f.args, { ...f.injected, platform: 'darwin' }), /requires linux/);
  await assert.rejects(encode({ ...f.args, nodeTags: 'studio-native' },
    { ...f.injected, platform: 'darwin', arch: 'arm64' }), /Homebrew/);
  await assert.rejects(prepare(f.args, f.injected), /preparation/);
  await assert.rejects(prepare({ ...f.args, inputFileObj: f.args.originalLibraryFile }, f.injected), /CRF/);
});

test('native encoder uses only mapped source and expected job result', linux, async t => {
  const f = await fixture(t);
  await fs.unlink(f.output);
  f.args.inputFileObj = f.args.originalLibraryFile;
  f.args.nodeTags = 'studio-native';
  f.args.ffmpegPath = MAC_FFMPEG;
  const result = await encode(f.args, { ...f.injected, platform: 'darwin', arch: 'arm64',
    macCache: f.cacheRoot, macMedia: f.media });
  assert.equal(result.outputFileObj._id, f.output);
  assert.equal(f.calls[0].binary, MAC_FFMPEG);
  f.args.variables.homeserverStudio.jobId = 'another-job';
  await assert.rejects(encode(f.args, { ...f.injected, platform: 'darwin', arch: 'arm64' }), /ticket/);
});

test('native mappings permit the macOS /var root alias but reject symlinks below mapped roots', linux, async t => {
  const f = await fixture(t);
  const alias = path.join(f.root, 'var-alias');
  await fs.symlink(f.root, alias);
  const macMedia = path.join(alias, 'media'), macCache = path.join(alias, 'cache');
  const source = path.join(macMedia, 'source.mkv');
  f.args.inputFileObj = f.args.originalLibraryFile = { _id: source };
  f.args.variables.homeserverStudio.source = source;
  f.args.nodeTags = 'studio-native';
  f.args.ffmpegPath = MAC_FFMPEG;
  const injected = { ...f.injected, platform: 'darwin', arch: 'arm64', macMedia, macCache };
  assert.equal((await encode(f.args, injected)).outputFileObj._id, path.join(macCache, f.token, 'result.mkv'));
  await fs.rename(f.work, `${f.work}-other`);
  await fs.symlink(`${f.work}-other`, f.work);
  await assert.rejects(encode(f.args, injected), /cache directory/);
  await fs.unlink(f.source);
  await fs.writeFile(path.join(f.root, 'other.mkv'), 'other');
  await fs.symlink(path.join(f.root, 'other.mkv'), f.source);
  await assert.rejects(encode(f.args, injected), /read-only source/);
});

test('native encoding is tracked by Tdarr CLI and refuses missing helpers or failed/cancelled encoding', linux, async t => {
  const f = await fixture(t);
  f.args.inputFileObj = f.args.originalLibraryFile;
  f.args.nodeTags = 'studio-native';
  f.args.ffmpegPath = MAC_FFMPEG;
  const injected = { ...f.injected, run: undefined, platform: 'darwin', arch: 'arm64',
    macCache: f.cacheRoot, macMedia: f.media };
  await assert.rejects(encode(f.args, injected), /untracked encode/);
  f.args.config = { pluginsPath: '/installed/plugins' };
  let code = 0, configuration, cancelled = false;
  const controller = new AbortController();
  class CLI {
    constructor(config) { configuration = config; }
    async runCli() {
      if (f.args.signal) controller.abort();
      return { cliExitCode: code };
    }
    killThread() { cancelled = true; }
  }
  injected.CLI = CLI;
  await encode(f.args, injected);
  assert.equal(configuration.outputFilePath, f.output);
  assert.equal(configuration.cli, MAC_FFMPEG);
  code = 1;
  await assert.rejects(encode(f.args, injected), /exited 1/);
  f.args.signal = controller.signal;
  await assert.rejects(encode(f.args, injected), /abort/i);
  assert(cancelled);
});

test('untrusted path escapes, per-job mismatches and forged contracts cannot publish', linux, async t => {
  for (const change of [
    f => { f.args.inputFileObj._id = path.join(f.work, '..', 'result.mkv'); },
    f => { f.args.inputFileObj._id = f.source; },
    f => { f.args.variables.homeserverStudio.token = '../escape'; },
    f => { f.args.job.jobId = 'different'; },
    f => { f.args.librarySettings._id = 'different'; },
    f => { f.args.originalLibraryFile._id = path.join(f.media, 'other.mkv'); },
  ]) {
    const f = await fixture(t);
    change(f);
    await assert.rejects(commit(f.args, f.injected));
    assert.equal((await fs.stat(f.source)).size, 1000);
    assert.equal(f.calls.length, 0);
  }
  const f = await fixture(t);
  f.args.variables.homeserverSafeHevc = { source: '/forged', fingerprint: {}, probe: {} };
  f.args.variables.homeserverStudio.probe = {};
  await commit(f.args, f.injected);
  assert.equal((await fs.stat(f.source)).size, 500, 'private manifest, not returned variables, is authoritative');
});

test('private copy rejects directory/leaf symlinks, hardlinks, nonregular and oversized output', linux, async t => {
  for (const kind of ['leaf', 'directory', 'hardlink', 'nonregular', 'oversized', 'escape']) {
    const f = await fixture(t), target = path.join(f.state, 'copy.mkv');
    if (kind === 'directory') {
      await fs.rename(f.work, `${f.work}-other`);
      await fs.symlink(`${f.work}-other`, f.work);
    } else {
      await fs.unlink(f.output);
      if (kind === 'leaf') await fs.symlink(f.source, f.output);
      if (kind === 'hardlink') await fs.link(f.source, f.output);
      if (kind === 'nonregular') await fs.mkdir(f.output);
      if (kind === 'oversized') await fs.writeFile(f.output, Buffer.alloc(2001));
    }
    await assert.rejects(privateCopy(f.cacheRoot, kind === 'escape' ? '../escape' : f.token, target, 2000));
    assert.equal((await fs.stat(f.source)).size, 1000);
    await assert.rejects(fs.access(target), /ENOENT/);
  }
});

test('shared bytes changed during validation never affect the private bytes that are published', linux, async t => {
  const f = await fixture(t);
  const run = f.injected.run;
  f.injected.run = async (binary, argv) => {
    const file = binary.endsWith('ffprobe') ? argv.at(-1) : argv[argv.indexOf('-i') + 1];
    assert.equal(file, path.join(f.state, 'validated.mkv'));
    assert.equal((await fs.readFile(file))[0], 2);
    await fs.writeFile(f.output, Buffer.alloc(600, 9));
    return run(binary, argv);
  };
  const result = await commit(f.args, f.injected);
  assert.equal(result.outputNumber, 1);
  assert.deepEqual(await fs.readFile(f.source), Buffer.alloc(500, 2));
  await assert.rejects(fs.access(path.join(f.state, 'validated.mkv')), /ENOENT/);
  await assert.rejects(fs.access(f.work), /ENOENT/);
  assert.equal(JSON.parse(await fs.readFile(path.join(f.state, 'outcome.json'))).outputNumber, 1);
  await assert.rejects(commit(f.args, f.injected), /manifest|EEXIST/);
});

test('pinned source handle prevents leaf replacement from redirecting the private copy', linux, async t => {
  const f = await fixture(t);
  const originalOpen = fs.open;
  let replaced = false;
  fs.open = async (...argv) => {
    const handle = await originalOpen(...argv);
    if (String(argv[0]).endsWith('/result.mkv') && String(argv[0]).startsWith('/proc/self/fd/')) {
      await fs.rename(f.output, `${f.output}.old`);
      await fs.symlink(f.source, f.output);
      replaced = true;
    }
    return handle;
  };
  try {
    await privateCopy(f.cacheRoot, f.token, path.join(f.state, 'copy.mkv'), 2000);
  } finally { fs.open = originalOpen; }
  assert(replaced);
  assert.deepEqual(await fs.readFile(path.join(f.state, 'copy.mkv')), Buffer.alloc(500, 2));
});

test('private copy streams multiple chunks and rejects mutation of the opened output', linux, async t => {
  const f = await fixture(t);
  const bytes = Buffer.alloc(2 * 1024 * 1024 + 17, 7);
  bytes[1024 * 1024] = 8;
  await fs.writeFile(f.output, bytes);
  const target = path.join(f.state, 'copy.mkv');
  await privateCopy(f.cacheRoot, f.token, target, bytes.length);
  assert.deepEqual(await fs.readFile(target), bytes);
  const originalOpen = fs.open;
  fs.open = async (...argv) => {
    const handle = await originalOpen(...argv);
    if (String(argv[0]).endsWith('/result.mkv') && String(argv[0]).startsWith('/proc/self/fd/')) {
      const read = handle.read.bind(handle);
      let mutated = false;
      handle.read = async (...parameters) => {
        const result = await read(...parameters);
        if (!mutated) { await fs.appendFile(f.output, 'changed'); mutated = true; }
        return result;
      };
    }
    return handle;
  };
  try {
    await assert.rejects(privateCopy(f.cacheRoot, f.token, path.join(f.state, 'mutated.mkv'), bytes.length),
      /changed during private copy/);
  } finally { fs.open = originalOpen; }
});

test('no saving, corrupt decode and changed originals never replace source', linux, async t => {
  for (const kind of ['savings', 'decode', 'truncation', 'source']) {
    const f = await fixture(t), run = f.injected.run;
    if (kind === 'savings') await fs.writeFile(f.output, Buffer.alloc(960, 2));
    f.injected.run = async (binary, argv) => {
      if (binary.endsWith('ffmpeg')) {
        if (kind === 'decode') throw new Error('decode failed');
        if (kind === 'truncation') return { stdout: 'out_time_us=0\n' };
        if (kind === 'source') await fs.appendFile(f.source, 'changed');
      }
      return run(binary, argv);
    };
    if (kind === 'savings') assert.equal((await commit(f.args, f.injected)).outputNumber, 2);
    else await assert.rejects(commit(f.args, f.injected));
    const handle = await fs.open(f.source);
    try {
      const buffer = Buffer.alloc(1000);
      await handle.read(buffer);
      assert.deepEqual(buffer, Buffer.alloc(1000, 1));
    } finally { await handle.close(); }
  }
});

test('installer creates only disabled canary records and never updates real libraries or workers', async () => {
  const records = {
    FlowsJSONDB: [{ _id: 'homeserver-hevc-cpu-v1', flowPlugins: [notify] }],
    LibrarySettingsJSONDB: [{ _id: 'real-tv', flowId: 'homeserver-hevc-cpu-v1', processLibrary: true }],
    VariablesJSONDB: [{ _id: 'real-crf', key: 'crf', value: '18', type: 'library:real-tv' }],
  };
  const before = structuredClone(records), writes = [], files = [];
  const crud = async (collection, mode, { docID, obj } = {}) => {
    if (mode === 'getAll') return structuredClone(records[collection]);
    if (mode === 'getById') return records[collection].find(r => r._id === docID);
    assert.equal(mode, 'insert');
    writes.push({ collection, docID });
    records[collection].push(obj);
  };
  const io = { access: async () => {}, mkdir: async () => {},
    writeFile: async (...argv) => files.push(argv) };
  const options = { crud, defaults: { decisionMaker: {}, schedule: [] }, log: () => {}, io };
  await install(options);
  assert.equal(writes.length, 0);
  await install({ ...options, apply: true });
  assert.deepEqual(records.LibrarySettingsJSONDB[0], before.LibrarySettingsJSONDB[0]);
  assert.deepEqual(records.VariablesJSONDB[0], before.VariablesJSONDB[0]);
  assert.equal(writes.length, 3);
  assert(writes.every(w => w.docID === FLOW_ID || w.docID.startsWith(LIBRARY_ID)));
  assert.equal(files[0][2].mode, 0o600);
  await install({ ...options, apply: true });
  assert.equal(writes.length, 3, 'idempotent installer must not overwrite versioned modules or settings');
  records.LibrarySettingsJSONDB[1].processLibrary = true;
  await assert.rejects(install({ ...options, apply: true }), /already enabled/);
});

test('Tdarr 3.07 installer uses existing safe library schema without importing removed JavaScript defaults', () => {
  const original = {
    _id: 'Io-wVbVRh', flowId: 'homeserver-hevc-cpu-v1', schedule: [{ checked: true }],
    decisionMaker: { settingsFlows: true, settingsPlugin: false }, foldersToIgnore: '/original/exclusion',
    processLibrary: true, folderWatching: true, totalTranscodeCount: 123,
  };
  const copy = structuredClone(original);
  const canary = libraryDefinition(libraryTemplate([original]));
  assert.equal(canary.processLibrary, false);
  assert.equal(canary.folderWatching, false);
  assert.equal(canary.totalTranscodeCount, 0);
  assert.equal(canary.foldersToIgnore, '');
  assert.deepEqual(canary.schedule, original.schedule);
  assert.deepEqual(original, copy);
  assert.throws(() => libraryTemplate([{ ...original, flowId: 'different' }]), /template/);
  assert.throws(() => libraryTemplate([{ ...original, schedule: undefined }]), /template/);
});

test('native exclusions include every current non-canary library but are not a future-library allowlist', () => {
  const libraries = [{ _id: 'tv' }, { _id: 'dv5' },
    { _id: LIBRARY_ID, flowId: FLOW_ID, folder: CANARY_FOLDER }];
  const result = exclusions(libraries, { retired: true, tv: false });
  assert.deepEqual(result, { retired: true, tv: true, dv5: true, [LIBRARY_ID]: false });
  assert.equal(result['future-library'], undefined);
  assert.throws(() => exclusions(libraries.slice(0, 2)), /canary/);
});

test('restriction utility changes only exclusions, verifies persistence and leaves native node paused', async () => {
  const libraries = [{ _id: 'tv' }, { _id: LIBRARY_ID, flowId: FLOW_ID, folder: CANARY_FOLDER,
    processLibrary: false, processTranscodes: false }];
  const initial = { nodeName: 'StudioNative', nodePaused: true, nodeTags: 'studio-native',
    workerLimits: { transcodecpu: 1, transcodegpu: 0, healthcheckcpu: 0, healthcheckgpu: 0 },
    allowGpuDoCpu: false, librariesToNotProcess: {} };
  let node = structuredClone(initial), persisted = structuredClone(initial);
  const writes = [], backups = [];
  const crud = async (collection, mode) => {
    if (collection === 'LibrarySettingsJSONDB' && mode === 'getAll') return structuredClone(libraries);
    assert.equal(collection, 'NodeJSONDB');
    assert.equal(mode, 'getById');
    return structuredClone(persisted);
  };
  const request = async (endpoint, payload) => {
    if (endpoint === 'get-nodes') return { nativeID: structuredClone(node) };
    assert.equal(endpoint, 'update-node');
    assert.equal(payload.data.nodeID, 'nativeID');
    assert.deepEqual(Object.keys(payload.data.nodeUpdates), ['librariesToNotProcess']);
    writes.push(payload);
    Object.assign(node, payload.data.nodeUpdates);
    Object.assign(persisted, payload.data.nodeUpdates);
  };
  const options = { crud, request, nodeName: initial.nodeName, log: () => {},
    io: { mkdir: async () => {}, writeFile: async (...args) => backups.push(args) } };
  await restrict(options);
  assert.equal(writes.length, 0);
  await restrict({ ...options, apply: true });
  assert.equal(writes.length, 1);
  assert.equal(backups[0][2].mode, 0o600);
  assert.equal(node.nodePaused, true);
  assert.deepEqual(node.workerLimits, initial.workerLimits);
  assert.deepEqual(persisted.librariesToNotProcess, { tv: true, [LIBRARY_ID]: false });
  node.nodePaused = false;
  await assert.rejects(restrict({ ...options, apply: true }), /paused/);
  assert.equal(writes.length, 1);
});

test('restriction utility refuses changed inventories and failed persistence while never unpausing', async () => {
  for (const failure of ['inventory', 'persistence']) {
    const libraries = [{ _id: LIBRARY_ID, flowId: FLOW_ID, folder: CANARY_FOLDER,
      processLibrary: false, processTranscodes: false }];
    const node = { nodeName: 'Studio', nodePaused: true, nodeTags: 'studio-native', allowGpuDoCpu: false,
      librariesToNotProcess: {}, workerLimits: { transcodecpu: 1 } };
    let reads = 0, writes = 0;
    const options = {
      nodeName: 'Studio', apply: true, log: () => {},
      io: { mkdir: async () => {}, writeFile: async () => {} },
      crud: async collection => {
        if (collection === 'NodeJSONDB') return structuredClone(node);
        reads++;
        return failure === 'inventory' && reads > 1 ? [...libraries, { _id: 'new' }] : libraries;
      },
      request: async (endpoint, payload) => {
        if (endpoint === 'get-nodes') return { id: structuredClone(node) };
        assert.deepEqual(Object.keys(payload.data.nodeUpdates), ['librariesToNotProcess']);
        writes++;
      },
    };
    await assert.rejects(restrict(options), failure === 'inventory' ? /inventory changed/ : /not applied/);
    assert.equal(writes, failure === 'inventory' ? 0 : 1);
    assert.equal(node.nodePaused, true);
  }
});
