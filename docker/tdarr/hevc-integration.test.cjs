'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { commit, fingerprint } = require('./hevc-safe-v1.cjs');
const { internals: { runProcess } } = require('./dv5-sidecar.cjs');

test('real FFmpeg encode, stream contract, full decode and transactional replacement', {
  skip: process.env.TDARR_INTEGRATION_TESTS !== '1',
}, async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'tdarr-integration-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const source = path.join(root, 'source.mkv'), output = path.join(root, 'encoded.mkv');
  const subtitles = path.join(root, 'subtitles.srt');
  const ffmpeg = '/usr/lib/jellyfin-ffmpeg/ffmpeg';
  const ffprobe = '/usr/lib/jellyfin-ffmpeg/ffprobe';
  await fs.writeFile(subtitles, '1\n00:00:00,500 --> 00:00:02,500\nTest subtitle\n');
  await runProcess(ffmpeg, ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=24:duration=4',
    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-i', subtitles,
    '-map', '0:v', '-map', '1:a', '-map', '2:s', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '16',
    '-c:a', 'aac', '-c:s', 'srt', '-metadata:s:a:0', 'language=eng', '-metadata:s:s:0', 'language=eng', source]);
  const probe = JSON.parse((await runProcess(ffprobe, ['-v', 'error', '-show_streams', '-show_format',
    '-show_chapters', '-of', 'json', source])).stdout);
  const saved = fingerprint(await fs.stat(source));
  await runProcess(ffmpeg, ['-v', 'error', '-i', source, '-map', '0', '-c', 'copy', '-c:v:0', 'libx265',
    '-crf', '20', '-preset', 'slow', '-x265-params', 'pools=1:frame-threads=1', output], { timeout: 300000 });
  const logs = [];
  const result = await commit({
    inputFileObj: { _id: output }, originalLibraryFile: { _id: source }, jobLog: l => logs.push(l),
    variables: { homeserverSafeHevc: { source, fingerprint: saved, probe } },
  });
  assert.equal(result.outputNumber, 1, logs.join('\n'));
  const actual = JSON.parse((await runProcess(ffprobe,
    ['-v', 'error', '-show_streams', '-of', 'json', source])).stdout);
  assert.deepEqual(actual.streams.map(s => s.codec_name), ['hevc', 'aac', 'subrip']);
  assert(logs.some(l => l.includes('decoding every')));
});
