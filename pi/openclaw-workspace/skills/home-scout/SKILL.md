---
name: home-scout
description: >
  Daily Zillow 78759 saved-search scan. Reads digest emails via gog,
  runs PITI math, scores by neighborhood tier, posts Matrix digest, ntfy
  push for Tier 1-2. Invoked by the home-scout-daily cron job.
metadata:
  openclaw:
    emoji: "🏠"
    requires:
      bins:
        - python3
        - gog
---

# home-scout

Step 0 — load `workspace/HOME.md`.

You are running the daily 78759 home-search scan. Be terse and deterministic.
No synthesis, no prose, no model escalation. Every step is a bash call;
your only job is to run them, handle errors, and assemble the Matrix digest.

## Routing shape

All turns are compact JSON in/out — Qwen-shaped. Do not produce long prose.
Do not explain anything unless a step fails.

## Budget

≤ 5 turns. ≤ 90 s wall-clock. If a step takes > 30 s, log it and continue.
On first unrecoverable error, emit the one-line error matrix message and stop.

---

## Step 1 — Fetch & parse new Zillow emails

```bash
python3 /home/openclaw/.openclaw/scripts/home_scout_fetch.py --since=2d
```

This returns JSON: `{"new": [...], "changed": [...], "processed_emails": N}`.

- If `gog` fails (non-zero exit, message contains "keyring" or "auth"):
  post `🏠 home-scout: gog auth error — check GOG_KEYRING_PASSWORD in secrets.env` and stop.
- If `processed_emails == 0` and the exit code is 0: no new Zillow emails.
  Jump to Step 4 (emit "No new listings today").
- If exit non-zero for any other reason:
  post `🏠 home-scout: fetch failed — <first line of stderr>. See cron logs.` and stop.

---

## Step 2 — Score the new / changed listings

```bash
python3 /home/openclaw/.openclaw/scripts/home_scout_score.py --since=2d
```

This writes scored output to stdout as JSONL (one JSON object per line),
already sorted by score descending.

Capture the full stdout to a variable. If exit non-zero:
post `🏠 home-scout: score failed — <first line of stderr>` and stop.

If no lines were emitted (all listings rejected), note "all listings hard-filtered"
and jump to Step 4 with an appropriate digest line.

---

## Step 3 — Send ntfy push notifications for Tier 1-2

Pipe the captured JSONL from Step 2 into the notifier:

```bash
echo "$SCORED_OUTPUT" | python3 /home/openclaw/.openclaw/scripts/home_scout_notify.py
```

Ignore non-zero exit (ntfy failures are non-blocking). Log the JSON result.

---

## Step 4 — Emit the Matrix digest

Output ONLY the following markdown as your final message (the gateway delivers
it to the Matrix announcement room). Do not add any other text.

If no new listings or all hard-filtered:

```
🏠 **home-scout YYYY-MM-DD** — No new 78759 listings in today's digest.
```

If there are scored listings, use this template (fill in the blanks):

```
🏠 **home-scout YYYY-MM-DD** — N new, M changed (P emails processed)

**Tier 1**
- [address](zillow_url) — $price · $psf/sqft · beds/baths · built year · PITI $monthly/mo · HOA $X/mo
...

**Tier 2**
...

**Tier 3**
...

Plus X Tier 4–5 listings filed silently.
```

Rules for the digest:
- Include Tier 1, 2, 3 listings by name. One bullet per listing.
- Omit HOA line if hoa_monthly is 0 or null.
- Omit Tier sections that have no listings.
- If Tier 3 has > 5 entries, collapse to: `Tier 3 — N listings (see state.db)`.
- Keep the total under 30 lines.
- If there were any rejected listings, add one line at the end:
  `Rejected: X over-budget, Y pre-1985, Z stale`

---

## Error handling (all steps)

One-line matrix message pattern:
`🏠 home-scout: <step name> failed — <error>. See ~/.openclaw/cron/runs/ logs.`

Never retry within the skill. The cron runner fires again tomorrow at 08:00 CT.
