#!/usr/bin/env python3
"""home_scout_notify.py — send ntfy push notifications for Tier 1-2 listings.

Reads one JSON listing per stdin line (output of home_scout_score.py).
For each Tier 1 or Tier 2 listing not already in notifications_log, POSTs
to ntfy and records the dedupe key.

Tier 3 listings get a Matrix announce via OpenClaw's cron delivery mechanism
(the skill assembles the digest). This script only handles ntfy push.

Requires:
    NTFY_TOPIC_HOME_SCOUT env var — the ntfy topic name on ntfy.danteb.com.
    /var/lib/openclaw/state.db — for notifications_log.

Usage:
    python3 home_scout_score.py --since=2d | python3 home_scout_notify.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone

DB_PATH = "/var/lib/openclaw/state.db"
NTFY_BASE = "https://ntfy.danteb.com"
TOPIC = os.environ.get("NTFY_TOPIC_HOME_SCOUT", "")


def dedupe_key(listing: dict) -> str:
    zid = listing["zillow_id"]
    price = listing.get("list_price") or 0
    rounded = round(price / 50_000) * 50_000
    return f"home-scout:listing:{zid}:{rounded}"


def already_sent(conn: sqlite3.Connection, dk: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM notifications_log WHERE dedupe_key = ?", (dk,)
        ).fetchone()
    )


def ntfy_priority(tier: int) -> str:
    return "5" if tier == 1 else "4"


def build_ntfy_body(listing: dict) -> bytes:
    lp = listing.get("list_price")
    psf = listing.get("psf")
    beds = listing.get("beds")
    baths = listing.get("baths")
    sqft = listing.get("sqft")
    piti = listing.get("piti_monthly")
    piti_pct = listing.get("piti_to_gross")
    yb = listing.get("year_built")
    hoa = listing.get("hoa_monthly")
    dom = listing.get("days_on_market")
    subdiv = listing.get("subdivision") or ""

    parts = []
    price_line = f"${lp:,}" if lp else "price unknown"
    if psf:
        price_line += f" · ${psf:.0f}/sqft"
    parts.append(price_line)

    if beds and sqft:
        parts.append(f"{beds} bd · {baths} ba · {sqft:,} sqft")
    elif beds:
        parts.append(f"{beds} bd · {baths} ba")

    if yb:
        parts.append(f"Built {yb}")

    if piti:
        pct_str = f" ({piti_pct * 100:.1f}% of gross)" if piti_pct else ""
        parts.append(f"PITI ${piti:,.0f}/mo{pct_str}")

    extras = []
    if hoa:
        extras.append(f"HOA ${hoa}/mo")
    if dom:
        extras.append(f"{dom}d on market")
    if subdiv:
        extras.append(subdiv)
    if extras:
        parts.append(" · ".join(extras))

    return "\n".join(parts).encode("utf-8")


def send_ntfy(listing: dict) -> bool:
    if not TOPIC:
        print("NTFY_TOPIC_HOME_SCOUT not set; skipping ntfy push", file=sys.stderr)
        return False

    tier = listing["tier"]
    address = listing.get("address", "unknown address")
    url = listing.get("url", "")

    body = build_ntfy_body(listing)
    headers = {
        "Title": f"Tier {tier}: {address}",
        "Priority": ntfy_priority(tier),
        "Tags": "house",
    }
    if url:
        headers["Click"] = url

    req = urllib.request.Request(
        f"{NTFY_BASE}/{TOPIC}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 300
    except Exception as exc:
        print(f"ntfy send failed for {listing.get('zillow_id')}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    sent = 0
    skipped_tier = 0
    skipped_dedup = 0

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            listing = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        tier = listing.get("tier", 5)
        if tier > 2:
            skipped_tier += 1
            continue

        dk = dedupe_key(listing)
        if already_sent(conn, dk):
            skipped_dedup += 1
            continue

        ok = send_ntfy(listing)
        if ok:
            conn.execute(
                "INSERT OR IGNORE INTO notifications_log (dedupe_key, channel, payload_md, sent_at) VALUES (?,?,?,?)",
                (
                    dk,
                    "ntfy",
                    json.dumps(listing),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            sent += 1

    summary = {
        "ntfy_sent": sent,
        "skipped_tier_3_plus": skipped_tier,
        "skipped_dedup": skipped_dedup,
    }
    json.dump(summary, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
