---
name: travel-watch
description: >
  Scheduled watchlist health monitor. Iterates active destinations, runs a
  news sweep via SearXNG, announces safety-relevant news to Matrix, and
  enqueues deep-plan refreshes for destinations whose seasons or
  trip_baselines have gone stale. Invoked by the travel-watch cron job.
metadata:
  openclaw:
    emoji: "🛰️"
    requires:
      bins:
        - python3
---

# Travel watch

Step 0 — load `workspace/TRAVEL.md`.

**Scope under v1:** this skill does NOT check live flight/hotel prices. Those
MCP servers aren't wired yet. Its role is **staleness monitoring + safety
news sweep**. When Amadeus + LiteAPI MCPs ship, Phase 2 of this skill will
add `price_history` writes and the ≥ 15 % drop logic.

## Routing shape

Per-destination gating is JSON in/out on `qwen-local`. News synthesis is
bounded enough to stay on `qwen-local` as well. The **only** path that
escalates to Sonnet is the enqueued `travel-deep-plan` invocations — which
happen in separate agent turns, not within this skill.

## Budget

- ≤ 20 SearXNG calls per run.
- ≤ 45 s per destination.
- ≤ 5 min total thinking — if the cap approaches, write partial progress to
  the cron-run JSONL and stop gracefully.

## Step 1 — load the watchlist

```python
import sqlite3, json, datetime
conn = sqlite3.connect('/var/lib/openclaw/state.db')
dests = conn.execute("""
  SELECT d.id, d.slug, d.display_name, d.country_code, d.priority,
         d.avoid_months, d.preferred_months,
         MAX(s.refreshed_at) AS seasons_refreshed,
         MAX(tb.generated_at) AS latest_baseline_at
  FROM destinations d
  LEFT JOIN seasons s ON s.destination_id = d.id
  LEFT JOIN trip_baselines tb ON tb.destination_id = d.id
  WHERE d.active = 1
  GROUP BY d.id
  ORDER BY d.priority, d.display_name
""").fetchall()
```

## Step 2 — fast-gate per destination

For each destination, emit a JSON decision. Compact prompt, no prose:

```
For destination "{display_name}" (country={country_code},
priority={priority}, avoid_months={avoid_months},
seasons_refreshed={seasons_refreshed}, latest_baseline_at={latest_baseline_at},
now={iso_now}):

Decide the action. Output only:
{"action": "skip|check", "reason": "<short phrase>"}

Skip if:
- destination was checked in this job run within the last 24h (see
  notifications_log)
- current month AND both 6mo and 12mo horizons (ISO month of now+180d,
  now+365d) are all in avoid_months
- both horizons land in any blackout range
- priority > 3 AND latest_baseline_at is within 7d

Otherwise: check.
```

## Step 3 — for each `check` destination

### 3a. News sweep

```python
query = f"{display_name} travel news {now.strftime('%B %Y')}"
# searxng MCP call: categories=news, time_range=week
results = searxng.search(query, categories='news', time_range='week', limit=5)
```

Scan top 3 titles + snippets for keywords: `strike`, `volcanic`, `eruption`,
`earthquake`, `unrest`, `protest`, `terror`, `airport closed`, `outbreak`,
`hurricane`, `typhoon`, `flood`, `coup`, `advisory`.

If any keyword hits:

1. Build a `dedupe_key`:
   `f"watch-news:{slug}:{keyword_hit}:{iso_week}"` — lets the same keyword
   re-announce in a new week but not within the same week.
2. Check `notifications_log` for that key. If absent, announce to Matrix
   with inline `[n]` citations (the top 3 URLs). If present within 72h,
   suppress and record an entry with suppressed reason.
3. Upsert the synthesized summary into `destination_knowledge` topic=`safety`
   with `ttl_days=7`.
4. Log to the cron-run JSONL with `"news_alert": {keyword, url_count,
   announced: bool}`.

### 3b. Staleness check

```python
seasons_stale = (seasons_refreshed is None or
  (now - parse(seasons_refreshed)).days >
    (180 if is_volatile(country_code) else 365))
baseline_stale = (latest_baseline_at is None or
  (now - parse(latest_baseline_at)).days > 60)
```

If `seasons_stale`: enqueue an agent turn invoking `travel-seasonality-synth`
for this destination. Log it; do not block.

If `baseline_stale`: enqueue two agent turns invoking `travel-deep-plan`
(one per horizon: 6, 12). Log each enqueue with `"enqueued_deep_plan":
horizon_months`. The deep-plan skill posts its own completion to Matrix;
this skill does NOT wait.

### 3c. Touch `last_checked`

Record this destination in `notifications_log` with a `dedupe_key =
f"watch-touched:{slug}:{iso_date}"` and empty payload so step 2 can skip
it on the next job run within 24h. Alternatively add a `last_checked_at`
column to `destinations` in a future migration — for now, log-based works.

## Step 4 — write run summary

Append to `~/.openclaw/cron/runs/<jobId>.jsonl` via the OpenClaw cron-runner
(automatic). Include a one-line summary:

```json
{
  "destinations_checked": N,
  "destinations_skipped": M,
  "news_alerts": [slug, ...],
  "enqueued_refreshes": [{slug, horizon}, ...],
  "suppressed": [{slug, reason}, ...],
  "budget_hit": false
}
```

## v2 TODO (do not implement)

When Amadeus + LiteAPI MCPs land:

- Before step 3a, add price sweep: Amadeus flight-offer-search AUS→dest and
  IAH→dest for both horizon windows, LiteAPI hotels for each candidate
  neighborhood, apply the carrier/lodging filters from TRAVEL.md.
- Diff `total_usd` vs the most recent `trip_baselines.baseline_total_usd`.
  If ≥ 15 % drop: news-gate (from 3a), then announce as a deal with inline
  citations + Amadeus offer ID.
- Also poll changedetection.io webhook log for deal-blog hits.
