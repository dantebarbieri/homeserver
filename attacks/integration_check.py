"""Opt-in Linux Docker integration test; never connects to production backends."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Docker {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def http(base, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        body = response.read()
        return json.loads(body) if response.headers.get("Content-Type", "").startswith("application/json") else body.decode()


def eventually(check, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (URLError, OSError, ValueError, AssertionError) as error:
            last = error
        time.sleep(2)
    raise AssertionError(f"Integration condition timed out ({last})")


def run(image, subnet=None):
    if sys.platform != "linux":
        raise SystemExit("Run this integration check on a Linux Docker host (container IPs are private).")
    if subnet:
        subnet = str(ipaddress.ip_network(subnet, strict=True))
    prefix = "attacks-test-" + uuid.uuid4().hex[:8]
    names = {role: prefix + "-" + role for role in ("loki", "prometheus", "collector", "web")}
    volume = prefix + "-state"
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
        root = Path(temporary)
        os.chmod(root, 0o755)
        for directory in ("npm", "keys", "geo"):
            (root / directory).mkdir()
        stamp = datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S %z")
        (root / "npm" / "proxy-host-1_access.log").write_text(
            f'[{stamp}] - 404 404 - GET https example.test "/.env?password=DO-NOT-STORE" [Client 8.8.8.8]\n'
            f'[{stamp}] - 200 200 - GET https example.test "/" [Client 8.8.8.8]\n'
        )
        key = b"\x00\x00\x00\x0bssh-ed25519" + b"\x00\x00\x00\x20" + bytes(range(32))
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
        (root / "keys" / "ssh-keys.json").write_text(json.dumps({
            "fixture-user": ["ssh-ed25519 " + base64.b64encode(key).decode() + " fixture-key"]
        }))
        (root / "geo" / "networks.json").write_text(json.dumps({"version": 1, "feeds": {
            "aws": {"checkedAt": time.time(), "networks": ["8.8.8.0/24"]},
            "mullvad": {"checkedAt": time.time(), "networks": ["8.8.8.8/32"]},
        }}))
        (root / "prometheus.yml").write_text(
            "global:\n  scrape_interval: 1s\nscrape_configs:\n"
            "  - job_name: attacks\n    static_configs:\n      - targets: ['attacks-collector:9108']\n"
        )
        try:
            docker("network", "create", "--internal", *(["--subnet", subnet] if subnet else []), prefix)
            docker("volume", "create", volume)
            docker("run", "--rm", "--network", "none", "--user", "0:0",
                   "-v", volume + ":/state", "--entrypoint", "sh", image,
                   "-c", "chown 65534:65534 /state")
            docker("run", "-d", "--name", names["loki"], "--network", prefix,
                   "--network-alias", "loki", "grafana/loki:latest",
                   "-config.file=/etc/loki/local-config.yaml")
            docker("run", "-d", "--name", names["prometheus"], "--network", prefix,
                   "--network-alias", "prometheus", "-v", str(root / "prometheus.yml") + ":/etc/prometheus/prometheus.yml:ro",
                   "prom/prometheus:latest")
            docker("run", "-d", "--name", names["collector"], "--network", prefix,
                   "--network-alias", "attacks-collector", "--read-only", "--cap-drop", "ALL",
                   "-v", volume + ":/state", "-v", str(root / "npm") + ":/npm:ro",
                   "-v", str(root / "keys") + ":/keys:ro", "-v", str(root / "geo") + ":/geo:ro",
                   image, "python", "collector.py")
            docker("run", "-d", "--name", names["web"], "--network", prefix,
                   "--read-only", "--cap-drop", "ALL", image)
            addresses = {}
            for role, name in names.items():
                ip = docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name)
                addresses[role] = f"http://{ip}:{dict(loki=3100, prometheus=9090, collector=9108, web=8080)[role]}"
            eventually(lambda: http(addresses["loki"], "/ready"))
            eventually(lambda: http(addresses["web"], "/healthz"))
            ns = time.time_ns()
            fixtures = [
                ({"container": "endlessh"}, ["ACCEPT host=8.8.8.8 port=1234 n=1/4096",
                                           "CLOSE host=8.8.8.8 port=1234 time=120.5 bytes=200"]),
                ({"container": "authelia"}, [
                    'level=error msg="Unsuccessful 1FA authentication attempt by user \'fixture-user\'" remote_ip=8.8.8.8',
                    'level=info msg="Access is not authorized, responding with status code 401" remote_ip=8.8.8.8',
                ]),
                ({"security_source": "ssh"}, [
                    "Invalid user guest from 8.8.8.8 port 1234",
                    f"Accepted publickey for fixture-user from 8.8.8.8 port 1235 ssh2: ED25519 {fingerprint}",
                    "Accepted publickey for other-user from 8.8.8.8 port 1236 ssh2: ED25519 SHA256:unknown",
                    f"Accepted publickey for fixture-user from 100.100.1.2 port 1237 ssh2: ED25519 {fingerprint}",
                    f"Accepted publickey for fixture-user from 2001:4860:1::123 port 1238 ssh2: ED25519 {fingerprint}",
                ]),
                ({"security_source": "fail2ban"}, ["[sshd] Ban 8.8.8.8"]),
                ({"security_source": "connections"}, [
                    json.dumps({"schema": "attacks-flow-v1", "heartbeat": True, "suppressed": 2,
                                "ownNetworks": ["2001:4860:1::/64"]}),
                    json.dumps({"schema": "attacks-flow-v1", "ip": "8.8.8.8", "port": 36676, "sourcePort": 5000, "protocol": "tcp"}),
                ]),
            ]
            http(addresses["loki"], "/loki/api/v1/push", {"streams": [
                {"stream": labels, "values": [[str(ns + i), line] for i, line in enumerate(lines)]}
                for labels, lines in fixtures
            ]})
            events = eventually(lambda: (result if len((result := http(addresses["web"], "/api/events"))["events"]) == 9 else None))
            rows = events["events"]
            assert {item["kind"] for item in rows} == {
                "endlessh_open", "endlessh_close", "auth_failure", "ssh_failure",
                "ssh_accepted", "ssh_accepted_unknown", "ssh_ban", "service_connection", "http_probe",
            }
            assert "DO-NOT-STORE" not in json.dumps(rows)
            assert all(item["networkProvider"] == "AWS" for item in rows)
            assert all(item["privacyServices"][0]["name"] == "Mullvad" for item in rows)
            assert next(item for item in rows if item["kind"] == "ssh_accepted")["keyLabel"] == "fixture-key"
            filtered = http(addresses["web"], "/api/events?" + urlencode({"outcome": "accepted,failure", "severity": "critical"}))
            assert [item["kind"] for item in filtered["events"]] == ["ssh_accepted_unknown"]
            own = http(addresses["web"], "/api/events?own=1")["events"]
            assert len(own) == 11 and sum(item["origin"] == "own" for item in own) == 2
            stats = eventually(lambda: (result if (result := http(addresses["web"], "/api/stats"))["lifetimeTrappedSeconds"] == 120.5 else None))
            assert stats["available"]
            assert sum(item["value"] for item in stats["totals"]) == 9
            assert stats["trappedSeconds"] == 120.5
            assert any(float(number) > 0 for _, number in stats["timeline"])
            assert stats["trapping"]["connections"] == 0
            metrics = http(addresses["collector"], "/metrics")
            assert "8.8.8.8" not in metrics and "fixture-user" not in metrics
            assert http(addresses["web"], "/api/status")["geo"]["state"] == "unavailable"
            time.sleep(5)
            assert len(http(addresses["web"], "/api/events")["events"]) == 9
            def push_endlessh(line):
                http(addresses["loki"], "/loki/api/v1/push", {"streams": [
                    {"stream": {"container": "endlessh"}, "values": [[str(time.time_ns()), line]]}]})
            push_endlessh("ACCEPT host=8.8.8.8 port=9999 n=1/4096")
            active = eventually(lambda: (s if (s := http(addresses["web"], "/api/stats"))["trapping"]["connections"] == 1 else None))
            time.sleep(2)
            later = http(addresses["web"], "/api/stats")
            assert later["trapping"]["seconds"] > active["trapping"]["seconds"]
            assert later["trappedSeconds"] == 120.5
            push_endlessh("CLOSE host=8.8.8.8 port=9999 time=8 bytes=200")
            closed = eventually(lambda: (s if (s := http(addresses["web"], "/api/stats"))["trappedSeconds"] == 128.5 else None))
            assert closed["trapping"]["connections"] == 0
            # Legacy unlabeled events are filtered in-place, never re-imported.
            old_ns = time.time_ns() - 1_000_000_000
            legacy = {"id": "legacy-own", "type": "ssh", "kind": "ssh_accepted", "ip": "100.100.1.3",
                      "observedAt": old_ns / 1e9, "timestamp": old_ns / 1e9}
            http(addresses["loki"], "/loki/api/v1/push", {"streams": [
                {"stream": {"job": "attacks", "type": "ssh", "kind": "ssh_accepted"},
                 "values": [[str(old_ns), json.dumps(legacy)]]}]})
            assert not any(item["id"] == "legacy-own" for item in http(addresses["web"], "/api/events")["events"])
            assert next(item for item in http(addresses["web"], "/api/events?own=1")["events"]
                        if item["id"] == "legacy-own")["origin"] == "own"
            print("PASS: isolated source ingestion, own/legacy filtering, exact Loki totals and nonzero timeline, Prometheus counters, live open/close accounting, replay deduplication, credential redaction.")
        except (AssertionError, RuntimeError, OSError, ValueError, KeyError):
            if "addresses" in locals():
                for endpoint in ("/api/events", "/api/status"):
                    try:
                        result = http(addresses["web"], endpoint)
                        if endpoint.endswith("events"):
                            result = [{key: item.get(key) for key in ("kind", "source", "networkProvider")} for item in result["events"]]
                        print(endpoint, json.dumps(result), file=sys.stderr)
                    except (OSError, ValueError, KeyError) as error:
                        print(f"Diagnostic {endpoint} unavailable: {error}", file=sys.stderr)
                for role in ("collector", "web"):
                    output = subprocess.run(["docker", "logs", "--tail", "30", names[role]], capture_output=True, text=True)
                    print(role, output.stdout, output.stderr, file=sys.stderr)
            raise
        finally:
            for name in names.values():
                result = subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, text=True)
                if result.returncode and "No such container" not in result.stderr:
                    print(result.stderr, file=sys.stderr)
            subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)
            subprocess.run(["docker", "network", "rm", prefix], check=False, capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="attacks:local")
    parser.add_argument("--subnet", help="Explicit non-overlapping test subnet when Docker's default pools are exhausted")
    args = parser.parse_args()
    run(args.image, args.subnet)
