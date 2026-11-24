from datetime import datetime, timezone
import base64
import hashlib
import ipaddress
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

import maxminddb

from capture import packet
from collector import Collector, Geo, Store, window
from common import Client, UpstreamError
from events import parse_authelia, parse_endlessh, parse_fail2ban, parse_flow, parse_npm, parse_ssh
from server import API, BadRequest, event_query, parameters
from ssh_keys import SSHKeys
from networks import FEEDS, Networks
from update_intelligence import ranges, refresh_prefixes


IP = "8.8.8.8"


def npm_line(path="/.env", status=404, stamp=None):
    stamp = stamp or datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S %z")
    return f'[{stamp}] - {status} {status} - GET https example.test "{path}" [Client {IP}] [Length 0] [Gzip -] [Sent-to app] "UA" "-"'


class ParserTests(unittest.TestCase):
    def test_endlessh_lifecycle_and_internal_healthchecks(self):
        opened = parse_endlessh(f"I1124 client.go:75] ACCEPT host={IP} port=50124 n=2/4096", 100)
        closed = parse_endlessh(f"CLOSE host={IP} port=50124 time=13.009 bytes=174", 113)
        self.assertEqual(opened["port"], 22)
        self.assertEqual(closed["duration"], 13.009)
        self.assertEqual(closed["sourcePort"], opened["sourcePort"])
        self.assertIsNone(parse_endlessh("ACCEPT host=172.20.0.1 port=35644 n=1/4096", 100))

    def test_auth_failure_not_an_authorization_redirect(self):
        line = f'time="2026-11-24T17:35:38Z" level=error msg="Unsuccessful 1FA authentication attempt by user \'example\'" remote_ip={IP}'
        item = parse_authelia(line, 100)
        self.assertEqual((item["user"], item["factor"]), ("example", "1FA"))
        item = parse_authelia(json.dumps({"msg": "Unsuccessful TOTP authentication attempt by user 'example'", "remote_ip": "::ffff:8.8.8.8"}), 100)
        self.assertEqual((item["ip"], item["factor"]), (IP, "TOTP"))
        self.assertIsNone(parse_authelia(f'msg="Access is not authorized, responding with status code 401" remote_ip={IP}', 100))
        self.assertIsNone(parse_authelia('msg="unterminated', 100))

    def test_key_only_ssh_and_ban_classification(self):
        item = parse_ssh(f"Failed publickey for invalid user guest from {IP} port 1234 ssh2", 100)
        self.assertEqual((item["user"], item["kind"]), ("guest", "ssh_failure"))
        self.assertIsNotNone(parse_ssh(f"Invalid user test from {IP} port 1234", 100))
        accepted = parse_ssh(f"Accepted publickey for admin from {IP} port 1234 ssh2: ED25519 SHA256:abc123", 100)
        self.assertEqual((accepted["verdict"], accepted["user"], accepted["keyFingerprint"]),
                         ("accepted", "admin", "SHA256:abc123"))
        incomplete = parse_ssh(f"Connection closed by invalid user guest {IP} port 1234 [preauth]", 100)
        self.assertEqual((incomplete["kind"], incomplete["authMethod"]), ("ssh_disconnect", "unknown"))
        self.assertEqual(item["rejectionReason"], "Username does not exist; authentication rejected")
        self.assertEqual(parse_fail2ban(f"[sshd] Ban {IP}", 100)["verdict"], "blocked")
        self.assertIsNone(parse_fail2ban(f"[sshd] Unban {IP}", 100))

    def test_exact_ssh_rejection_reasons_without_guessing_a_password(self):
        unknown = parse_ssh(f"Invalid user root123 from {IP} port 1234", 100)
        rejected = parse_ssh(f"Failed publickey for admin from {IP} port 1234 ssh2", 100)
        limited = parse_ssh(f"error: maximum authentication attempts exceeded for invalid user guest from {IP} port 1234 ssh2 [preauth]", 100)
        self.assertEqual(unknown["authMethod"], "unknown")
        self.assertEqual(rejected["rejectionReason"], "Public key rejected")
        self.assertEqual(limited["rejectionReason"], "Maximum authentication attempts exceeded")
        self.assertIsNone(parse_ssh(f"Accepted key ED25519 SHA256:abc123 found at /etc/ssh/authorized_keys.d/admin:3", 100))

    def test_npm_classifies_evidence_without_leaking_queries(self):
        item = parse_npm(npm_line("/.env?password=secret"))
        self.assertEqual(item["path"], "/.env")
        self.assertNotIn("secret", json.dumps(item))
        self.assertEqual(item["verdict"], "suspected")
        self.assertEqual(parse_npm(npm_line().replace("GET https", "GET http"))["port"], 80)
        self.assertEqual(parse_npm(npm_line("/ordinary-page", 401))["kind"], "http_denied")
        self.assertIsNone(parse_npm(npm_line("/ordinary-page", 404)))
        self.assertIsNone(parse_npm(npm_line("/ordinary-page", 200)))
        self.assertEqual(parse_npm(npm_line("/%252e%252e/etc/passwd"))["kind"], "http_probe")
        self.assertIsNone(parse_npm(npm_line().replace(IP, "192.168.1.1")))

    def test_flow_is_not_called_an_attack(self):
        item = parse_flow(json.dumps({"schema": "attacks-flow-v1", "ip": IP, "port": 36676,
                                     "sourcePort": 1234, "protocol": "tcp"}), 100)
        self.assertEqual((item["type"], item["verdict"]), ("minecraft", "unclassified"))
        self.assertIsNone(parse_flow('{"schema":"attacks-flow-v1","ip":"127.0.0.1","port":36676}', 100))


def ethernet(ipv6=False, udp=False, port=36676, flags=2, fragment=False, extension=False):
    source = ipaddress.ip_address("2001:4860:4860::8888" if ipv6 else IP).packed
    transport = struct.pack("!HH", 2345, port) + bytes(4 if udp else 16)
    if not udp:
        transport = transport[:13] + bytes([flags]) + transport[14:]
    protocol = 17 if udp else 6
    if ipv6:
        header = bytes([0x60, 0, 0, 0, 0, len(transport), 0 if extension else protocol, 64]) + source + bytes(16)
        if extension:
            header += bytes([protocol, 0]) + bytes(6)
    else:
        header = bytes([0x45, 0, 0, 40, 0, 0, 0, 1 if fragment else 0, 64, protocol, 0, 0]) + source + bytes(4)
    return bytes(12) + (b"\x86\xdd" if ipv6 else b"\x08\x00") + header + transport + b"NOT-RETAINED-PAYLOAD"


class CaptureTests(unittest.TestCase):
    def test_ipv4_syn_and_ipv6_udp_headers_only(self):
        item = packet(bytearray(ethernet()))
        self.assertEqual(item["ip"], IP)
        self.assertNotIn("PAYLOAD", json.dumps(item))
        self.assertIsNone(packet(ethernet(flags=18)))
        self.assertIsNone(packet(ethernet(fragment=True)))
        self.assertIsNone(packet(ethernet(port=443)))
        self.assertEqual(packet(ethernet(ipv6=True, udp=True, port=5205, extension=True))["protocol"], "udp")
        self.assertIsNone(packet(b"\x00" * 10))
        self.assertIsNone(packet(ethernet(), linktype=113))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / "state.sqlite")
        self.item = parse_endlessh(f"CLOSE host={IP} port=1000 time=4.5 bytes=64", time.time())

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def test_replay_does_not_increment_counters(self):
        self.assertTrue(self.store.enqueue(self.item, "endlessh", "stable"))
        self.assertFalse(self.store.enqueue(self.item, "endlessh", "stable"))
        metrics = self.store.metrics()
        self.assertIn('kind="tarpit_close",type="endlessh",country="ZZ"} 1', metrics)
        self.assertIn('attacks_tarpit_seconds_total{country="ZZ"} 4.5', metrics)
        self.assertNotIn(IP, metrics)
        self.assertNotIn("sourcePort", metrics)
        client = Mock()
        client.request.side_effect = UpstreamError("offline")
        with self.assertRaises(UpstreamError):
            self.store.flush(client)
        self.assertIn("attacks_outbox_events 1", self.store.metrics())
        client.request.side_effect = None
        self.store.flush(client)
        self.assertIn("attacks_outbox_events 0", self.store.metrics())
        self.assertFalse(self.store.enqueue(self.item, "endlessh", "stable"))

    def test_log_rotation_and_partial_lines(self):
        logdir = self.root / "logs"
        logdir.mkdir()
        log = logdir / "proxy-host-1_access.log"
        first, second = npm_line("/.env"), npm_line("/.git/config")
        log.write_text(first + "\n" + second[:20], encoding="utf-8")
        geo = Mock()
        geo.enrich.side_effect = lambda value: value
        collector = Collector(self.store, Mock(), geo, logdir)
        collector.files(time.time())
        self.assertIn("attacks_outbox_events 1", self.store.metrics())
        with log.open("a", encoding="utf-8") as stream:
            stream.write(second[20:] + "\n")
        log.rename(logdir / "proxy-host-1_access.log.1")
        log.write_text(npm_line("/wp-login.php") + "\n", encoding="utf-8")
        collector.files(time.time())
        collector.files(time.time())
        self.assertIn("attacks_outbox_events 3", self.store.metrics())

    def test_raw_checkpoint_retained_when_delivery_queue_full(self):
        client = Mock()
        client.query.return_value = [(time.time_ns(), f"ACCEPT host={IP} port=1000 n=1/4096", {})]
        geo = Mock()
        geo.enrich.side_effect = lambda value: value
        collector = Collector(self.store, client, geo, self.root)
        self.store.enqueue = Mock(side_effect=UpstreamError("full"))
        with self.assertRaises(UpstreamError):
            collector.raw("endlessh", time.time())
        self.assertIsNone(self.store.get("cursor:endlessh"))

    def test_missing_geo_database_is_explicit(self):
        geo = Geo(self.root / "missing.mmdb")
        geo.reload()
        self.assertEqual(geo.status["state"], "unavailable")
        self.assertNotIn("latitude", geo.enrich(self.item))

    def test_public_key_recognition_is_user_scoped_and_fails_visibly(self):
        raw = b"\x00\x00\x00\x0bssh-ed25519" + b"\x00\x00\x00\x20" + bytes(range(32))
        encoded = base64.b64encode(raw).decode()
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        path = self.root / "keys.json"
        path.write_text(json.dumps({"admin": [f'from="192.168.0.0/16" ssh-ed25519 {encoded} DOMAIN\\test']}))
        keys = SSHKeys(path)
        keys.reload()
        item = parse_ssh(f"Accepted publickey for admin from {IP} port 1234 ssh2: ED25519 {fingerprint}", 100)
        self.assertEqual(keys.annotate(item)["keyStatus"], "recognized")
        self.assertEqual(keys.annotate(item)["keyLabel"], "DOMAIN\\test")
        self.assertEqual(keys.annotate({**item, "user": "other"})["kind"], "ssh_accepted_unknown")
        path.write_text("invalid")
        keys.reload()
        self.assertEqual(keys.status["state"], "unavailable")
        self.assertEqual(keys.annotate(item)["keyStatus"], "unregistered")


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.networks = Networks(self.root)

    def tearDown(self):
        if self.networks.reader:
            self.networks.reader.close()
        self.directory.cleanup()

    def snapshot(self, feeds):
        (self.root / "networks.json").write_text(json.dumps({"version": 1, "feeds": feeds}))
        self.networks.reload_prefixes()

    def test_owner_cloud_and_vpn_evidence_remain_independent_for_ipv4_and_ipv6(self):
        self.snapshot({
            "aws": {"checkedAt": time.time(), "networks": ["8.8.8.0/24", "8.8.8.0/25", "2001:4860::/32"]},
            "mullvad": {"checkedAt": time.time(), "networks": ["8.8.8.8/32"]},
            "tor": {"checkedAt": time.time(), "networks": ["2001:4860:4860::8888/128"]},
        })
        (self.root / "ASN.mmdb").write_bytes(b"fixture")
        reader = Mock()
        reader.get.return_value = {"autonomous_system_number": 64512, "autonomous_system_organization": "Fixture Network"}
        reader.metadata.return_value.build_epoch = int(time.time())
        with patch("networks.maxminddb.open_database", return_value=reader):
            self.networks.reload()
        item = self.networks.enrich({"ip": IP})
        self.assertEqual((item["networkProvider"], item["asn"], item["networkOrganization"]), ("AWS", 64512, "Fixture Network"))
        self.assertIn("8.8.8.0/25", item["networkEvidence"])
        self.assertEqual(item["privacyServices"][0]["kind"], "vpn_server")
        self.assertIn("does not prove", item["privacyServices"][0]["evidence"])
        ipv6 = self.networks.enrich({"ip": "2001:4860:4860::8888"})
        self.assertEqual(ipv6["privacyServices"][0]["kind"], "tor_exit")
        unmatched = self.networks.enrich({"ip": "1.1.1.1"})
        self.assertNotIn("networkProvider", unmatched)
        self.assertEqual(unmatched["privacyServices"], [])
        self.assertEqual(self.networks.enrich({"ip": "10.0.0.1"}), {"ip": "10.0.0.1", "networkLookup": "not-public"})

    def test_expired_and_corrupt_datasets_withhold_attribution(self):
        self.snapshot({
            "aws": {"checkedAt": time.time() - 8 * 86400, "networks": ["8.8.8.0/24"]},
            "mullvad": {"checkedAt": time.time() - 3 * 86400, "networks": ["8.8.8.8/32"]},
        })
        item = self.networks.enrich({"ip": IP})
        self.assertNotIn("networkProvider", item)
        self.assertEqual(item["privacyServices"], [])
        self.assertEqual(self.networks.status["feeds"]["mullvad"]["state"], "stale")
        (self.root / "networks.json").write_text("{broken")
        with self.assertLogs("attacks", level="WARNING"):
            self.networks.reload_prefixes()
        self.assertEqual(self.networks.enrich({"ip": IP})["networkLookup"], "unavailable")

    def test_failed_refresh_retains_previous_data_without_refreshing_its_age(self):
        before = time.time() - 3600
        self.snapshot({"mullvad": {"checkedAt": before, "networks": ["8.8.8.8/32"]}})
        def download(url):
            if url == FEEDS["aws"][2]:
                return json.dumps({"prefixes": [{"ip_prefix": "8.8.8.0/24"}], "ipv6_prefixes": []})
            raise URLError("fixture offline")
        with self.assertLogs("attacks-intelligence", level="ERROR"):
            self.assertFalse(refresh_prefixes(self.root, download))
        saved = json.loads((self.root / "networks.json").read_text())["feeds"]
        self.assertEqual(saved["mullvad"]["checkedAt"], before)
        self.assertEqual(saved["mullvad"]["networks"], ["8.8.8.8/32"])
        self.assertIn("error", saved["mullvad"])
        self.assertGreater(saved["aws"]["checkedAt"], before)

    def test_official_feed_formats_and_pagination_fail_closed(self):
        fixtures = {
            "google": {"prefixes": [{"ipv4Prefix": "8.8.8.0/24"}, {"ipv6Prefix": "2001:4860::/32"}]},
            "oracle": {"regions": [{"cidrs": [{"cidr": "8.8.8.0/24"}]}]},
            "mullvad": [{"active": True, "ipv4_addr_in": IP}, {"active": False, "ipv4_addr_in": "1.1.1.1"}],
        }
        for name, data in fixtures.items():
            self.assertTrue(ranges(name, lambda url: json.dumps(data)))
        self.assertEqual(ranges("tor", lambda url: "# exit list\n8.8.8.8\n"), ["8.8.8.8/32"])
        azure_url = "https://download.microsoft.com/download/fixture/ServiceTags_Public_20261123.json"
        def azure(url):
            return azure_url if url == FEEDS["azure"][2] else json.dumps({"values": [
                {"name": "AzureCloud", "properties": {"addressPrefixes": ["8.8.8.0/24"]}},
                {"name": "AzureCloud.region", "properties": {"addressPrefixes": ["8.8.8.0/25"]}},
            ]})
        self.assertEqual(ranges("azure", azure), ["8.8.8.0/24"])
        page = json.dumps([{"id": i, "status": "online", "station": IP} for i in range(1000)])
        self.assertEqual(ranges("nordvpn", lambda url: page if "offset=0" in url else "[]"), ["8.8.8.8/32"])
        with self.assertRaisesRegex(ValueError, "repeated a page"):
            ranges("nordvpn", lambda url: page)
        with self.assertRaises(ValueError):
            ranges("google", lambda url: '{"prefixes":[{"ipv4Prefix":"0.0.0.0/0"}]}')

    def test_corrupt_database_lookup_does_not_stop_events_or_other_enrichment(self):
        self.snapshot({"aws": {"checkedAt": time.time(), "networks": ["8.8.8.0/24"]}})
        self.networks.reader = Mock()
        self.networks.reader.get.side_effect = maxminddb.InvalidDatabaseError("fixture corruption")
        with self.assertLogs("attacks", level="ERROR"):
            item = self.networks.enrich({"ip": IP})
        self.assertEqual(item["networkProvider"], "AWS")
        self.assertNotIn("asn", item)
        self.assertEqual(self.networks.status["asn"]["state"], "unavailable")
        geo = Geo(self.root / "missing.mmdb")
        geo.reader = Mock()
        geo.reader.get.side_effect = maxminddb.InvalidDatabaseError("fixture corruption")
        with self.assertLogs("attacks", level="ERROR"):
            self.assertEqual(geo.enrich(item)["location"], "Location unavailable")
        self.assertIsNone(geo.reader)


class QueryTests(unittest.TestCase):
    def test_escaped_filters_and_invalid_cursors(self):
        query, _, _ = event_query({"user": 'x" | line_format "secret', "ip": IP}, time.time())
        self.assertIn('user="x\\" | line_format \\"secret"', query)
        for params in ({"type": "x"}, {"range": "all"}, {"ip": "not-an-ip"},
                       {"before": "-1"}, {"query": "{}"}, {"before": "1", "after": "2"}):
            with self.assertRaises(BadRequest):
                event_query(params, time.time())
        with self.assertRaises(BadRequest):
            parameters("ip=a&ip=b")
        with self.assertRaises(ValueError):
            Client("https://user:secret@example.test/")

    def test_saturated_timestamp_fails_instead_of_skipping(self):
        client = Mock()
        client.query.return_value = [(1, "line", {})] * 1000
        with self.assertRaises(UpstreamError):
            window(client, "{}", 1, 1)

    def test_recursive_log_windows_preserve_all_rows(self):
        client = Mock()
        client.query.side_effect = lambda query, start, end: [(i, str(i), {}) for i in range(start, min(end + 1, start + 1000))]
        self.assertEqual(len(window(client, "{}", 1, 2500)), 2500)

    def test_api_deduplicates_crash_replay_and_bounds_pages(self):
        item = {"id": "one", "type": "ssh", "kind": "ssh_probe"}
        loki = Mock()
        loki.request.return_value = {"status": "success", "data": {"resultType": "streams", "result": [
            {"stream": {}, "values": [["123", json.dumps(item)], ["123", json.dumps(item)]]}
        ]}}
        api = API(loki, Mock(), Mock())
        self.assertEqual(len(api.events({})["events"]), 1)
        self.assertEqual(loki.request.call_args.args[1]["limit"], 251)

    def test_honeypot_totals_include_range_and_lifetime(self):
        prometheus = Mock()
        def result(path, params):
            query = params["query"]
            values = [] if "events_total" in query else [
                {"metric": {}, "value": [100, "15.5" if "increase(" in query else "120.75"]}
            ]
            return {"status": "success", "data": {"result": values}}
        prometheus.request.side_effect = result
        stats = API(Mock(), prometheus, Mock()).stats({})
        self.assertEqual(stats["trappedSeconds"], 15.5)
        self.assertEqual(stats["lifetimeTrappedSeconds"], 120.75)


if __name__ == "__main__":
    unittest.main()
