'use strict';

const fs = require('node:fs/promises');
const { constants: C } = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { internals: { inside, runProcess } } = require('./dv5-sidecar.cjs');

const PRIVATE_ROOT = '/app/server/Tdarr/Custom/state/studio-native-v1';
const CACHE_ROOT = '/temp/studio-native';
const MAC_CACHE = '/private/var/lib/studio-worker/mounts/cache';
const MAC_MEDIA = '/private/var/lib/studio-worker/mounts/media';
const MAC_FFMPEG = '/opt/homebrew/bin/ffmpeg';
const TOKEN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const assert = (ok, message) => { if (!ok) throw new Error(`Studio HEVC: ${message}`); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const identity = stat => Object.fromEntries(['dev', 'ino', 'size', 'mtimeMs', 'ctimeMs'].map(k => [k, stat[k]]));

function worker(args, platform, tag, injected) {
  assert((injected.platform || process.platform) === platform, `requires ${platform} worker`);
  assert(args.workerType === 'transcodecpu' && (args.nodeTags || '').split(',').map(s => s.trim()).includes(tag),
    `requires CPU worker tagged ${tag}`);
}

function jobId(args) {
  const id = args.job?.jobId;
  assert(typeof id === 'string' && id.length > 0 && id.length <= 256, 'missing job identity');
  return id;
}

function stateDirectory(args, injected) {
  return path.join(injected.privateRoot || PRIVATE_ROOT, crypto.createHash('sha256').update(jobId(args)).digest('hex'));
}

async function directory(root, privateDirectory = false) {
  assert(path.isAbsolute(root) && path.resolve(root) === root && await fs.realpath(root) === root,
    'directory must be canonical, without symlinks');
  const stat = await fs.lstat(root);
  assert(stat.isDirectory(), 'not a directory');
  if (privateDirectory) assert((stat.mode & 0o077) === 0 && stat.uid === process.getuid(),
    'private state must be owned by this user with mode 0700');
}

function crf(value) {
  assert(typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value)
    && Number(value) >= 0 && Number(value) <= 51, 'missing or invalid library CRF');
  return value;
}

async function prepare(args, injected = {}) {
  worker(args, 'linux', 'homeserver-storage', injected);
  const safe = require('./hevc-safe-v1.cjs');
  const privateRoot = injected.privateRoot || PRIVATE_ROOT;
  const cacheRoot = injected.cacheRoot || CACHE_ROOT;
  await directory(cacheRoot);
  await fs.mkdir(privateRoot, { recursive: true, mode: 0o700 });
  await directory(privateRoot, true);
  assert(!inside(cacheRoot, privateRoot) && !inside(privateRoot, cacheRoot) && privateRoot !== cacheRoot,
    'private state must be outside shared cache');
  const source = args.inputFileObj._id;
  assert(source === args.originalLibraryFile._id, 'preparation must use the original file');
  const quality = crf(args.userVariables?.library?.crf);
  const result = await safe.prepare(args, injected);
  if (result.outputNumber !== 1) return result;
  const saved = structuredClone(args.variables.homeserverSafeHevc);
  assert(same(identity(await fs.stat(source)), saved.fingerprint), 'source changed during preparation');
  const token = crypto.randomUUID();
  const state = stateDirectory(args, injected);
  await fs.mkdir(state, { mode: 0o700 }); // Exclusive: never overwrite an in-flight job's authority.
  await fs.writeFile(path.join(state, 'manifest.json'), JSON.stringify({
    version: 1, jobId: jobId(args), libraryId: args.librarySettings._id,
    root: await fs.realpath(args.librarySettings.folder), token, crf: quality, saved,
  }), { flag: 'wx', mode: 0o600 });
  await fs.mkdir(path.join(cacheRoot, token), { mode: 0o770 });
  args.variables.homeserverStudio = { token, jobId: jobId(args), source, probe: saved.probe, crf: quality };
  delete args.variables.homeserverSafeHevc;
  args.jobLog(`Studio HEVC: private source contract saved; cache job ${token}`);
  return result;
}

function encodeArgs(source, output, probe, quality) {
  crf(quality);
  assert(Array.isArray(probe?.streams), 'missing encode stream contract');
  const video = probe.streams.filter(s => s.codec_type === 'video' && !s.disposition?.attached_pic);
  assert(video.length === 1 && /^[a-z0-9]+$/.test(video[0].pix_fmt), 'invalid encode video');
  const videoIndex = probe.streams.filter(s => s.codec_type === 'video').indexOf(video[0]);
  const spec = `v:${videoIndex}`;
  const argv = ['-hide_banner', '-nostdin', '-n', '-i', source, '-map', '0',
    '-map_metadata', '0', '-map_chapters', '0', '-c', 'copy',
    `-c:${spec}`, 'libx265', `-preset:${spec}`, 'slow', `-crf:${spec}`, quality,
    `-pix_fmt:${spec}`, video[0].pix_fmt, `-fps_mode:${spec}`, 'passthrough',
    `-x265-params:${spec}`, 'pools=4'];
  probe.streams.forEach((s, i) => {
    const dispositions = Object.entries(s.disposition || {}).filter(([, value]) => value === 1).map(([key]) => key);
    argv.push(`-disposition:${i}`, dispositions.join('+') || '0');
  });
  return [...argv, '-f', 'matroska', output];
}

async function trackedEncode(args, argv, output, timeout, injected) {
  assert(args.config?.pluginsPath, 'Tdarr CLI helper unavailable; refusing an untracked encode');
  const { CLI } = injected.CLI ? { CLI: injected.CLI }
    : require(path.join(args.config.pluginsPath, 'FlowPlugins/FlowHelpers/1.0.0/cliUtils'));
  const cli = new CLI({
    cli: MAC_FFMPEG, spawnArgs: argv, spawnOpts: {}, jobLog: args.jobLog, outputFilePath: output,
    inputFileObj: args.inputFileObj, logFullCliOutput: false, updateWorker: args.updateWorker, args,
  });
  const signal = args.signal || args.abortSignal;
  signal?.throwIfAborted();
  const abort = () => cli.killThread();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; cli.killThread(); }, timeout);
  signal?.addEventListener('abort', abort, { once: true });
  try {
    const result = await cli.runCli();
    signal?.throwIfAborted();
    assert(!timedOut && result.cliExitCode === 0, `native FFmpeg ${timedOut ? 'timed out' : `exited ${result.cliExitCode}`}`);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

async function encode(args, injected = {}) {
  worker(args, 'darwin', 'studio-native', injected);
  assert((injected.arch || process.arch) === 'arm64', 'requires native Apple Silicon');
  assert(args.ffmpegPath === MAC_FFMPEG, 'select the Homebrew FFmpeg explicitly');
  const ticket = args.variables.homeserverStudio;
  assert(ticket && TOKEN.test(ticket.token) && ticket.jobId === jobId(args), 'invalid encode ticket');
  const media = injected.macMedia || MAC_MEDIA, cache = injected.macCache || MAC_CACHE;
  await directory(media);
  await directory(cache);
  const source = ticket.source;
  assert(source === args.originalLibraryFile._id && source === args.inputFileObj._id
    && inside(media, source) && path.resolve(source) === source
    && await fs.realpath(source) === source
    && (await fs.lstat(source)).isFile(), 'invalid mapped read-only source');
  const work = path.join(cache, ticket.token);
  await directory(work);
  const output = path.join(work, 'result.mkv');
  const seconds = Number(ticket.probe?.format?.duration);
  assert(Number.isFinite(seconds) && seconds > 0, 'invalid encode duration');
  const argv = encodeArgs(source, output, ticket.probe, ticket.crf);
  const timeout = Math.min(2147483647, Math.max(3600000, seconds * 60000));
  args.jobLog('Studio HEVC: software libx265 slow, original pixel format and library CRF, pools=4');
  if (injected.run) await injected.run(MAC_FFMPEG, argv, { signal: args.signal || args.abortSignal, timeout });
  else await trackedEncode(args, argv, output, timeout, injected);
  return { outputFileObj: { _id: output }, variables: args.variables, outputNumber: 1 };
}

async function privateCopy(cacheRoot, token, target, maxSize, signal) {
  assert(TOKEN.test(token), 'invalid cache job token');
  await directory(cacheRoot);
  let root, job, source, destination;
  try {
    root = await fs.open(cacheRoot, C.O_RDONLY | C.O_DIRECTORY | C.O_NOFOLLOW);
    // Pin each untrusted directory before opening its child: realpath+open alone races SMB renames.
    job = await fs.open(`/proc/self/fd/${root.fd}/${token}`, C.O_RDONLY | C.O_DIRECTORY | C.O_NOFOLLOW);
    source = await fs.open(`/proc/self/fd/${job.fd}/result.mkv`, C.O_RDONLY | C.O_NOFOLLOW | C.O_NONBLOCK);
    const before = await source.stat();
    assert(before.isFile() && before.nlink === 1 && before.size > 0 && before.size <= maxSize,
      'returned output must be a bounded, nonempty regular file with one link');
    destination = await fs.open(target, 'wx', 0o600);
    const buffer = Buffer.alloc(1024 * 1024);
    let remaining = before.size;
    while (remaining > 0) {
      signal?.throwIfAborted();
      const { bytesRead } = await source.read(buffer, 0, Math.min(buffer.length, remaining), null);
      assert(bytesRead > 0, 'returned output truncated during private copy');
      await destination.writeFile(buffer.subarray(0, bytesRead));
      remaining -= bytesRead;
    }
    assert(same(identity(before), identity(await source.stat())), 'returned output changed during private copy');
    await destination.sync();
  } finally {
    // All handles must close even if a previous close fails.
    const closed = await Promise.allSettled([destination, source, job, root].filter(Boolean).map(h => h.close()));
    const failed = closed.filter(r => r.status === 'rejected');
    if (failed.length) throw new AggregateError(failed.map(r => r.reason), 'Studio HEVC: closing copy handles failed');
  }
}

async function cleanupCache(cacheRoot, token) {
  let root, job;
  try {
    root = await fs.open(cacheRoot, C.O_RDONLY | C.O_DIRECTORY | C.O_NOFOLLOW);
    job = await fs.open(`/proc/self/fd/${root.fd}/${token}`, C.O_RDONLY | C.O_DIRECTORY | C.O_NOFOLLOW);
    await fs.unlink(`/proc/self/fd/${job.fd}/result.mkv`);
    await fs.rmdir(`/proc/self/fd/${root.fd}/${token}`);
  } finally {
    const closed = await Promise.allSettled([job, root].filter(Boolean).map(h => h.close()));
    const failed = closed.filter(r => r.status === 'rejected');
    if (failed.length) throw new AggregateError(failed.map(r => r.reason), 'Studio HEVC: closing cleanup handles failed');
  }
}

function matroskaOutputRunner(staged, run) {
  return (binary, argv, options) => {
    let index;
    if (binary === '/usr/lib/jellyfin-ffmpeg/ffprobe') {
      index = argv.length - 1;
    } else if (binary === '/usr/lib/jellyfin-ffmpeg/ffmpeg') {
      index = argv.indexOf('-i');
      assert(index >= 0 && argv[index + 1] === staged, 'unexpected validation decode input');
    } else {
      throw new Error('Studio HEVC: unexpected validation binary');
    }
    assert((binary.endsWith('/ffprobe') ? argv[index] : argv[index + 1]) === staged,
      'unexpected validation probe input');
    return run(binary, [...argv.slice(0, index), '-f', 'matroska', ...argv.slice(index)], options);
  };
}

async function commit(args, injected = {}) {
  worker(args, 'linux', 'homeserver-storage', injected);
  const privateRoot = injected.privateRoot || PRIVATE_ROOT, cacheRoot = injected.cacheRoot || CACHE_ROOT;
  await directory(privateRoot, true);
  const state = stateDirectory(args, injected);
  await directory(state, true);
  const manifest = JSON.parse(await fs.readFile(path.join(state, 'manifest.json'), 'utf8'));
  const ticket = args.variables.homeserverStudio;
  assert(manifest.version === 1 && manifest.jobId === jobId(args)
    && manifest.libraryId === args.librarySettings._id && TOKEN.test(manifest.token)
    && ticket?.token === manifest.token, 'job does not match private manifest');
  const saved = manifest.saved;
  assert(saved.source === args.originalLibraryFile._id
    && manifest.root === await fs.realpath(args.librarySettings.folder)
    && inside(manifest.root, saved.source) && await fs.realpath(saved.source) === saved.source,
  'original does not match private manifest');
  assert(args.inputFileObj._id === path.join(cacheRoot, manifest.token, 'result.mkv'),
    'unexpected per-job output path');
  const lock = await fs.open(path.join(state, 'commit.lock'), 'wx', 0o600);
  await lock.close();
  const staged = path.join(state, 'validated.mkv');
  try {
    await privateCopy(cacheRoot, manifest.token, staged, saved.fingerprint.size * 2, args.signal || args.abortSignal);
    args.jobLog('Studio HEVC: shared output copied into Linux-private staging; validating only private bytes');
    const variables = { ...args.variables, homeserverSafeHevc: saved };
    const result = await require('./hevc-safe-v1.cjs').commit({
      ...args, inputFileObj: { _id: staged }, variables,
    }, { ...injected, run: matroskaOutputRunner(staged, injected.run || runProcess) });
    await fs.writeFile(path.join(state, 'outcome.json'), JSON.stringify({
      outputNumber: result.outputNumber, output: result.outputFileObj._id, finishedAt: new Date().toISOString(),
    }), { flag: 'wx', mode: 0o600 });
    try { await cleanupCache(cacheRoot, manifest.token); }
    catch (error) { args.jobLog(`Studio HEVC: publication/skip completed, shared-cache cleanup requires review: ${error.message}`); }
    delete result.variables.homeserverSafeHevc;
    delete result.variables.homeserverStudio;
    return result;
  } finally {
    try { await fs.unlink(staged); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}

module.exports = { prepare, encode, commit, encodeArgs, privateCopy, PRIVATE_ROOT, CACHE_ROOT, MAC_MEDIA, MAC_CACHE, MAC_FFMPEG };
