"""Private normalizer: existing Loki + NPM files -> durable outbox -> Loki/Prometheus."""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time

import maxminddb

from common import Client, UpstreamError
from events import KINDS, PARSERS, home_networks, identity, parse_flow, parse_npm, public, text, traffic_origin
from networks import Networks
from ssh_keys import SSHKeys


LOG = logging.getLogger("attacks")
SELECTORS = {
    "connections": '{security_source="connections"} |= "attacks-flow-v1"',
    "endlessh": '{container="endlessh"} |~ "(^| )(ACCEPT|CLOSE) host=|Listening on"',
    "authelia": '{container="authelia"} |= "Unsuccessful" |= "authentication attempt"',
    "ssh": '{security_source="ssh"} |~ "Invalid user |Failed |Accepted .* for |maximum authentication attempts|Connection (closed|reset) by|Disconnected from|banner exchange:|kex_exchange_identification:"',
    "fail2ban": '{security_source="fail2ban"} |= " Ban "',
}
NANO = 1_000_000_000


def window(client, query, start, end, budget=None):
    budget = [128] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise UpstreamError("Log window exceeds query budget; checkpoint retained")
    rows = client.query(query, start, end)
    if len(rows) < 1000:
        return rows
    if start >= end:
        raise UpstreamError("A single log timestamp exceeds the page limit; refusing to skip events")
    middle = (start + end) // 2
    return window(client, query, start, middle, budget) + window(client, query, middle + 1, end, budget)


class Store:
    def __init__(self, path, clock=time.time):
        self.lock = threading.RLock()
        self.clock = clock
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS seen_at ON seen(at);
            CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, ns INTEGER, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS counters
              (kind TEXT, category TEXT, country TEXT, origin TEXT, count INTEGER, seconds REAL,
               PRIMARY KEY(kind,category,country,origin));
            CREATE TABLE IF NOT EXISTS trapped
              (ip TEXT, port INTEGER, since REAL, changed REAL, PRIMARY KEY(ip,port));
        """)
        # Old counters cannot be split by IP. Preserve them, explicitly unclassified.
        if "origin" not in {row[1] for row in self.db.execute("PRAGMA table_info(counters)")}:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("ALTER TABLE counters RENAME TO legacy_counters")
                self.db.execute("""CREATE TABLE counters
                    (kind TEXT, category TEXT, country TEXT, origin TEXT, count INTEGER, seconds REAL,
                     PRIMARY KEY(kind,category,country,origin))""")
                self.db.execute("INSERT INTO counters SELECT kind,category,country,'legacy',count,seconds FROM legacy_counters")
                self.db.execute("DROP TABLE legacy_counters")
        if self.get("started") is None:
            self.set("started", clock())
        if self.get("origins_started") is None:
            self.set("origins_started", clock())

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def enqueue(self, item, source, key):
        with self.lock, self.db:
            observed = max(self.clock(), self.get("last_observed", 0) + .000001,
                           self.get("published", {}).get("through", 0) + .000001)
            item = {**item, "id": identity(source, key), "source": source, "observedAt": observed,
                    "origin": item.get("origin", traffic_origin(item["ip"]))}
            country = item.get("countryCode", "ZZ")
            if self.db.execute("SELECT 1 FROM seen WHERE id=?", (item["id"],)).fetchone():
                return False
            if self.db.execute("SELECT count(*) FROM outbox").fetchone()[0] >= 50000:
                raise UpstreamError("Outbox full; source checkpoint has not advanced")
            self.db.execute("INSERT INTO seen VALUES (?,?)", (item["id"], self.clock()))
            self.db.execute("INSERT INTO outbox VALUES (?,?,?)",
                            (item["id"], int(observed * NANO), json.dumps(item, allow_nan=False)))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('last_observed',?)", (json.dumps(observed),))
            self.db.execute("""
                INSERT INTO counters VALUES (?,?,?,?,1,?)
                ON CONFLICT(kind,category,country,origin) DO UPDATE SET
                    count=count+1, seconds=seconds+excluded.seconds
            """, (item["kind"], item["type"], country, item["origin"], item.get("duration", 0)))
            if item["kind"] == "endlessh_close" or (item["origin"] == "external" and item["kind"] == "endlessh_open"):
                self.track(item)
        return True

    def track(self, item):
        timestamp = item["timestamp"]
        if timestamp < max(self.get("origins_started"), self.get("endlessh_restart", 0)):
            return
        self.db.execute("""INSERT INTO trapped VALUES (?,?,?,?)
            ON CONFLICT(ip,port) DO UPDATE SET since=excluded.since, changed=excluded.changed
            WHERE excluded.changed > changed OR (excluded.changed = changed AND excluded.since IS NULL)""",
                        (item["ip"], item["sourcePort"],
                         timestamp if item["kind"] == "endlessh_open" else None, timestamp))
        if self.db.execute("SELECT count(*) FROM trapped WHERE since IS NOT NULL").fetchone()[0] > 4096:
            raise UpstreamError("Endlessh active-session limit exceeded; checkpoint retained")
        self.db.execute("DELETE FROM trapped WHERE since IS NULL AND changed<?", (self.clock() - 172800,))

    def restart(self, timestamp):
        with self.lock, self.db:
            if timestamp > self.get("endlessh_restart", 0):
                self.db.execute("DELETE FROM trapped WHERE changed<=?", (timestamp,))
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('endlessh_restart',?)", (json.dumps(timestamp),))

    def publish(self):
        # Publish the open set only when all preceding closes are visible in Loki.
        # The API bounds its completed-duration query by the same watermark.
        if self.db.execute("SELECT 1 FROM outbox LIMIT 1").fetchone():
            return
        sessions = [row[0] for row in self.db.execute("SELECT since FROM trapped WHERE since IS NOT NULL")]
        value = {"through": max(self.clock(), self.get("last_observed", 0)), "sessions": sessions}
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('published',?)", (json.dumps(value),))

    def trapping(self):
        with self.lock:
            published = self.get("published", {"through": 0, "sessions": []})
        now = self.clock()
        return {"connections": len(published["sessions"]),
                "seconds": sum(max(0, now - since) for since in published["sessions"]),
                "asOf": now, "through": published["through"], "since": self.get("origins_started")}

    def flush(self, client):
        with self.lock:
            rows = self.db.execute("SELECT id,ns,body FROM outbox ORDER BY ns,id LIMIT 1000").fetchall()
        if not rows:
            with self.lock, self.db:
                self.publish()
            return
        streams = {}
        for _, ns, body in rows:
            item = json.loads(body)
            key = (item["source"], item["type"], item["kind"], item.get("origin", "legacy"))
            streams.setdefault(key, []).append([str(ns), body])
        client.request("/loki/api/v1/push", payload={"streams": [
            {"stream": {"job": "attacks", "source": key[0], "type": key[1], "kind": key[2], "origin": key[3]},
             "values": values} for key, values in streams.items()
        ]})
        # A crash after delivery may replay IDs. The UI deduplicates those IDs.
        with self.lock, self.db:
            self.db.executemany("DELETE FROM outbox WHERE id=?", ((row[0],) for row in rows))
            self.db.execute("DELETE FROM seen WHERE at<? AND id NOT IN (SELECT id FROM outbox)",
                            (self.clock() - 172800,))
            self.publish()

    def metrics(self):
        with self.lock:
            rows = self.db.execute("SELECT kind,category,country,origin,count,seconds FROM counters").fetchall()
            queued = self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]
            active = [row[0] for row in self.db.execute("SELECT since FROM trapped WHERE since IS NOT NULL")]
        result = ["# TYPE attacks_events_total counter", "# TYPE attacks_endlessh_seconds_total counter",
                  f"attacks_outbox_events {queued}", f"attacks_started_seconds {self.get('started')}",
                  f"attacks_origins_started_seconds {self.get('origins_started')}",
                  "# TYPE attacks_endlessh_trapped_connections gauge",
                  f"attacks_endlessh_trapped_connections {len(active)}",
                  "# TYPE attacks_endlessh_trapped_now_seconds gauge",
                  f"attacks_endlessh_trapped_now_seconds {sum(max(0, self.clock() - since) for since in active)}"]
        present = {(row[0], row[3]) for row in rows}
        for kind, (category, _, _) in KINDS.items():
            for origin in ("own", "external"):
                if (kind, origin) not in present:
                    rows.append((kind, category, "ZZ", origin, 0, 0))
        for kind, category, country, origin, count, seconds in rows:
            labels = f'kind="{kind}",type="{category}",country="{country}",origin="{origin}"'
            result.append(f"attacks_events_total{{{labels}}} {count}")
            if kind == "endlessh_close":
                result.append(f'attacks_endlessh_seconds_total{{country="{country}",origin="{origin}"}} {seconds}')
        return "\n".join(result) + "\n"


class Geo:
    def __init__(self, path):
        self.path, self.reader, self.modified = Path(path), None, None
        self.status = {"state": "unavailable", "message": "Local GeoIP database not installed"}

    def reload(self):
        try:
            modified = self.path.stat().st_mtime
            if modified != self.modified:
                reader = maxminddb.open_database(str(self.path))
                if self.reader:
                    self.reader.close()
                self.reader, self.modified = reader, modified
            built = self.reader.metadata().build_epoch
            stale = time.time() - built > 62 * 86400
            self.status = {"state": "stale" if stale else "ready",
                           "message": "Local GeoIP database is over 62 days old" if stale else "Offline IP geolocation",
                           "updatedAt": built}
        except (OSError, ValueError, maxminddb.InvalidDatabaseError) as error:
            if self.reader:
                self.reader.close()
            self.reader, self.modified = None, None
            self.status = {"state": "unavailable", "message": f"GeoIP unavailable ({type(error).__name__})"}
            LOG.warning(self.status["message"])

    def enrich(self, item):
        if not public(item["ip"]):
            return {**item, "location": "Private / reserved network"}
        if not self.reader:
            return {**item, "location": "Location unavailable"}
        try:
            record = self.reader.get(item["ip"])
        except (ValueError, maxminddb.InvalidDatabaseError) as error:
            self.reader.close()
            self.reader, self.modified = None, None
            self.status = {"state": "unavailable", "message": f"GeoIP lookup failed ({type(error).__name__})"}
            LOG.error(self.status["message"])
            return {**item, "location": "Location unavailable"}
        if not record:
            return {**item, "location": "Location unknown"}
        country = record.get("country", {}).get("iso_code", "ZZ")
        if len(country) != 2 or any(letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for letter in country):
            country = "ZZ"
        place = record.get("city", {}).get("names", {}).get("en")
        nation = record.get("country", {}).get("names", {}).get("en", country)
        result = {**item, "countryCode": country, "location": text(", ".join(filter(None, (place, nation))))}
        location = record.get("location", {})
        lat, lon = location.get("latitude"), location.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180:
            result.update(latitude=lat, longitude=lon)
        return result


class Collector:
    def __init__(self, store, loki, geo, npm, keys=None, networks=None):
        self.store, self.loki, self.geo, self.npm = store, loki, geo, Path(npm)
        self.status = {name: {"state": "waiting"} for name in (*SELECTORS, "npm", "delivery")}
        self.last_tick = 0
        self.last_geo = 0
        self.capture = store.get("capture", {})
        self.keys = keys or SSHKeys(os.environ.get("SSH_KEYS_PATH", "/keys/ssh-keys.json"))
        self.networks = networks or Networks(os.environ.get("NETWORK_DATA_DIR", "/geo"))

    def enrich(self, item):
        own = self.own_traffic()
        if own["state"] != "ready":
            raise UpstreamError(own["message"])
        return {**self.keys.annotate(self.networks.enrich(self.geo.enrich(item))),
                "origin": traffic_origin(item["ip"], own["networks"])}

    def own_traffic(self):
        ready = "ownNetworks" in self.capture and time.time() - self.capture.get("timestamp", 0) <= 90
        return {"state": "ready" if ready else "error",
                "message": "LAN, tailnet and home IPv6 traffic excluded from attack totals" if ready
                else "Fresh host network metadata unavailable; source checkpoints retained",
                "networks": home_networks(self.capture.get("ownNetworks", []))}

    def refresh_capture(self, now):
        query = SELECTORS["connections"] + ' |= "heartbeat"'
        for ns, line, _ in self.loki.query(query, int((now - 90) * NANO), int((now - 3) * NANO)):
            item = parse_flow(line, ns / NANO)
            if item and item.get("heartbeat") and item["timestamp"] >= self.capture.get("timestamp", 0):
                self.capture = item
                self.store.set("capture", item)

    def raw(self, source, now):
        cursor = self.store.get("cursor:" + source, int((now - 600) * NANO))
        end = min(cursor + 60 * NANO, int((now - 3) * NANO))
        if cursor < (now - 29 * 86400) * NANO:
            raise UpstreamError("Checkpoint predates Loki retention; explicit operator recovery required")
        start = max(0, cursor - 120 * NANO)
        counts = Counter()
        for ns, line, labels in window(self.loki, SELECTORS[source], start, end):
            item = PARSERS[source](line, ns / NANO)
            if not item:
                continue
            if item.get("heartbeat"):
                if item["timestamp"] >= self.capture.get("timestamp", 0):
                    self.capture = item
                    self.store.set("capture", item)
                continue
            if item.get("restart"):
                self.store.restart(item["timestamp"])
                continue
            key = json.dumps([ns, labels, line], sort_keys=True)
            counts[key] += 1
            self.store.enqueue(self.enrich(item), source, f"{key}:{counts[key]}")
        self.store.set("cursor:" + source, end)
        return {"lagSeconds": max(0, now - end / NANO)}

    def files(self, now):
        if not self.npm.is_dir():
            raise UpstreamError("NPM log directory is unavailable")
        paths = sorted(self.npm.glob("*_access.log*"))
        paths = [path for path in paths if not path.name.endswith(".gz") and not path.is_symlink()]
        if not paths:
            raise UpstreamError("No readable NPM access logs found")
        if len(paths) > 1024:
            raise UpstreamError("Unexpected number of NPM log files")
        positions = self.store.get("npm_positions", {})
        bootstrap = self.store.get("started") - 600
        skipped = self.store.get("npm_bootstrap_bytes", 0)
        for path in paths:
            with path.open("rb") as stream:
                stat = os.fstat(stream.fileno())
                key = f"{stat.st_dev}:{stat.st_ino}"
                saved = positions.get(key)
                if saved is None:
                    if stat.st_mtime < bootstrap:
                        continue
                    offset = max(0, stat.st_size - 1024 * 1024)
                    skipped += offset
                else:
                    offset = saved["offset"] if saved["offset"] <= stat.st_size else 0
                stream.seek(offset)
                if saved is None and offset:
                    stream.readline(65537)
                for _ in range(5000):
                    offset = stream.tell()
                    line = stream.readline(65537)
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        stream.seek(offset)
                        if len(line) > 65536:
                            raise UpstreamError("NPM line exceeds limit; checkpoint retained")
                        break
                    item = parse_npm(line.decode("utf-8", errors="replace"))
                    if item and item["timestamp"] >= bootstrap:
                        self.store.enqueue(self.enrich(item), "npm", f"{key}:{offset}:{line!r}")
                positions[key] = {"offset": stream.tell(), "seen": now}
        positions = {key: value for key, value in positions.items() if value["seen"] >= now - 7 * 86400}
        self.store.set("npm_positions", positions)
        self.store.set("npm_bootstrap_bytes", skipped)
        return {"bootstrapSkippedBytes": skipped}

    def tick(self):
        now = time.time()
        try:
            self.refresh_capture(now)
        except (UpstreamError, OSError, ValueError) as error:
            LOG.error("Host network metadata refresh failed: %s", type(error).__name__)
        if now - self.last_geo >= 60:
            self.geo.reload()
            self.keys.reload()
            self.networks.reload()
            self.last_geo = now
        for name in (*SELECTORS, "npm", "delivery"):
            try:
                if name in SELECTORS:
                    detail = self.raw(name, now)
                elif name == "npm":
                    detail = self.files(now)
                else:
                    self.store.flush(self.loki)
                    detail = {}
                self.status[name] = {"state": "ready", "lastSuccess": time.time(), **(detail or {})}
            except (UpstreamError, OSError, ValueError, sqlite3.Error) as error:
                previous = self.status[name]
                message = str(error) if isinstance(error, UpstreamError) else type(error).__name__
                if previous.get("message") != message:
                    LOG.error("%s: %s", name, message)
                self.status[name] = {**previous, "state": "error", "message": message}
        self.last_tick = time.time()

    def snapshot(self):
        sources = {key: dict(value) for key, value in self.status.items()}
        if time.time() - self.capture.get("timestamp", 0) > 90:
            sources["connections"] = {**sources["connections"], "state": "error",
                                      "message": "Host capture heartbeat missing or stale"}
        own = self.own_traffic()
        trapping = {**self.store.trapping(), "available": own["state"] == "ready" and all(
            sources[name]["state"] == "ready" and sources[name].get("lagSeconds", 0) <= 90
            and time.time() - sources[name].get("lastSuccess", 0) <= 90 for name in ("endlessh", "delivery"))}
        return {"sources": sources, "geo": self.geo.status, "sshKeys": self.keys.status, "networks": self.networks.status,
                "ownTraffic": own, "trapping": trapping,
                "lastTick": self.last_tick, "capture": self.capture,
                "startedAt": self.store.get("started")}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    state = Path(os.environ.get("STATE_DIR", "/state"))
    state.mkdir(parents=True, exist_ok=True)
    store = Store(state / "collector.sqlite")
    collector = Collector(store, Client(os.environ.get("LOKI_URL", "http://loki:3100")),
                          Geo(os.environ.get("GEOIP_PATH", "/geo/GeoIP.mmdb")),
                          os.environ.get("NPM_LOG_DIR", "/npm"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                status = collector.snapshot()
                body = store.metrics()
                for name, value in status["sources"].items():
                    body += f'attacks_source_ready{{source="{name}"}} {int(value["state"] == "ready")}\n'
                body += f'attacks_source_ready{{source="own_traffic"}} {int(status["ownTraffic"]["state"] == "ready")}\n'
                body += f'attacks_capture_suppressed_total {collector.capture.get("suppressed", 0)}\n'
                content_type = "text/plain; version=0.0.4"
                code = 200
            elif self.path in ("/status", "/healthz"):
                body = json.dumps(collector.snapshot())
                content_type = "application/json"
                code = 200 if time.time() - collector.last_tick < 90 else 503
            else:
                self.send_error(404)
                return
            raw = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    http = ThreadingHTTPServer(("0.0.0.0", 9108), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    while True:
        collector.tick()
        time.sleep(2)


if __name__ == "__main__":
    main()
