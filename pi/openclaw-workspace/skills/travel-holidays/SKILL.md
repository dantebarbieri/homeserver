---
name: travel-holidays
description: >
  Populate or refresh the us_holidays table with the next 2 calendar years
  of US federal holidays plus a pto_efficiency annotation per holiday
  (free_3day | bridge_4day | mega_9day | plain). Invoked by the
  travel-annual-holidays cron job on Jan 1.
metadata:
  openclaw:
    emoji: "🇺🇸"
    requires:
      bins:
        - python3
---

# Travel holidays

No LLM. Deterministic calendar math in pure Python stdlib.

## Schema note

The table name in the prompt was `us_holidays` but it's not yet created —
this skill's deploy inserts the table DDL as migration `0005_us_holidays.sql`
on first run. The deploy script handles the migration before this skill ever
runs.

Expected schema (added by 0005):

```sql
CREATE TABLE us_holidays (
  holiday_date    TEXT PRIMARY KEY,      -- ISO 'YYYY-MM-DD'
  name            TEXT NOT NULL,
  pto_efficiency  TEXT NOT NULL CHECK (pto_efficiency IN
                    ('free_3day','bridge_4day','mega_9day','plain'))
);
```

## Implementation

```python
import sqlite3, datetime, sys

def nth_weekday(year, month, weekday, n):
    """1-indexed Nth weekday in month; weekday 0=Mon..6=Sun."""
    d = datetime.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + datetime.timedelta(days=offset + (n - 1) * 7)

def last_weekday(year, month, weekday):
    """Last `weekday` in `month`."""
    # Start from last day of month, walk backward.
    if month == 12:
        end = datetime.date(year, 12, 31)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    offset = (end.weekday() - weekday) % 7
    return end - datetime.timedelta(days=offset)

def observed(d):
    """Federal observance rule: Saturday → Friday, Sunday → Monday."""
    if d.weekday() == 5:  # Sat
        return d - datetime.timedelta(days=1)
    if d.weekday() == 6:  # Sun
        return d + datetime.timedelta(days=1)
    return d

def us_federal_holidays(year):
    h = {}
    h[observed(datetime.date(year, 1, 1))]   = "New Year's Day"
    h[nth_weekday(year, 1, 0, 3)]            = "MLK Day"
    h[nth_weekday(year, 2, 0, 3)]            = "Presidents Day"
    h[last_weekday(year, 5, 0)]              = "Memorial Day"
    h[observed(datetime.date(year, 6, 19))]  = "Juneteenth"
    h[observed(datetime.date(year, 7, 4))]   = "Independence Day"
    h[nth_weekday(year, 9, 0, 1)]            = "Labor Day"
    h[nth_weekday(year, 10, 0, 2)]           = "Columbus Day"
    h[observed(datetime.date(year, 11, 11))] = "Veterans Day"
    h[nth_weekday(year, 11, 3, 4)]           = "Thanksgiving"
    h[observed(datetime.date(year, 12, 25))] = "Christmas"
    return h

def pto_efficiency(d, all_holidays):
    """Classify the PTO multiplier of a holiday:
       free_3day  — falls on Mon or Fri (3-day weekend, 0 PTO)
       bridge_4day — falls on Tue or Thu (1 PTO day → 4-day stretch)
       mega_9day  — another federal holiday within 7 days
       plain      — Wed / Sat / Sun / everything else
    """
    for other_date in all_holidays:
        if other_date != d and abs((other_date - d).days) <= 7:
            return "mega_9day"
    wd = d.weekday()
    if wd in (0, 4):
        return "free_3day"
    if wd in (1, 3):
        return "bridge_4day"
    return "plain"

def main():
    now = datetime.date.today()
    years = [now.year, now.year + 1, now.year + 2]
    all_dates = set()
    rows = []
    per_year = {y: us_federal_holidays(y) for y in years}
    for y, h in per_year.items():
        all_dates.update(h.keys())
    for y, h in per_year.items():
        for d, name in h.items():
            rows.append((d.isoformat(), name, pto_efficiency(d, all_dates)))

    conn = sqlite3.connect("/var/lib/openclaw/state.db")
    conn.executemany("""
      INSERT INTO us_holidays (holiday_date, name, pto_efficiency)
      VALUES (?, ?, ?)
      ON CONFLICT(holiday_date) DO UPDATE SET
        name = excluded.name,
        pto_efficiency = excluded.pto_efficiency
    """, rows)
    conn.commit()
    print(f"us_holidays: upserted {len(rows)} rows for {years}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Save to `/home/openclaw/.openclaw/scripts/travel-holidays.py`. Agent turn
runs:

```
python3 /home/openclaw/.openclaw/scripts/travel-holidays.py
```

## Delivery

Silent on success. On failure, Matrix alert to
`!IKHsmcvoWUABvnvcmj:danteb.com`.

## Edge cases

- The `mega_9day` classifier only checks federal holidays. If Thanksgiving +
  Black Friday (non-federal but culturally PTO-efficient) combine, this
  won't flag it. Fine for v1 — the planner can notice "Thanksgiving +
  following Friday" manually when it sees the weekday.
- Columbus Day is controversial; renaming to "Indigenous Peoples' Day" is
  an IRS-local vs federal distinction. Federal usage is still "Columbus
  Day"; keep that for consistency with federal PTO calendars.
