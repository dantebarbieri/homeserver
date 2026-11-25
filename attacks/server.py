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
from events import OWN_NETWORKS, SEVERITIES, SEVERITY, TYPES, VERDICTS, home_networks, kinds_at_least, traffic_origin


ROOT = Path(__file__).parent / "static"
MAP_ASSETS = {path.name for path in ROOT.glob("world-*.json")
              if re.fullmatch(r"world-(110m|50m|10m)-[0-9a-f]{12}\.json", path.name)}
STATIC = {"index.html", "styles.css", "app.mjs", "model.mjs", "map-view.mjs", "pwa.mjs", "sw.js",
          "atlas.mjs", "favicon.svg", "flags.woff2", "flags-LICENSE.txt", "manifest.webmanifest",
          "apple-touch-icon.png", "icon-192.png", "icon-512.png", "globe.mjs", "globe-draw.mjs", "geo-vendor.mjs",
          "geo-vendor-LICENSE.txt"} | MAP_ASSETS
RANGES = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
LIMIT = 250
NANO = 1_000_000_000


class BadRequest(Exception):
    pass


def parameters(query):
    try:
        raw = parse_qs(query, keep_blank_values=True, max_num_fields=16, strict_parsing=True)
        if any(len(values) != 1 for values in raw.values()):
            raise ValueError()
        return {key: values[0] for key, values in raw.items()}
    except ValueError:
        raise BadRequest("Invalid query parameters") from None


def choices(value, allowed, label):
    values = value.split(",")
    if len(values) > len(allowed) or len(set(values)) != len(values) or not set(values) <= set(allowed):
        raise BadRequest(f"Unknown {label}")
    return values


def alternatives(values):
    return "|".join(re.escape(value) for value in values)


def event_query(params, now, networks=()):
    if set(params) - {"range", "type", "outcome", "severity", "ip", "country", "asn", "before", "after", "own"}:
        raise BadRequest("Unknown filter")
    if params.get("own", "0") not in ("0", "1"):
        raise BadRequest("Unknown own-traffic setting")
    period = params.get("range", "24h")
    if period not in RANGES:
        raise BadRequest("Unknown time range")
    selector = '{job="attacks"' + (',origin!="own"' if params.get("own") != "1" else "")
    if params.get("type"):
        categories = choices(params["type"], TYPES, "event type")
        selector += ",type=~" + json.dumps(alternatives(categories))
    selector += "} | json"
    if params.get("own") != "1":
        selector += exclude_own(networks)
    if params.get("outcome"):
        outcomes = choices(params["outcome"], VERDICTS, "outcome")
        selector += " | verdict=~" + json.dumps(alternatives(outcomes))
    if params.get("severity"):
        if params["severity"] not in SEVERITIES:
            raise BadRequest("Unknown severity")
        if params["severity"] != SEVERITIES[0]:
            selector += " | kind=~" + json.dumps(alternatives(kinds_at_least(params["severity"])))
    if params.get("ip"):
        try:
            ip = str(ipaddress.ip_address(params["ip"]))
        except ValueError:
            raise BadRequest("Enter a complete IPv4 or IPv6 address") from None
        selector += " | ip=" + json.dumps(ip)
    if params.get("country"):
        if not re.fullmatch(r"[A-Z]{2}", params["country"]):
            raise BadRequest("Invalid country code")
        selector += " | countryCode=" + json.dumps(params["country"])
    if params.get("asn"):
        if not re.fullmatch(r"[1-9][0-9]{0,9}", params["asn"]):
            raise BadRequest("Invalid network number")
        selector += " | asn=" + json.dumps(params["asn"])
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


def exclude_own(networks):
    # Missing origin labels are pre-upgrade events, not missing history.
    return "".join(f" | ip != ip({json.dumps(cidr)})" for cidr in (*OWN_NETWORKS, *networks))


class API:
    def __init__(self, loki, prometheus, collector):
        self.loki, self.prometheus, self.collector = loki, prometheus, collector
        self.slots = threading.BoundedSemaphore(6)

    def events(self, params):
        networks = self.own_networks(self.collector.request("/status"))
        query, start, end = event_query(params, time.time(), networks)
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
                origin = "own" if item.get("origin") == "own" else traffic_origin(item["ip"], networks)
                rows.append({**item, "origin": origin, "cursor": ns,
                             "severity": SEVERITY.get(item.get("kind"), "low")})
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

    @staticmethod
    def own_networks(status):
        own = status.get("ownTraffic", {})
        if own.get("state") != "ready":
            raise UpstreamError("Own-traffic classification unavailable; check host capture health")
        return home_networks(own["networks"])

    def loki_metrics(self, query, **params):
        ranged = "start" in params
        endpoint = "/loki/api/v1/query_range" if ranged else "/loki/api/v1/query"
        data = self.loki.request(endpoint, {"query": query, **params})
        if (data.get("status") != "success"
                or data.get("data", {}).get("resultType") != ("matrix" if ranged else "vector")):
            raise UpstreamError("Invalid statistics response from Loki")
        return data["data"]["result"]

    def sources(self, params):
        period = params.get("range", "24h")
        if set(params) - {"range", "own"} or period not in RANGES or params.get("own", "0") not in ("0", "1"):
            raise BadRequest("Unknown source range")
        networks = self.own_networks(self.collector.request("/status"))
        base = '{job="attacks"' + (',origin!="own"' if params.get("own") != "1" else "") + "} | json"
        if params.get("own") != "1":
            base += exclude_own(networks)
        instant = {"time": str(int(time.time() * NANO))}

        def top(labels):
            query = f'topk(12, sum by ({labels}) (count_over_time({base} | keep {labels} | __error__="" [{period}])))'
            rows = []
            for row in self.loki_metrics(query, **instant):
                count = float(row["value"][1])
                if not math.isfinite(count):
                    raise UpstreamError("Source statistics contain an invalid value")
                rows.append({**row["metric"], "count": count})
            return sorted(rows, key=lambda row: -row["count"])

        countries = [row for row in top("countryCode") if re.fullmatch(r"[A-Z]{2}", row.get("countryCode", ""))]
        asns = [row for row in top("asn,networkOrganization") if re.fullmatch(r"[1-9][0-9]{0,9}", row.get("asn", ""))]
        return {"range": period, "countries": countries, "networks": asns, "queriedAt": time.time()}

    def facets(self, params):
        # Type, outcome and severity filters are applied by the browser, so each picker
        # can count its options against the other two without another round trip.
        if set(params) - {"range", "ip", "country", "asn", "own"}:
            raise BadRequest("Unknown facet filter")
        networks = self.own_networks(self.collector.request("/status"))
        query, _, _ = event_query(params, time.time(), networks)
        period = params.get("range", "24h")
        rows = self.loki_metrics(
            f"sum by (type,verdict,kind) (count_over_time({query} | keep type,verdict,kind [{period}]))",
            time=str(int(time.time() * NANO)))
        merged = {}
        for row in rows:
            count = float(row["value"][1])
            if not math.isfinite(count):
                raise UpstreamError("Facet counts contain an invalid value")
            metric = row["metric"]
            if metric.get("type") not in TYPES or metric.get("verdict") not in VERDICTS:
                continue
            key = (metric["type"], metric["verdict"], SEVERITY.get(metric.get("kind"), "low"))
            merged[key] = merged.get(key, 0) + count
        return {"range": period, "queriedAt": time.time(),
                "counts": [{"type": t, "outcome": v, "severity": s, "count": c} for (t, v, s), c in merged.items()]}

    def stats(self, params):
        period = params.get("range", "24h")
        if set(params) - {"range"} or period not in RANGES:
            raise BadRequest("Unknown statistics range")
        now, seconds = time.time(), RANGES[period]
        status = self.collector.request("/status")
        networks = self.own_networks(status)
        trapping = status["trapping"]
        query = '{job="attacks",origin!="own"} | json' + exclude_own(networks)
        query += f' | observedAt <= {float(trapping["through"]):.6f} | __error__=""'
        instant = {"time": str(int(now * NANO))}
        counts = query + " | keep type,kind"
        totals = self.loki_metrics(f"sum by (type,kind) (count_over_time({counts}[{period}]))", **instant)
        trapped = self.loki_metrics(
            f'sum(sum_over_time({query} | kind="endlessh_close" | keep duration | unwrap duration | __error__="" [{period}]))',
            **instant)
        lifetime_trapped = self.prometheus_query('sum(attacks_endlessh_seconds_total{origin="external"})')
        step = max(60, seconds // 120)
        # Loki aligns range samples to the step grid. Query full buckets on that
        # grid, then evaluate the current partial bucket without future timestamps.
        end = int(now) // step * step
        start = end - seconds + step
        timeline = self.loki_metrics(f"sum(count_over_time({counts}[{step}s])) * 60 / {step}",
                                     start=str(start * NANO), end=str(end * NANO), step=step)
        def value(row):
            result = float(row["value"][1])
            if not math.isfinite(result):
                raise UpstreamError("Statistics contain an invalid value")
            return result
        points = {int(float(at)): number for row in timeline for at, number in row["values"]}
        timeline = [[at, points.get(at, "0")] for at in range(start, end + 1, step)]
        partial = int(now) - end
        if partial:
            tail = self.loki_metrics(f"sum(count_over_time({counts}[{partial}s])) * 60 / {partial}", **instant)
            timeline.append([int(now), str(value(tail[0])) if tail else "0"])
        return {"range": period, "totals": [{**row["metric"], "value": value(row)} for row in totals],
                "trappedSeconds": value(trapped[0]) if trapped else 0,
                "lifetimeTrappedSeconds": value(lifetime_trapped[0]) if lifetime_trapped else None,
                "trapping": trapping,
                "timeline": timeline,
                "available": True, "queriedAt": now}


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
                        elif url.path == "/api/sources":
                            result = api.sources(params)
                        elif url.path == "/api/facets":
                            result = api.facets(params)
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
