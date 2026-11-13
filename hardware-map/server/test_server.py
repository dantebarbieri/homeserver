import http.client
import io
import json
from pathlib import Path
import shutil
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import uuid

import server


class APITests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".test-state-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text('<meta name="atlas-data" content="demo">', encoding="utf-8")
        (self.web / "secret.json").write_text('{"private":true}', encoding="utf-8")
        self.now = 1800000000
        self.snapshot = {"version": 1, "mode": "live", "capturedAt": server.utc(self.now),
                         "metrics": {"cpu": 12, "temp-cpu": None},
                         "channelKeys": {"cpu": "cpu", "temp-cpu": "temp-cpu"},
                         "capacities": {}, "available": {}, "issues": []}
        self.save()
        (self.root / "metrics.prom").write_text('server_atlas_value{metric="cpu"} 12\n', encoding="utf-8")
        self.state = server.State(self.root, self.web, clock=lambda: self.now)
        self.http = server.AtlasServer(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        shutil.rmtree(self.root)

    def save(self):
        (self.root / "snapshot.json").write_text(json.dumps(self.snapshot), encoding="utf-8")

    def request(self, path, method="GET"):
        connection = http.client.HTTPConnection(*self.http.server_address, timeout=3)
        connection.request(method, path)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_live_marker_snapshot_and_security_headers(self):
        status, headers, raw = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b'content="live"', raw)
        self.assertEqual(headers["Cache-Control"], "no-cache")
        status, headers, raw = self.request("/api/snapshot")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["metrics"]["cpu"], 12)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.request("/healthz")[0], 200)
        self.assertEqual(self.request("/metrics")[0], 200)
        status, _, raw = self.request("/api/snapshot", "HEAD")
        self.assertEqual((status, raw), (200, b""))

    def test_static_allowlist_traversals_and_methods(self):
        for path in ("/server/server.py", "/secret.json", "/../snapshot.json",
                     "/%2e%2e/snapshot.json", "/%2e%2e%5csnapshot.json",
                     "//secret.json", "/index.html/anything"):
            self.assertEqual(self.request(path)[0], 404, path)
        self.assertEqual(self.request("/", "POST")[0], 405)
        with patch.object(Path, "is_symlink", return_value=True):
            self.assertEqual(self.request("/index.html")[0], 404)

    def test_stale_missing_and_nonfinite_snapshot_fail_closed(self):
        self.now += 31
        for path in ("/healthz", "/metrics", "/api/snapshot", "/api/history?ids=cpu&seconds=60"):
            self.assertEqual(self.request(path)[0], 503, path)
        self.snapshot["capturedAt"] = server.utc(self.now)
        self.snapshot["metrics"]["cpu"] = float("nan")
        self.save()
        self.assertEqual(self.request("/api/snapshot")[0], 503)
        (self.root / "snapshot.json").unlink()
        self.assertEqual(self.request("/healthz")[0], 503)

    def test_history_allowlist_and_bounds(self):
        for query in ("ids=cpu&seconds=59", "ids=cpu&seconds=86401",
                      "ids=unknown&seconds=60", "ids=cpu&seconds=NaN",
                      "ids=cpu&seconds=60&query=up", "ids=cpu&ids=cpu&seconds=60",
                      "ids=&seconds=60", "ids=" + ",".join(["cpu"] * 129) + "&seconds=60",
                      "ids=cpu%22%7D&seconds=60"):
            self.assertEqual(self.request("/api/history?" + query)[0], 400, query)

    def test_history_preserves_missing_nonfinite_and_stale_gaps(self):
        calls = []

        def query(url):
            params = parse_qs(urlsplit(url).query)
            calls.append(params)
            start = int(params["start"][0])
            if params["query"][0].startswith("timestamp("):
                return [{"metric": {"metric": "cpu"}, "values": [[start, str(start)],
                          [start + 1, str(start + 1)], [start + 30, str(start)]]}]
            return [{"metric": {"metric": "cpu"}, "values": [[start, "14.5"],
                      [start + 1, "NaN"], [start + 30, "16"]]}]

        with patch.object(self.state, "prometheus_query", side_effect=query):
            status, _, raw = self.request("/api/history?ids=cpu,temp-cpu&seconds=60")
        self.assertEqual(status, 200)
        data = json.loads(raw)
        points = data["series"]["cpu"]
        self.assertEqual(len(points), 61)
        self.assertEqual(points[0]["value"], 14.5)
        self.assertIsNone(points[1]["value"])
        self.assertIsNone(points[2]["value"])
        self.assertIsNone(points[30]["value"])
        self.assertTrue(all(p["value"] is None for p in data["series"]["temp-cpu"]))
        self.assertEqual(len(calls), 2)
        self.assertIn("server_atlas_value", calls[0]["query"][0])

    def test_long_history_is_bounded_and_failures_are_explicit(self):
        with patch.object(self.state, "prometheus_query", return_value=[]):
            data = self.state.history("ids=cpu&seconds=86400")
        self.assertLessEqual(len(data["series"]["cpu"]), 301)
        self.assertTrue(all(p["value"] is None for p in data["series"]["cpu"]))
        with patch.object(self.state.opener, "open", side_effect=OSError("synthetic failure")):
            status, _, raw = self.request("/api/history?ids=cpu&seconds=60")
        self.assertEqual(status, 502)
        self.assertIn("Prometheus", json.loads(raw)["error"])
        for _ in range(4):
            self.state.history_slots.acquire()
        try:
            self.assertEqual(self.request("/api/history?ids=cpu&seconds=60")[0], 503)
        finally:
            for _ in range(4):
                self.state.history_slots.release()

    def test_regex_values_only_come_from_internal_allowlist(self):
        self.snapshot["channelKeys"]["cpu"] = "cpu.test"
        self.save()
        with patch.object(self.state, "prometheus_query", return_value=[]) as query:
            self.state.history("ids=cpu&seconds=60")
        expression = parse_qs(urlsplit(query.call_args_list[0].args[0]).query)["query"][0]
        self.assertEqual(expression, 'server_atlas_value{metric=~"cpu\\\\.test"}')

    def test_prometheus_error_malformed_and_oversized_envelopes(self):
        for payload in ({"status": "error", "error": "synthetic bad query"},
                        {"status": "success", "data": {"resultType": "vector", "result": []}},
                        {"status": "success", "data": {"resultType": "matrix", "result": [7]}},
                        {"status": "success", "data": {"resultType": "matrix", "result": [{}]}}):
            with patch.object(self.state.opener, "open", return_value=io.BytesIO(json.dumps(payload).encode())):
                self.assertEqual(self.request("/api/history?ids=cpu&seconds=60")[0], 502)
        with patch.object(self.state.opener, "open", return_value=io.BytesIO(b"x" * (server.MAX_FILE + 1))):
            self.assertEqual(self.request("/api/history?ids=cpu&seconds=60")[0], 502)

    def test_history_rejects_ambiguous_scrape_targets(self):
        duplicate = [{"metric": {"metric": "cpu"}, "values": []},
                     {"metric": {"metric": "cpu"}, "values": []}]
        with patch.object(self.state, "prometheus_query", return_value=duplicate):
            status, _, raw = self.request("/api/history?ids=cpu&seconds=60")
        self.assertEqual(status, 502)
        self.assertIn("Ambiguous", json.loads(raw)["error"])


if __name__ == "__main__":
    unittest.main()
