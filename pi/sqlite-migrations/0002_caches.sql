-- 0002_caches.sql — short-lived caches kept separate from the durable
-- knowledge tables so they can be truncated freely without affecting
-- agent state.

CREATE TABLE searxng_query_cache (
  id           INTEGER PRIMARY KEY,
  query_hash   TEXT NOT NULL UNIQUE,
  query_text   TEXT NOT NULL,
  results_json TEXT NOT NULL,
  cached_at    TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at   TEXT NOT NULL
);
CREATE INDEX idx_searx_cache_expiry ON searxng_query_cache(expires_at);

CREATE TABLE fetched_pages (
  id             INTEGER PRIMARY KEY,
  url_hash       TEXT NOT NULL UNIQUE,
  url            TEXT NOT NULL,
  status_code    INTEGER NOT NULL,
  content_type   TEXT,
  content        TEXT,
  raw_size_bytes INTEGER,
  fetched_at     TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at     TEXT NOT NULL
);
CREATE INDEX idx_fetched_expiry ON fetched_pages(expires_at);
