---
name: travel-dispatch
description: >
  Route an incoming Matrix message from Dante to the right travel-agent
  behavior. Use when Dante sends a DM that mentions destinations, trip plans,
  flight deals, seasonality, safety, events, vegetarian food, currency
  conversion, holidays, or says things like "add X", "remove X", "plan X",
  "show me X", "refresh X", "what's cheapest", "can we do X", "is X safe".
  Also the fallback for any travel-adjacent question that doesn't match
  a named skill.
metadata:
  openclaw:
    emoji: "🧭"
    requires:
      bins:
        - python3
---

# Travel dispatch

Step 0 — always load `workspace/TRAVEL.md` first. Every rule in this skill
assumes those preamble constraints.

## Classify the intent

Run intent classification as a tiny JSON-output step. Keep the prompt compact
so the router stays on `qwen-local`:

```
You are an intent classifier for a travel agent. Classify the user message
below into EXACTLY ONE of these intents. Output ONLY a JSON object — no
prose.

Intents:
- list_destinations  — "list destinations", "watchlist", "what am I watching"
- add_destination    — "add X", "watch X", "start tracking X"
- remove_destination — "remove X", "stop watching X", "drop X"
- show_plan          — "plan for X", "show X", "what's the plan for X"
- refresh            — "refresh X", "replan X", "update X"
- alter_plan         — "I don't want X in the trip, find something else",
                       "skip Y", "add a beach day", "swap Z for W"
- best_deal          — "best deal", "what's cheapest", "top pick"
- safety_check       — "is X safe", "safety in X", "advisories for X"
- events             — "festivals in X", "events during our X trip"
- veg_food           — "vegetarian places near X", "food in X for us"
- fx_convert         — "convert 500 EUR to USD", "what's X in Y"
- general_qa         — any other travel-adjacent question
- help               — "commands", "what can you do", "help"

Output:
{"intent": "<one of the above>", "args": "<extracted args or empty string>"}

Message: <the raw Matrix message>
```

## Dispatch table

Each intent either runs pure SQL, defers to a sub-skill, or does a bounded
knowledge lookup. Stay on `qwen-local` unless flagged **→ Sonnet**.

### `list_destinations` — pure SQL, no LLM beyond formatting

```python
import sqlite3
conn = sqlite3.connect('/var/lib/openclaw/state.db')
rows = conn.execute("""
  SELECT slug, display_name, country_code, priority,
         COALESCE((
           SELECT MAX(generated_at) FROM trip_baselines tb
           WHERE tb.destination_id = d.id
         ), 'never') AS last_plan_at
  FROM destinations d
  WHERE active = 1
  ORDER BY priority ASC, display_name
""").fetchall()
```

Format as compact Matrix markdown table: `slug | name | country | priority |
last plan`.

### `add_destination <name>` — SQL + Wikidata QID lookup

1. Call `wikidata-remote` MCP to resolve `<name>` → `{qid, display_name,
   country_code, lat, lon, kind}`. If ambiguous (e.g. "Georgia" = state or
   country?), reply with ONE clarifying question and stop.
2. Insert into `destinations` with derived `slug` (kebab-case of display_name).
3. Optimistically insert a `seasons` stub row (empty months, `confidence=0.0`)
   so downstream skills can detect it needs seeding.
4. Reply with confirmation + "running deep plan for both horizons, will post
   when ready" to Matrix.
5. Invoke `travel-deep-plan` skill **twice** — once for `horizon_months=6`,
   once for `horizon_months=12`. These fire async; the deep-plan skill posts
   its own completion to Matrix.

### `remove_destination <name>` — pure SQL

```sql
UPDATE destinations SET active = 0, updated_at = datetime('now') WHERE slug = ?;
```

Keep `trip_baselines` / `price_history` / `seasons` for archival. Reply with
confirmation.

### `show_plan <name>` — SQL SELECT from `trip_baselines`

Latest row per `(destination_id, horizon_months)`. If `generated_at > 30d ago`,
append `⚠️ stale — reply "refresh <name>" to regenerate`. Post both horizons
as two separate Matrix messages (6mo first, then 12mo).

### `refresh <name>` — invoke `travel-deep-plan` for both horizons

Same pattern as `add_destination` steps 4–5. Existing `trip_baselines` stay
— append-only-versioned via the `generated_at` column.

### `alter_plan <name> <instruction>` — invoke `travel-alter-plan` → **Sonnet**

Load the latest `trip_baselines.trip_plan_md` for `<name>` (both horizons —
user usually means the nearer one; if ambiguous, ask). Pass raw instruction
to the `travel-alter-plan` skill. That skill's prompt shape triggers Sonnet.

### `best_deal` — pure SQL ranking

No live pricing in v1, so rank by `expires_at - datetime('now')` (freshest
plans) rather than price delta:

```sql
SELECT d.display_name, tb.horizon_months, tb.baseline_total_usd,
       tb.generated_at, tb.expires_at
FROM trip_baselines tb
JOIN destinations d ON d.id = tb.destination_id
WHERE d.active = 1
  AND tb.generated_at = (
    SELECT MAX(generated_at) FROM trip_baselines x
    WHERE x.destination_id = tb.destination_id
      AND x.horizon_months = tb.horizon_months
  )
ORDER BY tb.baseline_total_usd ASC
LIMIT 3;
```

Reply: "Top 3 current plans by estimated total (live deal-hunting returns in
v2 when Amadeus/LiteAPI land)."

### `safety_check <destination>` — Qwen + bounded knowledge lookup

1. SearXNG: `{destination} travel advisory {current_month_year}`,
   `categories=news`, `time_range=month`.
2. SearXNG: `state department travel advisory {destination}`, `time_range=month`.
3. openzim Wikipedia: `<destination>` — pull "Safety" / "Current issues"
   section if present.
4. Synthesize as: `{overall_status: 'normal'|'caution'|'avoid', summary_md,
   top_sources: [...]}`. Post to Matrix with inline `[n]` citations.
5. Upsert into `destination_knowledge` (topic='safety', ttl_days=7) for cache
   re-use.

### `events <destination> <month>` — SearXNG scoped lookup

Query `festivals events {destination} {month} {year}`. Cross-reference any
existing `trip_baselines` window dates for the destination — if an event
intersects, flag it with "⚠️ may spike lodging prices during your planned
window". Upsert into `destination_knowledge` (topic='events', ttl_days=30).

### `veg_food <location>` — geocode + POI

1. Photon forward geocode → lat/lon.
2. Nominatim bbox search within 1000 m, `amenity=restaurant`, then filter
   client-side for `cuisine=vegetarian|vegan` via tag lookups.
3. Fallback: SearXNG `vegetarian restaurants near {location}`, top 10 with
   hostname diversity.
4. Rank by `has_website + opening_hours present` in tags.
5. Reply with top 5: name + address + cuisine + map-ready `lat,lon`.

### `fx_convert <amount> <from> <to>` — pure SQL

```sql
SELECT rate FROM fx_rates WHERE date = (SELECT MAX(date) FROM fx_rates)
  AND currency = ?;
```

`rate` is `1 EUR = N currency`. USD conversions cross through EUR. Reply:
`<amount> <from> ≈ <result> <to> (rate date: YYYY-MM-DD)`.

### `general_qa` — knowledge-first fallback

Wikivoyage → Wikipedia → Wikidata → SearXNG. Stop as soon as one answers
confidently. Always cite.

### `help` — static reply

List the intents above as user-facing commands with examples.

## Logging

After every dispatch, write a one-line JSON to stdout so it lands in the
session log — `{intent, destination_or_null, duration_ms, escalated_to_sonnet}`.
