"""AbuseIPDB reputation lookups and strict, delayed abuse reports.

Only external, public source addresses are sent. Reports carry fixed comments:
no usernames, hostnames, paths or other attacker-controlled text.
"""

from datetime import datetime, timezone
import json
import logging
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from events import public


LOG = logging.getLogger("attacks")
API = "https://api.abuseipdb.com/api/v2"
FRESH = 86400
DAILY_CAP = 900  # The free plan allows 1,000 checks and 1,000 reports a day.
REPORT_DELAY = 300  # Let other sources catch up, so a later successful login can still cancel a report.
REPORT_EVERY = 86400
WINDOW = 3600
# kind: (events within WINDOW, AbuseIPDB categories, public comment)
RULES = {
    "ssh_failure": (3, (18, 22), "Repeated failed SSH authentication against a key-only server."),
    # Host and Forgejo SSH only accept keys for known accounts, so a username that does not exist or may not
    # log in is a credential guess on its first try; failures for real accounts keep the threshold above.
    "ssh_guess": (1, (18, 22), "SSH login attempt with a guessed username against a key-only server."),
    "auth_failure": (5, (18, 21), "Repeated failed sign-in attempts against a single sign-on portal."),
    "http_probe": (2, (21,), "Requests for exploit, credential-file or administration paths on sites that do not serve them."),
    # Nothing legitimate is served on port 22; a sign-in within REPORT_DELAY (someone who forgot the real SSH port)
    # still cancels the report. Game-port scans are not reported: server-status sites probe those ports.
    "endlessh_open": (1, (14, 22), "Unsolicited SSH connection to a port that offers no SSH service."),
}
GUESSED = frozenset({"Username does not exist", "Username does not exist; authentication rejected",
                     "Account is not permitted to log in over SSH"})
# A source that has signed in successfully is trusted, and is never reported.
TRUSTED = frozenset({"ssh_accepted", "ssh_accepted_unknown", "plex_client"})
TRUST_FOR = 30 * 86400
# Filter grades; the first three partition checked addresses and match the badge colours.
GRADES = ("high", "medium", "clean", "unchecked", "reported")


def grade(score):
    return "high" if score >= 50 else "medium" if score > 0 else "clean"


class AbuseIPDB:
    def __init__(self, path, key, reporting="strict", clock=time.time, opener=None):
        self.key, self.clock = key or "", clock
        self.reporting = reporting if reporting in ("strict", "off") else "off"
        self.opener = opener or build_opener(ProxyHandler({}))
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS reputation (ip TEXT PRIMARY KEY, body TEXT NOT NULL, checked REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS pending (ip TEXT PRIMARY KEY, queued REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS hits (ip TEXT, kind TEXT, at REAL);
            CREATE INDEX IF NOT EXISTS hits_ip ON hits(ip, kind, at);
            CREATE TABLE IF NOT EXISTS trusted (ip TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS queue (ip TEXT PRIMARY KEY, kind TEXT NOT NULL, at REAL NOT NULL, queued REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS reported (ip TEXT PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (kind TEXT, at REAL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.error, self.retry_at = None, 0

    @property
    def enabled(self):
        return bool(self.key)

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def want(self, ip):
        """Queue a lookup unless a fresh answer is cached. Safe to call often."""
        if not self.enabled or not public(ip):
            return
        with self.lock, self.db:
            row = self.db.execute("SELECT checked FROM reputation WHERE ip=?", (ip,)).fetchone()
            if not row or row[0] < self.clock() - FRESH:
                self.db.execute("INSERT OR IGNORE INTO pending VALUES (?,?)", (ip, self.clock()))

    def observe(self, item):
        """Called once per newly collected event."""
        ip = item["ip"]
        if not self.enabled or item.get("origin") != "external" or not public(ip):
            return
        self.want(ip)
        kind, at = item["kind"], float(item["timestamp"])
        if kind == "ssh_failure" and item.get("rejectionReason") in GUESSED:
            kind = "ssh_guess"
        with self.lock, self.db:
            if kind in TRUSTED:
                self.db.execute("INSERT INTO trusted VALUES (?,?) ON CONFLICT(ip) DO UPDATE SET at=max(at, excluded.at)", (ip, at))
                self.db.execute("DELETE FROM queue WHERE ip=?", (ip,))
                return
            if self.reporting != "strict" or kind not in RULES or at < self.clock() - FRESH:
                return
            self.db.execute("INSERT INTO hits VALUES (?,?,?)", (ip, kind, at))
            self.db.execute("DELETE FROM hits WHERE at<?", (self.clock() - FRESH - WINDOW,))
            count = self.db.execute("SELECT count(*) FROM hits WHERE ip=? AND kind=? AND at>?",
                                    (ip, kind, at - WINDOW)).fetchone()[0]
            if count >= RULES[kind][0] and not self.skip(ip):
                self.db.execute("INSERT OR IGNORE INTO queue VALUES (?,?,?,?)", (ip, kind, at, self.clock()))

    def skip(self, ip):
        now = self.clock()
        if self.db.execute("SELECT 1 FROM trusted WHERE ip=? AND at>?", (ip, now - TRUST_FOR)).fetchone():
            return True
        if self.db.execute("SELECT 1 FROM reported WHERE ip=? AND at>?", (ip, now - REPORT_EVERY)).fetchone():
            return True
        row = self.db.execute("SELECT body FROM reputation WHERE ip=?", (ip,)).fetchone()
        return bool(row and json.loads(row[0]).get("whitelisted"))

    def lookup(self, ips):
        """Cached answers for these addresses; missing ones are queued."""
        result = {}
        for ip in ips:
            self.want(ip)
        with self.lock:
            for ip in ips:
                row = self.db.execute("SELECT body FROM reputation WHERE ip=?", (ip,)).fetchone()
                sent = self.db.execute("SELECT at FROM reported WHERE ip=?", (ip,)).fetchone()
                if row or sent:
                    result[ip] = {**(json.loads(row[0]) if row else {}), **({"reportedAt": sent[0]} if sent else {})}
        return result

    def grades(self, since=0):
        """Addresses by grade, for filtering. Any event after `since` had its source checked
        no earlier than a day before it, so older answers cannot match those events."""
        result = {"high": [], "medium": [], "clean": []}
        with self.lock:
            for ip, score in self.db.execute(
                    "SELECT ip, coalesce(json_extract(body, '$.score'), 0) FROM reputation WHERE checked>?",
                    (since - FRESH,)):
                result[grade(score)].append(ip)
            result["reported"] = [ip for (ip,) in self.db.execute("SELECT ip FROM reported")]
        return result

    def budget(self, kind):
        with self.lock, self.db:
            self.db.execute("DELETE FROM calls WHERE at<?", (self.clock() - 86400,))
            used = self.db.execute("SELECT count(*) FROM calls WHERE kind=?", (kind,)).fetchone()[0]
            if used >= DAILY_CAP or self.meta(f"paused:{kind}", 0) > self.clock():
                return False
            self.db.execute("INSERT INTO calls VALUES (?,?)", (kind, self.clock()))
            return True

    def call(self, kind, path, params=None, form=None):
        url = API + path + ("?" + urlencode(params) if params else "")
        data = urlencode(form).encode() if form else None
        request = Request(url, data=data, headers={"Key": self.key, "Accept": "application/json",
                                                   "User-Agent": "homeserver-attacks/1.0"})
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, json.loads(response.read(256 * 1024) or b"{}")
        except HTTPError as error:
            if error.code == 429:
                wait = error.headers.get("Retry-After", "")
                wait = int(wait) if wait.isdigit() else 3600
                with self.lock, self.db:
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                                    (f"paused:{kind}", json.dumps(self.clock() + min(wait, 86400))))
            with error:
                try:
                    body = json.loads(error.read(64 * 1024) or b"{}")
                except ValueError:
                    body = {}
            return error.code, body

    def check_one(self):
        with self.lock:
            row = self.db.execute("SELECT ip FROM pending ORDER BY queued LIMIT 1").fetchone()
        if not row or not self.budget("check"):
            return False
        ip = row[0]
        status, body = self.call("check", "/check", {"ipAddress": ip, "maxAgeInDays": 90})
        if status != 200 or not isinstance(body.get("data"), dict):
            if 400 <= status < 500 and status != 429:
                with self.lock, self.db:
                    self.db.execute("DELETE FROM pending WHERE ip=?", (ip,))
            raise OSError(f"AbuseIPDB check failed (HTTP {status})")
        data = body["data"]
        value = {"score": int(data.get("abuseConfidenceScore") or 0), "reports": int(data.get("totalReports") or 0),
                 "users": int(data.get("numDistinctUsers") or 0), "lastReportedAt": data.get("lastReportedAt"),
                 "usage": data.get("usageType"), "tor": bool(data.get("isTor")),
                 "whitelisted": bool(data.get("isWhitelisted")), "checkedAt": self.clock()}
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO reputation VALUES (?,?,?)", (ip, json.dumps(value), self.clock()))
            self.db.execute("DELETE FROM pending WHERE ip=?", (ip,))
        return True

    def report_one(self):
        if self.reporting != "strict":
            return False
        with self.lock, self.db:
            row = self.db.execute("SELECT ip, kind, at FROM queue WHERE queued<=? ORDER BY queued LIMIT 1",
                                  (self.clock() - REPORT_DELAY,)).fetchone()
            if not row:
                return False
            ip, kind, at = row
            if self.skip(ip) or kind not in RULES:
                self.db.execute("DELETE FROM queue WHERE ip=?", (ip,))
                return True
        if not self.budget("report"):
            return False
        _, categories, comment = RULES[kind]
        stamp = datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds")
        status, _ = self.call("report", "/report", form={
            "ip": ip, "categories": ",".join(map(str, categories)), "comment": comment, "timestamp": stamp})
        # 422 here means AbuseIPDB already has this address from us within 15 minutes.
        if status not in (200, 422):
            if 400 <= status < 500 and status != 429:
                with self.lock, self.db:
                    self.db.execute("DELETE FROM queue WHERE ip=?", (ip,))
            raise OSError(f"AbuseIPDB report failed (HTTP {status})")
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO reported VALUES (?,?,?)", (ip, self.clock(), kind))
            self.db.execute("DELETE FROM queue WHERE ip=?", (ip,))
        return True

    def work(self):
        """One bounded step; returns True when there may be more to do."""
        if not self.enabled or self.clock() < self.retry_at:
            return False
        try:
            busy = self.check_one()
            busy = self.report_one() or busy
            self.error = None
            return busy
        except (OSError, ValueError, sqlite3.Error) as error:
            message = str(error) if isinstance(error, OSError) and str(error).startswith("AbuseIPDB") else type(error).__name__
            if message != self.error:
                LOG.error("abuseipdb: %s", message)
            self.error, self.retry_at = message, self.clock() + 60
            return False

    def status(self):
        if not self.enabled:
            return {"state": "disabled", "message": "No AbuseIPDB API key configured; reputation lookups and reports are off"}
        with self.lock:
            now = self.clock()
            checks = self.db.execute("SELECT count(*) FROM calls WHERE kind='check' AND at>?", (now - 86400,)).fetchone()[0]
            reports = self.db.execute("SELECT count(*) FROM reported WHERE at>?", (now - 86400,)).fetchone()[0]
            pending = self.db.execute("SELECT count(*) FROM pending").fetchone()[0]
            paused = max(self.meta("paused:check", 0), self.meta("paused:report", 0))
        mode = "strict reporting" if self.reporting == "strict" else "reporting off"
        message = f"{checks} lookups and {reports} reports in 24 h ({mode}); {pending} lookups queued"
        if paused > now:
            return {"state": "error", "message": f"Rate limited by AbuseIPDB; {message}"}
        if self.error:
            return {"state": "error", "message": f"{self.error}; {message}"}
        return {"state": "ready", "message": message}
