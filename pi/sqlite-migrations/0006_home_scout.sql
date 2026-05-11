-- 0006_home_scout.sql — home-scout agent tables.
-- Per-listing enrichment cache, email dedup ledger, and separate table-level
-- scoring state. Reuses the shared notifications_log for Matrix/ntfy dedup.

-- Per-listing state: one row per Zillow ID, upserted each time the listing
-- appears in a digest email. price_changed_at is set when list_price changes
-- so the notifier can re-alert on price drops even for already-seen listings.
CREATE TABLE home_scout_listings (
  zillow_id         TEXT PRIMARY KEY,
  url               TEXT NOT NULL,
  address           TEXT NOT NULL,
  subdivision       TEXT,
  zip               TEXT,
  list_price        INTEGER,
  last_price        INTEGER,
  price_changed_at  TEXT,
  sqft              INTEGER,
  lot_sqft          INTEGER,
  beds              INTEGER,
  baths             REAL,
  year_built        INTEGER,
  hoa_monthly       INTEGER,
  days_on_market    INTEGER,
  listing_status    TEXT,
  score             REAL,
  tier              INTEGER,
  rejected_reason   TEXT,
  first_seen_at     TEXT NOT NULL,
  last_seen_at      TEXT NOT NULL,
  last_email_id     TEXT,
  raw_json          TEXT
);

CREATE INDEX idx_hs_listings_last_seen ON home_scout_listings(last_seen_at);
CREATE INDEX idx_hs_listings_tier      ON home_scout_listings(tier);

-- One row per Gmail message ID already processed, so re-running the fetcher
-- against the same time window doesn't double-count.
CREATE TABLE home_scout_seen_emails (
  gmail_message_id  TEXT PRIMARY KEY,
  received_at       TEXT NOT NULL,
  subject           TEXT,
  listing_count     INTEGER,
  processed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
