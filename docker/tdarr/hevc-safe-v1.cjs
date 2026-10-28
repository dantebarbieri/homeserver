'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { internals: { inside, runProcess } } = require('./dv5-sidecar.cjs');

const FFMPEG = '/usr/lib/jellyfin-ffmpeg/ffmpeg';
const FFPROBE = '/usr/lib/jellyfin-ffmpeg/ffprobe';
const LEGACY = new Set(['h264', 'mpeg4', 'mpeg2video', 'mpeg1video', 'vc1', 'wmv3']);
const fingerprint = stat => Object.fromEntries(['dev', 'ino', 'size', 'mtimeMs', 'ctimeMs'].map(k => [k, stat[k]]));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const assert = (ok, message) => { if (!ok) throw new Error(`Safe HEVC: ${message}`); };
const duration = probe => Number(probe.format?.duration);
const videos = probe => probe.streams.filter(s => s.codec_type === 'video' && !s.disposition?.attached_pic);
const dispositions = s => Object.entries(s.disposition || {}).filter(([, v]) => v === 1).map(([k]) => k).sort();

function eligibility(probe, size) {
  assert(Array.isArray(probe?.streams), 'missing source streams');
  const video = videos(probe);
  if (video.length !== 1) return 'not a single-video source';
  if (!LEGACY.has(video[0].codec_name)) return 'already-efficient or unsupported source codec';
  if (size < 100 * 1024 ** 2 || size > 100000 * 1024 ** 2) return 'outside compression size policy';
  if (probe.streams.some(s => s.codec_type === 'data' || s.codec_name === 'mov_text')) {
    return 'stream cannot be copied losslessly into Matroska';
  }
  if (probe.streams.some(s => ['smpte2084', 'arib-std-b67', 'bt2020-10', 'bt2020-12'].includes(s.color_transfer)
    || s.color_primaries === 'bt2020'
    || (s.side_data_list || []).some(d => /dovi|dolby|mastering display|content light|hdr10/i.test(d.side_data_type || '')))) {
    return 'HDR source preserved without recompression';
  }
  assert(Number.isFinite(duration(probe)) && duration(probe) > 0, 'invalid source duration');
  return null;
}

function validate(source, output) {
  assert(Array.isArray(output?.streams), 'missing output streams');
  assert(Number.isFinite(duration(output)) && Math.abs(duration(source) - duration(output)) <= 1, 'duration mismatch');
  assert(source.streams.length === output.streams.length, 'stream count mismatch');
  for (let i = 0; i < source.streams.length; i++) {
    const a = source.streams[i], b = output.streams[i];
    assert(a.codec_type === b.codec_type, `stream ${i} type mismatch`);
    const video = a.codec_type === 'video' && !a.disposition?.attached_pic;
    assert(b.codec_name === (video ? 'hevc' : a.codec_name), `stream ${i} codec mismatch`);
    if (video) {
      assert(a.width === b.width && a.height === b.height, 'video dimensions changed');
      assert(b.pix_fmt === a.pix_fmt, 'video pixel format changed');
      if (a.sample_aspect_ratio && a.sample_aspect_ratio !== 'N/A') {
        assert(b.sample_aspect_ratio === a.sample_aspect_ratio, 'pixel aspect ratio changed');
      }
      if (a.avg_frame_rate && a.avg_frame_rate !== '0/0') {
        const rate = value => value.split('/').map(Number).reduce((n, d) => n / d);
        assert(Math.abs(rate(a.avg_frame_rate) - rate(b.avg_frame_rate || '0/1')) < 0.01, 'frame rate changed');
      }
      for (const k of ['color_primaries', 'color_transfer', 'color_space', 'color_range']) {
        if (a[k] && a[k] !== 'unknown') assert(b[k] === a[k], `${k} changed`);
      }
    } else if (a.codec_type === 'audio') {
      assert(a.channels === b.channels && a.sample_rate === b.sample_rate, `audio stream ${i} changed`);
    }
    for (const key of ['language', 'title']) {
      if (a.tags?.[key]) assert(b.tags?.[key] === a.tags[key], `stream ${i} ${key} changed`);
    }
    assert(equal(dispositions(a), dispositions(b)), `stream ${i} disposition changed`);
  }
  assert((source.chapters || []).length === (output.chapters || []).length, 'chapter count changed');
  for (let i = 0; i < (source.chapters || []).length; i++) {
    for (const k of ['start_time', 'end_time']) {
      assert(Math.abs(Number(source.chapters[i][k]) - Number(output.chapters[i][k])) <= 0.01, 'chapter timing changed');
    }
  }
}

function context(args, injected) {
  const io = injected.fs || fs, run = injected.run || runProcess;
  const probe = async file => JSON.parse((await run(FFPROBE,
    ['-v', 'error', '-show_streams', '-show_format', '-show_chapters', '-of', 'json', file],
    { signal: args.signal || args.abortSignal })).stdout);
  return { io, run, probe };
}

async function prepare(args, injected = {}) {
  const { io, probe } = context(args, injected);
  const source = args.inputFileObj._id;
  const root = await io.realpath(args.librarySettings.folder);
  assert(await io.realpath(source) === source && inside(root, source), 'source is redirected or outside library');
  const stat = await io.stat(source);
  assert(stat.isFile(), 'source is not a regular file');
  assert((injected.now || Date.now)() - stat.mtimeMs >= 120000, 'source is still settling');
  const original = await probe(source);
  const skip = eligibility(original, stat.size);
  if (skip) args.jobLog(`Safe HEVC: skipped: ${skip}`);
  else {
    args.variables.homeserverSafeHevc = { source, fingerprint: fingerprint(stat), probe: original };
    args.jobLog('Safe HEVC: captured source identity and stream contract');
  }
  return { outputFileObj: args.inputFileObj, variables: args.variables, outputNumber: skip ? 2 : 1 };
}

async function commit(args, injected = {}) {
  const { io, run, probe } = context(args, injected);
  const saved = args.variables.homeserverSafeHevc;
  assert(saved?.source === args.originalLibraryFile._id, 'source identity was not captured');
  const source = saved.source, output = args.inputFileObj._id;
  assert(output !== source && path.extname(output) === '.mkv', 'invalid encoded working file');
  const unchanged = async file => assert(equal(fingerprint(await io.stat(file)), saved.fingerprint), 'source changed during processing');
  await unchanged(source);
  const stat = await io.stat(output);
  assert(stat.isFile() && stat.size > 0, 'empty encoded output');
  validate(saved.probe, await probe(output));
  if (stat.size > saved.fingerprint.size * 0.95) {
    args.jobLog('Safe HEVC: skipped: less than 5% storage saving; original retained');
    return { outputFileObj: args.originalLibraryFile, variables: args.variables, outputNumber: 2 };
  }
  args.jobLog('Safe HEVC: decoding every video/audio packet before original replacement');
  const decoded = await run(FFMPEG, ['-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode',
    '-i', output, '-map', '0:v?', '-map', '0:a?', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'],
  { signal: args.signal || args.abortSignal, timeout: Math.max(300000, duration(saved.probe) * 2000) });
  const times = [...decoded.stdout.matchAll(/(?:^|\n)out_time_us=(\d+)/g)].map(m => Number(m[1]) / 1e6);
  assert(times.length && Math.max(...times) >= duration(saved.probe) - 2, 'full decode did not reach end of media');
  assert(equal(fingerprint(await io.stat(output)), fingerprint(stat)), 'encoded output changed during validation');
  await unchanged(source);
  const destination = path.join(path.dirname(source), path.basename(source, path.extname(source)) + '.mkv');
  const token = crypto.randomUUID();
  const stage = path.join(path.dirname(source), `.tdarr-${token}.partial`);
  const backup = `${source}.${token}.partial.old`;
  let moved = false, published = false;
  try {
    await io.copyFile(output, stage, 1);
    const staged = await io.stat(stage);
    assert(staged.size === stat.size, 'staging copy size mismatch');
    const handle = await io.open(stage, 'r+');
    try { await handle.sync(); } finally { await handle.close(); }
    await unchanged(source);
    await io.rename(source, backup);
    moved = true;
    // rename changes ctime; verify all other identity fields after taking ownership.
    const captured = fingerprint(await io.stat(backup));
    assert(['dev', 'ino', 'size', 'mtimeMs'].every(k => captured[k] === saved.fingerprint[k]), 'source changed before publication');
    await io.link(stage, destination);
    published = true;
    assert(equal(fingerprint(await io.stat(backup)), captured), 'original changed during publication');
    await io.unlink(backup);
    moved = false;
  } catch (error) {
    if (moved && !published) {
      try { await io.link(backup, source); await io.unlink(backup); }
      catch (restore) { throw new AggregateError([error, restore], `Safe HEVC: restore requires review; original preserved at ${backup}`); }
    }
    if (published) args.jobLog(`Safe HEVC: original retained for manual recovery at ${backup}`);
    throw error;
  } finally {
    try { await io.unlink(stage); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  args.jobLog(`Safe HEVC: verified replacement published: ${destination}`);
  return { outputFileObj: { _id: destination }, variables: args.variables, outputNumber: 1 };
}

module.exports = { prepare, commit, eligibility, validate, fingerprint, LEGACY };
