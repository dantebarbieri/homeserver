from datetime import datetime, timedelta, timezone
import base64
from contextlib import closing
import hashlib
import ipaddress
import json
import re
from pathlib import Path
import struct
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import maxminddb

import io
from abuseipdb import REPORT_DELAY, AbuseIPDB
from capture import interface_networks, packet
from collector import Collector, Geo, Store, window
from common import Client, UpstreamError
from events import (KINDS, SEVERITIES, SEVERITY, home_networks, kinds_at_least, parse_authelia, parse_endlessh,
                    parse_fail2ban, parse_flow, parse_forgejo_ssh, parse_hytale, parse_npm, parse_plex, parse_ssh,
                    refine, traffic_origin)
from server import API, NANO, BadRequest, event_query, parameters, reputation_match
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
        for path in ("/.aws/credentials", "/staging/phpinfo.php", "/_profiler/phpinfo", "/wp-config.php.bak",
                     "/.docker/config.json", "/backup.sql.gz", "/vendor/composer/installed.json", "/.ssh/id_rsa"):
            self.assertEqual(parse_npm(npm_line(path, 404))["kind"], "http_probe", path)
        # Forgejo serves repository files, and the wiki and Nextcloud are PHP.
        for path in ("/danteb/homeserver/raw/commit/abc/pi/sqlite-migrations/0001_init.sql", "/index.php",
                     "/index.php/core/preview", "/docker/.dockerignore"):
            self.assertIsNone(parse_npm(npm_line(path, 200)), path)
        self.assertIsNone(parse_npm(npm_line().replace(IP, "192.168.1.1")))

    def test_flow_is_not_called_an_attack(self):
        item = parse_flow(json.dumps({"schema": "attacks-flow-v1", "ip": IP, "port": 36676,
                                     "sourcePort": 1234, "protocol": "tcp"}), 100)
        self.assertEqual((item["type"], item["verdict"]), ("minecraft", "unclassified"))
        self.assertIsNone(parse_flow('{"schema":"attacks-flow-v1","ip":"127.0.0.1","port":36676}', 100))

    def test_forgejo_ssh_reuses_ssh_kinds_but_only_for_bare_sshd_lines(self):
        denied = parse_forgejo_ssh(f"User root from {IP} not allowed because not listed in AllowUsers", 100)
        self.assertEqual((denied["kind"], denied["service"], denied["port"], denied["type"]),
                         ("ssh_failure", "Forgejo SSH", 2222, "git"))
        self.assertEqual(parse_forgejo_ssh(f"Timeout before authentication for connection from {IP} to 192.168.128.52, pid = 9", 100)["kind"],
                         "ssh_disconnect")
        self.assertEqual(parse_forgejo_ssh(f"Unable to negotiate with {IP} port 5000: no matching key exchange method found.", 100)["kind"],
                         "ssh_probe")
        self.assertEqual(parse_forgejo_ssh(f"Connection reset by {IP} port 54741 [preauth]", 100)["kind"], "ssh_disconnect")
        # Application log lines can echo attacker-chosen text, and post-auth closes are routine.
        self.assertIsNone(parse_forgejo_ssh(f"2026/11/24 router: Failed login from {IP} port 22", 100))
        self.assertIsNone(parse_forgejo_ssh(f"Connection closed by {IP} port 5000", 100))
        host = parse_ssh(f"User root from {IP} not allowed because none of user's groups are listed in AllowGroups", 100)
        self.assertEqual((host["service"], host["port"], host["kind"]), ("SSH", 28, "ssh_failure"))

    def test_hytale_rejection_keeps_only_network_facts(self):
        line = ("[2026/11/24 21:45:51   INFO] [Hytale] Disconnecting QuicConnectionAddress{connId=1a2b} "
                f"(/{IP}:50000, streamId=0) (SNI: danteb.com) with the message: client.general.disconnect.invalidIdentityToken")
        item = parse_hytale(line, 100)
        self.assertEqual((item["kind"], item["service"], item["port"], item["protocol"], item["sni"]),
                         ("hytale_rejected", "Hytale", 5205, "udp", "danteb.com"))
        self.assertEqual(item["sourcePort"], 50000)
        self.assertIsNone(parse_hytale(line.replace("invalidIdentityToken", "other"), 100))
        self.assertIsNone(parse_hytale(line.replace(IP, "172.20.0.1"), 100))
        self.assertIsNone(parse_hytale("Playing(player=Alice) null (null, streamId=0)", 100))

    def test_plex_requests_are_classified_without_tokens_queries_or_accounts(self):
        def plex(request, flags=""):
            return parse_plex(f"Nov 24, 2026 09:56:57.701 [134702459300664] DEBUG - Request: [{IP}:55314 (WAN)] "
                              f"{request} (6 live) #74fa2 TLS GZIP{flags}")
        client = plex("GET /library/sections?X-Plex-Token=secret", " Signed-in Token (alice)")
        self.assertEqual(client["kind"], "plex_client")
        self.assertNotIn("alice", json.dumps(client))
        self.assertNotIn("secret", json.dumps(client))
        self.assertNotIn("path", client)
        self.assertEqual(plex("GET /identity")["kind"], "plex_public")
        stream = plex("GET /video/:/transcode/universal/session/0a1b2c3d-1111-2222-3333-444455556666/base/12.ts")
        self.assertEqual((stream["kind"], stream["path"]), ("plex_public", "/video/:/transcode/universal/session/[session]"))
        for request in ("GET /", "HEAD /", "GET /mcp", "GET /robots.txt", "PRI *"):
            self.assertEqual(plex(request)["kind"], "plex_probe", request)
        self.assertEqual(plex("GET /.env?x=secret")["path"], "/.env")
        for source in ("LAN", "Loopback"):
            self.assertIsNone(parse_plex(f"Nov 24, 2026 09:56:57.701 [1] DEBUG - Request: [{IP}:1 ({source})] GET / (6 live) #a"))
        self.assertIsNone(parse_plex("Nov 24, 2026 09:56:57.701 [1] DEBUG - Request: [192.168.1.5:1 (WAN)] GET / (6 live) #a"))
        # Local log time is converted using the configured zone.
        chicago = parse_plex("Jun 01, 2026 12:00:00.000 [1] DEBUG - Request: [8.8.8.8:1 (WAN)] GET / (1 live) #a",
                             timezone(timedelta(hours=-5)))
        self.assertEqual(chicago["timestamp"], datetime(2026, 6, 1, 17, tzinfo=timezone.utc).timestamp())

    def test_aws_identity_checks_are_retagged_as_probable_reachability(self):
        item = parse_plex(f"Nov 24, 2026 09:56:57.701 [1] DEBUG - Request: [{IP}:1 (WAN)] GET /identity (1 live) #a")
        self.assertEqual(refine({**item, "networkProvider": "AWS"})["kind"], "plex_reachability")
        self.assertEqual(refine({**item, "networkProvider": "Google Cloud"})["kind"], "plex_public")
        self.assertEqual(refine(item)["kind"], "plex_public")

    def test_severity_is_total_and_ordered(self):
        self.assertEqual(set(SEVERITY), set(KINDS))
        self.assertTrue(set(SEVERITY.values()) <= set(SEVERITIES))
        self.assertIn("ssh_failure", kinds_at_least("high"))
        self.assertNotIn("plex_probe", kinds_at_least("high"))
        self.assertEqual(kinds_at_least("critical"), ["ssh_accepted_unknown"])
        self.assertIn("plex_probe", kinds_at_least("suspicious"))


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
    def test_own_networks_follow_only_usable_uplink_addresses(self):
        content = (
            "20014860000100000000000000000001 02 40 00 80 bond0\n"
            "20014860000100000000000000000002 02 40 00 80 bond0\n"
            "20014860000200000000000000000001 02 40 00 40 bond0\n"
            "20014860000300000000000000000001 02 40 00 80 other0\n"
            "fd000000000000000000000000000001 02 40 00 80 bond0\n"
        )
        networks = interface_networks(content, "bond0")
        self.assertEqual(networks, ["2001:4860:1::/64"])
        heartbeat = parse_flow(json.dumps({"schema": "attacks-flow-v1", "heartbeat": True,
                                          "ownNetworks": networks}), 100)
        self.assertEqual(heartbeat["ownNetworks"], networks)
        for ip in ("192.168.50.2", "100.100.1.2", "127.0.0.1", "fd00::2", "2001:4860:1::abcd"):
            self.assertEqual(traffic_origin(ip, networks), "own")
        self.assertEqual(traffic_origin("2001:4860:2::1", networks), "external")
        self.assertEqual(traffic_origin(IP, networks), "external")
        for invalid in (["::/0"], ["2001:4860::/32"], ["10.0.0.0/8"], "2001:4860:1::/64"):
            with self.assertRaises(ValueError):
                home_networks(invalid)

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
        self.store.set("capture", {"timestamp": time.time(), "ownNetworks": []})
        self.item = parse_endlessh(f"CLOSE host={IP} port=1000 time=4.5 bytes=64", time.time())

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def test_replay_does_not_increment_counters(self):
        self.assertTrue(self.store.enqueue(self.item, "endlessh", "stable"))
        self.assertFalse(self.store.enqueue(self.item, "endlessh", "stable"))
        metrics = self.store.metrics()
        self.assertIn('kind="endlessh_close",type="endlessh",country="ZZ",origin="external"} 1', metrics)
        self.assertIn('attacks_endlessh_seconds_total{country="ZZ",origin="external"} 4.5', metrics)
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

    def test_upgrade_preserves_legacy_counters_cursors_and_pending_events(self):
        path = self.root / "legacy.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE counters (kind TEXT, category TEXT, country TEXT, count INTEGER, seconds REAL,
                                       PRIMARY KEY(kind,category,country));
                INSERT INTO counters VALUES ('endlessh_close','endlessh','ZZ',10,123.5);
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO meta VALUES ('started','100'), ('cursor:endlessh','12345');
                CREATE TABLE outbox (id TEXT PRIMARY KEY, ns INTEGER, body TEXT NOT NULL);
                INSERT INTO outbox VALUES ('pending',1000000000,'{}');
            """)
        store = Store(path, clock=lambda: 200)
        try:
            self.assertEqual(store.get("started"), 100)
            self.assertEqual(store.get("cursor:endlessh"), 12345)
            self.assertEqual(store.db.execute("SELECT * FROM outbox").fetchone(), ("pending", 1000000000, "{}"))
            self.assertIn('attacks_endlessh_seconds_total{country="ZZ",origin="legacy"} 123.5', store.metrics())
            self.assertIn('attacks_endlessh_seconds_total{country="ZZ",origin="external"} 0', store.metrics())
        finally:
            store.db.close()

    def test_live_traps_publish_with_delivery_survive_restart_and_ignore_own(self):
        now = [time.time() + 1]
        self.store.clock = lambda: now[0]
        opened = parse_endlessh(f"ACCEPT host={IP} port=1000 n=1/4096", now[0])
        self.store.enqueue(opened, "endlessh", "open")
        self.store.enqueue({**opened, "sourcePort": 1001, "origin": "own"}, "endlessh", "own-open")
        self.assertEqual(self.store.trapping()["connections"], 0)
        self.store.flush(Mock())
        now[0] += 10
        self.assertEqual(self.store.trapping()["seconds"], 10)
        self.assertEqual(self.store.trapping()["connections"], 1)
        path = self.root / "state.sqlite"
        self.store.db.close()
        self.store = Store(path, clock=lambda: now[0])
        self.assertEqual(self.store.trapping()["seconds"], 10)
        self.assertFalse(self.store.enqueue(opened, "endlessh", "open"))
        closed = parse_endlessh(f"CLOSE host={IP} port=1000 time=10 bytes=64", now[0])
        self.store.enqueue(closed, "endlessh", "close")
        # An undelivered close cannot disappear from the published active snapshot.
        before = self.store.trapping()
        self.assertEqual(before["connections"], 1)
        body = json.loads(self.store.db.execute("SELECT body FROM outbox").fetchone()[0])
        self.assertGreater(body["observedAt"], before["through"])
        failed = Mock()
        failed.request.side_effect = UpstreamError("offline")
        with self.assertRaises(UpstreamError):
            self.store.flush(failed)
        self.assertEqual(self.store.trapping()["through"], before["through"])
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["connections"], 0)
        self.assertIn('attacks_endlessh_seconds_total{country="ZZ",origin="external"} 10.0', self.store.metrics())
        # Late/replayed opens cannot resurrect a closed tuple.
        self.store.enqueue({**opened, "timestamp": now[0] - 5}, "endlessh", "late-open")
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["connections"], 0)
        now[0] += 1
        self.store.enqueue({**opened, "timestamp": now[0]}, "endlessh", "new-open")
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["connections"], 1)
        restarted = parse_endlessh("I1124 main.go:98] Listening on [ipv4]:2222", now[0] + 1)
        self.store.restart(restarted["timestamp"])
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["connections"], 0)
        self.assertIn('attacks_endlessh_seconds_total{country="ZZ",origin="external"} 10.0', self.store.metrics())
        now[0] += 2
        self.store.enqueue({**opened, "timestamp": now[0]}, "endlessh", "post-restart")
        self.store.flush(Mock())
        now[0] += 1
        # A changed home prefix must not prevent a matching close from retiring an open.
        self.store.enqueue({**closed, "timestamp": now[0], "origin": "own"}, "endlessh", "own-close")
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["connections"], 0)

    def test_published_active_sessions_name_open_connections_and_flag_truncation(self):
        now = [time.time() + 1]
        self.store.clock = lambda: now[0]
        opened = parse_endlessh(f"ACCEPT host={IP} port=1000 n=1/4096", now[0])
        self.store.enqueue(opened, "endlessh", "open")
        self.store.enqueue({**opened, "sourcePort": 1001, "origin": "own"}, "endlessh", "own-open")
        self.assertEqual(self.store.trapping()["active"], [])
        self.store.flush(Mock())
        trapping = self.store.trapping()
        self.assertEqual(trapping["active"], [{"ip": IP, "sourcePort": 1000, "since": opened["timestamp"]}])
        self.assertFalse(trapping["activeTruncated"])
        now[0] += 10
        self.store.enqueue(parse_endlessh(f"CLOSE host={IP} port=1000 time=10 bytes=64", now[0]), "endlessh", "close")
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["active"], [])
        with patch("collector.ACTIVE_SESSIONS_SHOWN", 2):
            for port in (2000, 2001, 2002):
                now[0] += 1
                self.store.enqueue({**opened, "timestamp": now[0], "sourcePort": port}, "endlessh", f"open-{port}")
            self.store.flush(Mock())
        trapping = self.store.trapping()
        self.assertEqual([item["sourcePort"] for item in trapping["active"]], [2002, 2001])
        self.assertTrue(trapping["activeTruncated"])
        self.assertEqual(trapping["connections"], 3)
        # A snapshot published before this field existed reports an unknown set, not an empty one.
        self.store.set("published", {"through": now[0], "sessions": [now[0] - 5]})
        old = self.store.trapping()
        self.assertEqual(old["active"], [])
        self.assertTrue(old["activeTruncated"])
        self.store.restart(now[0] + 1)
        self.store.flush(Mock())
        self.assertEqual(self.store.trapping()["active"], [])
        self.assertFalse(self.store.trapping()["activeTruncated"])

    def test_missing_own_network_metadata_retains_source_checkpoint(self):
        self.store.set("capture", {"timestamp": time.time()})
        client = Mock()
        client.query.return_value = [(time.time_ns(), f"ACCEPT host={IP} port=1000 n=1/4096", {})]
        collector = Collector(self.store, client, Mock(), self.root)
        with self.assertRaisesRegex(UpstreamError, "network metadata"):
            collector.raw("endlessh", time.time())
        self.assertIsNone(self.store.get("cursor:endlessh"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM outbox").fetchone()[0], 0)

    def test_messaging_port_without_game_contact_is_a_port_scan(self):
        collector = Collector(self.store, Mock(), Mock(), self.root)
        flow = lambda ip, port, at: parse_flow(json.dumps({"schema": "attacks-flow-v1", "ip": ip, "port": port,
                                                           "sourcePort": 1234, "protocol": "tcp"}), at)
        self.assertEqual(collector.companion(flow("8.8.4.4", 29778, 100))["kind"], "port_scan")
        collector.companion(flow("9.9.9.9", 7778, 100))
        self.assertEqual(collector.companion(flow("9.9.9.9", 29778, 102))["kind"], "service_connection")
        self.assertEqual(collector.companion(flow("9.9.9.9", 29778, 800))["kind"], "port_scan")
        self.assertEqual(collector.companion(flow("1.0.0.1", 7778, 100))["kind"], "service_connection")

    def test_steady_game_port_contacts_become_pollers_but_scanner_retries_do_not(self):
        collector = Collector(self.store, Mock(), Mock(), self.root)
        contact = lambda ip, at, port=5205: collector.polled(parse_flow(json.dumps({
            "schema": "attacks-flow-v1", "ip": ip, "port": port, "sourcePort": 1234, "protocol": "udp"}), at))
        poller = "148.113.200.55"
        self.assertEqual([contact(poller, at) for at in (1000, 1300, 1610, 1900)], [False, False, True, True])
        self.assertFalse(contact(poller, 1960), "an off-cadence retry is not a poll")
        self.assertTrue(contact(poller, 2200))
        self.assertTrue(contact(poller, 2202), "a poll's trailing packets share its verdict")
        rejected = lambda at: collector.polled({"kind": "hytale_rejected", "ip": poller, "port": 5205, "timestamp": at})
        self.assertTrue(rejected(2203))
        self.assertFalse(rejected(4000))
        self.assertEqual([contact(poller, at) for at in (2300, 2303)], [False, False],
                         "a retry's trailing packets are not polls either")
        # Scanners retry within seconds or minutes; their contacts never settle into a cadence.
        self.assertFalse(any(contact("45.56.79.53", at, 36676) for at in (1000, 1002, 1030, 1090, 1190, 1290, 1390)))
        self.assertFalse(any(contact("45.33.109.17", at, 32400) for at in (1000, 1300, 1600, 1900)))
        self.assertEqual(self.store.pollers(), [{"ip": poller, "port": 5205, "interval": 300,
                                                  "confirmed": 1610, "lastSeen": 2300}])
        self.store.db.close()
        self.store = Store(self.root / "state.sqlite")
        collector = Collector(self.store, Mock(), Mock(), self.root)
        self.assertTrue(contact(poller, 2500), "a restart keeps confirmed pollers")
        self.assertFalse(contact(poller, 2500 + 86401), "a day of silence starts over")
        self.assertEqual(self.store.pollers(), [{"ip": poller, "port": 5205, "interval": None,
                                                  "confirmed": 1610, "lastSeen": 2500 + 86401}])
        self.assertFalse(contact(poller, 1610 + 31 * 86400 + 1))
        self.assertEqual(self.store.pollers(), [], "a lapsed confirmation past Loki's retention is dropped")

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

    def test_us_locations_name_the_state(self):
        geo = Geo(self.root / "missing.mmdb")
        geo.reader = Mock()
        def record(country, nation, city, state):
            return {"country": {"iso_code": country, "names": {"en": nation}}, "city": {"names": {"en": city}},
                    "subdivisions": [{"names": {"en": state}}]}
        cases = [(record("US", "United States", "Cedar Park", "Texas"), "Cedar Park, TX, United States"),
                 (record("US", "United States", "Springfield", "Unlisted"), "Springfield, Unlisted, United States"),
                 (record("PR", "Puerto Rico", "San Juan", "San Juan"), "San Juan, Puerto Rico"),
                 (record("NL", "Netherlands", "Amsterdam", "North Holland"), "Amsterdam, Netherlands")]
        for value, expected in cases:
            geo.reader.get.return_value = value
            self.assertEqual(geo.enrich(self.item)["location"], expected)

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
        forgejo = parse_forgejo_ssh(f"Accepted publickey for git from {IP} port 1234 ssh2: ED25519 {fingerprint}", 100)
        self.assertEqual(keys.annotate({**forgejo, "user": "other"})["kind"], "ssh_accepted")
        path.write_text("invalid")
        keys.reload()
        self.assertEqual(keys.status["state"], "unavailable")
        self.assertEqual(keys.annotate(item)["keyStatus"], "unregistered")

    def test_plex_requests_are_summarised_per_source_and_window(self):
        logdir = self.root / "plex"
        logdir.mkdir()
        stamp = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M:%S.%f")[:-3]
        def request(ip, target, flags=""):
            return (f"{stamp} [1] DEBUG - Request: [{ip}:5000 (WAN)] {target} (1 live) #a TLS GZIP{flags}\n")
        (logdir / "Plex Media Server.log").write_text(
            request(IP, "GET /") * 5 + request(IP, "GET /robots.txt") + request(IP, "GET /library", " Token (a)") * 4
            + request("8.8.4.4", "GET /"), encoding="utf-8")
        geo = Mock()
        geo.enrich.side_effect = lambda value: value
        collector = Collector(self.store, Mock(), geo, self.root, plex=logdir)
        collector.keys, collector.networks = Mock(), Mock()
        collector.keys.annotate.side_effect = collector.networks.enrich.side_effect = lambda value: value
        self.store.set("capture", {"timestamp": time.time(), "ownNetworks": []})
        collector.plex_logs(time.time())
        metrics = self.store.metrics()
        self.assertIn('kind="plex_probe",type="plex",country="ZZ",origin="external"} 3', metrics)
        self.assertIn('kind="plex_client",type="plex",country="ZZ",origin="external"} 1', metrics)
        collector.plex_logs(time.time())
        self.assertEqual(metrics, self.store.metrics())


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
    def test_multi_value_severity_and_source_filters(self):
        query, _, _ = event_query({"type": "ssh,plex", "outcome": "failure,suspected", "severity": "high",
                                   "country": "NL", "asn": "14061", "ip": IP}, time.time())
        self.assertIn('type=~"ssh|plex"', query)
        self.assertIn('| verdict=~"failure|suspected"', query)
        self.assertIn('| kind=~"auth_failure|http_probe|ssh_accepted_unknown|ssh_ban|ssh_failure"', query)
        self.assertIn('| countryCode="NL" | asn="14061"', query)
        self.assertNotIn("kind=~", event_query({"severity": "info"}, time.time())[0])
        for params in ({"type": "ssh,ssh"}, {"type": "ssh,nope"}, {"outcome": "failure,"}, {"severity": "severe"},
                       {"country": "nl"}, {"country": 'N"'}, {"asn": "0"}, {"asn": "AS1"}, {"user": "root"}):
            with self.assertRaises(BadRequest, msg=params):
                event_query(params, time.time())

    def test_invalid_cursors_and_parameters(self):
        for params in ({"type": "x"}, {"range": "all"}, {"ip": "not-an-ip"},
                       {"before": "-1"}, {"query": "{}"}, {"before": "1", "after": "2"}, {"own": "yes"}):
            with self.assertRaises(BadRequest):
                event_query(params, time.time())
        with self.assertRaises(BadRequest):
            parameters("ip=a&ip=b")
        with self.assertRaises(ValueError):
            Client("https://user:secret@example.test/")

    def test_events_carry_severity_and_sources_are_bounded_facets(self):
        item = {"id": "one", "type": "plex", "kind": "plex_probe", "ip": IP}
        loki = Mock()
        loki.request.side_effect = lambda path, params: (
            {"status": "success", "data": {"resultType": "streams", "result": [
                {"stream": {}, "values": [["123", json.dumps(item)]]}]}} if "query_range" in path else
            {"status": "success", "data": {"resultType": "vector", "result": [
                {"metric": {"countryCode": "NL", "asn": "14061", "networkOrganization": "DigitalOcean"}, "value": [1, "7"]},
                {"metric": {"countryCode": "", "asn": ""}, "value": [1, "99"]}]}})
        collector = Mock()
        collector.request.return_value = {"ownTraffic": {"state": "ready", "networks": []}}
        api = API(loki, Mock(), collector)
        self.assertEqual(api.events({})["events"][0]["severity"], "suspicious")
        sources = api.sources({"range": "7d"})
        self.assertEqual(sources["countries"], [{"countryCode": "NL", "asn": "14061",
                                                 "networkOrganization": "DigitalOcean", "count": 7.0}])
        self.assertEqual(sources["networks"][0]["asn"], "14061")
        with self.assertRaises(BadRequest):
            api.sources({"range": "7d", "type": "ssh"})

    def test_facets_merge_kinds_into_severity_and_reject_picker_filters(self):
        loki = Mock()
        loki.request.return_value = {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"type": "plex", "verdict": "observed", "kind": "plex_client"}, "value": [1, "4"]},
            {"metric": {"type": "plex", "verdict": "observed", "kind": "plex_reachability"}, "value": [1, "2"]},
            {"metric": {"type": "plex", "verdict": "observed", "kind": "plex_public"}, "value": [1, "3"]},
            {"metric": {"type": "nope", "verdict": "observed", "kind": "x"}, "value": [1, "9"]}]}}
        collector = Mock()
        collector.request.return_value = {"ownTraffic": {"state": "ready", "networks": []}}
        result = API(loki, Mock(), collector).facets({"range": "7d", "country": "NL"})
        self.assertCountEqual(result["counts"], [
            {"type": "plex", "outcome": "observed", "severity": "info", "count": 6.0},
            {"type": "plex", "outcome": "observed", "severity": "low", "count": 3.0}])
        query = loki.request.call_args[0][1]["query"]
        self.assertIn('| countryCode="NL"', query)
        self.assertIn("keep type,verdict,kind [7d]", query)
        self.assertIn('origin!~"own|poller"', query)
        for params in ({"type": "ssh"}, {"severity": "high"}, {"outcome": "failure"}, {"after": "1"}):
            with self.assertRaises(BadRequest, msg=params):
                API(loki, Mock(), collector).facets(params)

    def test_reputation_match_mirrors_the_pickers_and_needs_a_key(self):
        grades = {"high": ["1.2.3.4"], "medium": ["5.6.7.8"], "clean": ["2001:db8::1"], "reported": ["9.9.9.9", "1.2.3.4"]}
        matched = lambda value: {ip for ip in ("1.2.3.4", "5.6.7.8", "2001:db8::1", "9.9.9.9", "7.7.7.7")
                                 if reputation_match(value.split(","), grades)(ip)}
        self.assertEqual(matched("high,reported"), {"1.2.3.4", "9.9.9.9"})
        self.assertEqual(matched("unchecked"), {"9.9.9.9", "7.7.7.7"})  # Reporting doesn't grade an address.
        self.assertEqual(matched("medium"), {"5.6.7.8"})
        with self.assertRaises(BadRequest):
            reputation_match(["high"], None)
        for value in ("severe", "high,high"):
            with self.assertRaises(BadRequest, msg=value):
                event_query({"reputation": value}, time.time())
        self.assertNotIn("ip=~", event_query({"reputation": "high"}, time.time())[0])

    def test_reputation_events_are_filtered_in_python_across_bounded_pages(self):
        lines = [(str(1000 - i), {"id": str(i), "type": "ssh", "kind": "ssh_failure",
                                   "ip": "1.2.3.4" if i in (0, 299, 400, 598, 800) else "8.8.8.8"}) for i in range(1000)]
        calls = []

        def query_range(path, params):
            calls.append(params)
            if "query_range" not in path:
                at, seconds = int(params["time"]), int(re.search(r"\[(\d+)s\]", params["query"])[1])
                inside = [item for ns, item in lines if at - seconds * NANO < int(ns) <= at]
                return {"status": "success", "data": {"resultType": "vector", "result": [
                    {"metric": {"ip": ip}, "value": [1, str(sum(item["ip"] == ip for item in inside))]}
                    for ip in ("1.2.3.4", "8.8.8.8")]}}
            rows = [(ns, item) for ns, item in lines if params["start"] <= int(ns) < params["end"]]  # Loki's end is exclusive.
            rows = rows[:params["limit"]] if params["direction"] == "backward" else rows[::-1][:params["limit"]]
            return {"status": "success", "data": {"resultType": "streams", "result": [
                {"stream": {}, "values": [[ns, json.dumps(item)] for ns, item in rows]}]}}
        loki = Mock()
        loki.request.side_effect = query_range
        collector = Mock()
        grades = {"enabled": True, "grades": {"high": ["1.2.3.4"], "medium": [], "clean": [], "reported": []}}
        collector.request.side_effect = lambda path, params=None: grades if path == "/reputation/grades" else (
            {} if path == "/reputation" else {"ownTraffic": {"state": "ready", "networks": []}})
        api = API(loki, Mock(), collector)
        with patch("server.time.time", return_value=2000 / NANO), patch("server.SCAN_PAGE", 300), patch("server.SCAN_PAGES", 2):
            first = api.events({"reputation": "high"})
            # Two pages of 300 cover cursors 1000..403. Each page's boundary timestamp (701, then 402)
            # is read again whole: id 299 by the second page, id 598 by the next request.
            self.assertEqual([item["id"] for item in first["events"]], ["0", "299", "400"])
            self.assertTrue(first["more"])
            self.assertEqual(first["next"], "403")
            rest = api.events({"reputation": "high", "before": first["next"]})
            # The count says both are found, so the scan stops without reading the oldest page,
            # but still offers a cursor in case the count missed late-delivered events.
            self.assertEqual([item["id"] for item in rest["events"]], ["598", "800"])
            self.assertEqual(sum("direction" in params for params in calls), 3)
            self.assertTrue(rest["more"])
            calls.clear()
            end = api.events({"reputation": "high", "before": rest["next"]})
        self.assertEqual((end["events"], end["more"]), ([], False))
        self.assertEqual(len(calls), 1)  # Nothing left to match: only the count query runs.
        grades["grades"]["high"] = []
        calls.clear()
        self.assertEqual(api.events({"reputation": "high"})["events"], [])
        self.assertEqual(len(calls), 1)  # Nothing matches: only the count query runs.
        self.assertTrue(all("ip=~" not in params["query"] and '| ip="' not in params["query"] for params in calls))

    def test_facets_split_counts_by_reputation_only_with_a_key(self):
        loki = Mock()
        loki.request.return_value = {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"type": "ssh", "verdict": "failure", "kind": "ssh_failure", "ip": ip}, "value": [1, "2"]}
            for ip in ("1.2.3.4", "5.6.7.8", "9.9.9.9", "7.7.7.7")]}}
        collector = Mock()
        grades = {"enabled": True, "grades": {"high": ["1.2.3.4"], "medium": [], "clean": ["5.6.7.8"], "reported": ["1.2.3.4", "9.9.9.9"]}}
        collector.request.side_effect = lambda path, params=None: grades if path == "/reputation/grades" else {
            "ownTraffic": {"state": "ready", "networks": []}}
        result = API(loki, Mock(), collector).facets({"range": "24h"})
        self.assertTrue(result["reputation"])
        self.assertCountEqual([(row["reputation"], row["reported"], row["count"]) for row in result["counts"]],
                              [("high", True, 2), ("clean", False, 2), ("unchecked", True, 2), ("unchecked", False, 2)])
        self.assertEqual(loki.request.call_count, 1)
        query = loki.request.call_args[0][1]["query"]
        self.assertIn("sum by (type,verdict,kind,ip)", query)
        self.assertNotIn("ip=~", query)
        grades = {"enabled": False}
        loki.request.reset_mock()
        loki.request.return_value = {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"type": "ssh", "verdict": "failure", "kind": "ssh_failure"}, "value": [1, "2"]}]}}
        result = API(loki, Mock(), collector).facets({"range": "24h"})
        self.assertFalse(result["reputation"])
        self.assertEqual(loki.request.call_count, 1)
        self.assertNotIn("reputation", result["counts"][0])
        self.assertIn("sum by (type,verdict,kind) ", loki.request.call_args[0][1]["query"])

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
        item = {"id": "one", "type": "ssh", "kind": "ssh_probe", "ip": "100.100.1.2"}
        loki = Mock()
        loki.request.return_value = {"status": "success", "data": {"resultType": "streams", "result": [
            {"stream": {}, "values": [["123", json.dumps(item)], ["123", json.dumps(item)]]}
        ]}}
        collector = Mock()
        collector.request.return_value = {"ownTraffic": {"state": "ready", "networks": ["2001:4860:1::/64"]}}
        api = API(loki, Mock(), collector)
        events = api.events({"own": "1"})["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["origin"], "own")
        self.assertNotIn('origin!="own"', loki.request.call_args.args[1]["query"])
        self.assertEqual(loki.request.call_args.args[1]["limit"], 251)
        api.events({})
        query = loki.request.call_args.args[1]["query"]
        self.assertIn('origin!~"own|poller"', query)
        self.assertIn('ip != ip("100.64.0.0/10")', query)
        self.assertIn('ip != ip("2001:4860:1::/64")', query)

    def test_known_pollers_are_hidden_unless_requested_and_marked_when_shown(self):
        rows = [{"id": "poll", "type": "game", "kind": "service_connection", "ip": "208.69.78.130", "port": 5205,
                 "origin": "external", "timestamp": 50},
                {"id": "retry", "type": "game", "kind": "service_connection", "ip": "208.69.78.130", "port": 5205,
                 "origin": "external", "timestamp": 90},
                {"id": "scan", "type": "game", "kind": "service_connection", "ip": "208.69.78.130", "port": 36676,
                 "origin": "external", "timestamp": 50},
                {"id": "new", "type": "game", "kind": "service_connection", "ip": "148.113.200.55", "port": 5205,
                 "origin": "poller", "timestamp": 90}]
        loki = Mock()
        loki.request.return_value = {"status": "success", "data": {"resultType": "streams", "result": [
            {"stream": {}, "values": [[str(100 + i), json.dumps(row)] for i, row in enumerate(rows)]}]}}
        collector = Mock()
        collector.request.return_value = {"ownTraffic": {"state": "ready", "networks": []},
                                          "pollers": [{"ip": "208.69.78.130", "port": 5205, "confirmed": 80}]}
        api = API(loki, Mock(), collector)
        api.events({})
        query = loki.request.call_args.args[1]["query"]
        self.assertIn('origin!~"own|poller"', query)
        self.assertIn('| (ip != "208.69.78.130" or port != "5205" or timestamp >= 80.000000)', query)
        origins = {item["id"]: item["origin"] for item in api.events({"pollers": "1"})["events"]}
        # Only contacts from before confirmation are the poller's; later external ones were judged retries.
        self.assertEqual(origins, {"poll": "poller", "retry": "external", "scan": "external", "new": "poller"})
        query = loki.request.call_args.args[1]["query"]
        self.assertIn('origin!="own"', query)
        self.assertNotIn("208.69.78.130", query)
        for bad in ({"ip": '1.2.3.4" or ip != "', "port": 5205, "confirmed": 80},
                    {"ip": "1.2.3.4", "port": 5205, "confirmed": "nan"}, {"ip": "1.2.3.4", "port": 5205}):
            collector.request.return_value["pollers"] = [bad]
            with self.assertRaises(UpstreamError):
                api.events({})
        with self.assertRaises(BadRequest):
            event_query({"pollers": "yes"}, 1000)

    def test_endlessh_time_totals_include_range_and_lifetime(self):
        prometheus = Mock()
        prometheus.request.return_value = {"status": "success", "data": {"result": [
            {"metric": {}, "value": [100, "120.75"]}]}}
        loki = Mock()
        def result(path, params):
            query = params["query"]
            if "start" in params:
                return {"status": "success", "data": {"resultType": "matrix", "result": [
                    {"metric": {}, "values": [[int(params["end"]) // 1_000_000_000, "3"]]}]}}
            values = [] if "sum by" in query else [{"metric": {}, "value": [100, "15.5" if "unwrap duration" in query else "3"]}]
            return {"status": "success", "data": {"resultType": "vector", "result": values}}
        loki.request.side_effect = result
        collector = Mock()
        collector.request.return_value = {"ownTraffic": {"state": "ready", "networks": []},
            "trapping": {"through": 100, "seconds": 12, "connections": 2, "available": True, "since": 90}}
        with patch("server.time.time", return_value=100000):
            stats = API(loki, prometheus, collector).stats({})
        self.assertEqual(stats["trappedSeconds"], 15.5)
        self.assertEqual(stats["lifetimeTrappedSeconds"], 120.75)
        self.assertEqual(stats["trapping"]["seconds"], 12)
        self.assertTrue(stats["available"])  # A valid empty window is zero, not a scrape failure.
        self.assertEqual(stats["sources"], 0)
        self.assertEqual(collector.request.call_args_list[-1].args, ("/reputation/summary", {"since": "13600"}))
        self.assertEqual(len(stats["timeline"]), 121)
        self.assertEqual(stats["timeline"][0][1], "0")
        self.assertEqual(float(stats["timeline"][-1][1]), 3)
        self.assertIn('origin="external"', prometheus.request.call_args.args[1]["query"])
        self.assertTrue(all("observedAt <= 100.000000" in call.args[1]["query"] for call in loki.request.call_args_list))


class FakeAbuseIPDB:
    def __init__(self):
        self.calls, self.replies = [], []

    def open(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url, request.data))
        status, body, headers = self.replies.pop(0) if self.replies else (200, {"data": {"abuseConfidenceScore": 0}}, {})
        if status >= 400:
            raise HTTPError(request.full_url, status, "error", headers, io.BytesIO(json.dumps(body).encode()))
        response = Mock(status=status)
        response.read.return_value = json.dumps(body).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response


class AbuseIPDBTests(unittest.TestCase):
    IP = "8.8.4.4"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = 1_800_000_000.0
        self.http = FakeAbuseIPDB()
        self.abuse = AbuseIPDB(Path(self.dir.name) / "a.sqlite", "key", clock=lambda: self.now, opener=self.http)
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(self.abuse.db.close)

    def event(self, kind, ip=IP, origin="external", age=0):
        self.abuse.observe({"ip": ip, "kind": kind, "origin": origin, "timestamp": self.now - age})

    def drain(self):
        while self.abuse.work():
            pass

    def reports(self):
        return [call for call in self.http.calls if call[0] == "POST"]

    def test_threshold_and_delay_gate_a_fixed_comment_report(self):
        self.event("ssh_failure"); self.event("ssh_failure")
        self.now += REPORT_DELAY; self.drain()
        self.assertEqual(self.reports(), [])
        self.event("ssh_failure")
        self.drain()
        self.assertEqual(self.reports(), [], "a report waits for REPORT_DELAY")
        self.now += REPORT_DELAY; self.drain()
        (_, url, form), = self.reports()
        self.assertTrue(url.endswith("/report"))
        self.assertIn(b"categories=18%2C22", form)
        self.assertEqual(self.abuse.lookup([self.IP])[self.IP]["reportedAt"], self.now)
        for _ in range(3):
            self.event("ssh_failure")
        self.now += REPORT_DELAY; self.drain()
        self.assertEqual(len(self.reports()), 1, "at most one report a day per address")

    def test_successful_sign_in_cancels_a_queued_report(self):
        for _ in range(3):
            self.event("ssh_failure")
        self.event("ssh_accepted")
        self.now += REPORT_DELAY; self.drain()
        self.assertEqual(self.reports(), [])

    def test_own_private_old_and_unruled_events_are_not_reported(self):
        for _ in range(5):
            self.event("ssh_failure", origin="own")
            self.event("ssh_failure", ip="192.168.1.5")
            self.event("ssh_failure", ip="9.9.9.9", age=2 * 86400)
            self.event("service_connection", ip="1.0.0.1")
            self.event("port_scan", ip="1.0.0.2")
        self.now += REPORT_DELAY; self.drain()
        self.assertEqual(self.reports(), [])
        checked = {url.split("ipAddress=")[1].split("&")[0] for _, url, _ in self.http.calls}
        self.assertEqual(checked, {"9.9.9.9", "1.0.0.1", "1.0.0.2"})

    def test_one_guessed_ssh_username_is_reported_but_a_real_account_needs_repeats(self):
        for ip, reason in (("1.0.0.1", "Username does not exist"),
                           ("1.0.0.2", "Account is not permitted to log in over SSH"),
                           (self.IP, "Public key rejected")):
            self.abuse.observe({"ip": ip, "kind": "ssh_failure", "origin": "external", "timestamp": self.now,
                                "rejectionReason": reason})
        self.now += REPORT_DELAY; self.drain()
        sent = sorted(form for _, _, form in self.reports())
        self.assertEqual(len(sent), 2)
        self.assertTrue(all(b"categories=18%2C22" in form and b"guessed+username" in form for form in sent))
        self.assertEqual({self.abuse.lookup([ip])[ip].get("reportedAt") is not None for ip in ("1.0.0.1", "1.0.0.2")}, {True})

    def test_repeated_ssh_port_probes_and_login_form_rejections_are_reported(self):
        for _ in range(3):
            self.event("ssh_probe", ip="1.0.0.1")
            self.event("ssh_probe", ip="1.0.0.3")
        self.event("ssh_accepted", ip="1.0.0.3")
        for path in ["/login"] * 10 + ["/api/v1/auth/local"] * 9:
            for ip, method in (("1.0.0.2", "POST"), ("1.0.0.4", "GET")):
                self.abuse.observe({"ip": ip, "kind": "http_denied", "origin": "external", "timestamp": self.now,
                                    "method": method, "path": path})
        for _ in range(20):
            self.abuse.observe({"ip": self.IP, "kind": "http_denied", "origin": "external", "timestamp": self.now,
                                "method": "POST", "path": "/api/auth/refresh"})
        self.now += REPORT_DELAY; self.drain()
        sent = {form.split(b"&")[0]: form for _, _, form in self.reports()}
        self.assertEqual(set(sent), {b"ip=1.0.0.1", b"ip=1.0.0.2"})
        self.assertIn(b"categories=14%2C22", sent[b"ip=1.0.0.1"])
        self.assertIn(b"categories=18%2C21", sent[b"ip=1.0.0.2"])

    def test_one_endlessh_visit_is_reported_as_an_ssh_port_scan_unless_a_sign_in_follows(self):
        self.event("endlessh_open")
        self.event("endlessh_open", ip="1.0.0.1")
        self.event("ssh_accepted", ip="1.0.0.1")
        self.now += REPORT_DELAY; self.drain()
        (_, _, form), = self.reports()
        self.assertIn(b"ip=8.8.4.4", form)
        self.assertIn(b"categories=14%2C22", form)
        start = self.now
        self.now += 86401
        self.event("endlessh_open")
        self.now += REPORT_DELAY; self.drain()
        self.assertEqual(self.abuse.summary(start - 3600), {"reports": 2, "sources": 1})
        self.assertEqual(self.abuse.summary(start + 3600), {"reports": 1, "sources": 1})

    def test_lookups_are_cached_for_a_day(self):
        self.http.replies.append((200, {"data": {"abuseConfidenceScore": 87, "totalReports": 4, "numDistinctUsers": 2}}, {}))
        self.abuse.lookup([self.IP]); self.drain()
        self.assertEqual(self.abuse.lookup([self.IP])[self.IP]["score"], 87)
        self.drain()
        self.assertEqual(len(self.http.calls), 1)
        self.now += 86401
        self.abuse.lookup([self.IP]); self.drain()
        self.assertEqual(len(self.http.calls), 2)

    def test_grades_group_checked_and_reported_addresses(self):
        self.http.replies.append((200, {"data": {"abuseConfidenceScore": 87, "totalReports": 4, "numDistinctUsers": 2}}, {}))
        self.abuse.lookup([self.IP]); self.drain()
        self.assertEqual(self.abuse.grades(self.now)["high"], [self.IP])
        self.assertEqual(self.abuse.grades(self.now + 2 * 86400)["high"], [], "a stale answer cannot match newer events")

    def test_rate_limit_pauses_calls(self):
        self.http.replies.append((429, {}, {"Retry-After": "600"}))
        self.abuse.lookup([self.IP]); self.drain()
        self.assertEqual(self.abuse.status()["state"], "error")
        self.now += 300; self.drain()
        self.assertEqual(len(self.http.calls), 1)
        self.now += 301; self.drain()
        self.assertEqual(len(self.http.calls), 2)
        self.assertEqual(self.abuse.status()["state"], "ready")

    def test_duplicate_report_rejection_counts_as_reported(self):
        self.abuse.lookup([self.IP]); self.drain()
        for _ in range(2):
            self.event("http_probe")
        self.http.replies.append((422, {"errors": [{"detail": "already reported"}]}, {}))
        self.now += REPORT_DELAY; self.drain()
        self.assertIn("reportedAt", self.abuse.lookup([self.IP])[self.IP])

    def test_disabled_without_key(self):
        abuse = AbuseIPDB(Path(self.dir.name) / "b.sqlite", "", opener=self.http)
        self.addCleanup(abuse.db.close)
        abuse.observe({"ip": self.IP, "kind": "ssh_failure", "origin": "external", "timestamp": time.time()})
        self.assertEqual((abuse.lookup([self.IP]), abuse.work(), abuse.status()["state"]), ({}, False, "disabled"))
        self.assertEqual(self.http.calls, [])

if __name__ == "__main__":
    unittest.main()
