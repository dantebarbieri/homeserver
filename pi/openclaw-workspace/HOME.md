# HOME — house-hunting agent constraints

Load this document at the start of any home-scout skill turn. All home-scout
skills (`home-scout`) assume these rules without restating them.

## Target

Saved search: "Homes for Sale in ZIP: 78759" (Austin, TX north-central).
Budget: ≤ $1.1M offer. Target: 2000+ sqft, ≥ 3BR, ≥ 0.2 acre, year built ≥ 1985.
Buyers: Dante + Anjali Barbieri. Combined gross ~$339K/yr. Wedding 2026-Q2 —
assume normal income through close.

## Hard filters (reject if any fails)

- ZIP ≠ 78759 (only alert on in-ZIP listings)
- list_price > $1,100,000
- year_built < 1985 unless: extensive renovation AND lot ≥ 0.25 acre AND list ≤ $750K
  (RRISD-zoning condition is Phase 2; for MVP this is the relaxed pre-1985 test)
- days_on_market > 60 with no price drop (price_changed_at IS NULL)
- hoa_monthly > $400

Reference case: 11301 Maidenstone Dr (Barrington Oaks) — passed on due to
1976 build + systems risk at budget. Pre-1985 needs a compelling compensating story.

## Soft scoring (tier 1=must-see, 5=skip)

| Factor | MVP weight (school zone weight redistributed proportionally) |
|---|---|
| Neighborhood tier (A/B/C/D from neighborhoods.yaml) | 37.5% |
| Year built (2000+ = full, 1985–1999 = partial, <1985 = 0 unless filter passed) | 25.0% |
| Price/sqft vs neighborhood_median_psf from config.yaml | 18.75% |
| Lot size (≥ 0.2 ac = full credit) | 6.25% |
| Days on market (≤ 7 d = full credit) | 6.25% |
| Bedrooms (≥ 4 = full credit) | 6.25% |

Tier thresholds from weighted score s:
- s ≥ 0.85 → Tier 1
- 0.70 ≤ s < 0.85 → Tier 2
- 0.55 ≤ s < 0.70 → Tier 3
- 0.40 ≤ s < 0.55 → Tier 4
- s < 0.40 → Tier 5

## Notification policy

- Tier 1 → ntfy priority 5 ("max") + Matrix announcement
- Tier 2 → ntfy priority 4 ("high") + Matrix announcement
- Tier 3 → Matrix announcement only (no ntfy)
- Tier 4–5 → silent log only (persisted in state.db, not announced)

Dedupe key: `home-scout:listing:{zillow_id}:{round(list_price/50000)*50}`
A $50K+ price change generates a new dedupe key → re-alerts even for prior listings.

## Sources (priority order)

1. Gmail (via `gog`) — the saved-search digest emails (from:zillow.com)
2. SQLite cache `home_scout_listings` — prior enrichment, dedup, price history
3. (Phase 2+) SearXNG → per-address school zone lookup, Google Fiber check,
   Zillow listing-page enrichment via SearXNG site: query

Direct Zillow fetching is not viable — CloudFront returns 403 from this pi.

## Budget caps per run

- ≤ 5 LLM turns total
- ≤ 60 s wall-clock for fetch + score combined
- Stop on first hard error; emit a one-line Matrix message:
  `🏠 home-scout: aborted at step N — <error>. See cron logs.`
- Never retry inside the skill; the cron runner fires again tomorrow.

## Routing shape

This skill is fully Qwen-shaped: compact JSON in/out, deterministic steps,
no synthesis verbs. Do NOT produce long prose. The LLM router will send
structured turns to Qwen-local automatically.
