"""Read-only, same-origin UI API. No arbitrary LogQL/PromQL or upstream URLs."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import math
import mimetypes
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

from common import UpstreamError, clients
from events import TYPES, VERDICTS


ROOT = Path(__file__).parent / "static"
MAP_ASSETS = {path.name for path in ROOT.glob("world-*.json")
              if re.fullmatch(r"world-(110m|50m|10m)-[0-9a-f]{12}\.json", path.name)}
STATIC = {"index.html", "styles.css", "app.mjs", "model.mjs", "map-view.mjs", "pwa.mjs", "sw.js",
          "atlas.mjs", "favicon.svg", "flags.woff2", "flags-LICENSE.txt", "manifest.webmanifest",
          "apple-touch-icon.png", "icon-192.png", "icon-512.png", "globe.mjs", "geo-vendor.mjs", "geo-vendor-LICENSE.txt"} | MAP_ASSETS
RANGES = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
LIMIT = 250
NANO = 1_000_000_000


class BadRequest(Exception):
    pass


def parameters(query):
    try:
        raw = parse_qs(query, keep_blank_values=True, max_num_fields=8, strict_parsing=True)
        if any(len(values) != 1 for values in raw.values()):
            raise ValueError()
        return {key: values[0] for key, values in raw.items()}
    except ValueError:
        raise BadRequest("Invalid query parameters") from None


def event_query(params, now):
    if set(params) - {"range", "type", "outcome", "ip", "user", "before", "after"}:
        raise BadRequest("Unknown filter")
    period = params.get("range", "24h")
    if period not in RANGES:
        raise BadRequest("Unknown time range")
    selector = '{job="attacks"'
    category = params.get("type", "")
    if category:
        if category not in TYPES:
            raise BadRequest("Unknown event type")
        selector += ",type=" + json.dumps(category)
    selector += "} | json"
    if params.get("outcome"):
        if params["outcome"] not in VERDICTS:
            raise BadRequest("Unknown outcome")
        selector += " | verdict=" + json.dumps(params["outcome"])
    if params.get("ip"):
        try:
            ip = str(ipaddress.ip_address(params["ip"]))
        except ValueError:
            raise BadRequest("Enter a complete IPv4 or IPv6 address") from None
        selector += " | ip=" + json.dumps(ip)
    if params.get("user"):
        if len(params["user"]) > 64 or any(ord(char) < 32 for char in params["user"]):
            raise BadRequest("Invalid username")
        selector += " | user=" + json.dumps(params["user"])
    start, end = int((now - RANGES[period]) * NANO), int(now * NANO)
    if "before" in params and "after" in params:
        raise BadRequest("Use one cursor direction")
    for key in ("before", "after"):
        if key in params:
            value = params[key]
            if not value.isdigit() or len(value) > 20:
                raise BadRequest("Invalid cursor")
            cursor = int(value)
            if not 0 < cursor <= end:
                raise BadRequest("Cursor outside supported range")
            if key == "before":
                end = cursor - 1
            else:
                start = max(start, cursor)
    return selector + ' | __error__=""', start, max(start, end)


class API:
    def __init__(self, loki, prometheus, collector):
        self.loki, self.prometheus, self.collector = loki, prometheus, collector
        self.slots = threading.BoundedSemaphore(6)

    def events(self, params):
        query, start, end = event_query(params, time.time())
        data = self.loki.request("/loki/api/v1/query_range", {
            "query": query, "start": start, "end": end,
            "direction": "forward" if "after" in params else "backward", "limit": LIMIT + 1,
        })
        if data.get("status") != "success" or data.get("data", {}).get("resultType") != "streams":
            raise UpstreamError("Invalid event response from Loki")
        rows = []
        for stream in data["data"]["result"]:
            for ns, line in stream["values"]:
                item = json.loads(line)
                if (not isinstance(item, dict) or item.get("type") not in TYPES
                        or not isinstance(item.get("id"), str)):
                    raise UpstreamError("Invalid normalized event")
                rows.append({**item, "cursor": ns})
        rows.sort(key=lambda item: int(item["cursor"]), reverse="after" not in params)
        more = len(rows) > LIMIT
        # Do not silently drop events sharing a pagination timestamp.
        if more and rows[LIMIT - 1]["cursor"] == rows[LIMIT]["cursor"]:
            raise UpstreamError("Event timestamp exceeds page capacity; narrow the filters")
        rows = rows[:LIMIT]
        unique = {item["id"]: item for item in rows}
        return {"events": sorted(unique.values(), key=lambda item: int(item["cursor"]), reverse=True),
                "more": more, "next": rows[-1]["cursor"] if rows else None,
                "latest": str(max((int(item["cursor"]) for item in rows), default=end)),
                "queriedAt": time.time()}

    def prometheus_query(self, query, **params):
        endpoint = "/api/v1/query_range" if "start" in params else "/api/v1/query"
        data = self.prometheus.request(endpoint, {"query": query, "timeout": "8s", **params})
        if data.get("status") != "success" or not isinstance(data.get("data", {}).get("result"), list):
            raise UpstreamError("Invalid metrics response from Prometheus")
        return data["data"]["result"]

    def stats(self, params):
        period = params.get("range", "24h")
        if set(params) - {"range"} or period not in RANGES:
            raise BadRequest("Unknown statistics range")
        now, seconds = time.time(), RANGES[period]
        totals = self.prometheus_query(f"sum by (type,kind) (increase(attacks_events_total[{period}]))")
        trapped = self.prometheus_query(f"sum(increase(attacks_tarpit_seconds_total[{period}]))")
        lifetime_trapped = self.prometheus_query("sum(attacks_tarpit_seconds_total)")
        timeline = self.prometheus_query("sum(rate(attacks_events_total[5m])) * 60",
                                         start=int(now - seconds), end=int(now), step=max(60, seconds // 120))
        def value(row):
            result = float(row["value"][1])
            if not math.isfinite(result):
                raise UpstreamError("Metrics contain an invalid value")
            return result
        return {"range": period, "totals": [{**row["metric"], "value": value(row)} for row in totals],
                "trappedSeconds": value(trapped[0]) if trapped else None,
                "lifetimeTrappedSeconds": value(lifetime_trapped[0]) if lifetime_trapped else None,
                "timeline": timeline[0]["values"] if timeline else [],
                "available": bool(totals), "queriedAt": now}


def serve(host="127.0.0.1", port=8080):
    api = API(*clients())

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            url = urlsplit(self.path)
            status, content_type, body = 200, "application/json", b""
            asset = False
            try:
                if url.path.startswith("/api/"):
                    if not api.slots.acquire(blocking=False):
                        raise UpstreamError("Query capacity exhausted; retry shortly")
                    try:
                        params = parameters(url.query)
                        if url.path == "/api/events":
                            result = api.events(params)
                        elif url.path == "/api/stats":
                            result = api.stats(params)
                        elif url.path == "/api/status" and not params:
                            result = api.collector.request("/status")
                        else:
                            raise BadRequest("Unknown API route")
                        body = json.dumps(result, allow_nan=False).encode()
                    finally:
                        api.slots.release()
                elif url.path == "/healthz":
                    body = b'{"status":"ok"}'
                else:
                    name = "index.html" if url.path == "/" else url.path.removeprefix("/")
                    if name not in STATIC:
                        status, body = 404, b'{"error":"Not found"}'
                    else:
                        compressed = ROOT / (name + ".gz")
                        gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower().replace(" ", "").split(",") and compressed.is_file()
                        body = (compressed if gzip else ROOT / name).read_bytes()
                        asset = True
                        content_type = ("text/javascript" if name.endswith((".mjs", ".js"))
                                        else "application/manifest+json" if name.endswith(".webmanifest")
                                        else "font/woff2" if name.endswith(".woff2")
                                        else "application/geo+json" if name.endswith(".geojson")
                                        else mimetypes.guess_type(name)[0] or "application/octet-stream")
            except BadRequest as error:
                status, body = 400, json.dumps({"error": str(error)}).encode()
            except (UpstreamError, OSError, ValueError, KeyError, TypeError) as error:
                logging.error("API unavailable: %s", type(error).__name__)
                message = str(error) if isinstance(error, UpstreamError) else "Telemetry response unavailable"
                status, body = 503, json.dumps({"error": message}).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if asset and name in MAP_ASSETS else "no-store")
            if asset:
                self.send_header("X-Attacks-Asset", "1")
                self.send_header("Vary", "Accept-Encoding")
                if gzip:
                    self.send_header("Content-Encoding", "gzip")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
                             "connect-src 'self'; font-src 'self'; worker-src 'self'; manifest-src 'self'; "
                             "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def log_message(self, *_):
            # Request queries can include IPs/usernames; don't echo them to logs.
            pass

    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.host, args.port)
