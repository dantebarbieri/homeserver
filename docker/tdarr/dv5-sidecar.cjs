'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

const VERSION = '1';
const HOME = '/app/server/Tdarr/Custom';
const GIB = 1024 ** 3;
const TEXT = new Set(['subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt', 'text']);
const COPY_AUDIO = new Set(['aac', 'ac3', 'eac3']);
const suffix = ' - [WEBRip-1080p][SDR][h264]-PlexSDR.mp4';
const assert = (ok, message) => { if (!ok) throw new Error(`DV5 sidecar: ${message}`); };
const fingerprint = (realpath, stat) => ({ realpath, size: stat.size, mtimeMs: stat.mtimeMs });
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const inside = (root, file) => file !== root && !path.relative(root, file).startsWith(`..${path.sep}`)
  && path.relative(root, file) !== '..' && !path.isAbsolute(path.relative(root, file));
const skipped = file => /(?:^|[/\\])Plex Versions(?:[/\\]|$)|\.partial(?:[./\\-]|$)|-AppleTV\.mp4$|-PlexSDR(?:[.\s-]|$)/i.test(file);
const disposition = stream => Object.entries(stream.disposition || {}).filter(([, v]) => v === 1).map(([k]) => k).sort();
const duration = probe => Number(probe.format?.duration);

function dimensions(width, height) {
  assert(Number.isInteger(width) && Number.isInteger(height) && width >= 2 && height >= 2, 'invalid video dimensions');
  const scale = Math.min(1, 1920 / width, 1080 / height);
  return [Math.max(2, Math.floor(width * scale / 2) * 2), Math.max(2, Math.floor(height * scale / 2) * 2)];
}

function plan(probe) {
  assert(probe && Array.isArray(probe.streams) && probe.streams.length, 'invalid probe streams');
  const videos = probe.streams.filter(s => s.codec_type === 'video' && !s.disposition?.attached_pic);
  assert(videos.length === 1, 'expected exactly one actual video stream');
  const video = videos[0];
  const dovi = (video.side_data_list || []).find(s => s.dv_profile !== undefined);
  if (video.codec_name !== 'hevc' || Number(dovi?.dv_profile) !== 5
    || Number(dovi?.dv_bl_signal_compatibility_id) !== 0) return null;
  assert(Number.isFinite(duration(probe)) && duration(probe) > 0, 'invalid source duration');
  const audio = probe.streams.filter(s => s.codec_type === 'audio');
  const subtitles = probe.streams.filter(s => s.codec_type === 'subtitle');
  assert(audio.length > 0, 'source has no audio');
  assert(audio.every(s => Number.isInteger(s.channels) && s.channels > 0), 'invalid audio channel count');
  assert(subtitles.every(s => TEXT.has(s.codec_name)), 'bitmap or unknown subtitle codec; refusing to drop tracks');
  const streams = [video, ...audio, ...subtitles];
  assert(streams.every(s => Number.isInteger(s.index) && s.index >= 0)
    && new Set(streams.map(s => s.index)).size === streams.length, 'invalid stream indices');
  return { video, audio, subtitles, dimensions: dimensions(video.width, video.height), seconds: duration(probe) };
}

function streamArgs(p, input = 0) {
  const argv = [];
  for (const [kind, streams] of [['a', p.audio], ['s', p.subtitles]]) {
    streams.forEach((s, i) => {
      argv.push('-map', `${input}:${s.index}`);
      if (kind === 'a') {
        const copy = COPY_AUDIO.has(s.codec_name) && s.channels <= 6;
        argv.push(`-c:a:${i}`, copy ? 'copy' : 'aac');
        if (!copy) argv.push(`-ac:a:${i}`, String(Math.min(6, s.channels)), `-b:a:${i}`, '512k');
      } else argv.push(`-c:s:${i}`, 'mov_text');
      argv.push(`-disposition:${kind}:${i}`, disposition(s).join('+') || '0');
      for (const tag of ['language', 'title']) {
        if (s.tags?.[tag]) argv.push(`-metadata:s:${kind}:${i}`, `${tag}=${s.tags[tag]}`);
      }
    });
  }
  if (p.subtitles.length) argv.push('-bsf:s', 'setts=pts=PTS*TB/TB_OUT:dts=DTS*TB/TB_OUT:duration=DURATION*TB/TB_OUT:time_base=1/1000');
  return argv;
}

function encodeArgs(source, output, p) {
  const [w, h] = p.dimensions;
  return ['-hide_banner', '-nostdin', '-n', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-i', source,
    '-map', `0:${p.video.index}`, '-map_metadata', '-1', '-map_chapters', '0', ...streamArgs(p),
    '-vf', `tonemap_cuda=tonemap=bt2390:apply_dovi=1:format=yuv420p:range=tv,scale_cuda=w=${w}:h=${h}:format=yuv420p`,
    '-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-b:v', '7M',
    '-maxrate:v', '8M', '-bufsize:v', '8M', '-profile:v', 'high', '-level:v', '4.1',
    '-color_range', 'tv', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
    '-movflags', '+faststart', '-f', 'mp4', output];
}

function validate(probe, p) {
  assert(probe && Array.isArray(probe.streams), 'invalid output probe');
  const video = probe.streams.filter(s => s.codec_type === 'video');
  const audio = probe.streams.filter(s => s.codec_type === 'audio');
  const subs = probe.streams.filter(s => s.codec_type === 'subtitle');
  assert(video.length === 1 && video[0].codec_name === 'h264', 'output is not single-video H264');
  const v = video[0];
  assert(v.width === p.dimensions[0] && v.height === p.dimensions[1] && v.pix_fmt === 'yuv420p', 'output dimensions/pixel format mismatch');
  assert(['color_primaries', 'color_transfer', 'color_space'].every(k => v[k] === 'bt709'), 'output is not BT709 SDR');
  assert(!probe.streams.some(s => (s.side_data_list || []).some(d => d.dv_profile !== undefined
    || /dolby|dovi|mastering display|content light/i.test(d.side_data_type || ''))), 'output retains HDR/Dolby metadata');
  assert(Number.isFinite(duration(probe)) && Math.abs(duration(probe) - p.seconds) <= 1, 'output duration mismatch');
  assert(audio.length === p.audio.length && subs.length === p.subtitles.length, 'output lost audio/subtitle streams');
  for (const [actual, expected, kind] of [[audio, p.audio, 'audio'], [subs, p.subtitles, 'subtitle']]) {
    actual.forEach((s, i) => {
      const original = expected[i];
      const copied = kind === 'audio' && COPY_AUDIO.has(original.codec_name) && original.channels <= 6;
      assert(s.codec_name === (kind === 'subtitle' ? 'mov_text' : copied ? original.codec_name : 'aac'), `${kind} codec mismatch`);
      if (kind === 'audio') assert(s.channels === Math.min(original.channels, 6), 'audio channel mismatch');
      assert(same(disposition(s), disposition(original)), `${kind} disposition mismatch`);
      if (original.tags?.language) assert(s.tags?.language === original.tags.language, `${kind} language mismatch`);
    });
  }
}

function runProcess(binary, argv, { signal, timeout = 90000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(binary, argv, { stdio: ['ignore', 'pipe', 'pipe'], signal });
    let stdout = '', stderr = '', failure;
    const kill = () => child.kill('SIGKILL');
    const timer = setTimeout(() => { failure = new Error(`${path.basename(binary)} timed out`); kill(); }, timeout);
    process.once('exit', kill);
    child.stdout.on('data', b => {
      stdout += b;
      if (stdout.length > 4 * 1024 * 1024) { failure = new Error('probe output exceeded limit'); kill(); }
    });
    child.stderr.on('data', b => { stderr = (stderr + b).slice(-8192); });
    child.on('error', error => { failure = error; });
    child.on('close', code => {
      clearTimeout(timer);
      process.removeListener('exit', kill);
      if (failure || code !== 0) reject(failure || new Error(`${path.basename(binary)} exited ${code}: ${stderr}`));
      else resolve({ stdout });
    });
  });
}

function runner(args) {
  return async (binary, argv, options = {}) => {
    const signal = args.signal || args.abortSignal;
    signal?.throwIfAborted();
    if (!options.encode) return runProcess(binary, argv, { signal });
    assert(args.config?.pluginsPath, 'Tdarr CLI helper unavailable; refusing an untracked encode');
    const { CLI } = require(path.join(args.config.pluginsPath, 'FlowPlugins/FlowHelpers/1.0.0/cliUtils'));
    const cli = new CLI({ cli: binary, spawnArgs: argv, spawnOpts: {}, jobLog: args.jobLog,
      outputFilePath: options.output, inputFileObj: args.inputFileObj, logFullCliOutput: false,
      updateWorker: args.updateWorker, args });
    const abort = () => cli.killThread();
    signal?.addEventListener('abort', abort, { once: true });
    try {
      const result = await cli.runCli();
      signal?.throwIfAborted();
      assert(result.cliExitCode === 0, `FFmpeg failed with exit ${result.cliExitCode}`);
      return {};
    } finally { signal?.removeEventListener('abort', abort); }
  };
}

async function generate(args, injected = {}) {
  const io = injected.fs || fs, run = injected.run || runner(args), now = injected.now || Date.now;
  const home = injected.home || HOME, minAge = injected.minAge ?? 120000;
  const result = (outputNumber = 1) => ({ outputFileObj: args.inputFileObj, outputNumber, variables: args.variables });
  const skip = () => result(injected.classifyOnly ? 2 : 1);
  const log = message => args.jobLog(`DV5 sidecar: ${message}`);
  const input = args.inputFileObj?._id, folder = args.librarySettings?.folder;
  assert(typeof input === 'string' && path.isAbsolute(input) && typeof folder === 'string' && path.isAbsolute(folder), 'absolute source/library paths required');
  if (skipped(input)) { log('skipped generated/partial file'); return skip(); }
  const root = await io.realpath(folder), source = await io.realpath(input);
  assert(inside(root, source), 'source escapes library folder');
  if (skipped(source)) { log('skipped generated target'); return skip(); }
  const initial = await io.stat(source);
  assert(initial.isFile() && initial.size > 0, 'source is not a nonempty regular file');
  assert(now() - initial.mtimeMs >= minAge, 'source is still settling (minimum 120 seconds)');
  const original = fingerprint(source, initial);
  // Tdarr's default "tdarr-ffmpeg" wrapper is not the verified DV-aware binary.
  const ffmpeg = '/usr/lib/jellyfin-ffmpeg/ffmpeg';
  const ffprobe = path.join(path.dirname(ffmpeg), 'ffprobe');
  const probe = async file => {
    const res = await run(ffprobe, ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', file]);
    try { return JSON.parse(res.stdout); } catch { throw new Error('DV5 sidecar: invalid ffprobe JSON'); }
  };
  const p = plan(await probe(source));
  if (!p) { log('skipped: not HEVC Dolby Vision profile 5 compatibility 0'); return skip(); }
  if (injected.classifyOnly) {
    log('eligible Profile 5 source; routing to the dedicated GPU worker');
    return result();
  }
  for (const s of p.audio) if (!COPY_AUDIO.has(s.codec_name) || s.channels > 6) log(`audio stream ${s.index}: ${s.codec_name}/${s.channels}ch -> AAC/${Math.min(s.channels, 6)}ch`);
  const name = path.basename(path.dirname(source)).replace(/[\x00-\x1f]/g, '').trim();
  assert(name && name !== '.' && name !== '..', 'invalid movie folder name');
  const outputDir = path.join(path.dirname(source), 'Plex Versions', 'Homeserver SDR');
  const output = path.join(outputDir, name + suffix);
  const state = path.join(home, 'state'), lock = path.join(home, 'dv5-sidecar.lock');
  await io.mkdir(state, { recursive: true });
  let acquired = false, work;
  const stable = async () => {
    const current = await io.stat(source);
    assert(same(original, fingerprint(await io.realpath(input), current))
      && ['ino', 'dev', 'ctimeMs'].every(k => current[k] === initial[k]), 'source changed during processing');
  };
  const checkedOutput = async file => {
    const stat = await io.stat(file);
    assert(stat.isFile() && stat.size > 0, 'output is empty or not a regular file');
    validate(await probe(file), p);
    for (const seconds of [0, p.seconds / 2, Math.max(0, p.seconds - 2)]) {
      const sample = await run(ffmpeg, ['-v', 'error', '-nostdin', '-xerror', '-ss', String(seconds), '-i', file,
        '-map', '0:v:0', '-frames:v', '3', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']);
      assert([...sample.stdout.matchAll(/(?:^|\n)frame=(\d+)/g)].some(m => Number(m[1]) >= 3), 'sample decode did not produce three frames');
    }
  };
  try {
    try { await io.mkdir(lock); acquired = true; } catch (e) {
      if (e.code === 'EEXIST') throw new Error('DV5 sidecar: GPU lock busy; retry after its owner finishes');
      throw e;
    }
    await stable();
    for (const dir of [path.dirname(outputDir), outputDir]) {
      await io.mkdir(dir, { recursive: true });
      assert(await io.realpath(dir) === dir && inside(root, dir), 'output directory is redirected or outside library');
    }
    const manifest = path.join(state, crypto.createHash('sha256').update(output).digest('hex') + '.json');
    let existing;
    try { existing = await io.lstat(output); } catch (e) { if (e.code !== 'ENOENT') throw e; }
    if (existing) {
      assert(existing.isFile() && !existing.isSymbolicLink(), 'existing output is not a regular file');
      let saved;
      try { saved = JSON.parse(await io.readFile(manifest, 'utf8')); } catch { throw new Error('DV5 sidecar: existing output lacks an owned valid manifest'); }
      assert(saved.version === VERSION && saved.output === output && same(saved.source, original), 'stale/conflicting sidecar; manual review required');
      await checkedOutput(output); await stable();
      log(`validated existing sidecar: ${output}`); return result();
    }
    const audioRate = p.audio.reduce((sum, s) => sum + (COPY_AUDIO.has(s.codec_name) && s.channels <= 6
      ? Math.max(6000000, Number(s.bit_rate) || 0) : 512000), 0);
    const space = await io.statfs(outputDir);
    const required = Math.ceil((8000000 + audioRate) * p.seconds / 8 * 1.1) + initial.size + GIB;
    assert(Number(space.bavail) * Number(space.bsize) >= required, 'insufficient free space for output, staging and 1 GiB reserve');
    const candidate = path.join(outputDir, `.dv5-${crypto.randomUUID()}.partial`);
    await io.mkdir(candidate);
    work = candidate;
    const stage = path.join(work, 'sidecar.mp4');
    await run(ffmpeg, encodeArgs(source, stage, p), { encode: true, output: stage });
    await checkedOutput(stage); await stable();
    const manifestStage = path.join(work, 'manifest.json');
    await io.writeFile(manifestStage, JSON.stringify({ version: VERSION, source: original, output }), { flag: 'wx', mode: 0o600 });
    // Hard-link publication is atomic and cannot clobber a concurrent or unmanaged output.
    await io.link(stage, output);
    await io.unlink(stage);
    const stateStage = path.join(state, `.manifest-${crypto.randomUUID()}.partial`);
    try {
      await io.copyFile(manifestStage, stateStage, 1);
      await io.rename(stateStage, manifest);
    } finally { await io.unlink(stateStage).catch(e => { if (e.code !== 'ENOENT') throw e; }); }
    await stable();
    log(`created and verified SDR sidecar; original preserved: ${output}`);
    return result();
  } finally {
    try { if (work) await io.rm(work, { recursive: true, force: true }); }
    finally { if (acquired) await io.rmdir(lock); }
  }
}

module.exports = async args => generate(args);
module.exports.classify = async args => generate(args, { classifyOnly: true });
module.exports.internals = { VERSION, dimensions, plan, streamArgs, encodeArgs, validate, skipped, inside, fingerprint, runProcess, generate };
