---
name: travel-seasonality-synth
description: >
  Produce or refresh a seasonality row for a destination: which months are
  high/shoulder/low/rainy, plus confidence and citations. Invoked by
  travel-deep-plan step 2 on cache miss, by the annual travel-seasonality
  cron job, and by the mid-year volatile-zone refresh. Output lands in the
  seasons table keyed to destination_id.
metadata:
  openclaw:
    emoji: "📅"
    requires:
      bins:
        - python3
---

# Travel seasonality synthesis

Step 0 — load `workspace/TRAVEL.md`. The tool-priority order there is
authoritative for which sources to query.

**Inputs** — `{destination_id, display_name, country_code,
volatile_zone?: str|null}`.

## Routing shape

Bounded synthesis, compact JSON in + compact JSON out. Keep the prompt
small enough to stay on **`qwen-local`** (`local-thinking` if the heuristic
promotes it because of the triangulation step — that's fine).

## Step 1 — three parallel SearXNG queries for triangulation

Use `searxng` MCP with `engines=wikivoyage,wikipedia,reddit,google,brave`.
Run all three queries in parallel:

- `best time to visit {display_name}`
- `{display_name} weather by month climate`
- `{display_name} when to avoid tourists crowds`

Cache-key the queries in `searxng_query_cache` with a 30-day TTL so the
annual refresh doesn't re-hit SearXNG for destinations already in cache
(unless the cache row is older than 30 days).

## Step 2 — pick top 5 URLs

Boost hostnames in this order: `wikivoyage.org`, `wikipedia.org`,
`reddit.com/r/travel`, `lonelyplanet.com`, `fodors.com`. If fewer than 5
high-signal hits, drop to `nationalgeographic.com`, `cntraveler.com`, and
broad Google results.

## Step 3 — fetch URL contents

For each URL, use the `searxng` MCP URL-read tool (if available) or
`urllib.request` via Python. Cache bodies in `fetched_pages` (24 h TTL) so
re-runs within a day are free.

## Step 4 — Wikivoyage climate-section extraction (offline fallback)

If the destination has a Wikivoyage article accessible via `openzim` (local
ZIM):

```
# openzim MCP call pseudocode
climate_md = openzim.get_article(
  "wikivoyage",
  title=display_name,
  section="Climate"
)
```

Upsert into `wikivoyage_excerpts` with `section='climate'`. This is the
offline fallback the router uses when SearXNG is down.

## Step 5 — synthesize

Small prompt shape — Qwen will handle it cleanly:

```
From the five sources below, output a JSON object describing seasonality
for {display_name}.

Sources:
[1] {wikivoyage_url} — {excerpt}
[2] {wikipedia_url}  — {excerpt}
[3] {reddit_url}     — {excerpt}
[4] {lonelyplanet_url} — {excerpt}
[5] {fodors_url}     — {excerpt}

Output EXACTLY this schema — no prose:
{
  "high_season_months": [1..12],
  "shoulder_months":    [1..12],
  "low_season_months":  [1..12],
  "rainy_months":       [1..12],
  "events_md":          "optional short markdown of major seasonal events",
  "confidence":         0.0..1.0,
  "notes":              "optional 1-sentence caveat"
}

Rules:
- Month lists must be disjoint (a month in high cannot also be in low).
- Union of high + shoulder + low must equal all 12 months.
- Set confidence = 0.9 if ≥3 sources agree; 0.6 if 2 agree; 0.4 if 1; 0.2 if none.
- rainy_months may overlap with any other list.
```

## Step 6 — persist

```python
import json, sqlite3
conn = sqlite3.connect('/var/lib/openclaw/state.db')
ttl = 180 if volatile_zone else 365
conn.execute("""
  INSERT INTO seasons (destination_id, high_season_months, shoulder_months,
    low_season_months, rainy_months, events_md, confidence,
    source_urls_json, searxng_query, model_used, refreshed_at, ttl_days)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
  ON CONFLICT(destination_id) DO UPDATE SET
    high_season_months = excluded.high_season_months,
    shoulder_months    = excluded.shoulder_months,
    low_season_months  = excluded.low_season_months,
    rainy_months       = excluded.rainy_months,
    events_md          = excluded.events_md,
    confidence         = excluded.confidence,
    source_urls_json   = excluded.source_urls_json,
    searxng_query      = excluded.searxng_query,
    model_used         = excluded.model_used,
    refreshed_at       = datetime('now'),
    ttl_days           = excluded.ttl_days
""", (destination_id,
      json.dumps(high), json.dumps(shoulder), json.dumps(low),
      json.dumps(rainy), events_md, confidence,
      json.dumps(urls), searxng_query_used, model_used_reported, ttl))
conn.commit()
```

TTL rationale:

- Default 365 days.
- `volatile_zone IN ('mediterranean','south_asia','sea_monsoon','caribbean')`
  → 180 days, so the Jul 2 mid-year refresh hits them.

## Step 7 — return

Return the full `seasons` row to the caller (deep-plan step 2 or the cron
job). Do not post to Matrix — that's the caller's responsibility if needed.

## Confidence floor

If `confidence < 0.4`, append the destination to an "attention needed" list
the caller can surface. Do not write the row — return the list so the cron
job can batch-announce low-confidence rows to Matrix at end-of-run.
