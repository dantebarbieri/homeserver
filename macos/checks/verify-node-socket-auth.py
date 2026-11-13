"""Prove Tdarr's node socket rejects missing and invalid API keys.

Run on the Studio while the studio-transfer tunnel is up (127.0.0.1:8266).
"""
import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:8266"


def check(kind):
    name = "auth-rejection-probe-" + str(uuid.uuid4())
    config = {
        "nodeName": name,
        "nodeType": "mapped",
        "serverURL": BASE,
        "startPaused": True,
        "transcodecpuWorkers": 0,
        "transcodegpuWorkers": 0,
        "healthcheckcpuWorkers": 0,
        "healthcheckgpuWorkers": 0,
        "pathTranslators": [],
    }
    headers = {
        "nodeid": name,
        "nodeversion": "3.07.00",
        "config": json.dumps(config, separators=(",", ":")),
    }
    if kind == "invalid":
        headers["x-api-key"] = "tapi_invalid_socket_probe_not_a_real_key"
    deadline = time.monotonic() + 10
    sid = None
    evidence = {"case": kind, "probeName": name, "events": []}

    def request(body=None, cleanup=False):
        timeout = 2 if cleanup else min(5, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("Probe deadline exceeded")
        query = {"EIO": "4", "transport": "polling", "t": uuid.uuid4().hex}
        if sid is not None:
            query["sid"] = sid
        url = BASE + "/socket.io/?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(
            url,
            data=None if body is None else body.encode(),
            headers=headers | {"Content-Type": "text/plain;charset=UTF-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read(32768).decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read(32768).decode()

    try:
        status, opened = request()
        evidence["engineHttp"] = status
        if status != 200 or not opened.startswith("0"):
            raise RuntimeError("Transport did not open; namespace rejection unproven")
        sid = json.loads(opened[1:])["sid"]
        status, _ = request("40/node,")
        evidence["connectPostHttp"] = status
        if status != 200:
            raise RuntimeError("Namespace connect POST failed")
        rejected = False
        for _ in range(3):
            status, payload = request()
            if status != 200:
                raise RuntimeError("No explicit namespace auth rejection received")
            for packet in payload.split("\x1e"):
                if packet == "2":
                    ping_status, _ = request("3")
                    if ping_status != 200:
                        raise RuntimeError("Ping response failed")
                elif packet.startswith("40/node,"):
                    evidence["events"].append("namespace connect packet (not auth success)")
                elif packet.startswith("44/node,"):
                    reason = json.loads(packet[len("44/node,"):])
                    evidence["events"].append({"CONNECT_ERROR": reason})
                    rejected = any(word in json.dumps(reason).lower()
                                   for word in ("auth", "api key", "api-key", "apikey", "token"))
                elif packet.startswith("42/node,"):
                    event = json.loads(packet[len("42/node,"):])
                    if event[0] == "/node/connected":
                        raise RuntimeError("FAIL: unauthenticated node accepted")
                    if event[0] == "connect_error":
                        evidence["events"].append({"connect_error": event[1:]})
                        rejected = any(word in json.dumps(event[1:]).lower()
                                       for word in ("auth", "api key", "api-key", "apikey", "token"))
                    else:
                        evidence["events"].append({"eventName": event[0]})
                elif packet in ("1", "41/node,"):
                    evidence["events"].append("disconnect")
                else:
                    evidence["events"].append({"packetPrefix": packet[:2]})
            if rejected:
                break
        if not rejected:
            raise RuntimeError("Explicit node authentication rejection not established")
        evidence["result"] = "namespace authentication rejected"
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        evidence["result"] = "inconclusive or failed"
        evidence["error"] = str(error)
    finally:
        if sid is not None:
            try:
                status, _ = request("1", cleanup=True)
                evidence["closeHttp"] = status
            except (OSError, urllib.error.URLError) as error:
                evidence["closeError"] = str(error)
    return evidence


results = []
for kind in ("missing", "invalid"):
    results.append(check(kind))
    if results[-1]["result"] != "namespace authentication rejected":
        break
print(json.dumps({
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "base": BASE,
    "results": results,
}, indent=2))
raise SystemExit(0 if len(results) == 2 and
                 all(r["result"] == "namespace authentication rejected"
                     for r in results) else 1)
