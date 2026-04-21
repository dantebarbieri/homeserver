# Pi — OpenClaw v3

Content in this directory is intended to be deployed to the Raspberry Pi 5
that hosts OpenClaw, not to the homeserver. The OpenClaw application code
itself lives in a separate repo; this directory only holds the SQLite
schema, migration runner, and MCP client config sample.

## Layout

```
pi/
├── apply-migrations.py        # SQLite migration runner (stdlib only)
├── mcp-clients.json.sample    # MCP endpoint registry (copy + fill in bearers)
└── sqlite-migrations/
    ├── 0001_init.sql          # destinations, baselines, price history, knowledge
    ├── 0002_caches.sql        # ephemeral query/page caches
    └── 0003_blackouts.sql     # date-range constraints (Feb 2027, etc.)
```

## Deployment

On the Pi:

```sh
# 1. Pull this repo (or just rsync the pi/ directory)
sudo install -d -o openclaw -g openclaw /var/lib/openclaw

# 2. Apply migrations
python3 apply-migrations.py /var/lib/openclaw/state.db sqlite-migrations/

# 3. Configure MCP endpoints — run from the DEV MACHINE (which has ssh
#    access to both server and pi). The Pi is firewalled off from the
#    server by design, so the dev machine acts as a trusted middleman.
#    Args: pi-ssh-host (defaults to "pi").
./install-mcp-config.sh pi

# Then restart OpenClaw on the Pi so it picks up the new config.
```

Re-running `apply-migrations.py` is safe — it only applies new files and
refuses out-of-order migrations.

## Schema rationale

- **Two-tier caching.** Knowledge tables (`destinations`, `seasons`,
  `destination_knowledge`) carry a `refreshed_at` + `ttl_days`; ephemeral
  caches (`searxng_query_cache`, `fetched_pages`) carry a hard
  `expires_at` and live in `0002_caches.sql` so they can be wiped freely.
- **Wide history, narrow current.** `price_history` is append-only;
  "latest price" and "7-day median" are computed via SQL using the
  composite indexes `idx_price_latest` and `idx_price_window`.
- **Source provenance.** Generated content stores `model_used`,
  `searxng_query`, and `source_urls_json` so the agent can re-explain or
  invalidate when sources change.
- **Hard constraints survive prompt regression.** The Feb 2027 blackout
  lives in the `blackouts` table with a `CHECK` constraint, queried by
  the planner code — not by prompt instruction.

## Hot query patterns (verified against the indexes)

| Task | SQL | Index |
|---|---|---|
| Stale season caches | `WHERE julianday('now') - julianday(refreshed_at) > ttl_days` | `idx_seasons_stale` |
| Stale knowledge per topic | `WHERE topic=? AND julianday('now') - julianday(refreshed_at) > ttl_days` | `idx_knowledge_stale` |
| Latest price for (dest, horizon) | `ORDER BY checked_at DESC LIMIT 1` | `idx_price_latest` (DESC) |
| 7-day median price | window CTE over `WHERE checked_at > datetime('now','-7 days')` | `idx_price_window` |
| Active destinations by priority | `WHERE active=1 ORDER BY priority` | partial `idx_destinations_active_priority` |
| Date-range blacked out? | `WHERE NOT (end_date < ? OR start_date > ?)` | full table scan; tiny |
| Recent dedup | `WHERE dedupe_key=? AND sent_at > datetime('now','-7 days')` | `UNIQUE(dedupe_key)` |
