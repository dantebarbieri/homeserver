-- 0001_init.sql — base tables for the OpenClaw v3 travel agent.
-- Durable knowledge tables (destinations, baselines, history, seasons,
-- per-topic knowledge, watch registry, FX, wikivoyage excerpts, notifications).
-- Cache tables (queries, pages) live in 0002_caches.sql.

PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE _migrations (
  id          INTEGER PRIMARY KEY,
  filename    TEXT    NOT NULL UNIQUE,
  applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ---------- Destinations watchlist ----------
CREATE TABLE destinations (
  id               INTEGER PRIMARY KEY,
  slug             TEXT NOT NULL UNIQUE,
  display_name     TEXT NOT NULL,
  country_code     TEXT NOT NULL,
  region           TEXT,
  lat              REAL,
  lon              REAL,
  preferred_months TEXT,
  avoid_months     TEXT,
  priority         INTEGER NOT NULL DEFAULT 5,
  active           INTEGER NOT NULL DEFAULT 1,
  notes            TEXT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_destinations_active_priority
  ON destinations(active, priority)
  WHERE active = 1;

-- ---------- Trip baselines (the diff target for deal detection) ----------
CREATE TABLE trip_baselines (
  id                   INTEGER PRIMARY KEY,
  destination_id       INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
  horizon_months       INTEGER NOT NULL CHECK (horizon_months IN (6, 12)),
  baseline_total_usd   REAL NOT NULL,
  baseline_flight_usd  REAL,
  baseline_lodging_usd REAL,
  baseline_other_usd   REAL,
  trip_plan_md         TEXT NOT NULL,
  source_urls_json     TEXT NOT NULL,
  searxng_query        TEXT,
  model_used           TEXT NOT NULL,
  generated_at         TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at           TEXT NOT NULL,
  UNIQUE(destination_id, horizon_months, generated_at)
);
CREATE INDEX idx_baselines_active
  ON trip_baselines(destination_id, horizon_months, generated_at DESC);

-- ---------- Price history (append-only) ----------
CREATE TABLE price_history (
  id              INTEGER PRIMARY KEY,
  destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
  horizon_months  INTEGER NOT NULL CHECK (horizon_months IN (6, 12)),
  checked_at      TEXT NOT NULL DEFAULT (datetime('now')),
  total_usd       REAL NOT NULL,
  flight_usd      REAL,
  lodging_usd     REAL,
  other_usd       REAL,
  source_provider TEXT,
  source_url      TEXT,
  raw_json        TEXT,
  fx_rate_eur_usd REAL,
  notes           TEXT
);
CREATE INDEX idx_price_latest
  ON price_history(destination_id, horizon_months, checked_at DESC);
CREATE INDEX idx_price_window
  ON price_history(destination_id, horizon_months, checked_at);

-- ---------- Seasons (per destination) ----------
CREATE TABLE seasons (
  id                  INTEGER PRIMARY KEY,
  destination_id      INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
  high_season_months  TEXT NOT NULL,
  shoulder_months     TEXT NOT NULL,
  low_season_months   TEXT NOT NULL,
  rainy_months        TEXT,
  events_md           TEXT,
  confidence          REAL NOT NULL DEFAULT 0.5,
  source_urls_json    TEXT NOT NULL,
  searxng_query       TEXT,
  model_used          TEXT NOT NULL,
  refreshed_at        TEXT NOT NULL DEFAULT (datetime('now')),
  ttl_days            INTEGER NOT NULL DEFAULT 180,
  UNIQUE(destination_id)
);
CREATE INDEX idx_seasons_stale ON seasons(refreshed_at);

-- ---------- Destination knowledge (per-topic, per-TTL) ----------
CREATE TABLE destination_knowledge (
  id              INTEGER PRIMARY KEY,
  destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
  topic           TEXT NOT NULL CHECK (topic IN
    ('visa','safety','food','transit','events','neighborhoods',
     'tipping','power','health','customs')),
  content_md      TEXT NOT NULL,
  source_urls_json TEXT NOT NULL,
  model_used      TEXT NOT NULL,
  refreshed_at    TEXT NOT NULL DEFAULT (datetime('now')),
  ttl_days        INTEGER NOT NULL,
  UNIQUE(destination_id, topic)
);
CREATE INDEX idx_knowledge_stale ON destination_knowledge(topic, refreshed_at);

-- ---------- Changedetection.io watch registry mirror ----------
CREATE TABLE cd_watches (
  id              INTEGER PRIMARY KEY,
  cd_uuid         TEXT NOT NULL UNIQUE,
  destination_id  INTEGER REFERENCES destinations(id) ON DELETE SET NULL,
  url             TEXT NOT NULL,
  title           TEXT,
  purpose         TEXT,
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  last_changed_at TEXT
);

-- ---------- ECB FX daily snapshots ----------
CREATE TABLE fx_rates (
  id        INTEGER PRIMARY KEY,
  date      TEXT NOT NULL,
  base      TEXT NOT NULL DEFAULT 'EUR',
  currency  TEXT NOT NULL,
  rate      REAL NOT NULL,
  UNIQUE(date, base, currency)
);
CREATE INDEX idx_fx_lookup ON fx_rates(date, currency);

-- ---------- Wikivoyage excerpts (pre-extracted from Kiwix for hot dests) ----------
CREATE TABLE wikivoyage_excerpts (
  id              INTEGER PRIMARY KEY,
  destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
  section         TEXT NOT NULL,
  content_md      TEXT NOT NULL,
  zim_revision    TEXT,
  fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(destination_id, section)
);

-- ---------- Notifications log (dedupe deal announcements within 7 days) ----------
CREATE TABLE notifications_log (
  id          INTEGER PRIMARY KEY,
  dedupe_key  TEXT NOT NULL UNIQUE,
  channel     TEXT NOT NULL,
  payload_md  TEXT NOT NULL,
  sent_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_notifications_recent ON notifications_log(sent_at);
