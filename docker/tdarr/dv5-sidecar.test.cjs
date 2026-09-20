'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { internals: h } = require('./dv5-sidecar.cjs');

function sourceProbe() {
  return { format: { duration: '120' }, streams: [
    { index: 0, codec_type: 'video', codec_name: 'hevc', width: 3840, height: 1600,
      side_data_list: [{ side_data_type: 'DOVI configuration record', dv_profile: 5, dv_bl_signal_compatibility_id: 0 }] },
    { index: 1, codec_type: 'audio', codec_name: 'eac3', channels: 6, disposition: { default: 1 }, tags: { language: 'eng' } },
    { index: 2, codec_type: 'subtitle', codec_name: 'subrip', disposition: { forced: 1, default: 0 }, tags: { language: 'eng' } },
  ] };
}
function outputProbe(source = sourceProbe()) {
  const p = h.plan(source);
  return { format: { duration: '120' }, streams: [
    { index: 0, codec_type: 'video', codec_name: 'h264', width: p.dimensions[0], height: p.dimensions[1],
      pix_fmt: 'yuv420p', color_primaries: 'bt709', color_transfer: 'bt709', color_space: 'bt709' },
    ...p.audio.map(s => ({ ...s, codec_name: ['aac', 'ac3', 'eac3'].includes(s.codec_name) && s.channels <= 6 ? s.codec_name : 'aac', channels: Math.min(s.channels, 6) })),
    ...p.subtitles.map(s => ({ ...s, codec_name: 'mov_text' })),
  ] };
}

test('DV5 only; no Dolby Vision, other codecs and profile 8 skip normally', () => {
  assert.ok(h.plan(sourceProbe()));
  for (const change of [v => { v.side_data_list = []; }, v => { v.side_data_list[0].dv_profile = 8; },
    v => { v.codec_name = 'h264'; }, v => { v.side_data_list[0].dv_bl_signal_compatibility_id = 1; }]) {
    const probe = sourceProbe(); change(probe.streams[0]); assert.equal(h.plan(probe), null);
  }
});
test('guards partials and both old/new generated naming conventions', () => {
  for (const name of ['/movies/A/Plex Versions/Homeserver SDR/a.mp4', '/movies/a-AppleTV.mp4', '/movies/a-PlexSDR.mp4', '/movies/.dv5-x.partial/a.mp4']) assert.ok(h.skipped(name));
  assert.equal(h.skipped('/movies/A/movie.mkv'), false);
  assert.equal(h.inside('/movies', '/movies-evil/a.mkv'), false);
});
test('dimension limits preserve aspect, even dimensions and no upscale', () => {
  assert.deepEqual(h.dimensions(3840, 1600), [1920, 800]);
  assert.deepEqual(h.dimensions(3840, 2160), [1920, 1080]);
  assert.deepEqual(h.dimensions(720, 1280), [606, 1080]);
  assert.deepEqual(h.dimensions(641, 481), [640, 480]);
  assert.throws(() => h.dimensions(0, 1080));
});
test('invalid probes, extra actual videos, missing audio and bitmap subtitles fail closed', () => {
  assert.throws(() => h.plan({}));
  for (const change of [p => { p.format.duration = 'NaN'; }, p => p.streams.push({ ...p.streams[0], index: 3 }),
    p => { p.streams = p.streams.filter(s => s.codec_type !== 'audio'); }, p => { p.streams[2].codec_name = 'hdmv_pgs_subtitle'; }]) {
    const p = sourceProbe(); change(p); assert.throws(() => h.plan(p));
  }
  const p = sourceProbe(); p.streams.push({ index: 3, codec_type: 'video', disposition: { attached_pic: 1 } });
  assert.ok(h.plan(p));
});
test('argv preserves Atmos, all subtitles and millisecond subtitle time base', () => {
  const probe = sourceProbe(); probe.streams.push({ index: 4, codec_type: 'audio', codec_name: 'truehd', channels: 8, disposition: {} });
  const p = h.plan(probe), argv = h.encodeArgs('/a/movie [DV].mkv', '/a/.partial/out.mp4', p);
  assert.equal(argv[argv.indexOf('-i') + 1], '/a/movie [DV].mkv');
  assert.equal(argv[argv.indexOf('-c:a:0') + 1], 'copy');
  assert.equal(argv[argv.indexOf('-c:a:1') + 1], 'aac');
  assert.equal(argv[argv.indexOf('-ac:a:1') + 1], '6');
  assert.equal(argv[argv.indexOf('-disposition:s:0') + 1], 'forced');
  assert.match(argv[argv.indexOf('-bsf:s') + 1], /duration=DURATION\*TB\/TB_OUT:time_base=1\/1000$/);
  assert.match(argv[argv.indexOf('-vf') + 1], /apply_dovi=1.*w=1920:h=800/);
  assert.ok(argv.includes('-n'));
});
test('validation rejects lost streams, Dolby metadata, wrong color and wrong duration', () => {
  const p = h.plan(sourceProbe());
  h.validate(outputProbe(), p);
  for (const change of [o => o.streams.pop(), o => { o.format.duration = '124'; },
    o => { o.streams[0].color_space = 'bt2020nc'; },
    o => { o.streams[0].side_data_list = [{ side_data_type: 'DOVI configuration record' }]; },
    o => { o.streams[1].codec_name = 'aac'; }, o => { o.streams[2].disposition.forced = 0; }]) {
    const o = outputProbe(); change(o); assert.throws(() => h.validate(o, p));
  }
});

function fixture() {
  const input = '/media/Movie (2026)/Movie - [DV].mkv';
  const home = '/state', files = new Map([[input, { size: 1000, mtimeMs: 1000 }]]);
  const dirs = new Set(['/media', '/media/Movie (2026)', home]), calls = [], logs = [];
  const error = code => Object.assign(new Error(code), { code });
  const stat = f => {
    if (!files.has(f)) throw error('ENOENT');
    return { ...files.get(f), isFile: () => true, isSymbolicLink: () => false };
  };
  const io = {
    realpath: async f => f, stat: async f => stat(f), lstat: async f => stat(f),
    mkdir: async (f, o) => { if (dirs.has(f) && !o?.recursive) throw error('EEXIST'); dirs.add(f); },
    statfs: async () => ({ bavail: 100000000, bsize: 4096 }),
    readFile: async f => { if (!files.has(f)) throw error('ENOENT'); return files.get(f).data; },
    writeFile: async (f, data) => { if (files.has(f)) throw error('EEXIST'); files.set(f, { data, size: data.length }); },
    link: async (a, b) => { if (files.has(b)) throw error('EEXIST'); files.set(b, { ...files.get(a) }); },
    unlink: async f => { if (!files.delete(f)) throw error('ENOENT'); },
    copyFile: async (a, b) => { if (files.has(b)) throw error('EEXIST'); files.set(b, { ...files.get(a) }); },
    rename: async (a, b) => { files.set(b, files.get(a)); files.delete(a); },
    rm: async f => { for (const k of files.keys()) if (k.startsWith(f + '/')) files.delete(k); dirs.delete(f); },
    rmdir: async f => { dirs.delete(f); },
  };
  const run = async (binary, argv, options = {}) => {
    calls.push({ binary, argv, options });
    if (path.basename(binary) === 'ffprobe') return { stdout: JSON.stringify(argv.at(-1) === input ? sourceProbe() : outputProbe()) };
    if (options.encode) files.set(options.output, { size: 800, mtimeMs: 2000 });
    return { stdout: argv.includes('-frames:v') ? 'frame=3\nprogress=end\n' : '' };
  };
  const args = { inputFileObj: { _id: input }, librarySettings: { folder: '/media' }, variables: { retained: true }, jobLog: s => logs.push(s) };
  return { input, home, files, dirs, calls, logs, io, run, args, options: { fs: io, run, home, now: () => 200000 } };
}
test('publishes sidecar, preserves source identity and idempotently validates every reuse', async () => {
  const f = fixture(), original = { ...f.files.get(f.input) };
  const res = await h.generate(f.args, f.options);
  assert.equal(res.outputFileObj, f.args.inputFileObj);
  assert.equal(res.variables, f.args.variables);
  assert.equal(res.outputNumber, 1);
  assert.deepEqual(f.files.get(f.input), original);
  assert.equal(f.calls.filter(c => c.options.encode).length, 1);
  await h.generate(f.args, f.options);
  assert.equal(f.calls.filter(c => c.options.encode).length, 1);
  assert.equal(f.calls.filter(c => c.argv.includes('-frames:v')).length, 6);
  assert.equal(f.dirs.has('/state/dv5-sidecar.lock'), false);
  assert.ok(f.logs.some(l => l.includes('validated existing')));
});
test('uses the DV-aware bundled tools instead of Tdarr wrapper paths', async () => {
  const f = fixture();
  f.args.ffmpegPath = 'tdarr-ffmpeg';
  await h.generate(f.args, f.options);
  assert.ok(f.calls.every(call => call.binary.startsWith('/usr/lib/jellyfin-ffmpeg/')));
});
test('CPU classification routes only eligible sources to GPU without creating output or locks', async () => {
  const f = fixture();
  const options = { ...f.options, classifyOnly: true };
  assert.equal((await h.generate(f.args, options)).outputNumber, 1);
  assert.equal(f.files.size, 1);
  assert.equal(f.dirs.has('/state/state'), false);
  assert.equal(f.calls.filter(call => call.options.encode).length, 0);
  const probe = sourceProbe();
  probe.streams[0].side_data_list[0].dv_profile = 8;
  options.run = async () => ({ stdout: JSON.stringify(probe) });
  assert.equal((await h.generate(f.args, options)).outputNumber, 2);
  f.args.inputFileObj._id = '/media/Movie/Plex Versions/Homeserver SDR/movie.mp4';
  assert.equal((await h.generate(f.args, options)).outputNumber, 2);
});
test('unowned/conflicting output is never overwritten', async () => {
  const f = fixture();
  const output = '/media/Movie (2026)/Plex Versions/Homeserver SDR/Movie (2026) - [WEBRip-1080p][SDR][h264]-PlexSDR.mp4';
  f.files.set(output, { size: 123 });
  await assert.rejects(h.generate(f.args, f.options), /manifest/);
  assert.equal(f.files.get(output).size, 123);
  assert.equal(f.calls.filter(c => c.options.encode).length, 0);
});
test('stale source manifest is explicit, not overwritten', async () => {
  const f = fixture(); await h.generate(f.args, f.options);
  f.files.get(f.input).mtimeMs++;
  await assert.rejects(h.generate(f.args, f.options), /stale/);
  assert.equal(f.calls.filter(c => c.options.encode).length, 1);
});
test('lock contention never releases another worker lock', async () => {
  const f = fixture(); f.dirs.add('/state/dv5-sidecar.lock');
  await assert.rejects(h.generate(f.args, f.options), /lock busy/);
  assert.ok(f.dirs.has('/state/dv5-sidecar.lock'));
});
test('source age, space, redirected paths and source changes fail closed', async () => {
  const young = fixture(); young.options.now = () => 1001;
  await assert.rejects(h.generate(young.args, young.options), /settling/);
  const full = fixture(); full.io.statfs = async () => ({ bavail: 1, bsize: 1 });
  await assert.rejects(h.generate(full.args, full.options), /free space/);
  const escape = fixture(); escape.io.realpath = async f => f === escape.input ? '/outside/movie.mkv' : f;
  await assert.rejects(h.generate(escape.args, escape.options), /escapes/);
  const changed = fixture();
  changed.options.run = async (...args) => { const result = await changed.run(...args); if (args[2]?.encode) changed.files.get(changed.input).mtimeMs++; return result; };
  await assert.rejects(h.generate(changed.args, changed.options), /source changed/);
  assert.equal([...changed.files.keys()].filter(k => k.endsWith('-PlexSDR.mp4')).length, 0);
});
test('publication refuses a competing output appearing after encoding', async () => {
  const f = fixture(), link = f.io.link;
  f.io.link = async (a, b) => { f.files.set(b, { size: 777 }); return link(a, b); };
  await assert.rejects(h.generate(f.args, f.options), /EEXIST/);
  assert.equal([...f.files.values()].filter(v => v.size === 777).length, 1);
  assert.ok(f.files.has(f.input));
});
test('output symlink escape is refused before creating children outside library', async () => {
  const f = fixture();
  f.io.realpath = async p => p.endsWith('/Plex Versions') ? '/outside' : p;
  await assert.rejects(h.generate(f.args, f.options), /redirected/);
  assert.equal(f.dirs.has('/media/Movie (2026)/Plex Versions/Homeserver SDR'), false);
});
test('zero-frame sample decodes prevent publication', async () => {
  const f = fixture();
  f.options.run = async (...args) => args[1].includes('-frames:v') ? { stdout: 'frame=0\nprogress=end\n' } : f.run(...args);
  await assert.rejects(h.generate(f.args, f.options), /three frames/);
  assert.equal([...f.files.keys()].filter(k => k.endsWith('-PlexSDR.mp4')).length, 0);
});
test('non-DV and generated files do not create outputs, locks or state', async () => {
  const f = fixture(), probe = sourceProbe(); probe.streams[0].side_data_list = [];
  f.options.run = async () => ({ stdout: JSON.stringify(probe) });
  assert.equal((await h.generate(f.args, f.options)).outputFileObj, f.args.inputFileObj);
  assert.equal(f.files.size, 1);
  assert.equal(f.dirs.has('/state/state'), false);
  f.args.inputFileObj._id = '/media/Movie/Plex Versions/Homeserver SDR/movie.mp4';
  f.io.realpath = async () => { throw new Error('should not reach filesystem'); };
  await h.generate(f.args, f.options);
});
test('encode/probe errors clean only owned staging and release acquired lock', async () => {
  const f = fixture();
  f.options.run = async (...args) => { if (args[2]?.encode) throw new Error('GPU failed'); return f.run(...args); };
  await assert.rejects(h.generate(f.args, f.options), /GPU failed/);
  assert.equal(f.files.size, 1);
  assert.equal(f.dirs.has('/state/dv5-sidecar.lock'), false);
  const invalid = fixture(); invalid.options.run = async () => ({ stdout: 'not JSON' });
  await assert.rejects(h.generate(invalid.args, invalid.options), /invalid ffprobe JSON/);
});
test('existing owned output is revalidated, not trusted solely by its manifest', async () => {
  const f = fixture(); await h.generate(f.args, f.options);
  f.options.run = async (binary, argv, options) => {
    if (path.basename(binary) === 'ffprobe' && argv.at(-1) !== f.input) return { stdout: JSON.stringify({ streams: [] }) };
    return f.run(binary, argv, options);
  };
  await assert.rejects(h.generate(f.args, f.options), /single-video/);
  assert.equal(f.calls.filter(c => c.options.encode).length, 1);
});
test('subprocess runner reports process errors and observes cancellation and timeouts', async () => {
  await assert.rejects(h.runProcess(process.execPath, ['-e', 'process.exit(7)']), /exited 7/);
  const controller = new AbortController();
  const promise = h.runProcess(process.execPath, ['-e', 'setTimeout(() => {}, 30000)'], { signal: controller.signal });
  controller.abort();
  await assert.rejects(promise, /abort/i);
  await assert.rejects(h.runProcess(process.execPath, ['-e', 'setTimeout(() => {}, 30000)'], { timeout: 30 }), /timed out/);
});
