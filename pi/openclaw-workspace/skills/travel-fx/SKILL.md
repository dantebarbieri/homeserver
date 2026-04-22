---
name: travel-fx
description: >
  Pull the daily ECB reference exchange rates and upsert them into the
  fx_rates table. No LLM in the loop — pure HTTP fetch + XML parse + SQL
  write. Invoked by the travel-ecb-fx cron job on weekdays at 17:00
  Europe/Berlin (shortly after ECB publishes the daily snapshot).
metadata:
  openclaw:
    emoji: "💱"
    requires:
      bins:
        - python3
---

# Travel FX

This skill has no LLM reasoning. It's a deterministic data fetch.

## Implementation

```python
import sqlite3, urllib.request, xml.etree.ElementTree as ET, sys

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
NS = {
    "gesmes": "http://www.gesmes.org/xml/2002-08-01",
    "ecb":    "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
}

def main():
    with urllib.request.urlopen(URL, timeout=30) as r:
        body = r.read()
    root = ET.fromstring(body)
    # Structure: Envelope → Cube → Cube[time=YYYY-MM-DD] → Cube[currency, rate]*
    day_cube = root.find("ecb:Cube/ecb:Cube", NS)
    if day_cube is None:
        print("no daily cube in ECB response", file=sys.stderr)
        return 1
    date = day_cube.attrib["time"]
    rows = [
        (date, "EUR", c.attrib["currency"], float(c.attrib["rate"]))
        for c in day_cube.findall("ecb:Cube", NS)
    ]
    # EUR self-rate for completeness
    rows.append((date, "EUR", "EUR", 1.0))

    conn = sqlite3.connect("/var/lib/openclaw/state.db")
    conn.executemany("""
      INSERT INTO fx_rates (date, base, currency, rate)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(date, base, currency) DO UPDATE SET rate = excluded.rate
    """, rows)
    conn.commit()
    print(f"fx_rates: upserted {len(rows)} rows for {date}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Save the above to `/home/openclaw/.openclaw/scripts/travel-fx.py` (the deploy
script installs it there) and the agent turn simply runs:

```
python3 /home/openclaw/.openclaw/scripts/travel-fx.py
```

## Delivery

Job delivery is `"silent"` — no Matrix post on success. On failure (HTTP
error, schema change, SQL error), the agent should post a short alert to
`!IKHsmcvoWUABvnvcmj:danteb.com` with the Python traceback tail and the URL
fetched.

## Caveats

- ECB doesn't publish on target weekends or Eurosystem holidays. On those
  days the last published cube is returned, which means this job will
  re-upsert yesterday's row (idempotent via ON CONFLICT). Fine.
- `rate` is **1 EUR = N currency**. USD cross is `(amount_local / rate) *
  fx_rates.rate_where_currency='USD'` — do the math in `fx_convert` intent,
  not here.
