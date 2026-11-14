#!/usr/bin/env python3
"""Unprivileged read-only ChasEx static/API server."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import socketserver
import threading
import time
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request


STATIC = frozenset(("index.html", "styles.css", "favicon.svg", "app.mjs", "board.mjs",
                    "model.mjs", "metric-model.mjs", "metrics.mjs", "live-data.mjs", "linux-snapshot.mjs",
                    "mobile-ui.mjs", "pwa.mjs", "services.mjs", "service-model.mjs", "sw.js", "manifest.webmanifest",
                    "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"))
MAX_FILE = 8 * 1024 * 1024
KEY = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def utc(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp,
                                  timezone.utc).isoformat().replace("+00:00", "Z")


def strict_json(data):
    return json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))


class State:
    def __init__(self, state_dir, web_root, prometheus_url="http://prometheus:9090", clock=time.time):
        self.state_dir, self.web_root = Path(state_dir), Path(web_root).resolve()
        url = urlsplit(prometheus_url)
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError("PROMETHEUS_URL must be a fixed HTTP(S) base URL without credentials/query")
        self.prometheus_url, self.clock = prometheus_url.rstrip("/"), clock
        self.history_slots = threading.BoundedSemaphore(4)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def snapshot(self):
        try:
            path = self.state_dir / "snapshot.json"
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                raise ValueError("Snapshot too large")
            data = strict_json(raw)
            if data["version"] != 1 or data["mode"] != "live" or not isinstance(data["metrics"], dict):
                raise ValueError("Invalid snapshot")
            for key in ("channelKeys", "capacities", "available"):
                if not isinstance(data[key], dict):
                    raise ValueError("Invalid snapshot fields")
            for value in data["metrics"].values():
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or not math.isfinite(value)):
                    raise ValueError("Invalid measurement")
            captured = datetime.fromisoformat(data["capturedAt"].replace("Z", "+00:00")).timestamp()
            age = self.clock() - captured
            if age > 30 or age < -10:
                raise APIError(503, "Collector snapshot is stale or has invalid clock skew")
            return data, age
        except APIError:
            raise
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            raise APIError(503, "Collector snapshot unavailable or invalid") from None

    def history(self, query):
        try:
            params = parse_qs(query, keep_blank_values=True, max_num_fields=4)
            if set(params) - {"ids", "seconds"} or len(params.get("ids", [])) != 1 or len(params.get("seconds", [])) != 1:
                raise ValueError()
            seconds = int(params["seconds"][0])
            ids = params["ids"][0].split(",")
            if not 60 <= seconds <= 86400 or not 1 <= len(ids) <= 128 or any(not item for item in ids):
                raise ValueError()
        except ValueError:
            raise APIError(400, "Expected ids (1..128) and seconds (60..86400)") from None
        snapshot, _ = self.snapshot()
        channels = snapshot["channelKeys"]
        if any(item not in channels or not isinstance(channels[item], str) or not KEY.fullmatch(channels[item]) for item in ids):
            raise APIError(400, "Unknown or unavailable metric ID")
        ids = list(dict.fromkeys(ids))
        keys = sorted({channels[item] for item in ids})
        # Escape regex first, then JSON-quote the resulting PromQL label string.
        label = json.dumps("|".join(re.escape(key) for key in keys))
        expression = f"server_atlas_value{{metric=~{label}}}"
        step = max(1, math.ceil(seconds / 300))
        # Align the evaluation grid so repeated requests don't interpolate samples.
        end = math.floor(self.clock() / step) * step
        start = end - math.floor(seconds / step) * step
        if not self.history_slots.acquire(blocking=False):
            raise APIError(503, "History request capacity exhausted")
        try:
            url = self.prometheus_url + "/api/v1/query_range?" + urlencode({
                # timestamp() prevents Prometheus's default lookback from silently
                # repeating an old numeric value across missing/stale scrapes.
                "query": expression, "start": start, "end": end, "step": step,
                "timeout": "4s"})
            times_url = self.prometheus_url + "/api/v1/query_range?" + urlencode({
                "query": f"timestamp({expression})", "start": start, "end": end,
                "step": step, "timeout": "4s"})
            result = self.prometheus_query(url)
            timestamps = self.prometheus_query(times_url)
            actual_times = {}
            for entry in timestamps:
                key = entry.get("metric", {}).get("metric")
                if key in keys:
                    actual_times[key] = self.points(entry)
            values = {}
            for entry in result:
                key = entry.get("metric", {}).get("metric")
                if key not in keys:
                    continue
                if key in values:
                    raise APIError(502, "Ambiguous Prometheus series; configure a single ChasEx scrape target")
                values[key] = self.points(entry)
            series = {}
            for frontend in ids:
                key = channels[frontend]
                points = []
                for timestamp in range(start, end + 1, step):
                    sample_time = actual_times.get(key, {}).get(timestamp)
                    value = values.get(key, {}).get(timestamp)
                    if sample_time is None or not 0 <= timestamp - sample_time <= 20:
                        value = None
                    points.append({"timestamp": timestamp, "value": value})
                series[frontend] = points
            return {"capturedAt": utc(self.clock()), "seconds": seconds, "step": step,
                    "series": series, "issues": []}
        finally:
            self.history_slots.release()

    def services(self):
        try:
            with (self.state_dir / "services.json").open("rb") as stream:
                raw = stream.read(MAX_FILE + 1)
            if len(raw) > MAX_FILE:
                raise ValueError("Services snapshot too large")
            data = strict_json(raw)
            if data["version"] != 1 or data["mode"] != "live" or not isinstance(data["services"], list):
                raise ValueError("Invalid services snapshot")
            age = self.clock() - datetime.fromisoformat(data["capturedAt"].replace("Z", "+00:00")).timestamp()
            if not -10 <= age <= 20 or data["status"] != "ok":
                raise ValueError("Services stale or unavailable")
            return data
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            raise APIError(503, "Service accounting unavailable or stale") from None

    def prometheus_query(self, url):
        try:
            with self.opener.open(Request(url, headers={"Accept": "application/json"}), timeout=5) as response:
                raw = response.read(MAX_FILE + 1)
                if len(raw) > MAX_FILE:
                    raise ValueError("Prometheus response too large")
                data = strict_json(raw)
            if data.get("status") != "success" or data["data"]["resultType"] != "matrix":
                raise ValueError("Prometheus query unsuccessful")
            result = data["data"]["result"]
            if not isinstance(result, list) or len(result) > 128:
                raise ValueError("Unexpected Prometheus series count")
            if any(not isinstance(entry, dict) or not isinstance(entry.get("metric"), dict)
                   for entry in result):
                raise ValueError("Invalid Prometheus series")
            return result
        except (OSError, URLError, ValueError, KeyError, TypeError):
            raise APIError(502, "Prometheus unavailable or returned an invalid range response") from None

    @staticmethod
    def points(entry):
        try:
            samples = entry["values"]
            if not isinstance(samples, list) or len(samples) > 301:
                raise ValueError()
            result = {}
            for timestamp, raw in samples:
                stamp, value = float(timestamp), float(raw)
                if not math.isfinite(stamp):
                    raise ValueError()
                result[stamp] = value if math.isfinite(value) else None
            return result
        except (ValueError, TypeError, KeyError, OverflowError):
            raise APIError(502, "Prometheus returned invalid samples") from None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ChasEx"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def log_message(self, format, *args):
        # Never log URLs, query strings, response bodies or private inventory.
        pass

    def respond(self, status, body, content_type="application/json; charset=utf-8", api=True):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if api else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data: https://cdn.jsdelivr.net https://*.danteb.com; connect-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        try:
            if len(self.path) > 12000:
                raise APIError(414, "Request target too long")
            url = urlsplit(self.path)
            state = self.server.state
            if url.path == "/api/snapshot":
                snapshot, _ = state.snapshot()
                self.respond(200, snapshot)
            elif url.path == "/api/services":
                self.respond(200, state.services())
            elif url.path == "/healthz":
                snapshot, age = state.snapshot()
                self.respond(200, {"ready": True, "capturedAt": snapshot["capturedAt"],
                                   "ageSeconds": age, "sources": snapshot.get("sources", {})})
            elif url.path == "/api/history":
                self.respond(200, state.history(url.query))
            elif url.path == "/metrics":
                state.snapshot()  # Never scrape indefinitely stale collector output.
                try:
                    with (state.state_dir / "metrics.prom").open("rb") as stream:
                        raw = stream.read(MAX_FILE + 1)
                    if len(raw) > MAX_FILE:
                        raise OSError()
                except OSError:
                    raise APIError(503, "Collector metrics unavailable") from None
                self.respond(200, raw, "text/plain; version=0.0.4; charset=utf-8")
            else:
                name = unquote(url.path, errors="strict")
                if name == "/":
                    name = "/index.html"
                if name[1:] not in STATIC or not name.startswith("/") or "\\" in name:
                    raise APIError(404, "Not found")
                path = state.web_root / name[1:]
                if path.is_symlink() or path.resolve().parent != state.web_root:
                    raise APIError(404, "Not found")
                try:
                    with path.open("rb") as stream:
                        raw = stream.read(MAX_FILE + 1)
                    if len(raw) > MAX_FILE:
                        raise OSError()
                except OSError:
                    raise APIError(404, "Not found") from None
                if name == "/index.html":
                    raw = raw.replace(b'<meta name="atlas-data" content="demo">',
                                      b'<meta name="atlas-data" content="live">')
                mime = {".mjs": "text/javascript", ".js": "text/javascript", ".webmanifest": "application/manifest+json"}.get(
                    path.suffix, mimetypes.guess_type(name)[0] or "application/octet-stream")
                self.respond(200, raw, mime, api=False)
        except APIError as error:
            self.respond(error.status, {"error": error.message, "ready": False} if urlsplit(self.path).path == "/healthz"
                         else {"error": error.message})
        except (ValueError, UnicodeError):
            self.respond(400, {"error": "Invalid request"})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True

    do_HEAD = do_GET

    def do_POST(self):
        self.respond(405, {"error": "GET and HEAD only"})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_TRACE = do_POST
    do_CONNECT = do_POST


class AtlasServer(socketserver.ThreadingMixIn, HTTPServer):
    """Bound accepted request workers; close idle HTTP connections promptly."""
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, state):
        self.state = state
        self.workers = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="/var/lib/server-atlas")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--web-root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    state = State(args.state_dir, args.web_root, os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"))
    with AtlasServer((args.host, args.port), state) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
