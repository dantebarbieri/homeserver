---
name: travel-alter-plan
description: >
  Modify an existing trip plan in place based on a free-text instruction like
  "skip Osaka and find something else for that leg", "add a beach day on day
  4", "swap Naples for more Rome time". Preserves every unmentioned
  constraint (dates, PTO budget, other cities, flights already priced) and
  produces a versioned revision with a diff summary.
metadata:
  openclaw:
    emoji: "✂️"
    requires:
      bins:
        - python3
---

# Travel alter plan

Step 0 — load `workspace/TRAVEL.md`. Everything in it applies.

**Inputs** — `{destination: "<slug>", horizon_months?: 6|12,
instruction: "<raw user text>"}`. If `horizon_months` is unset and the user
didn't clarify, assume the nearer horizon (6) and mention that assumption in
the reply.

## Routing shape

**This entire skill runs on `claude-sonnet`.** The task is genuine plan
synthesis: understanding natural-language constraint deltas, identifying
affected sections, preserving everything else, and re-pricing. The prompt is
structured to be long-prose + synthesis-heavy so the homeserver router
classifies correctly without model-name hints.

## Step 1 — load current plan

```python
import sqlite3, json
conn = sqlite3.connect('/var/lib/openclaw/state.db')
dest = conn.execute(
  "SELECT id, slug, display_name, country_code, lat, lon FROM destinations"
  " WHERE slug=? OR display_name=?", (name, name)
).fetchone()
current = conn.execute("""
  SELECT id, baseline_total_usd, trip_plan_md, source_urls_json, model_used,
         generated_at
  FROM trip_baselines
  WHERE destination_id=? AND horizon_months=?
  ORDER BY generated_at DESC LIMIT 1
""", (dest[0], horizon_months)).fetchone()
```

If no row → reply "no plan to alter — run `refresh {name}` first" and stop.

## Step 2 — fetch supporting context

- `seasons` row for the destination.
- All fresh `destination_knowledge` rows.
- `blackouts` table (must re-check any new window the alteration implies).
- `fx_rates` latest.

## Step 3 — synthesize the revision

Compose a single Sonnet-shaped prompt. Load:

1. TRAVEL.md verbatim.
2. The current plan markdown (including YAML frontmatter).
3. All context from step 2.
4. The user's alteration instruction, unedited.

Then ask:

> Revise the trip plan above according to the user's instruction. Synthesize
> across the preserved constraints (dates, flight totals already priced,
> vegetarian dining requirement, mid-range lodging, blackout ranges, PTO
> budget, carrier preferences, output format) and the alteration request.
>
> Do the following explicitly:
>
> 1. Identify which section(s) of the plan the instruction affects. Leave
>    every other section textually intact — do not regenerate unaffected
>    prose.
> 2. Propose substitute content for the affected section(s). For city
>    substitutions: pick an alternative base city that fits the same season,
>    PTO budget, and vegetarian-dining availability as what it replaces.
>    For day-level edits: rewrite only the affected day(s), keeping the
>    surrounding narrative coherent.
> 3. Re-price the affected portion only. Flight cost usually unchanged for
>    within-country edits; for base-city changes, re-estimate lodging via
>    SearXNG (mid-range neighborhood rate × new nights) and adjust inter-city
>    transport via Valhalla if applicable.
> 4. Query SearXNG for any new city's seasonal appropriateness given the
>    existing window — flag if the substitute is a poor seasonal fit.
> 5. Produce TWO outputs:
>    - A **full revised plan** in the same YAML-frontmatter + markdown
>      format as the original, with an incremented `plan_version` in
>      frontmatter if present.
>    - A **diff block** at the end: three short sections — `## Changed`,
>      `## Why`, `## Cost delta` — in ≤ 150 words total. Include inline
>      `[n]` citations for any new knowledge pulled.

## Step 4 — validate against blackouts

Before writing, re-check:

```python
def intersects_blackout(start, end):
    return conn.execute(
      "SELECT 1 FROM blackouts WHERE NOT (end_date < ? OR start_date > ?) LIMIT 1",
      (start, end)
    ).fetchone() is not None
```

If any implied window in the revised plan intersects a blackout, refuse and
reply: "Revision would land in blackout {reason} ({start}–{end}) — rephrase."

## Step 5 — budget sanity check

```python
old = current['baseline_total_usd']
new = parsed_frontmatter['total_usd_2p']
delta_pct = (new - old) / old * 100
flag_large_delta = abs(delta_pct) > 15
```

If `flag_large_delta` is true, prepend the diff block with: "⚠️ Total cost
changed {delta_pct:.1f}% — significant; review before booking."

## Step 6 — persist

1. Write markdown to
   `/home/openclaw/.openclaw/itineraries/{slug}-h{horizon_months}-v{N+1}.md`.
2. Append a new row to `trip_baselines` — append-only-versioned; do NOT
   update the prior row. `generated_at` = now, `expires_at` = now + 60 days,
   `model_used` = whatever model the router actually used (recorded from the
   Sonnet call's response headers).
3. Record a `notifications_log` row with `dedupe_key =
   "alter:{slug}:{horizon}:{timestamp}"` to avoid replaying the Matrix post
   on retry.
4. Post to Matrix `!IKHsmcvoWUABvnvcmj:danteb.com`:
   - The diff block first (user probably cares about that more).
   - Then the full revised plan.
   - Then citations.

## Failure modes

- Ambiguous instruction ("change Osaka" — to what?) → reply with ONE
  clarifying question, do not write.
- Substitute city fails seasonality check → include the warning inline but
  proceed if the user's instruction was explicit. Don't refuse.
- SearXNG timeout during re-pricing → use the old lodging total ± 10% as
  placeholder and annotate the diff block with "estimated; re-run when
  SearXNG responds."
