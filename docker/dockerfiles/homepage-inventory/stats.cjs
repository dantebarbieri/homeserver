const { DatabaseSync } = require("node:sqlite");

const databaseFiles = Object.freeze({
  aurral: "/stats/aurral/aurral.db",
  storyteller: "/stats/storyteller/storyteller.db",
  bookbridge: "/stats/bookbridge/database.db",
  vaultwarden: "/stats/vaultwarden/db.sqlite3",
  ntfy: "/stats/ntfy/cache.db",
  convertx: "/stats/convertx/mydb.sqlite",
});

function count(value) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error("Invalid aggregate count");
  return value.toLocaleString("en-US");
}

function duration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) throw new Error("Invalid aggregate duration");
  const minutes = Math.floor(seconds / 60);
  return `${Math.floor(minutes / 60).toLocaleString("en-US")}h ${minutes % 60}m`;
}

function collectStats(db, name) {
  const item = (label, value) => [label, count(value)];
  let result;
  switch (name) {
    case "convertx": {
      const files = db.prepare(`
        SELECT COUNT(CASE WHEN status = 'Done' THEN 1 END) AS completed,
          COUNT(CASE WHEN status != 'Done' THEN 1 END) AS other FROM file_names
      `).get();
      const jobs = db.prepare("SELECT COUNT(*) AS count FROM jobs").get();
      result = [item("completed", files.completed), item("other", files.other), item("jobs", jobs.count)];
      break;
    }
    case "aurral": {
      const library = db.prepare(`
        SELECT COUNT(DISTINCT track_id) AS songs, COUNT(DISTINCT album_id) AS albums
        FROM library_media_files WHERE available = 1
      `).get();
      const artists = db.prepare(`
        SELECT COUNT(DISTINCT a.artist_id) AS count FROM library_albums a
        WHERE EXISTS (SELECT 1 FROM library_media_files f WHERE f.album_id = a.id AND f.available = 1)
      `).get();
      const requests = db.prepare(`
        SELECT COUNT(*) AS count FROM aurral_history
        WHERE kind = 'album_requested' AND created_at >= ?
      `).get(Date.now() - 30 * 86400000);
      result = [
        item("songs", library.songs), item("albums", library.albums),
        item("artists", artists.count), item("requests", requests.count),
      ];
      break;
    }
    case "storyteller": {
      const audio = db.prepare(`
        SELECT COUNT(DISTINCT book_uuid) AS books, COUNT(*) AS assets, COUNT(duration) AS timed,
          COALESCE(SUM(duration), 0) AS seconds,
          COUNT(CASE WHEN duration IS NOT NULL AND
            (typeof(duration) NOT IN ('real', 'integer') OR duration < 0) THEN 1 END) AS invalid
        FROM audiobook WHERE missing = 0
      `).get();
      if (audio.invalid) throw new Error("Invalid audiobook duration");
      const readaloud = db.prepare(`
        SELECT COUNT(DISTINCT book_uuid) AS count FROM readaloud WHERE missing = 0 AND status = 'ALIGNED'
      `).get();
      result = [
        item("audiobooks", audio.books), item("readalouds", readaloud.count),
        ["duration", duration(audio.seconds)],
        item("untimed", audio.assets - audio.timed),
      ];
      break;
    }
    case "bookbridge": {
      const books = db.prepare(`
        SELECT COUNT(CASE WHEN status = 'active' THEN 1 END) AS active,
          COUNT(CASE WHEN status = 'pending' THEN 1 END) AS pending,
          COUNT(CASE WHEN status = 'processing' THEN 1 END) AS processing,
          COUNT(CASE WHEN status IN ('failed_retry_later', 'failed_permanent') THEN 1 END) AS failed,
          COUNT(CASE WHEN status IS NULL OR status NOT IN
            ('active', 'pending', 'processing', 'failed_retry_later', 'failed_permanent') THEN 1 END) AS other
        FROM books
      `).get();
      result = [
        item("active", books.active), item("pending", books.pending),
        item("processing", books.processing), item("issues", books.failed + books.other),
      ];
      break;
    }
    case "vaultwarden": {
      const vault = db.prepare(`
        SELECT COUNT(CASE WHEN deleted_at IS NULL THEN 1 END) AS items,
          COUNT(CASE WHEN deleted_at IS NULL AND atype = 1 THEN 1 END) AS logins,
          COUNT(CASE WHEN deleted_at IS NOT NULL THEN 1 END) AS trash FROM ciphers
      `).get();
      result = [
        item("logins", vault.logins), item("items", vault.items), item("trash", vault.trash),
      ];
      break;
    }
    case "ntfy": {
      const cache = db.prepare(`
        SELECT COUNT(DISTINCT CASE WHEN published = 1 THEN topic END) AS topics,
          COUNT(CASE WHEN published = 1 THEN 1 END) AS messages,
          COUNT(CASE WHEN published = 0 THEN 1 END) AS scheduled
        FROM messages WHERE expires > unixepoch()
      `).get();
      result = [
        item("topics", cache.topics), item("messages", cache.messages), item("scheduled", cache.scheduled),
      ];
      break;
    }
    default:
      throw new Error("Unsupported statistics source");
  }
  return Object.fromEntries(result);
}

function readDatabaseStats(filename, name) {
  const db = new DatabaseSync(filename, { readOnly: true, timeout: 1000 });
  try {
    db.exec("PRAGMA query_only = ON; PRAGMA trusted_schema = OFF; BEGIN");
    return collectStats(db, name);
  } finally {
    db.close();
  }
}

function readStats(name) {
  if (!Object.hasOwn(databaseFiles, name)) throw new Error("Unsupported statistics source");
  return readDatabaseStats(databaseFiles[name], name);
}

module.exports = { collectStats, databaseFiles, duration, readDatabaseStats, readStats };
