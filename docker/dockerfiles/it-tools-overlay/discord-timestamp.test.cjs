'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, 'discord-timestamp.html'), 'utf8');
const script = /<script>([\s\S]*?)<\/script>/.exec(html)[1];
const page = vm.createContext({ Intl, Date, Number, Math, String });
vm.runInContext(script, page);

const iso = (sec) => new Date(sec * 1000).toISOString().replace('.000Z', 'Z');
const wall = (year, month, day, hour, minute, second = 0) => ({ year, month, day, hour, minute, second });
const toEpoch = (w, zone) => page.wallToEpochSec(w, zone);

test('converts wall time to UTC across offsets', () => {
  assert.equal(iso(toEpoch(wall(2026, 11, 24, 20, 0), 'America/New_York')), '2026-11-25T01:00:00Z');
  assert.equal(iso(toEpoch(wall(2026, 7, 4, 12, 0), 'America/New_York')), '2026-07-04T16:00:00Z');
  assert.equal(iso(toEpoch(wall(2026, 1, 1, 0, 0), 'Asia/Kolkata')), '2025-12-31T18:30:00Z');
  assert.equal(iso(toEpoch(wall(2026, 1, 1, 12, 0), 'Pacific/Kiritimati')), '2025-12-31T22:00:00Z');
  assert.equal(iso(toEpoch(wall(2026, 3, 1, 9, 30, 15), 'UTC')), '2026-03-01T09:30:15Z');
});

test('handles half-hour daylight saving', () => {
  assert.equal(iso(toEpoch(wall(2026, 1, 1, 12, 0), 'Australia/Lord_Howe')), '2026-01-01T01:00:00Z');
  assert.equal(iso(toEpoch(wall(2026, 7, 1, 12, 0), 'Australia/Lord_Howe')), '2026-07-01T01:30:00Z');
});

test('moves a nonexistent time forward and picks the first of a repeated time', () => {
  const gap = toEpoch(wall(2024, 3, 10, 2, 30), 'America/New_York');
  assert.equal(iso(gap), '2024-03-10T07:30:00Z');
  assert.equal(page.wallToInputValue(page.epochToWall(gap, 'America/New_York')), '2024-03-10T03:30:00');

  assert.equal(iso(toEpoch(wall(2024, 11, 3, 1, 30), 'America/New_York')), '2024-11-03T05:30:00Z');
});

test('round-trips wall time in every supported zone', () => {
  const zones = page.zoneList();
  assert.ok(zones.length > 300);
  const samples = [wall(2026, 1, 15, 12, 0), wall(2026, 7, 15, 12, 0), wall(2030, 6, 1, 23, 59, 59), wall(1999, 12, 31, 0, 0)];
  for (const zone of zones) {
    for (const w of samples) {
      const back = page.epochToWall(toEpoch(w, zone), zone);
      assert.equal(page.wallToInputValue(back), page.wallToInputValue(w), `${zone} ${page.wallToInputValue(w)}`);
    }
  }
});

test('accepts seconds, milliseconds and pasted Discord codes', () => {
  assert.deepEqual({ ...page.parseTimestampInput('1700000000') }, { seconds: 1700000000, unit: 'seconds' });
  assert.deepEqual({ ...page.parseTimestampInput(' <t:1700000000:R> ') }, { seconds: 1700000000, unit: 'seconds' });
  assert.deepEqual({ ...page.parseTimestampInput('t:1700000000') }, { seconds: 1700000000, unit: 'seconds' });
  assert.deepEqual({ ...page.parseTimestampInput('1700000000123') }, { seconds: 1700000000, unit: 'milliseconds' });
  for (const bad of ['', 'abc', '1.5', '<t:1700000000:x>', '99999999999999999', '<t:>']) {
    assert.equal(page.parseTimestampInput(bad), null, bad);
  }
});

test('builds codes and previews for every format', () => {
  assert.deepEqual(Array.from(page.FORMATS, (f) => page.discordCode(1700000000, f.flag)),
    ['t', 'T', 'd', 'D', 'f', 'F', 'R'].map((f) => `<t:1700000000:${f}>`));
  const opts = { locale: 'en-US', timeZone: 'UTC' };
  const preview = (flag) => page.formatPreview(flag, 1700000000, 1700000000 + 3 * 3600, opts);
  assert.equal(preview('d'), '11/14/2023');
  assert.equal(preview('D'), 'November 14, 2023');
  assert.equal(preview('F'), 'Tuesday, November 14, 2023 10:13 PM');
  assert.equal(preview('R'), '3 hours ago');
  assert.equal(page.relativeTime(90, 'en-US'), 'in 1 minute');
  assert.equal(page.relativeTime(0, 'en-US'), 'now');
});

test('keeps the page free of external requests', () => {
  assert.doesNotMatch(html, /(?:src|href)=["']https?:/i);
  assert.doesNotMatch(html, /@import|url\(\s*["']?https?:/i);
});
