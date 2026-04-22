# Pi — OpenClaw v3

Content in this directory is intended to be deployed to the Raspberry Pi 5
that hosts OpenClaw, not to the homeserver. The OpenClaw application code
itself lives in a separate repo; this directory only holds the SQLite
schema, migration runner, MCP client config sample, and the travel-agent
workspace / skill / cron-job definitions.

## Layout

```
pi/
├── apply-migrations.py            # SQLite migration runner (stdlib only)
├── mcp-clients.json.sample        # MCP endpoint registry (copy + fill in bearers)
├── install-mcp-config.sh          # Ship mcp-clients.json from server → pi
├── install-openclaw-skills.sh     # Deploy travel-agent workspace + scripts + jobs
├── sqlite-migrations/
│   ├── 0001_init.sql              # destinations, baselines, price history, knowledge
│   ├── 0002_caches.sql            # ephemeral query/page caches
│   ├── 0003_blackouts.sql         # date-range constraints
│   ├── 0004_blackout_widen.sql    # widen Feb 2027 to Jan 15–Mar 31 2027
│   └── 0005_us_holidays.sql       # us_holidays with pto_efficiency annotation
├── openclaw-workspace/
│   ├── TRAVEL.md                  # travel-agent system preamble
│   └── skills/
│       ├── travel-dispatch/       # Matrix DM intent classifier + dispatcher
│       ├── travel-deep-plan/      # Job 2 — full trip-plan template
│       ├── travel-alter-plan/     # "skip Osaka, find something else" revisions
│       ├── travel-seasonality-synth/  # SearXNG-first seasonality pipeline
│       ├── travel-watch/          # Job 1 — watchlist health monitor
│       ├── travel-fx/             # Job 4 — ECB FX fetch
│       └── travel-holidays/       # Job 5 — US federal holidays refresh
├── openclaw-scripts/
│   ├── travel-fx.py               # Called by travel-fx skill (pure data fetch)
│   └── travel-holidays.py         # Called by travel-holidays skill
└── openclaw-jobs/
    ├── travel-jobs.json           # 5 cron-job definitions (upserted by name)
    └── upsert-jobs.py             # Merge script — idempotent, backs up first
```

## Deployment

### Initial bootstrap (already done)

```sh
# On the Pi, once:
sudo install -d -o openclaw -g openclaw /var/lib/openclaw
sudo -u openclaw python3 apply-migrations.py /var/lib/openclaw/state.db sqlite-migrations/
```

### MCP endpoints — run from the DEV MACHINE

```sh
# The Pi is firewalled off from the server by design, so the dev machine
# acts as a trusted middleman for token delivery. Args: pi-ssh-host (default "pi").
./install-mcp-config.sh pi
```

### Travel agent workspace + cron jobs — run from the DEV MACHINE

```sh
# Preconditions: commits pulled on the Pi's /home/openclaw/HomeServer clone.
# The installer verifies this and refuses if the repo is behind.
./install-openclaw-skills.sh pi

# After install, restart the gateway so the new skills/TRAVEL.md are re-read:
ssh pi 'XDG_RUNTIME_DIR=/run/user/$(id -u openclaw) \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u openclaw)/bus \
  sudo -u openclaw systemctl --user restart openclaw-gateway.service'
```

Re-running `apply-migrations.py` or `install-openclaw-skills.sh` is safe —
they only apply new migrations / upsert skill + job files in place.

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
