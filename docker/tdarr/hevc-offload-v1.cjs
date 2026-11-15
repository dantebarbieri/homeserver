'use strict';

// Two-leg HEVC compression. The Mac Studio only encodes; the server validates and publishes.
//   prepare / finish  run on the mapped macOS CPU worker (read-only media share, writable cache share)
//   commit            runs on the Linux GPU worker slot, which Tdarr hands the staged job to
// The Mac is treated as untrusted-ish: it parses hostile media and can write only the cache share, so
// everything it returns is re-validated on Linux against a fresh Linux-side source fingerprint.

const fs = require('node:fs/promises');
const { constants: C } = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { internals: { inside, runProcess } } = require('./dv5-sidecar.cjs');
const safe = require('./hevc-safe-v1.cjs');

const MEDIA_ROOT = '/data/media';
const CACHE_ROOT = '/temp/studio-native';
const PRIVATE_ROOT = '/app/server/Tdarr/Custom/state/offload-v1';
const JOBS = 'offload-v1';
const MAC_MEDIA = '/private/var/lib/studio-worker/mounts/media';
const MAC_CACHE = '/private/var/lib/studio-worker/mounts/cache';
const MAC_FFMPEG = '/opt/homebrew/bin/ffmpeg';
const MAC_FFPROBE = '/opt/homebrew/bin/ffprobe';
const JOB_FILES = ['result.mkv', 'manifest.json', 'manifest.json.tmp'];
const ID = /^[0-9a-f]{32}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const PART = /^[A-Za-z0-9._-]+$/;
const DIRECTORY = C.O_RDONLY | C.O_DIRECTORY | C.O_NOFOLLOW;
const STALE_JOB_MS = 7 * 24 * 3600 * 1000;
const STALE_PRIVATE_MS = 24 * 3600 * 1000;
const MANIFEST_LIMIT = 64 * 1024;

const assert = (ok, message) => { if (!ok) throw new Error(`Offload HEVC: ${message}`); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const identity = stat => Object.fromEntries(['dev', 'ino', 'size', 'mtimeMs', 'ctimeMs'].map(k => [k, stat[k]]));
// dev/ino/ctime differ between the Mac's SMB view and the native filesystem, and SMB may round timestamps.
const portable = stat => ({ size: stat.size, mtimeSec: Math.floor(stat.mtimeMs / 1000) });
const samePortable = (a, b) => Number.isInteger(a?.size) && a.size === b?.size
  && Number.isInteger(a?.mtimeSec) && Number.isInteger(b?.mtimeSec) && Math.abs(a.mtimeSec - b.mtimeSec) <= 1;
const without = variables => {
  const copy = { ...variables };
  delete copy.homeserverSafeHevc;
  delete copy.homeserverOffload;
  return copy;
};
const nfc = value => value.normalize('NFC');

function jobId(relpath) {
  return crypto.createHash('sha256').update(relpath, 'utf8').digest('hex').slice(0, 32);
}

function relative(file, root) {
  assert(typeof file === 'string' && path.isAbsolute(file) && path.resolve(file) === file && inside(root, file),
    'file is outside the media root');
  return nfc(path.relative(root, file));
}

async function directory(root, privateDirectory = false) {
  assert(path.isAbsolute(root) && path.resolve(root) === root && await fs.realpath(root) === root,
    'directory must be canonical, without symlinks');
  const stat = await fs.lstat(root);
  assert(stat.isDirectory(), 'not a directory');
  if (privateDirectory) assert((stat.mode & 0o077) === 0 && stat.uid === process.getuid(),
    'private state must be owned by this user with mode 0700');
}

// macOS presents SMB names decomposed, so only a structural redirect (a symlink) may fail this check.
async function canonical(file) {
  return nfc(await fs.realpath(file)) === nfc(file);
}

function crf(value) {
  assert(typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value)
    && Number(value) >= 0 && Number(value) <= 51, 'missing or invalid library CRF');
  return value;
}

function macWorker(args, injected) {
  assert((injected.platform || process.platform) === 'darwin' && (injected.arch || process.arch) === 'arm64',
    'the encode legs run only on the native Apple Silicon worker');
  assert(args.workerType === 'transcodecpu', 'the encode legs require a CPU worker');
  assert(args.ffmpegPath === MAC_FFMPEG, 'select the Homebrew FFmpeg explicitly');
  return { media: injected.macMedia || MAC_MEDIA, cache: injected.macCache || MAC_CACHE };
}

async function probeFile(args, run, file) {
  const result = await run(MAC_FFPROBE, ['-v', 'error', '-show_streams', '-show_format', '-show_chapters', '-of', 'json', file],
    { signal: args.signal || args.abortSignal });
  return JSON.parse(result.stdout);
}

async function prepare(args, injected = {}) {
  const { media } = macWorker(args, injected);
  const run = injected.run || runProcess;
  crf(args.userVariables?.library?.crf);
  await directory(media);
  const source = args.inputFileObj._id;
  assert(source === args.originalLibraryFile._id, 'preparation must use the original file');
  const relpath = relative(source, media);
  assert(await canonical(source), 'source is redirected');
  const stat = await fs.stat(source);
  assert(stat.isFile(), 'source is not a regular file');
  assert((injected.now || Date.now)() - stat.mtimeMs >= 120000, 'source is still settling');
  const probe = await probeFile(args, run, source);
  const skip = safe.eligibility(probe, stat.size);
  if (skip) {
    args.jobLog(`Offload HEVC: skipped: ${skip}`);
    return { outputFileObj: args.inputFileObj, variables: args.variables, outputNumber: 2 };
  }
  args.variables.homeserverOffload = { relpath, source: portable(stat), probe };
  args.jobLog('Offload HEVC: captured source identity and stream contract on the encode worker');
  return { outputFileObj: args.inputFileObj, variables: args.variables, outputNumber: 1 };
}

async function removeJobFiles(directoryPath) {
  for (const file of JOB_FILES) {
    try { await fs.unlink(path.join(directoryPath, file)); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  try { await fs.rmdir(directoryPath); } catch (error) { if (error.code !== 'ENOENT') throw error; }
}

async function finish(args, injected = {}) {
  const { media, cache } = macWorker(args, injected);
  const run = injected.run || runProcess;
  const ticket = args.variables.homeserverOffload;
  assert(typeof ticket?.relpath === 'string' && ticket.probe && Number.isInteger(ticket.source?.size),
    'missing offload ticket');
  await directory(media);
  await directory(cache);
  const source = args.originalLibraryFile._id;
  assert(relative(source, media) === ticket.relpath, 'ticket belongs to another file');
  assert(samePortable(ticket.source, portable(await fs.stat(source))), 'source changed during encoding');
  const output = args.inputFileObj._id;
  assert(output !== source && path.extname(output) === '.mkv' && path.isAbsolute(output)
    && path.resolve(output) === output && inside(cache, output) && await canonical(output),
  'the encode must write a Matroska file inside the cache share');
  const stat = await fs.lstat(output);
  assert(stat.isFile() && stat.size > 0, 'empty encoded output');
  safe.validate(ticket.probe, await probeFile(args, run, output));
  if (stat.size > ticket.source.size * 0.95) {
    args.jobLog('Offload HEVC: skipped: less than 5% storage saving; original retained');
    return { outputFileObj: args.originalLibraryFile, variables: without(args.variables), outputNumber: 2 };
  }
  // Tdarr deletes the job's work directory when this leg ends, so move the result out of it first.
  const jobs = path.join(cache, JOBS), job = path.join(jobs, jobId(ticket.relpath));
  try { await fs.mkdir(jobs, { mode: 0o770 }); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  await removeJobFiles(job);
  await fs.mkdir(job, { mode: 0o770 });
  try {
    await fs.rename(output, path.join(job, 'result.mkv'));
    const pending = path.join(job, 'manifest.json.tmp');
    await fs.writeFile(pending, JSON.stringify({
      version: 1, relpath: ticket.relpath, source: ticket.source, resultSize: stat.size,
      finishedAt: new Date((injected.now || Date.now)()).toISOString(),
    }), { flag: 'wx', mode: 0o600 });
    await fs.rename(pending, path.join(job, 'manifest.json')); // The manifest is the last write: it marks a complete result.
  } catch (error) {
    try { await removeJobFiles(job); } catch { /* the sweeper retries */ }
    throw error;
  }
  args.jobLog(`Offload HEVC: encoded ${Math.round(stat.size / 1048576)} MiB of ${Math.round(ticket.source.size / 1048576)} MiB; handing over for validation`);
  return { outputFileObj: args.inputFileObj, variables: args.variables, outputNumber: 1 };
}

// Walks root/parts[0]/parts[1]/... holding every directory open, so a rename or symlink swap on the
// shared cache can never redirect a later step. `use` receives the pinned /proc/self/fd paths.
async function chain(root, parts, use) {
  const handles = [];
  const open = async (target, flags, mode) => {
    const handle = await fs.open(target, flags, mode);
    handles.push(handle);
    return handle;
  };
  try {
    const dirs = [`/proc/self/fd/${(await open(root, DIRECTORY)).fd}`];
    for (const part of parts) {
      assert(PART.test(part) && part !== '.' && part !== '..', 'invalid cache path component');
      dirs.push(`/proc/self/fd/${(await open(`${dirs.at(-1)}/${part}`, DIRECTORY)).fd}`);
    }
    return await use(dirs, open);
  } finally {
    // All handles must close even if one close fails.
    const closed = await Promise.allSettled(handles.reverse().map(handle => handle.close()));
    const failed = closed.filter(result => result.status === 'rejected');
    if (failed.length) throw new AggregateError(failed.map(result => result.reason), 'Offload HEVC: closing directory handles failed');
  }
}

async function privateCopy(cacheRoot, parts, file, target, maxSize, signal) {
  assert(PART.test(file) && file !== '.' && file !== '..', 'invalid cache file name');
  await directory(cacheRoot);
  return chain(cacheRoot, parts, async (dirs, open) => {
    const source = await open(`${dirs.at(-1)}/${file}`, C.O_RDONLY | C.O_NOFOLLOW | C.O_NONBLOCK);
    const before = await source.stat();
    assert(before.isFile() && before.nlink === 1 && before.size > 0 && before.size <= maxSize,
      'returned output must be a bounded, nonempty regular file with one link');
    const destination = await open(target, 'wx', 0o600);
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
    return before.size;
  });
}

async function readManifest(cacheRoot, id, relpath) {
  let text;
  try {
    text = await chain(cacheRoot, [JOBS, id], async (dirs, open) => {
      const handle = await open(`${dirs.at(-1)}/manifest.json`, C.O_RDONLY | C.O_NOFOLLOW | C.O_NONBLOCK);
      const stat = await handle.stat();
      assert(stat.isFile() && stat.nlink === 1 && stat.size > 0 && stat.size <= MANIFEST_LIMIT, 'invalid manifest file');
      const buffer = Buffer.alloc(stat.size);
      const { bytesRead } = await handle.read(buffer, 0, stat.size, 0);
      assert(bytesRead === stat.size, 'manifest changed while being read');
      return buffer.toString('utf8');
    });
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('Offload HEVC: no encoded result was handed over for this file');
    throw error;
  }
  let manifest;
  try { manifest = JSON.parse(text); } catch { assert(false, 'handover manifest is not valid JSON'); }
  assert(manifest?.version === 1 && manifest.relpath === relpath && Number.isInteger(manifest.source?.size)
    && Number.isInteger(manifest.source?.mtimeSec) && Number.isInteger(manifest.resultSize) && manifest.resultSize > 0,
  'handover manifest does not match this file');
  return manifest;
}

// Deletes one job directory through the pinned parent. With a cutoff, only if everything in it is older.
async function purge(parent, name, cutoff) {
  let job;
  try { job = await fs.open(`${parent}/${name}`, DIRECTORY); } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
  try {
    const inner = `/proc/self/fd/${job.fd}`;
    if (cutoff !== undefined) {
      const newest = [(await job.stat()).mtimeMs];
      for (const file of JOB_FILES) {
        try { newest.push((await fs.lstat(`${inner}/${file}`)).mtimeMs); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      }
      if (Math.max(...newest) >= cutoff) return false;
    }
    for (const file of JOB_FILES) {
      try { await fs.unlink(`${inner}/${file}`); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  } finally {
    await job.close();
  }
  await fs.rmdir(`${parent}/${name}`);
  return true;
}

async function purgeJob(cacheRoot, id) {
  try { await chain(cacheRoot, [JOBS], ([, jobs]) => purge(jobs, id)); } catch (error) { if (error.code !== 'ENOENT') throw error; }
}

// Best effort: abandoned handovers (killed jobs, reset queue rows) must not fill the cache forever.
async function sweep(cacheRoot, privateRoot, keep, now, log) {
  try {
    await chain(cacheRoot, [JOBS], async ([, jobs]) => {
      for (const name of await fs.readdir(jobs)) {
        if (!ID.test(name) || name === keep) continue;
        try { if (await purge(jobs, name, now - STALE_JOB_MS)) log(`Offload HEVC: removed an abandoned handover ${name}`); }
        catch (error) { log(`Offload HEVC: abandoned handover ${name} needs review: ${error.message}`); }
      }
    });
  } catch (error) {
    if (error.code !== 'ENOENT') log(`Offload HEVC: cache sweep failed: ${error.message}`);
  }
  try {
    for (const name of await fs.readdir(privateRoot)) {
      const target = path.join(privateRoot, name);
      try {
        const stat = await fs.lstat(target);
        if (!UUID.test(name) || !stat.isDirectory() || stat.mtimeMs >= now - STALE_PRIVATE_MS) continue;
        try { await fs.unlink(path.join(target, 'validated.mkv')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
        await fs.rmdir(target);
        log(`Offload HEVC: removed abandoned private staging ${name}`);
      } catch (error) { log(`Offload HEVC: private staging ${name} needs review: ${error.message}`); }
    }
  } catch (error) {
    log(`Offload HEVC: private sweep failed: ${error.message}`);
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
      throw new Error('Offload HEVC: unexpected validation binary');
    }
    assert((binary.endsWith('/ffprobe') ? argv[index] : argv[index + 1]) === staged,
      'unexpected validation probe input');
    return run(binary, [...argv.slice(0, index), '-f', 'matroska', ...argv.slice(index)], options);
  };
}

async function commit(args, injected = {}) {
  assert((injected.platform || process.platform) === 'linux', 'the publication leg runs only on the Linux worker');
  assert(/^transcode(?:cpu|gpu)$/.test(args.workerType), 'the publication leg requires a transcode worker');
  const mediaRoot = injected.mediaRoot || MEDIA_ROOT, cacheRoot = injected.cacheRoot || CACHE_ROOT;
  const privateRoot = injected.privateRoot || PRIVATE_ROOT;
  await directory(mediaRoot);
  await directory(cacheRoot);
  await fs.mkdir(privateRoot, { recursive: true, mode: 0o700 });
  await directory(privateRoot, true);
  assert(!inside(cacheRoot, privateRoot) && !inside(privateRoot, cacheRoot) && privateRoot !== cacheRoot,
    'private state must be outside shared cache');
  const source = args.originalLibraryFile._id;
  const relpath = relative(source, mediaRoot);
  const id = jobId(relpath);
  await sweep(cacheRoot, privateRoot, id, (injected.now || Date.now)(), args.jobLog);
  const work = path.join(privateRoot, crypto.randomUUID());
  await fs.mkdir(work, { mode: 0o700 });
  const staged = path.join(work, 'validated.mkv');
  try {
    const manifest = await readManifest(cacheRoot, id, relpath);
    // A fresh Linux-side probe and fingerprint: every later check compares against these, not the Mac's claims.
    const variables = { ...args.variables };
    const prepared = await safe.prepare({ ...args, inputFileObj: args.originalLibraryFile, variables }, injected);
    if (prepared.outputNumber !== 1) return { outputFileObj: args.originalLibraryFile, variables: without(args.variables), outputNumber: 2 };
    const saved = structuredClone(variables.homeserverSafeHevc);
    assert(samePortable(manifest.source, portable(saved.fingerprint)), 'source changed during offload');
    const copied = await privateCopy(cacheRoot, [JOBS, id], 'result.mkv', staged, saved.fingerprint.size,
      args.signal || args.abortSignal);
    assert(copied === manifest.resultSize, 'result size does not match its manifest');
    args.jobLog('Offload HEVC: shared result copied into Linux-private staging; validating only private bytes');
    const result = await safe.commit({
      ...args, inputFileObj: { _id: staged }, variables: { ...variables, homeserverSafeHevc: saved },
    }, { ...injected, run: matroskaOutputRunner(staged, injected.run || runProcess) });
    return { ...result, variables: without(result.variables) };
  } finally {
    // Cleanup must never fail a job whose original was already replaced.
    try { await fs.unlink(staged); } catch (error) { if (error.code !== 'ENOENT') args.jobLog(`Offload HEVC: private staging requires review: ${error.message}`); }
    try { await fs.rmdir(work); } catch (error) { if (error.code !== 'ENOENT') args.jobLog(`Offload HEVC: private staging requires review: ${error.message}`); }
    try { await purgeJob(cacheRoot, id); } catch (error) { args.jobLog(`Offload HEVC: shared handover cleanup requires review: ${error.message}`); }
  }
}

module.exports = {
  prepare, finish, commit, privateCopy, sweep, jobId, relative, crf,
  MEDIA_ROOT, CACHE_ROOT, PRIVATE_ROOT, JOBS, MAC_MEDIA, MAC_CACHE, MAC_FFMPEG, MAC_FFPROBE,
};
