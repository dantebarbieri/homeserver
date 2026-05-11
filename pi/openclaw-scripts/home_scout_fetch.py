#!/usr/bin/env python3
"""home_scout_fetch.py — pull Zillow saved-search digest emails via gog,
parse listings, upsert into home_scout_listings, record processed emails.

Usage:
    python3 home_scout_fetch.py [--since=2d] [--dry-run]

--since: passed verbatim to gog's newer_than: filter (e.g. 1d, 2d, 7d).
--dry-run: uses in-memory SQLite; no writes to state.db.

Outputs JSON to stdout:
    {"new": ["<zid>", ...], "changed": ["<zid>", ...], "processed_emails": N}

Requires GOG_KEYRING_PASSWORD in env (loaded from ~/.openclaw/secrets.env
by the openclaw-gateway process before any agent turn runs).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser

DB_PATH = "/var/lib/openclaw/state.db"
GOG = "/usr/local/bin/gog"
MIGRATION_SQL = os.path.expanduser(
    "~/repos/homeserver/pi/sqlite-migrations/0006_home_scout.sql"
)

# --- Regex patterns for Zillow plain-text email bodies ---
ZILLOW_URL_RE = re.compile(
    r"https?://(?:www\.)?zillow\.com/homedetails/[^\s<>\"'\\)]+", re.I
)
ZID_FROM_URL_RE = re.compile(r"/(\d{6,12})_zpid/?")
PRICE_RE = re.compile(r"\$([\d,]{3,})")
FACTS_RE = re.compile(
    r"(\d+)\s*(?:bds?|beds?|bdrs?)"
    r"\s*[\|·,]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:bas?|baths?)"
    r"\s*[\|·,]\s*"
    r"([\d,]+)\s*(?:sqft|sq\.?\s*ft)",
    re.I,
)
DOM_RE = re.compile(r"(\d+)\s*days?\s*(?:on\s+zillow|ago)", re.I)
JUST_LISTED_RE = re.compile(r"just\s+listed", re.I)


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _HtmlStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_tags = {"style", "script", "head"}
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._skip_tags:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _strip_html(text: str) -> str:
    s = _HtmlStripper()
    s.feed(text)
    return s.get_text()


# ---------------------------------------------------------------------------
# gog helpers
# ---------------------------------------------------------------------------

def gog_search(window: str) -> list[dict]:
    """Return list of thread metadata dicts for Zillow emails in the window."""
    cmd = [
        GOG, "-j", "--results-only",
        "gmail", "search",
        f"from:zillow.com newer_than:{window}",
        "--all",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        if not result.stdout.strip():
            # Empty result set returns 0 normally; non-zero likely auth error
            raise RuntimeError(
                f"gog search exited {result.returncode}: {result.stderr.strip()[:200]}"
            )
    raw = result.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def gog_get(thread_id: str) -> dict:
    """Fetch full message body for a thread ID."""
    cmd = [GOG, "-j", "gmail", "get", thread_id, "--format", "full"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    result.check_returncode()
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Email body parser
# ---------------------------------------------------------------------------

def parse_body(body: str) -> list[dict]:
    """Extract listing records from a Zillow digest email plain-text body.

    Returns a list of dicts. Each dict contains all extractable fields;
    fields that couldn't be parsed are None.
    """
    # Strip HTML if needed
    if re.search(r"<(?:html|div|table|td)\b", body, re.I):
        body = _strip_html(body)

    listings: list[dict] = []
    seen_zids: set[str] = set()

    for url_match in ZILLOW_URL_RE.finditer(body):
        url = url_match.group(0).rstrip(".,;)")
        zid_match = ZID_FROM_URL_RE.search(url)
        if not zid_match:
            continue
        zid = zid_match.group(1)
        if zid in seen_zids:
            continue
        seen_zids.add(zid)

        # Context window: up to 600 chars before the URL
        url_start = url_match.start()
        ctx_start = max(0, url_start - 600)
        context = body[ctx_start:url_start]

        # Price
        price: int | None = None
        pm = PRICE_RE.search(context)
        if pm:
            try:
                price = int(pm.group(1).replace(",", ""))
            except ValueError:
                pass

        # Beds / baths / sqft
        beds = baths = sqft = None
        fm = FACTS_RE.search(context)
        if fm:
            try:
                beds = int(fm.group(1))
                baths = float(fm.group(2))
                sqft = int(fm.group(3).replace(",", ""))
            except ValueError:
                pass

        # Days on market
        dom: int | None = None
        if JUST_LISTED_RE.search(context):
            dom = 1
        else:
            dm = DOM_RE.search(context)
            if dm:
                try:
                    dom = int(dm.group(1))
                except ValueError:
                    pass

        # Address: first line matching "\d+ <word>" pattern (house number + street)
        address: str | None = None
        for ln in context.split("\n"):
            ln = ln.strip()
            if re.match(r"\d{1,6}\s+[A-Za-z]", ln) and "$" not in ln and "zillow" not in ln.lower():
                address = ln
                break

        # Subdivision: non-empty line after the facts line, before the URL
        subdivision: str | None = None
        if fm:
            after_facts = context[fm.end():]
            for ln in after_facts.split("\n"):
                ln = ln.strip()
                if (ln and len(ln) < 60
                        and not re.search(r"\$|zillow|\d{5}|bd|ba|sqft", ln, re.I)
                        and re.search(r"[A-Za-z]{3}", ln)):
                    subdivision = ln
                    break

        listings.append({
            "zillow_id": zid,
            "url": url.split("?")[0],  # strip tracking params
            "address": address or "(unknown)",
            "subdivision": subdivision,
            "list_price": price,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "days_on_market": dom,
        })

    return listings


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def upsert_listing(conn: sqlite3.Connection, row: dict, email_id: str,
                   received_iso: str) -> str:
    """Insert or update a listing row. Returns 'new' | 'changed' | 'unchanged'."""
    cur = conn.execute(
        "SELECT list_price FROM home_scout_listings WHERE zillow_id = ?",
        (row["zillow_id"],),
    )
    existing = cur.fetchone()
    now = received_iso

    if existing is None:
        conn.execute(
            """INSERT INTO home_scout_listings
               (zillow_id, url, address, subdivision, list_price,
                beds, baths, sqft, days_on_market,
                first_seen_at, last_seen_at, last_email_id, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["zillow_id"], row["url"], row["address"], row.get("subdivision"),
                row.get("list_price"), row.get("beds"), row.get("baths"),
                row.get("sqft"), row.get("days_on_market"),
                now, now, email_id, json.dumps(row),
            ),
        )
        return "new"

    old_price = existing[0]
    new_price = row.get("list_price")
    if new_price is not None and old_price is not None and new_price != old_price:
        conn.execute(
            """UPDATE home_scout_listings
               SET last_price = ?, list_price = ?, price_changed_at = ?,
                   last_seen_at = ?, last_email_id = ?,
                   days_on_market = ?, raw_json = ?
             WHERE zillow_id = ?""",
            (
                old_price, new_price, now,
                now, email_id,
                row.get("days_on_market"), json.dumps(row),
                row["zillow_id"],
            ),
        )
        return "changed"

    conn.execute(
        "UPDATE home_scout_listings SET last_seen_at = ?, last_email_id = ?, days_on_market = ? WHERE zillow_id = ?",
        (now, email_id, row.get("days_on_market"), row["zillow_id"]),
    )
    return "unchanged"


def open_db(dry_run: bool) -> sqlite3.Connection:
    if dry_run:
        conn = sqlite3.connect(":memory:")
        if os.path.isfile(MIGRATION_SQL):
            with open(MIGRATION_SQL) as f:
                conn.executescript(f.read())
        else:
            # Minimal schema for dry-run without the migration file
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS home_scout_listings (
                  zillow_id TEXT PRIMARY KEY, url TEXT NOT NULL, address TEXT NOT NULL,
                  subdivision TEXT, list_price INTEGER, last_price INTEGER,
                  price_changed_at TEXT, sqft INTEGER, lot_sqft INTEGER,
                  beds INTEGER, baths REAL, year_built INTEGER, hoa_monthly INTEGER,
                  days_on_market INTEGER, listing_status TEXT, score REAL, tier INTEGER,
                  rejected_reason TEXT, first_seen_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL, last_email_id TEXT, raw_json TEXT
                );
                CREATE TABLE IF NOT EXISTS home_scout_seen_emails (
                  gmail_message_id TEXT PRIMARY KEY, received_at TEXT NOT NULL,
                  subject TEXT, listing_count INTEGER,
                  processed_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
        return conn
    return sqlite3.connect(DB_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="2d",
                    help="gog newer_than window (default: 2d)")
    ap.add_argument("--dry-run", action="store_true",
                    help="use in-memory DB; print parsed listings but do not write")
    args = ap.parse_args()

    try:
        threads = gog_search(args.since)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not threads:
        json.dump({"new": [], "changed": [], "processed_emails": 0}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    conn = open_db(args.dry_run)
    new_ids: list[str] = []
    changed_ids: list[str] = []
    processed = 0

    for thread in threads:
        tid = thread.get("id") or thread.get("threadId") or ""
        if not tid:
            continue

        try:
            msg = gog_get(tid)
        except subprocess.CalledProcessError as exc:
            print(f"gog get {tid} failed: {exc}", file=sys.stderr)
            continue
        except json.JSONDecodeError as exc:
            print(f"gog get {tid} returned invalid JSON: {exc}", file=sys.stderr)
            continue

        body = (msg.get("body") or "").strip()
        if not body or "zillow.com" not in body.lower():
            continue

        # Skip already-processed emails
        already = conn.execute(
            "SELECT 1 FROM home_scout_seen_emails WHERE gmail_message_id = ?", (tid,)
        ).fetchone()
        if already:
            continue

        headers = msg.get("headers") or {}
        received_iso = headers.get("date") or datetime.now(timezone.utc).isoformat()
        subject = headers.get("subject") or ""

        rows = parse_body(body)
        for row in rows:
            result = upsert_listing(conn, row, tid, received_iso)
            if result == "new":
                new_ids.append(row["zillow_id"])
            elif result == "changed":
                changed_ids.append(row["zillow_id"])

        conn.execute(
            """INSERT INTO home_scout_seen_emails
               (gmail_message_id, received_at, subject, listing_count, processed_at)
               VALUES (?,?,?,?,?)""",
            (tid, received_iso, subject, len(rows),
             datetime.now(timezone.utc).isoformat()),
        )
        processed += 1

    conn.commit()

    result = {"new": new_ids, "changed": changed_ids, "processed_emails": processed}
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
