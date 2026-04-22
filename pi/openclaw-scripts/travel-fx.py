#!/usr/bin/env python3
"""travel-fx.py — pull the ECB daily reference rates and upsert into
fx_rates. No LLM in the loop. Idempotent via ON CONFLICT."""
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
DB = "/var/lib/openclaw/state.db"
NS = {
    "gesmes": "http://www.gesmes.org/xml/2002-08-01",
    "ecb":    "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
}


def main() -> int:
    with urllib.request.urlopen(URL, timeout=30) as r:
        body = r.read()
    root = ET.fromstring(body)
    day_cube = root.find("ecb:Cube/ecb:Cube", NS)
    if day_cube is None:
        print("no daily cube in ECB response", file=sys.stderr)
        return 1
    date = day_cube.attrib["time"]
    rows = [
        (date, "EUR", c.attrib["currency"], float(c.attrib["rate"]))
        for c in day_cube.findall("ecb:Cube", NS)
    ]
    rows.append((date, "EUR", "EUR", 1.0))

    conn = sqlite3.connect(DB)
    conn.executemany(
        """
        INSERT INTO fx_rates (date, base, currency, rate)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date, base, currency) DO UPDATE SET rate = excluded.rate
        """,
        rows,
    )
    conn.commit()
    print(f"fx_rates: upserted {len(rows)} rows for {date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
