const assert = require("node:assert/strict");
const { test } = require("node:test");
const { DatabaseSync } = require("node:sqlite");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { collectStats, readDatabaseStats, readStats } = require("./stats.cjs");

function fixture(t, schema) {
  const db = new DatabaseSync(":memory:");
  db.exec(schema);
  t.after(() => db.close());
  return db;
}

test("Aurral counts available songs once, excludes missing files, and shows retained requests", (t) => {
  const db = fixture(t, `
    CREATE TABLE library_media_files (track_id INTEGER, album_id INTEGER, available INTEGER);
    CREATE TABLE library_albums (id INTEGER, artist_id INTEGER);
    CREATE TABLE aurral_history (kind TEXT, created_at INTEGER);
    CREATE TABLE playlist_download_jobs (status TEXT);
    INSERT INTO library_albums VALUES (1, 8), (2, 8), (3, 9);
    INSERT INTO library_media_files VALUES (10,1,1), (10,1,1), (11,2,1), (12,3,0);
    INSERT INTO playlist_download_jobs VALUES ('pending'), ('downloading'), ('cancel_requested'),
      ('done'), ('failed'), ('cancelled'), ('blocked');
  `);
  const insert = db.prepare("INSERT INTO aurral_history VALUES (?, ?)");
  insert.run("album_requested", Date.now());
  insert.run("album_requested", Date.now() - 31 * 86400000);
  insert.run("artist_added", Date.now());
  assert.deepEqual(collectStats(db, "aurral"), {
    songs: "2", albums: "2", artists: "1", requests: "1",
  });
});

test("Storyteller returns duration in seconds and counts missing duration independently of processing", (t) => {
  const db = fixture(t, `
    CREATE TABLE book (uuid TEXT);
    CREATE TABLE audiobook (book_uuid TEXT, missing INTEGER, duration REAL);
    CREATE TABLE readaloud (book_uuid TEXT, missing INTEGER, status TEXT);
    INSERT INTO book VALUES ('one'), ('two'), ('ebook-only');
    INSERT INTO audiobook VALUES ('one',0,3661.5), ('two',0,60.5), ('missing',1,999999);
    INSERT INTO readaloud VALUES ('one',0,'ALIGNED'), ('two',0,'PROCESSING'), ('missing',1,'ALIGNED');
  `);
  assert.deepEqual(collectStats(db, "storyteller"), {
    audiobooks: "2", readalouds: "1", duration: 3722, untimed: "0",
  });
  db.exec("INSERT INTO audiobook VALUES ('unknown-length',0,NULL)");
  assert.deepEqual(collectStats(db, "storyteller"), {
    audiobooks: "3", readalouds: "1", duration: 3722, untimed: "1",
  });
  db.exec("INSERT INTO audiobook VALUES ('invalid-length',0,-100)");
  assert.throws(() => collectStats(db, "storyteller"), /Invalid audiobook duration/);
  db.exec("DELETE FROM audiobook WHERE duration < 0; INSERT INTO audiobook VALUES ('invalid-length',0,'corrupt')");
  assert.throws(() => collectStats(db, "storyteller"), /Invalid audiobook duration/);
});

test("BookBridge reports instance-wide sync/processing status, not reading progress or owners", (t) => {
  const db = fixture(t, `
    CREATE TABLE books (status TEXT, user_id INTEGER, abs_title TEXT);
    INSERT INTO books VALUES ('active',1,'private title'), ('pending',2,'private title'),
      ('processing',2,'private title'), ('failed_retry_later',1,'private title'),
      ('failed_permanent',1,'private title'), ('private unknown status',1,'private title'),
      (NULL,NULL,'private title');
  `);
  const result = collectStats(db, "bookbridge");
  assert.deepEqual(result, {
    active: "1", pending: "1", processing: "1", issues: "4",
  });
  assert.ok(!JSON.stringify(result).includes("private"));
});

test("Vaultwarden distinguishes active logins from all items and excludes trash from category counts", (t) => {
  const db = fixture(t, `
    CREATE TABLE ciphers (atype INTEGER, deleted_at TEXT, name TEXT, data TEXT);
    INSERT INTO ciphers VALUES (1,NULL,'encrypted private name','encrypted private data'),
      (1,NULL,'secret','secret'), (1,'2026-01-01','secret','secret'),
      (2,NULL,'secret','secret'), (3,NULL,'secret','secret'), (4,NULL,'secret','secret');
  `);
  assert.deepEqual(collectStats(db, "vaultwarden"), {
    logins: "2", items: "5", trash: "1",
  });
});

test("ntfy counts only unexpired cache topics/messages and separates unpublished scheduled messages", (t) => {
  const db = fixture(t, `
    CREATE TABLE messages (topic TEXT, expires INTEGER, published INTEGER);
    INSERT INTO messages VALUES ('private-a',unixepoch()+3600,1), ('private-a',unixepoch()+3600,1),
      ('private-b',unixepoch()+3600,1), ('expired',unixepoch()-1,1),
      ('scheduled',unixepoch()+3600,0), ('expired-schedule',unixepoch()-1,0);
  `);
  assert.deepEqual(collectStats(db, "ntfy"), {
    topics: "2", messages: "3", scheduled: "1",
  });
});

test("empty valid databases give real zeros, but missing schemas and sources fail explicitly", (t) => {
  const db = fixture(t, "CREATE TABLE ciphers (atype INTEGER, deleted_at TEXT)");
  assert.equal(collectStats(db, "vaultwarden").logins, "0");
  assert.throws(() => collectStats(db, "ntfy"));
  assert.throws(() => collectStats(db, "unknown"), /Unsupported/);
  assert.throws(() => readStats("../../etc/shadow"), /Unsupported/);
  assert.throws(() => readStats("toString"), /Unsupported/);
});

test("Storyteller preserves numeric seconds for Homepage's native duration formatter", (t) => {
  const db = fixture(t, `
    CREATE TABLE audiobook (book_uuid TEXT, missing INTEGER, duration REAL);
    CREATE TABLE readaloud (book_uuid TEXT, missing INTEGER, status TEXT);
  `);
  const insert = db.prepare("INSERT INTO audiobook VALUES ('audio',0,?)");
  for (const seconds of [0, 59.9, 60, 3661.5, 84 * 3600 + 12 * 60, 3600 * 1234 + 60 * 59 + 59.9]) {
    db.exec("DELETE FROM audiobook");
    insert.run(seconds);
    assert.equal(collectStats(db, "storyteller").duration, seconds);
  }
  db.exec("DELETE FROM audiobook");
  insert.run(Infinity);
  assert.throws(() => collectStats(db, "storyteller"), /Invalid audiobook duration/);
});

test("read-only collection sees live uncheckpointed WAL updates and never creates a missing database", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "homepage-stats-"));
  const filename = path.join(directory, "vault.db");
  const writer = new DatabaseSync(filename);
  t.after(async () => {
    writer.close();
    await fs.rm(directory, { recursive: true });
  });
  writer.exec(`
    PRAGMA journal_mode=WAL;
    PRAGMA wal_autocheckpoint=0;
    CREATE TABLE ciphers (atype INTEGER, deleted_at TEXT);
    INSERT INTO ciphers VALUES (1,NULL);
  `);
  assert.ok((await fs.stat(filename + "-wal")).size > 0);
  assert.equal(readDatabaseStats(filename, "vaultwarden").logins, "1");
  writer.exec("INSERT INTO ciphers VALUES (1,NULL)");
  assert.equal(readDatabaseStats(filename, "vaultwarden").logins, "2");
  const missing = path.join(directory, "missing.db");
  assert.throws(() => readDatabaseStats(missing, "vaultwarden"));
  await assert.rejects(fs.access(missing), { code: "ENOENT" });
});
