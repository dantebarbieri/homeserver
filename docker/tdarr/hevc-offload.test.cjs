'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {
  prepare, finish, commit, privateCopy, sweep, jobId, relative, JOBS, MAC_FFMPEG, MAC_FFPROBE,
} = require('./hevc-offload-v2.cjs');
const { fingerprint, validate } = require('./hevc-safe-v1.cjs');
const { internals: { runProcess } } = require('./dv5-sidecar.cjs');

// The Mac legs run on macOS and the publication leg on Linux, so each is skipped where it cannot run.
const linux = { skip: process.platform !== 'linux' };
const posix = { skip: process.platform === 'win32' };
const MIB = 1024 ** 2;
const OLD = new Date('2024-01-01T00:00:00Z');
const OLD_SEC = OLD.getTime() / 1000;
const FFMPEG = '/usr/lib/jellyfin-ffmpeg/ffmpeg';
const FFPROBE = '/usr/lib/jellyfin-ffmpeg/ffprobe';
const exists = file => fs.access(file).then(() => true, () => false);

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

// A sparse file: large enough for the compression-size policy without writing the bytes.
async function sparse(file, size, byte = 2) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, Buffer.alloc(Math.min(size, 1000), byte));
  await fs.truncate(file, size);
}

async function fixture(t, { name = 'Show S01E01.mkv', size = 101 * MIB, create = true } = {}) {
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'tdarr-offload-test-')));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const media = path.join(root, 'media'), library = path.join(media, 'tv');
  const cacheRoot = path.join(root, 'cache'), privateRoot = path.join(root, 'private');
  await fs.mkdir(library, { recursive: true });
  await fs.mkdir(cacheRoot, { mode: 0o700 });
  await fs.mkdir(privateRoot, { mode: 0o700 });
  const source = path.join(library, name);
  if (create) {
    await sparse(source, size, 1);
    await fs.utimes(source, OLD, OLD);
  }
  const relpath = relative(source, media), id = jobId(relpath), job = path.join(cacheRoot, JOBS, id);
  const workDir = path.join(cacheRoot, 'tdarr-workDir2-test');
  const f = {
    root, media, library, cacheRoot, privateRoot, name, source, size, relpath, id, job,
    result: path.join(job, 'result.mkv'), workDir,
    stale: path.join(workDir, '1700000000000', `${path.basename(name, path.extname(name))}.mkv`),
    logs: [], calls: [], sourceCodec: 'h264', outputCodec: 'hevc',
  };
  f.run = async (binary, argv) => {
    f.calls.push({ binary, argv });
    if (binary.endsWith('ffprobe')) {
      return { stdout: JSON.stringify(probe(argv.at(-1) === source ? f.sourceCodec : f.outputCodec)) };
    }
    return { stdout: 'out_time_us=120000000\nprogress=end\n' };
  };
  f.args = {
    inputFileObj: { _id: f.stale }, originalLibraryFile: { _id: source }, librarySettings: { folder: library },
    variables: {}, workerType: 'transcodegpu', jobLog: line => f.logs.push(line),
  };
  f.injected = { mediaRoot: media, cacheRoot, privateRoot, run: f.run };
  return f;
}

const mac = (f, extra = {}) => ({
  platform: 'darwin', arch: 'arm64', macMedia: f.media, macCache: f.cacheRoot, run: f.run, ...extra,
});
const macArgs = (f, extra = {}) => ({
  inputFileObj: { _id: f.source }, originalLibraryFile: { _id: f.source }, workerType: 'transcodecpu',
  ffmpegPath: MAC_FFMPEG, userVariables: { library: { crf: '20' } }, variables: {},
  jobLog: line => f.logs.push(line), ...extra,
});

// What the encode step leaves behind in its work directory, with the ticket `prepare` saved.
async function encoded(f, bytes = 500) {
  await sparse(f.stale, bytes);
  const args = macArgs(f, { inputFileObj: { _id: f.stale } });
  args.variables.homeserverOffload = { relpath: f.relpath, source: { size: f.size, mtimeSec: OLD_SEC }, probe: probe() };
  return args;
}

// What the Mac leaves on the shared cache for the Linux leg.
async function handover(f, { size = 500, bytes, manifest = {} } = {}) {
  await fs.rm(f.job, { recursive: true, force: true });
  await fs.mkdir(path.dirname(f.job), { recursive: true });
  await fs.mkdir(f.job);
  if (bytes) await fs.writeFile(f.result, bytes); else await sparse(f.result, size);
  const stat = await fs.stat(f.source);
  await fs.writeFile(path.join(f.job, 'manifest.json'), JSON.stringify({
    version: 1, relpath: f.relpath, source: { size: stat.size, mtimeSec: Math.floor(stat.mtimeMs / 1000) },
    resultSize: bytes ? bytes.length : size, finishedAt: new Date().toISOString(), ...manifest,
  }), { mode: 0o600 });
}

function intercept(f, hook) {
  const run = f.run;
  f.injected.run = async (binary, argv, options) => (await hook(binary, argv)) || run(binary, argv, options);
}

async function untouched(f) {
  assert.equal((await fs.stat(f.source)).size, f.size);
  const handle = await fs.open(f.source);
  try {
    const buffer = Buffer.alloc(1000);
    await handle.read(buffer, 0, 1000, 0);
    assert.deepEqual(buffer, Buffer.alloc(1000, 1));
  } finally { await handle.close(); }
  assert.deepEqual(await fs.readdir(f.library), [f.name]);
  assert.deepEqual(await fs.readdir(f.privateRoot), []);
}

const probedFile = call => call.argv.at(call.binary.endsWith('ffprobe') ? -1 : call.argv.indexOf('-i') + 1);
const forcesMatroska = call => {
  const format = call.argv.indexOf('-f');
  return call.argv[format + 1] === 'matroska' && format < call.argv.indexOf(probedFile(call));
};

test('relative paths are NFC-normalized, confined to the media root and hashed into a stable job id', posix, () => {
  assert.equal(relative('/m/tv/Pok\u00e9mon.mkv', '/m'), 'tv/Pok\u00e9mon.mkv');
  assert.equal(relative('/m/tv/Poke\u0301mon.mkv', '/m'), 'tv/Pok\u00e9mon.mkv');
  for (const bad of ['/m', '/', '/other/a.mkv', '/m/../a.mkv', 'tv/a.mkv', '/m/tv//a.mkv', '/mx/a.mkv']) {
    assert.throws(() => relative(bad, '/m'), /outside the media root/, bad);
  }
  assert.match(jobId('tv/a.mkv'), /^[0-9a-f]{32}$/);
  assert.notEqual(jobId('tv/a.mkv'), jobId('tv/b.mkv'));
  assert.equal(jobId('tv/Pok\u00e9mon.mkv'), jobId(relative('/m/tv/Poke\u0301mon.mkv', '/m')));
});

test('Mac legs refuse any other platform, architecture, worker, FFmpeg or library CRF', posix, async t => {
  const f = await fixture(t);
  for (const leg of [prepare, finish]) {
    for (const [overrides, extra, pattern] of [
      [{ platform: 'linux' }, {}, /native Apple Silicon/],
      [{ arch: 'x64' }, {}, /native Apple Silicon/],
      [{}, { workerType: 'transcodegpu' }, /CPU worker/],
      [{}, { ffmpegPath: 'tdarr-ffmpeg' }, /Homebrew/],
    ]) await assert.rejects(leg(macArgs(f, extra), mac(f, overrides)), pattern);
  }
  for (const value of [undefined, '', '-1', '52', '20 -preset fast', '1e1']) {
    const args = macArgs(f, { userVariables: { library: { crf: value } } });
    await assert.rejects(prepare(args, mac(f)), /library CRF/, String(value));
  }
  await assert.rejects(prepare(macArgs(f, { userVariables: undefined }), mac(f)), /library CRF/);
});

test('Mac prepare captures a ticket from the read-only share and writes nothing', posix, async t => {
  const f = await fixture(t);
  const args = macArgs(f);
  const result = await prepare(args, mac(f));
  assert.equal(result.outputNumber, 1);
  assert.deepEqual(args.variables.homeserverOffload, {
    relpath: f.relpath, source: { size: f.size, mtimeSec: OLD_SEC }, probe: probe(),
  });
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].binary, MAC_FFPROBE);
  assert.equal(f.calls[0].argv.at(-1), f.source);
  assert.deepEqual(await fs.readdir(f.cacheRoot), []);
  assert.deepEqual(await fs.readdir(f.library), [f.name]);
});

test('Mac prepare refuses redirected, foreign, unsettled and non-regular sources', posix, async t => {
  const f = await fixture(t);
  const link = path.join(f.library, 'link.mkv'), folder = path.join(f.library, 'folder.mkv');
  const elsewhere = path.join(f.root, 'elsewhere', 'a.mkv'), mediaLink = path.join(f.root, 'media-link');
  await fs.symlink(f.source, link);
  await fs.mkdir(folder);
  await fs.symlink(f.media, mediaLink);
  for (const [label, extra, overrides, pattern] of [
    ['symlink', { inputFileObj: { _id: link }, originalLibraryFile: { _id: link } }, {}, /redirected/],
    ['outside the media root', { inputFileObj: { _id: elsewhere }, originalLibraryFile: { _id: elsewhere } }, {}, /outside the media root/],
    ['not the original file', { inputFileObj: { _id: path.join(f.library, 'other.mkv') } }, {}, /original file/],
    ['still settling', {}, { now: () => OLD.getTime() + 60000 }, /still settling/],
    ['directory', { inputFileObj: { _id: folder }, originalLibraryFile: { _id: folder } }, {}, /regular file/],
    ['missing media root', {}, { macMedia: path.join(f.root, 'missing') }, /ENOENT/],
    ['symlinked media root', {}, { macMedia: mediaLink }, /canonical/],
  ]) {
    const args = macArgs(f, extra);
    await assert.rejects(prepare(args, mac(f, overrides)), pattern, label);
    assert.equal(args.variables.homeserverOffload, undefined, label);
  }
  assert.deepEqual(await fs.readdir(f.cacheRoot), []);
});

test('Mac prepare skips efficient or tiny sources without issuing a ticket', posix, async t => {
  for (const [label, options, change] of [
    ['already HEVC', {}, f => { f.sourceCodec = 'hevc'; }],
    ['below the size policy', { size: 50 * MIB }, () => {}],
  ]) {
    const f = await fixture(t, options);
    change(f);
    const args = macArgs(f);
    const result = await prepare(args, mac(f));
    assert.equal(result.outputNumber, 2, label);
    assert.equal(args.variables.homeserverOffload, undefined, label);
    assert(f.logs.some(line => /skipped/.test(line)), label);
  }
});

test('Mac prepare accepts the decomposed names an SMB mount presents but still rejects redirects', posix, async t => {
  const f = await fixture(t, { name: 'Pok\u00e9mon S01E01.mkv' });
  const realpath = fs.realpath;
  try {
    fs.realpath = async (...argv) => {
      const real = await realpath(...argv);
      return real === f.source ? real.normalize('NFD') : real;
    };
    const args = macArgs(f);
    assert.equal((await prepare(args, mac(f))).outputNumber, 1);
    assert.equal(args.variables.homeserverOffload.relpath, 'tv/Pok\u00e9mon S01E01.mkv');
    fs.realpath = async (...argv) => {
      const real = await realpath(...argv);
      return real === f.source ? path.join(path.dirname(real), 'Other.mkv') : real;
    };
    await assert.rejects(prepare(macArgs(f), mac(f)), /redirected/);
  } finally { fs.realpath = realpath; }
});

test('Mac finish moves the result out of the work directory and writes the manifest last', posix, async t => {
  const f = await fixture(t);
  const args = await encoded(f, 500);
  const destinations = [], rename = fs.rename;
  let result;
  try {
    fs.rename = async (from, to) => { destinations.push(path.basename(to)); return rename(from, to); };
    result = await finish(args, mac(f));
  } finally { fs.rename = rename; }
  assert.deepEqual(destinations, ['result.mkv', 'manifest.json']);
  assert.equal(result.outputNumber, 1);
  assert.equal(result.outputFileObj, args.originalLibraryFile);
  assert.equal(result.variables.homeserverOffload.relpath, f.relpath);
  assert.equal(await exists(f.stale), false);
  assert.deepEqual((await fs.readdir(f.job)).sort(), ['manifest.json', 'result.mkv']);
  assert.equal((await fs.stat(f.result)).size, 500);
  const manifestFile = path.join(f.job, 'manifest.json');
  const { finishedAt, ...manifest } = JSON.parse(await fs.readFile(manifestFile, 'utf8'));
  assert.deepEqual(manifest, { version: 1, relpath: f.relpath, source: { size: f.size, mtimeSec: OLD_SEC }, resultSize: 500 });
  assert(Number.isFinite(Date.parse(finishedAt)));
  assert.equal((await fs.stat(manifestFile)).mode & 0o777, 0o600);
  assert.equal(f.calls.at(-1).binary, MAC_FFPROBE);
  assert.equal(f.calls.at(-1).argv.at(-1), f.stale);
});

test('Mac finish tolerates one second of SMB timestamp rounding but no more', posix, async t => {
  for (const [offset, accepted] of [[-1, true], [1, true], [-2, false], [2, false]]) {
    const f = await fixture(t);
    const args = await encoded(f);
    args.variables.homeserverOffload.source.mtimeSec = OLD_SEC + offset;
    if (accepted) assert.equal((await finish(args, mac(f))).outputNumber, 1, String(offset));
    else await assert.rejects(finish(args, mac(f)), /changed during encoding/, String(offset));
  }
});

test('Mac finish retains the original when the saving is under 5%, without creating a handover', posix, async t => {
  const f = await fixture(t);
  const args = await encoded(f, 98 * MIB);
  const result = await finish(args, mac(f));
  assert.equal(result.outputNumber, 2);
  assert.equal(result.outputFileObj, args.originalLibraryFile);
  assert.deepEqual(result.variables, {});
  assert.equal(await exists(path.join(f.cacheRoot, JOBS)), false);
  assert.equal(await exists(f.stale), true);
});

test('Mac finish rejects forged tickets and unusable encoder output before creating a handover', posix, async t => {
  const pattern = /Matroska file inside the cache share/;
  for (const [label, change, expected] of [
    ['no ticket', (f, a) => { delete a.variables.homeserverOffload; }, /missing offload ticket/],
    ['ticket for another file', (f, a) => { a.variables.homeserverOffload.relpath = 'tv/Other.mkv'; }, /another file/],
    ['source size changed', (f, a) => { a.variables.homeserverOffload.source.size += 1; }, /changed during encoding/],
    ['output outside the cache', (f, a) => { a.inputFileObj = { _id: path.join(f.root, 'elsewhere', 'x.mkv') }; }, pattern],
    ['output is the source', (f, a) => { a.inputFileObj = { _id: f.source }; }, pattern],
    ['output path is relative', (f, a) => { a.inputFileObj = { _id: 'result.mkv' }; }, pattern],
    ['output is not Matroska', async (f, a) => {
      const other = f.stale.replace(/\.mkv$/, '.mp4');
      await fs.rename(f.stale, other);
      a.inputFileObj = { _id: other };
    }, pattern],
    ['output is a symlink', async (f, a) => {
      const link = path.join(f.workDir, 'link.mkv');
      await fs.symlink(f.source, link);
      a.inputFileObj = { _id: link };
    }, pattern],
    ['output is empty', f => sparse(f.stale, 0), /empty encoded output/],
    ['output is a directory', async f => { await fs.rm(f.stale); await fs.mkdir(f.stale); }, /empty encoded output/],
    ['output has the wrong codec', f => { f.outputCodec = 'h264'; }, /codec mismatch/],
  ]) {
    const f = await fixture(t);
    const args = await encoded(f);
    await change(f, args);
    await assert.rejects(finish(args, mac(f)), expected, label);
    assert.equal(await exists(path.join(f.cacheRoot, JOBS)), false, label);
    assert.deepEqual(await fs.readdir(f.library), [f.name], label);
  }
});

test('Mac finish never treats the source as its own output, even if the cache share contains the media', posix, async t => {
  const f = await fixture(t);
  const args = await encoded(f);
  args.inputFileObj = { _id: f.source };
  await assert.rejects(finish(args, mac(f, { macCache: f.root })), /Matroska file inside the cache share/);
  assert.deepEqual(await fs.readdir(f.library), [f.name]);
  assert.equal(await exists(path.join(f.root, JOBS)), false);
});

test('Mac finish replaces a stale handover and removes a partial one when publication fails', posix, async t => {
  const f = await fixture(t);
  await fs.mkdir(f.job, { recursive: true });
  for (const file of ['result.mkv', 'manifest.json', 'manifest.json.tmp']) await fs.writeFile(path.join(f.job, file), 'stale');
  assert.equal((await finish(await encoded(f, 500), mac(f))).outputNumber, 1);
  assert.equal((await fs.stat(f.result)).size, 500);
  assert.deepEqual((await fs.readdir(f.job)).sort(), ['manifest.json', 'result.mkv']);

  const g = await fixture(t);
  const args = await encoded(g, 500), writeFile = fs.writeFile;
  try {
    fs.writeFile = async (file, ...rest) => {
      if (String(file).endsWith('manifest.json.tmp')) throw new Error('disk full');
      return writeFile(file, ...rest);
    };
    await assert.rejects(finish(args, mac(g)), /disk full/);
  } finally { fs.writeFile = writeFile; }
  assert.deepEqual(await fs.readdir(path.join(g.cacheRoot, JOBS)), []);
});

test('Linux commit validates only private bytes, publishes, sweeps and strips every ticket', linux, async t => {
  const f = await fixture(t);
  await handover(f, { size: 500 });
  const abandoned = path.join(f.cacheRoot, JOBS, 'a'.repeat(32)), stalePrivate = path.join(f.privateRoot, crypto.randomUUID());
  await fs.mkdir(abandoned);
  await fs.writeFile(path.join(abandoned, 'result.mkv'), 'old');
  await fs.utimes(path.join(abandoned, 'result.mkv'), OLD, OLD);
  await fs.utimes(abandoned, OLD, OLD);
  await fs.mkdir(stalePrivate, { mode: 0o700 });
  await fs.writeFile(path.join(stalePrivate, 'validated.mkv'), 'old');
  await fs.utimes(stalePrivate, OLD, OLD);
  f.args.variables = { keep: 'me', homeserverSafeHevc: { forged: true }, homeserverOffload: { forged: true } };

  const result = await commit(f.args, f.injected);
  assert.equal(result.outputNumber, 1);
  assert.deepEqual(result.variables, { keep: 'me' });
  assert.equal(result.outputFileObj._id, f.source);
  assert.deepEqual(await fs.readFile(f.source), Buffer.alloc(500, 2));
  assert.deepEqual(await fs.readdir(f.library), [f.name]);
  assert.deepEqual(await fs.readdir(f.privateRoot), []);
  assert.deepEqual(await fs.readdir(path.join(f.cacheRoot, JOBS)), []);
  assert.deepEqual(f.calls.map(c => c.binary), [FFPROBE, FFPROBE, FFMPEG]);
  assert.equal(f.calls[0].argv.at(-1), f.source);
  assert(!f.calls[0].argv.includes('-f'));
  for (const call of f.calls.slice(1)) {
    assert.match(probedFile(call), /\/validated\.mkv$/);
    assert(forcesMatroska(call));
  }
});

test('Linux commit publishes the private copy even if the shared bytes are rewritten during validation', linux, async t => {
  const f = await fixture(t);
  await handover(f, { size: 500 });
  intercept(f, async (binary, argv) => {
    if (!argv.some(arg => arg.endsWith('/validated.mkv'))) return undefined;
    assert.equal((await fs.readFile(probedFile({ binary, argv })))[0], 2);
    await fs.writeFile(f.result, Buffer.alloc(600, 9));
    return undefined;
  });
  assert.equal((await commit(f.args, f.injected)).outputNumber, 1);
  assert.deepEqual(await fs.readFile(f.source), Buffer.alloc(500, 2));
});

test('Linux commit refuses unsafe contexts before touching the shared handover', linux, async t => {
  for (const [label, setup, pattern] of [
    ['wrong platform', async () => ({ platform: 'darwin' }), /only on the Linux worker/],
    ['not a transcode worker', async f => { f.args.workerType = 'healthcheckcpu'; return {}; }, /requires a transcode worker/],
    ['private state inside the shared cache', async f => ({ privateRoot: path.join(f.cacheRoot, 'private') }), /outside shared cache/],
    ['private state readable by others', async f => { await fs.chmod(f.privateRoot, 0o755); return {}; }, /mode 0700/],
    ['symlinked media root', async f => {
      const link = path.join(f.root, 'media-link');
      await fs.symlink(f.media, link);
      return { mediaRoot: link };
    }, /canonical/],
    ['source outside the media root', async f => {
      f.args.originalLibraryFile = { _id: path.join(f.root, 'elsewhere.mkv') };
      return {};
    }, /outside the media root/],
  ]) {
    const f = await fixture(t);
    await handover(f);
    const overrides = await setup(f);
    await assert.rejects(commit(f.args, { ...f.injected, ...overrides }), pattern, label);
    assert.equal(await exists(f.result), true, label);
    await untouched(f);
  }
});

test('Linux commit rejects missing, malformed, foreign or mismatching manifests', linux, async t => {
  const manifestFile = f => path.join(f.job, 'manifest.json');
  const decoy = async f => {
    const file = path.join(f.root, 'decoy.json');
    await fs.writeFile(file, '{}');
    await fs.rm(manifestFile(f));
    return file;
  };
  for (const [label, setup, pattern] of [
    ['missing manifest', async f => { await handover(f); await fs.rm(manifestFile(f)); }, /no encoded result was handed over/],
    ['not JSON', async f => { await handover(f); await fs.writeFile(manifestFile(f), '{nope'); }, /not valid JSON/],
    ['another file', f => handover(f, { manifest: { relpath: 'tv/Other.mkv' } }), /does not match this file/],
    ['future version', f => handover(f, { manifest: { version: 2 } }), /does not match this file/],
    ['fractional source size', f => handover(f, { manifest: { source: { size: 1.5, mtimeSec: OLD_SEC } } }), /does not match this file/],
    ['empty result', f => handover(f, { manifest: { resultSize: 0 } }), /does not match this file/],
    ['result size mismatch', f => handover(f, { manifest: { resultSize: 501 } }), /result size does not match/],
    ['source size changed', f => handover(f, { manifest: { source: { size: f.size + 1, mtimeSec: OLD_SEC } } }), /changed during offload/],
    ['source mtime changed', f => handover(f, { manifest: { source: { size: f.size, mtimeSec: OLD_SEC + 5 } } }), /changed during offload/],
    ['empty manifest', async f => { await handover(f); await fs.writeFile(manifestFile(f), ''); }, /invalid manifest file/],
    ['oversized manifest', async f => { await handover(f); await fs.writeFile(manifestFile(f), ' '.repeat(70 * 1024)); }, /invalid manifest file/],
    ['manifest is a directory', async f => { await handover(f); await fs.rm(manifestFile(f)); await fs.mkdir(manifestFile(f)); }, /invalid manifest file/],
    ['manifest is hardlinked', async f => { await handover(f); await fs.link(await decoy(f), manifestFile(f)); }, /invalid manifest file/],
    ['manifest is a symlink', async f => { await handover(f); await fs.symlink(await decoy(f), manifestFile(f)); }, /ELOOP/],
  ]) {
    const f = await fixture(t);
    await setup(f);
    await assert.rejects(commit(f.args, f.injected), pattern, label);
    await untouched(f);
  }
});

test('Linux commit leaves the original alone when it is no longer eligible or saves under 5%', linux, async t => {
  const changed = await fixture(t);
  await handover(changed);
  changed.sourceCodec = 'hevc';
  const small = await fixture(t, { size: 100 * MIB });
  await handover(small, { size: 96 * MIB });
  for (const f of [changed, small]) {
    const result = await commit(f.args, f.injected);
    assert.equal(result.outputNumber, 2);
    assert.equal(result.outputFileObj, f.args.originalLibraryFile);
    assert.deepEqual(result.variables, {});
    await untouched(f);
    assert.equal(await exists(f.job), false);
  }
});

test('Linux commit never publishes a failed validation and always cleans up after itself', linux, async t => {
  for (const [label, setup, pattern] of [
    ['decode fails', f => intercept(f, binary => { if (binary === FFMPEG) throw new Error('decode failed'); }), /decode failed/],
    ['decode truncated', f => intercept(f, binary => binary === FFMPEG && { stdout: 'out_time_us=0\n' }), /did not reach end of media/],
    ['source changes while validating', f => intercept(f, async binary => {
      if (binary === FFMPEG) await fs.appendFile(f.source, 'changed');
    }), /source changed during processing/],
    ['output has the wrong codec', f => { f.outputCodec = 'h264'; }, /codec mismatch/],
    ['library folder does not contain the source', async f => {
      const other = path.join(f.media, 'movies');
      await fs.mkdir(other);
      f.args.librarySettings.folder = other;
    }, /outside library/],
    ['job is cancelled', f => { f.args.signal = AbortSignal.abort(); }, /abort/i],
  ]) {
    const f = await fixture(t);
    await handover(f);
    await setup(f);
    await assert.rejects(commit(f.args, f.injected), pattern, label);
    assert.deepEqual(await fs.readdir(f.library), [f.name], label);
    assert.deepEqual(await fs.readdir(f.privateRoot), [], label);
    assert.equal(await exists(f.job), false, label);
    if (label !== 'source changes while validating') await untouched(f);
  }
});

test('Linux commit publishes a decomposed (NFD) file name against its NFC manifest key', linux, async t => {
  const f = await fixture(t, { name: 'Poke\u0301mon S01E01.mkv' });
  assert.equal(f.relpath, 'tv/Pok\u00e9mon S01E01.mkv');
  await handover(f);
  const result = await commit(f.args, f.injected);
  assert.equal(result.outputNumber, 1);
  assert.equal(result.outputFileObj._id, f.source);
  assert.equal((await fs.stat(f.source)).size, 500);
});

test('sweep removes only abandoned, well-named handovers and staging, and reports what it cannot remove', linux, async t => {
  const f = await fixture(t, { create: false });
  const jobs = path.join(f.cacheRoot, JOBS), logs = [], hex = char => char.repeat(32);
  await fs.mkdir(jobs);
  const make = async (parent, name, files, { old = true } = {}) => {
    const directory = path.join(parent, name);
    await fs.mkdir(directory);
    for (const [file, ancient = true] of files) {
      await fs.writeFile(path.join(directory, file), 'x');
      if (ancient) await fs.utimes(path.join(directory, file), OLD, OLD);
    }
    if (old) await fs.utimes(directory, OLD, OLD);
  };
  await make(jobs, hex('1'), [['result.mkv'], ['manifest.json']]);
  await make(jobs, hex('2'), [['result.mkv', false]], { old: false });
  await make(jobs, hex('3'), [['result.mkv']]);
  await make(jobs, hex('4'), [['result.mkv', false]]);
  await make(jobs, hex('5'), [['result.mkv'], ['surprise.txt']]);
  await make(jobs, 'notes', [['result.mkv']]);
  await make(jobs, hex('A'), [['result.mkv']]);
  const abandoned = crypto.randomUUID(), fresh = crypto.randomUUID(), loose = crypto.randomUUID();
  await make(f.privateRoot, abandoned, [['validated.mkv']]);
  await make(f.privateRoot, fresh, [['validated.mkv', false]], { old: false });
  await make(f.privateRoot, 'manual', [['validated.mkv']]);
  await fs.writeFile(path.join(f.privateRoot, loose), 'x');
  await fs.utimes(path.join(f.privateRoot, loose), OLD, OLD);

  await sweep(f.cacheRoot, f.privateRoot, hex('3'), Date.now(), line => logs.push(line));
  assert.deepEqual((await fs.readdir(jobs)).sort(), [hex('2'), hex('3'), hex('4'), hex('5'), hex('A'), 'notes'].sort());
  assert.deepEqual(await fs.readdir(path.join(jobs, hex('5'))), ['surprise.txt']);
  assert.deepEqual((await fs.readdir(f.privateRoot)).sort(), [fresh, loose, 'manual'].sort());
  assert.equal(logs.length, 3, logs.join('\n'));
  assert(logs.some(line => line.includes(`removed an abandoned handover ${hex('1')}`)));
  assert(logs.some(line => line.includes(`${hex('5')} needs review`)));
  assert(logs.some(line => line.includes(`removed abandoned private staging ${abandoned}`)));

  const quiet = await fixture(t, { create: false }), quietLogs = [];
  await sweep(quiet.cacheRoot, quiet.privateRoot, hex('3'), Date.now(), line => quietLogs.push(line));
  assert.deepEqual(quietLogs, []);
});

test('private copy rejects directory and leaf symlinks, hardlinks, non-regular and oversized results', linux, async t => {
  const bounded = /bounded, nonempty regular file with one link/;
  for (const [kind, pattern] of [
    ['leaf', /ELOOP/], ['directory', /ELOOP|ENOTDIR/], ['hardlink', bounded], ['nonregular', bounded],
    ['oversized', bounded], ['escape', /invalid cache path component/], ['name', /invalid cache file name/],
  ]) {
    const f = await fixture(t), target = path.join(f.privateRoot, 'copy.mkv');
    await handover(f);
    // A small, valid regular file: only the link checks can reject it, not the size or type checks.
    const decoy = path.join(f.root, 'decoy.mkv');
    await fs.writeFile(decoy, 'x');
    let parts = [JOBS, f.id], file = 'result.mkv';
    if (kind === 'directory') {
      await fs.rename(f.job, `${f.job}-other`);
      await fs.symlink(`${f.job}-other`, f.job);
    } else if (kind === 'escape') {
      parts = [JOBS, '../escape'];
    } else if (kind === 'name') {
      file = '../result.mkv';
    } else {
      await fs.unlink(f.result);
      if (kind === 'leaf') await fs.symlink(decoy, f.result);
      if (kind === 'hardlink') await fs.link(decoy, f.result);
      if (kind === 'nonregular') await fs.mkdir(f.result);
      if (kind === 'oversized') await fs.writeFile(f.result, Buffer.alloc(2001));
    }
    await assert.rejects(privateCopy(f.cacheRoot, parts, file, target, 2000), pattern, kind);
    assert.equal((await fs.stat(f.source)).size, f.size, kind);
    await assert.rejects(fs.access(target), /ENOENT/, kind);
  }
});

test('private copy holds its directories and file open so a later swap cannot redirect it', linux, async t => {
  for (const kind of ['leaf', 'directory']) {
    const f = await fixture(t), target = path.join(f.privateRoot, 'copy.mkv');
    await handover(f, { size: 500 });
    const decoys = path.join(f.root, 'decoys');
    await sparse(path.join(decoys, 'result.mkv'), 500, 9);
    const suffix = kind === 'leaf' ? '/result.mkv' : `/${f.id}`, originalOpen = fs.open;
    let swapped = false;
    try {
      fs.open = async (...argv) => {
        const handle = await originalOpen(...argv);
        const file = String(argv[0]);
        if (!swapped && file.startsWith('/proc/self/fd/') && file.endsWith(suffix)) {
          swapped = true;
          if (kind === 'leaf') {
            await fs.rename(f.result, `${f.result}.old`);
            await fs.symlink(path.join(decoys, 'result.mkv'), f.result);
          } else {
            await fs.rename(f.job, `${f.job}.old`);
            await fs.symlink(decoys, f.job);
          }
        }
        return handle;
      };
      await privateCopy(f.cacheRoot, [JOBS, f.id], 'result.mkv', target, 2000);
    } finally { fs.open = originalOpen; }
    assert(swapped, kind);
    assert.deepEqual(await fs.readFile(target), Buffer.alloc(500, 2), kind);
  }
});

test('private copy streams multiple chunks and rejects mutation of the opened result', linux, async t => {
  const f = await fixture(t);
  const bytes = Buffer.alloc(2 * MIB + 17, 7);
  bytes[MIB] = 8;
  await handover(f, { bytes });
  const target = path.join(f.privateRoot, 'copy.mkv');
  assert.equal(await privateCopy(f.cacheRoot, [JOBS, f.id], 'result.mkv', target, bytes.length), bytes.length);
  assert.deepEqual(await fs.readFile(target), bytes);

  const originalOpen = fs.open;
  try {
    fs.open = async (...argv) => {
      const handle = await originalOpen(...argv);
      if (String(argv[0]).startsWith('/proc/self/fd/') && String(argv[0]).endsWith('/result.mkv')) {
        const read = handle.read.bind(handle);
        let mutated = false;
        handle.read = async (...parameters) => {
          const result = await read(...parameters);
          if (!mutated) { await fs.appendFile(f.result, 'changed'); mutated = true; }
          return result;
        };
      }
      return handle;
    };
    await assert.rejects(privateCopy(f.cacheRoot, [JOBS, f.id], 'result.mkv', path.join(f.privateRoot, 'mutated.mkv'),
      bytes.length), /changed during private copy/);
  } finally { fs.open = originalOpen; }
});

test('real media: reject a disguised external HLS playlist and publish a genuine Matroska result', {
  skip: process.platform !== 'linux' || process.env.TDARR_INTEGRATION_TESTS !== '1',
  timeout: 180000,
}, async t => {
  const f = await fixture(t, { name: 'Episode.avi', create: false });
  await runProcess(FFMPEG, ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x96:rate=24:duration=4',
    '-c:v', 'mpeg4', '-q:v', '2', f.source]);
  // Sparse padding makes the real non-Matroska source eligible and ensures a meaningful saving.
  const handle = await fs.open(f.source, 'r+');
  try { await handle.truncate(101 * MIB); } finally { await handle.close(); }
  await fs.utimes(f.source, OLD, OLD);
  const sourceProbe = JSON.parse((await runProcess(FFPROBE,
    ['-v', 'error', '-show_streams', '-show_format', '-show_chapters', '-of', 'json', f.source])).stdout);
  const genuine = path.join(f.root, 'genuine.mkv');
  await runProcess(FFMPEG, ['-v', 'error', '-i', f.source, '-map', '0', '-c:v', 'libx265',
    '-preset', 'ultrafast', '-crf', '20', '-x265-params', 'pools=1:frame-threads=1', genuine], { timeout: 120000 });
  // The segments live outside the job directory, which is only ever emptied of its known files.
  const segments = path.join(f.root, 'segments'), playlist = path.join(f.root, 'playlist.m3u8');
  await fs.mkdir(segments);
  await runProcess(FFMPEG, ['-v', 'error', '-i', genuine, '-c', 'copy', '-f', 'hls', '-hls_time', '4',
    '-hls_list_size', '0', '-hls_segment_filename', path.join(segments, 'segment-%d.ts'), playlist]);
  const disguised = (await fs.readFile(playlist, 'utf8')).replace(/segment-(\d+)\.ts/g, `${segments}/segment-$1.ts`);
  await handover(f, { bytes: Buffer.from(disguised) });
  // The installed FFprobe rejects HLS autodetection with an .mkv suffix; forcing HLS establishes that this
  // playlist can otherwise read matching external media and satisfy the stream contract.
  const hlsProbe = JSON.parse((await runProcess(FFPROBE,
    ['-v', 'error', '-show_streams', '-show_format', '-show_chapters', '-of', 'json', '-f', 'hls', f.result])).stdout);
  assert.match(hlsProbe.format.format_name, /hls/);
  validate(sourceProbe, hlsProbe);

  const calls = [];
  const run = async (binary, argv, options) => {
    calls.push({ binary, argv });
    return runProcess(binary, argv, options);
  };
  const injected = { ...f.injected, run };
  const original = fingerprint(await fs.stat(f.source));
  await assert.rejects(commit(f.args, injected), /ffprobe exited/);
  assert.deepEqual(fingerprint(await fs.stat(f.source)), original);

  await handover(f, { bytes: Buffer.from(disguised) });
  const mockedProbe = {
    ...injected, run: async (binary, argv, options) => {
      if (binary === FFPROBE && argv.at(-1).endsWith('/validated.mkv')) return { stdout: JSON.stringify(hlsProbe) };
      return run(binary, argv, options);
    },
  };
  await assert.rejects(commit(f.args, mockedProbe), /ffmpeg exited/);
  assert.deepEqual(fingerprint(await fs.stat(f.source)), original);

  await handover(f, { bytes: await fs.readFile(genuine) });
  const result = await commit(f.args, injected);
  assert.equal(result.outputNumber, 1);
  assert.equal(result.outputFileObj._id, path.join(f.library, 'Episode.mkv'));
  assert.deepEqual(await fs.readFile(result.outputFileObj._id), await fs.readFile(genuine));
  assert.equal(await exists(f.source), false);
  assert.deepEqual(await fs.readdir(f.privateRoot), []);
  const staged = calls.filter(call => probedFile(call).endsWith('/validated.mkv'));
  assert(staged.some(call => call.binary === FFPROBE));
  assert(staged.some(call => call.binary === FFMPEG));
  for (const call of staged) assert(forcesMatroska(call));
});
