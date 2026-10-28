'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { eligibility, validate, fingerprint, commit } = require('./hevc-safe-v1.cjs');
const { flowDefinition } = require('./install-safe-flows.cjs');
const { recoveryStatus } = require('./recover-policy-errors.cjs');

function probe(codec = 'h264') {
  return { format: { duration: '120' }, chapters: [{ start_time: '0', end_time: '120' }], streams: [
    { codec_type: 'video', codec_name: codec, width: 1920, height: 1080, pix_fmt: 'yuv420p',
      avg_frame_rate: '24000/1001', color_primaries: 'bt709', color_transfer: 'bt709', color_space: 'bt709',
      disposition: { default: 1 } },
    { codec_type: 'audio', codec_name: 'aac', channels: 2, sample_rate: '48000', tags: { language: 'eng' } },
    { codec_type: 'subtitle', codec_name: 'subrip', tags: { language: 'eng', title: 'Forced' }, disposition: { forced: 1 } },
  ] };
}

test('only legacy SDR sources are eligible; efficient codecs, HDR, incompatible streams and size policy skip', () => {
  assert.equal(eligibility(probe(), 200 * 1024 ** 2), null);
  for (const codec of ['hevc', 'av1', 'vp9']) assert.match(eligibility(probe(codec), 200 * 1024 ** 2), /codec/);
  for (const transfer of ['smpte2084', 'arib-std-b67', 'bt2020-10']) {
    const p = probe(); p.streams[0].color_transfer = transfer;
    assert.match(eligibility(p, 200 * 1024 ** 2), /HDR/);
  }
  const p = probe(); p.streams[2].codec_name = 'mov_text';
  assert.match(eligibility(p, 200 * 1024 ** 2), /Matroska/);
  assert.match(eligibility(probe(), 10), /size policy/);
});

test('stream contract detects truncation, lost audio/subtitles, metadata, color, chapters and dimensions', () => {
  validate(probe(), probe('hevc'));
  for (const change of [
    p => { p.format.duration = '115'; }, p => p.streams.pop(),
    p => { p.streams[0].width = 1280; }, p => { p.streams[0].pix_fmt = 'yuv420p10le'; },
    p => { p.streams[0].avg_frame_rate = '25/1'; }, p => { p.streams[0].color_transfer = 'smpte2084'; },
    p => { p.streams[1].channels = 1; }, p => { p.streams[2].tags.language = 'fra'; },
    p => { p.streams[2].disposition.forced = 0; }, p => { p.chapters[0].end_time = '119'; },
  ]) {
    const p = probe('hevc'); change(p); assert.throws(() => validate(probe(), p));
  }
});

test('safe flow routes to CPU and has no failure path for benign skips or unvalidated replacement', () => {
  const flow = flowDefinition({ pluginName: 'notifyRadarrOrSonarr', inputsDB: { arr: 'sonarr' } });
  assert.equal(flow.flowPlugins[1].inputsDB.requiredWorkerType, 'CPU');
  assert(!flow.flowPlugins.some(n => ['replaceOriginalFile', 'failFlow', 'compareFileSizeRatio', 'checkHdr'].includes(n.pluginName)));
  assert(flow.flowEdges.every(e => e.sourceHandle === '1'));
  assert.match(flow.flowPlugins.find(n => n.id === 'commit').inputsDB.code, /\.commit/);
  assert.equal(flow.flowPlugins.find(n => n.id === 'encode').inputsDB.ffmpegPreset, 'slow');
});
test('historical recovery changes only positively identified size-policy errors', () => {
  assert.equal(recoveryStatus('New file size not within limits. ratio 99. upperBound is 95%', 'h264'), 'Not required');
  assert.equal(recoveryStatus('New file size not within limits. ratio 20. lowerBound is 30%', 'h264'), 'Queued');
  assert.equal(recoveryStatus('New file size not within limits. ratio 20. lowerBound is 30%', 'av1'), null);
  assert.equal(recoveryStatus('FFmpeg error: Invalid data found when processing input', 'h264'), null);
});

async function fixture(t, { extension = '.mkv', outputSize = 500 } = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'tdarr-safe-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const source = path.join(root, `source${extension}`), output = path.join(root, 'cache', 'encoded.mkv');
  await fs.mkdir(path.dirname(output));
  await fs.writeFile(source, Buffer.alloc(1000, 1));
  await fs.writeFile(output, Buffer.alloc(outputSize, 2));
  const calls = [], logs = [];
  const args = {
    inputFileObj: { _id: output }, originalLibraryFile: { _id: source }, jobLog: l => logs.push(l),
    variables: { homeserverSafeHevc: { source, fingerprint: fingerprint(await fs.stat(source)), probe: probe() } },
  };
  const run = async (binary, argv) => {
    calls.push({ binary, argv });
    return { stdout: binary.endsWith('ffprobe') ? JSON.stringify(probe('hevc')) : 'out_time_us=120000000\nprogress=end\n' };
  };
  return { root, source, output, args, calls, logs, options: { run } };
}

test('replacement completes only after metadata and full decode, preserving copied streams', async t => {
  const f = await fixture(t);
  const result = await commit(f.args, f.options);
  assert.equal(result.outputNumber, 1);
  assert.equal((await fs.stat(f.source)).size, 500);
  assert(f.calls[1].argv.includes('-xerror'));
  assert(f.calls[1].argv.includes('0:a?'));
  assert.deepEqual((await fs.readdir(f.root)).sort(), ['cache', 'source.mkv']);
});

test('very small anime output is accepted after complete validation rather than an arbitrary 30% floor', async t => {
  const f = await fixture(t, { outputSize: 100 });
  await commit(f.args, f.options);
  assert.equal((await fs.stat(f.source)).size, 100);
});

test('insufficient savings returns original normally and never replaces or notifies', async t => {
  const f = await fixture(t, { outputSize: 960 });
  const result = await commit(f.args, f.options);
  assert.equal(result.outputNumber, 2);
  assert.equal(result.outputFileObj, f.args.originalLibraryFile);
  assert.equal((await fs.stat(f.source)).size, 1000);
  assert.equal(f.calls.length, 1);
});

test('failed or incomplete decode and source changes preserve originals', async t => {
  for (const failure of ['decode', 'incomplete', 'source']) {
    const f = await fixture(t);
    const run = f.options.run;
    f.options.run = async (...argv) => {
      if (argv[0].endsWith('ffmpeg')) {
        if (failure === 'decode') throw new Error('decode failed');
        if (failure === 'incomplete') return { stdout: 'out_time_us=0\n' };
        await fs.appendFile(f.source, 'changed');
      }
      return run(...argv);
    };
    await assert.rejects(commit(f.args, f.options));
    assert.equal((await fs.readFile(f.source))[0], 1);
  }
});

test('existing MKV target is never overwritten and the source is restored', async t => {
  const f = await fixture(t, { extension: '.mp4' });
  const target = path.join(f.root, 'source.mkv');
  await fs.writeFile(target, 'unmanaged');
  await assert.rejects(commit(f.args, f.options), /EEXIST/);
  assert.equal(await fs.readFile(target, 'utf8'), 'unmanaged');
  assert.equal((await fs.stat(f.source)).size, 1000);
});
