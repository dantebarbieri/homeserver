---
name: travel-deep-plan
description: >
  Generate a fresh trip plan for a destination at a given horizon (6 or 12
  months). Use when Dante adds a destination, asks to refresh one, or when
  travel-watch detects a stale/missing baseline. Produces a reduced-estimate
  plan in YAML-frontmatter + Markdown format, writes it to
  ~/.openclaw/itineraries/, and appends a new row to trip_baselines.
metadata:
  openclaw:
    emoji: "🗺️"
    requires:
      bins:
        - python3
---

# Travel deep plan

Step 0 — load `workspace/TRAVEL.md`. Do not restate its rules; they apply.

**Inputs** — expect `{destination: "<slug or display name>", horizon_months:
6|12, constraints?: "<freetext extra>"}`. If called with just a name, default
both horizons (run twice, one per horizon).

## Routing shape

Steps 1–6, 8, 9, 10 are bounded extractions — compact JSON in, compact JSON
out → **`qwen-local`**.

**Step 7 is the one place this skill escalates.** Its prompt loads the full
preamble + every piece of context gathered in steps 1–6, plus analogs from
existing `trip_baselines`, and asks for synthesis across past-trip patterns
and current constraints. The prose shape + size naturally triggers
**`claude-sonnet`** through the homeserver router. Do not hardcode a model —
just shape the prompt correctly.

## Step 1 — resolve the destination

```python
import sqlite3
conn = sqlite3.connect('/var/lib/openclaw/state.db')
row = conn.execute(
  "SELECT id, slug, display_name, country_code, lat, lon, preferred_months,"
  " avoid_months, priority FROM destinations WHERE slug=? OR display_name=?",
  (name, name)
).fetchone()
```

If missing: resolve via `wikidata-remote` (country Q-ID for a country, settle
Q-ID for a city), insert into `destinations`, then proceed.

## Step 2 — seasonality (delegate to `travel-seasonality-synth`)

Check `seasons` for a fresh row:

```sql
SELECT * FROM seasons
WHERE destination_id = ?
  AND julianday('now') - julianday(refreshed_at) < ttl_days;
```

Fresh hit → use it. Miss or `confidence < 0.6` → invoke
`travel-seasonality-synth` skill with `{destination_id, display_name}`. That
skill writes the row and returns it.

## Step 3 — candidate windows

Intersect `seasons.shoulder_months ∪ seasons.high_season_months` with the
user's horizon (e.g. horizon_months=6 → today + 150 to today + 210 days),
minus every blackout row:

```python
blackouts = conn.execute(
  "SELECT start_date, end_date FROM blackouts"
).fetchall()
def ok(s, e):
    return all(e_ < s or s_ > e for s_, e_ in blackouts)
```

Pick **three** 7–14 day windows:

1. Anchored to a US holiday from `us_holidays` where `pto_efficiency` is
   `free_3day`/`bridge_4day`/`mega_9day` and the window falls in good months.
2. Mid-week departures (Tue/Wed) preferred when no holiday anchor.
3. Shoulder season preferred. International ≥ 9 nights, domestic 4–5.

## Step 4 — weather reality check

For each candidate window, call Open-Meteo via `python3` + `urllib.request`
(no MCP needed — it's a public JSON API):

```
https://api.open-meteo.com/v1/forecast
  ?latitude={lat}&longitude={lon}
  &daily=temperature_2m_max,precipitation_probability_mean,uv_index_max
  &timezone=auto
  &start_date={window_start}&end_date={window_end}
```

**Flag (don't drop)** windows with:

- 7-day mean max > 34 °C
- Precipitation probability > 50 % on > 3 days
- UV index max > 10

Store flags alongside the window in memory for step 7.

## Step 5 — destination knowledge sweep (parallel, all on Qwen)

For each topic, check `destination_knowledge` freshness (TTL): `visa` 7 d,
`safety` 7 d, `food` 90 d, `transit` 30 d, `events` targeted to candidate
window dates, `neighborhoods` 90 d, `tipping` 365 d, `power` 365 d,
`customs` 90 d.

Stale/missing → synthesize fresh. Source priority from TRAVEL.md. For
`events` specifically: run SearXNG scoped to each candidate window's month.
For `visa` + `safety`: include State Department / home-country foreign office
results. Upsert each into `destination_knowledge` with appropriate `ttl_days`.

## Step 6 — pricing (v1 scope-cut: estimate only)

No Amadeus/LiteAPI yet. Estimate fare + lodging via SearXNG with explicit
caveat:

- `flights AUS to {destination} {window_month} {year}` — top 3 results,
  pull typical-price range (e.g. "$800–$1200 rt"). Median the range.
- `hotels {destination} {neighborhood} mid-range` — per-night median from
  top 3 results.
- Compute `baseline_total_usd = flight_median * 2 + lodging_per_night *
  nights * 1.15` (15 % misc buffer already baked into TRAVEL.md format).

**Output must include a caveat banner in the markdown body**:

> ⚠️ Estimated pricing only — live fare/rate lookups will arrive when the
> Amadeus + LiteAPI MCP servers ship. Verify before booking.

Do **not** write to `price_history` — that table stays empty in v1.

## Step 7 — itinerary drafting → **Sonnet escalation**

Assemble a single prompt containing:

1. Verbatim TRAVEL.md preamble.
2. Full `seasons` row.
3. All fresh `destination_knowledge` rows (all topics).
4. The 3 candidate windows with weather flags.
5. Pricing estimates from step 6.
6. **Analogs**: fetch up to 3 prior `trip_baselines` rows from other
   destinations with similar characteristics (same `country_code` region,
   same `priority` tier, or manual curated list in TRAVEL.md).
7. User constraints (if provided).

Then phrase the task using synthesis language that naturally triggers the
router's complexity classifier:

> Synthesize across the past-trip analogs above and the current constraints
> below to design an itinerary. Weigh trade-offs explicitly: pace vs coverage,
> cost vs comfort, shoulder-season risk vs crowd avoidance. Plan either:
>
> - **Multi-city country** (India / Japan / Italy / ...) — cap 3–4 bases,
>   3–5 nights each. Propose inter-city transport with explicit preference
>   ordering: train > regional flight > bus. Verify transit feasibility with
>   Valhalla `costing=multimodal` and report drive/transit times.
>
> - **Single city** — 4–7 nights, pick neighborhood by cross-referencing
>   Wikivoyage neighborhood notes with POI density.
>
> For either: include 1 major + 1 minor activity per day, vegetarian dining
> anchors per base city (use knowledge.food + Photon/Nominatim POI search),
> and an inter-base transit narrative where applicable.

Output requirements: YAML frontmatter per TRAVEL.md template, markdown body
≤ 500 words, 2 alternative dates at the end, inline `[n]` citations, sources
block listing tool + article/Q-ID per citation.

## Step 8 — pre-departure fact sheet (Wikidata SPARQL)

Single round-trip to `wikidata-remote`:

```sparql
SELECT ?currency ?language ?calling ?tz ?iso2 ?iso3 ?plug ?side ?visa WHERE {
  wd:{country_qid} wdt:P38 ?currency ;
                    wdt:P37 ?language ;
                    wdt:P474 ?calling ;
                    wdt:P421 ?tz ;
                    wdt:P297 ?iso2 ;
                    wdt:P298 ?iso3 ;
                    wdt:P2853 ?plug ;
                    wdt:P1622 ?side .
  OPTIONAL { wd:{country_qid} wdt:P3005 ?visa . }
}
```

Append as a compact card (not prose) at the end of the markdown body:

```
| | |
|--|--|
| Currency | JPY |
| Language | Japanese |
| Calling code | +81 |
| Timezone | Asia/Tokyo |
| Plug | Type A / B |
| Driving | Left |
```

## Step 9 — trail/activity scoring

For any planned hike/walk/ride > 5 km, call Valhalla for the polyline
(`costing=pedestrian` or `bicycle`), then the `elev` MCP for the elevation
profile along that polyline. Report: cumulative ascent (m), max grade (%),
difficulty verdict calibrated to "moderately active but not serious hikers."

## Step 10 — output + persist

1. Write markdown to `/home/openclaw/.openclaw/itineraries/{slug}-h{6|12}-v{N}.md`.
   `N` = `(existing row count for (dest, horizon)) + 1`.
2. Append to `trip_baselines`:

```python
conn.execute("""
  INSERT INTO trip_baselines (destination_id, horizon_months,
    baseline_total_usd, baseline_flight_usd, baseline_lodging_usd,
    baseline_other_usd, trip_plan_md, source_urls_json, searxng_query,
    model_used, generated_at, expires_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
          datetime('now'), datetime('now', '+60 days'))
""", (...))
```

3. Post to Matrix room `!IKHsmcvoWUABvnvcmj:danteb.com`:
   - YAML frontmatter rendered as a short summary block
   - The full markdown body
   - Sources section

## Failure modes

- SearXNG timeout → retry once with 30s budget, then downgrade seasonality
  confidence and proceed.
- Wikidata SPARQL 5xx → fall back to Wikipedia infobox; note source change.
- No blackout-clean candidate windows → reply "no valid windows in this
  horizon; try a wider horizon or a different destination" and do not write
  a baseline.
