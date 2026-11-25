"""Bounded HTTP clients shared by the private collector and read-only API."""

import json
import os
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class UpstreamError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base):
        url = urlsplit(base)
        if (url.scheme not in ("http", "https") or not url.netloc or url.username
                or url.password or url.query or url.fragment):
            raise ValueError("Expected a fixed HTTP(S) base URL without credentials")
        self.base = base.rstrip("/")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, params=None, payload=None):
        query = urlencode(params) if params else ""
        if payload is None and len(query) > 4096:
            # Long queries (reputation IP filters) go in a form body; Loki accepts both.
            request = Request(self.base + path, data=query.encode(),
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
        else:
            url = self.base + path + ("?" + query if query else "")
            data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
            request = Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=10) as response:
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise UpstreamError("Response exceeds size limit")
                return json.loads(body) if body else {}
        except (OSError, ValueError) as error:
            # URLs, response bodies and raw logs can contain credentials.
            raise UpstreamError(f"Upstream request failed ({type(error).__name__})") from None

    def query(self, expression, start, end, limit=1000):
        result = self.request("/loki/api/v1/query_range", {
            "query": expression, "start": str(start), "end": str(end),
            "direction": "forward", "limit": limit,
        })
        if result.get("status") != "success" or result.get("data", {}).get("resultType") != "streams":
            raise UpstreamError("Loki returned an invalid log response")
        rows = []
        for stream in result["data"]["result"]:
            for timestamp, line in stream["values"]:
                rows.append((int(timestamp), line, stream["stream"]))
        return sorted(rows, key=lambda row: row[0])


def clients():
    return (
        Client(os.environ.get("LOKI_URL", "http://loki:3100")),
        Client(os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")),
        Client(os.environ.get("COLLECTOR_URL", "http://attacks-collector:9108")),
    )
