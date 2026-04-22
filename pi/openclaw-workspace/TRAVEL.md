# TRAVEL.md — travel agent preamble

Load this document at the start of any travel-related turn. The travel skills
(`travel-dispatch`, `travel-deep-plan`, `travel-alter-plan`,
`travel-seasonality-synth`, `travel-watch`, `travel-fx`, `travel-holidays`)
all assume these rules without restating them.

## Travelers

- **Dante Barbieri** and **Anjali** (fiancée). Two adults. Both vegetarian —
  lodging and all restaurant suggestions must respect this.

## Departure airports

- **AUS** (Austin) is primary.
- **IAH / HOU** (Houston) acceptable if it saves **≥ $150/pp** vs AUS, or
  unlocks a nonstop that AUS can't match.

## Carriers

- Preferred: **AA, DL**.
- Acceptable fallback: **UA**.
- Domestic only: **WN** (Southwest).
- **Never: F9 (Frontier), NK (Spirit).**

## Flight rules

- Nonstop preferred.
- ≤ 1 stop with healthy layover: **90 min** domestic, **150 min** intl,
  **210 min** at LHR/CDG/FRA/JFK.
- Redeye only if it saves **≥ $200/pp**.
- Economy default; premium economy for **≥ 8 h** flights only when the
  upgrade is **< $60/h**.

## Lodging

- **Mid-range**, $150–$300/night typical.
- **3–4 stars**, **≥ 7.5/10** rating, **≥ 30 reviews**.
- Pricing falls in the **P25–P80** percentile of the result set (not cheapest,
  not luxury).

## Trip style

- Moderate pace: **1 major + 1 minor** activity per day.
- Shoulder season preferred.
- **International**: 9–14 days. **Domestic long-weekend**: 4–5 days.

## Horizons

- **6 months** (~180 days out)
- **12 months** (~365 days out)

## Hard blackout — never suggest trips in this range

**2027-01-15 through 2027-03-31** — wedding + buffer. Enforced by the
`blackouts` table in `state.db`; skills must re-check via SQL before proposing
windows:

```python
import sqlite3
conn = sqlite3.connect('/var/lib/openclaw/state.db')
def intersects_blackout(start, end):
    row = conn.execute(
        "SELECT 1 FROM blackouts WHERE NOT (end_date < ? OR start_date > ?) LIMIT 1",
        (start, end)
    ).fetchone()
    return row is not None
```

## Output format — reduced-estimate

Every trip plan emits YAML frontmatter with totals + short markdown body.
Always include:

- `total_usd_2p`, `per_person_usd`, `pto_days`, `anchor_holidays`, `carriers`,
  `dates` (`window_start`, `window_end`), `cabin`, `horizon_months`.
- **Always cite** inline with `[n]`, references block at the end.
- **15% miscellaneous buffer** added to `total_usd_2p`.
- Local-currency conversion via the `fx_rates` table (date, currency → rate_eur;
  USD cross calculated as EUR-intermediate).

Example frontmatter:

```yaml
---
destination: tokyo
horizon_months: 12
window_start: 2027-04-12
window_end:   2027-04-22
pto_days: 6
anchor_holidays: [2027-04-16 (Good Friday), 2027-04-19 (not-US)]
carriers: [AA, JL codeshare]
cabin: premium-economy
total_usd_2p: 6450
per_person_usd: 3225
local_currency: JPY
local_total: 985000
fx_date: 2026-04-22
confidence: high
---
```

## Tool priority — stop as soon as one source answers with confidence

1. **Wikivoyage** (openzim MCP) — practical travel content: what to do/see/eat,
   neighborhoods, transit, scams, tipping, packing, regional food, opening-hour
   norms. **First choice.**
2. **Wikipedia** (openzim MCP local ZIM; wikipedia MCP online as fallback) —
   encyclopedic background, history, geography, culture. Online only if local
   is empty or the question is time-sensitive within the last 6 months.
3. **Wikidata** (wikidata-remote or wikidata-local MCP) — structured facts
   keyed to country Q-ID. **Always prefer Wikidata over Wikipedia prose** for
   plug types (P2853), driving side (P1622), currency (P38), language (P37),
   calling code (P474), timezone (P421), ISO codes (P297/P298), visa
   requirements (P3005). Single SPARQL → structured JSON.
4. **SearXNG-AI** — last resort; use for freshness < 3 months, current events,
   strikes, advisories. Also the fallback when the above three miss.

Cite the source tool and article title or Q-ID in replies.

## Geocoding

- **Photon** — free-text place strings; multilingual, fuzzy, typo-tolerant.
- **Nominatim** — structured addresses; reverse geocoding.

## Routing

- **Valhalla** with explicit `costing` (`auto` | `bicycle` | `pedestrian` |
  `bus` | `multimodal`).
- For pedestrian/bicycle routes **> 5 km**: follow up with elevation profile
  via `elev` MCP on the polyline → report cumulative ascent, max grade,
  difficulty verdict calibrated to "moderately active but not serious hikers."

## POI discovery

- `Nominatim` bbox search + `Photon` named-POI lookup + `SearXNG` (Wikivoyage
  neighborhood notes, reddit r/travel recs). Overture places and OSM Overpass
  are not yet wired — skip references to them.

## Database access

Every travel skill reads/writes `/var/lib/openclaw/state.db` via Python
`sqlite3`. The DB is Pi-local, owned by `openclaw`. Schema is documented in
`~/HomeServer/pi/sqlite-migrations/`. Key tables the skills use:

- `destinations` (slug, display_name, country_code, lat, lon, priority, active,
  preferred_months, avoid_months) — the watchlist.
- `trip_baselines` (destination_id, horizon_months (6|12), baseline_total_usd,
  trip_plan_md, source_urls_json, model_used, generated_at, expires_at) —
  append-only-versioned. The "current plan" is the latest row per
  `(destination_id, horizon_months)`.
- `price_history` (append-only) — **v1 scope-cut, not populated yet.** Stays
  empty until Amadeus + LiteAPI MCPs land in v2.
- `seasons` (destination_id, high_season_months, shoulder_months,
  low_season_months, rainy_months, confidence, source_urls_json, refreshed_at,
  ttl_days default 180) — annual refresh target.
- `destination_knowledge` (destination_id, topic, content_md,
  source_urls_json, refreshed_at, ttl_days) — short-TTL per-topic facts.
  Topics: `visa, safety, food, transit, events, neighborhoods, tipping, power,
  health, customs`.
- `fx_rates` (date, currency, base='EUR', rate) — daily ECB snapshot; Job 4
  populates.
- `blackouts` (reason, start_date, end_date) — hard constraints; queries use
  `WHERE NOT (end_date < ? OR start_date > ?)` to test intersection.
- `notifications_log` (dedupe_key UNIQUE, channel, payload_md, sent_at) —
  7-day dedupe of Matrix announcements.
- `wikivoyage_excerpts` (destination_id, section, content_md, fetched_at) —
  offline fallback; Job 3 populates from openzim ZIM dumps.
- `cd_watches` — changedetection.io mirror; unused in v1.

## Routing discipline (shapes how the LLM router escalates)

The homeserver router classifies by content shape, not by model hint. Skills
must structure prompts to trigger the right tier:

- **Small structured tasks** (classification, SQL formatting, fact lookup,
  seasonality JSON) — compact prompts, JSON schema output, no plan/design/
  synthesize/analyze keywords → routes to **`qwen-local`**.
- **Deep planning** (the itinerary-drafting step in `travel-deep-plan`, all of
  `travel-alter-plan`) — long prose context (loaded baselines, seasons,
  knowledge), explicit "synthesize across the following past-trip analogs and
  current constraints" phrasing, > 8 K tokens → naturally escalates to
  **`claude-sonnet`**.
- Never hardcode model names. Trust the router.

## Matrix target

Default announcement room: `!IKHsmcvoWUABvnvcmj:danteb.com` (the room the bot
is already paired in). User DMs originate from `@dante:danteb.com`.
