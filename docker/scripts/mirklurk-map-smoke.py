#!/usr/bin/env python3
"""Exercise one synthetic share over HTTPS; never print capability keys."""

import argparse
import json
import socket
import struct
import time
import urllib.error
import urllib.request


ORIGIN = "https://map.mirklurk.danteb.com"


def packet(name):
    player = json.dumps([{"worldGrid": [[1] * 5 for _ in range(5)]}]).encode()
    manifest = json.dumps({
        "name": name,
        "entries": [{"path": "Player.save", "size": len(player), "modified": 0}],
    }).encode()
    return struct.pack(">I", len(manifest)) + manifest + player


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exercise():
    opener = urllib.request.build_opener(NoRedirect)

    def request(method, path, expected, body=None, owner=None, headers=None):
        values = {"Content-Type": "application/octet-stream", **(headers or {})}
        if owner:
            values["Authorization"] = f"Bearer {owner}"
        req = urllib.request.Request(ORIGIN + path, data=body, headers=values, method=method)
        try:
            response = opener.open(req, timeout=90)
        except urllib.error.HTTPError as error:
            response = error
        except urllib.error.URLError:
            raise RuntimeError("HTTPS connection failed (URL withheld)") from None
        with response:
            status, data, result_headers = response.status, response.read(), response.headers
        if status != expected:
            raise RuntimeError(f"{method} returned {status}, expected {expected}; response withheld")
        return data, result_headers

    config, _ = request("GET", "/api/shares", 200)
    settings = json.loads(config)
    assert settings == {
        "enabled": True, "maxBytes": 64 * 1024 * 1024,
        "maxActivePerIP": 3, "lifetimeDays": 7, "pollSeconds": 30,
    }, "Unexpected sharing contract"
    original = packet("Synthetic deployment check")
    replacement = packet("Synthetic deployment check updated")
    created, _ = request("POST", "/api/shares", 201, original, headers={
        "X-Forwarded-For": "198.51.100.111",
        "X-Real-IP": "198.51.100.112",
        "X-Upload-IP": "198.51.100.113",
    })
    share = json.loads(created)
    path = "/api/shares/" + share["id"]
    deleted = False
    try:
        metadata, _ = request("GET", path, 200)
        metadata = json.loads(metadata)
        assert "edit" not in metadata and "owner" not in metadata, "Read API exposed owner data"
        assert metadata["expires"] - metadata["created"] == 7 * 24 * 60 * 60 * 1000
        data, headers = request("GET", path + "/data", 200)
        assert data == original, "Read bytes differ"
        assert headers["Cache-Control"] == "no-store", "API data must not be cached"
        etag = headers["ETag"]
        request("GET", path + "/data", 304, headers={"If-None-Match": etag})
        time.sleep(2)
        request("PUT", path, 403, replacement)
        request("DELETE", path, 403)
        request("PUT", path, 429, replacement, share["edit"])
        time.sleep(31)
        changed, _ = request("PUT", path, 200, replacement, share["edit"])
        changed = json.loads(changed)
        assert changed["expires"] == share["expires"], "Update extended expiry"
        assert changed["version"] != share["version"], "Update did not change version"
        data, headers = request("GET", path + "/data", 200, headers={"If-None-Match": etag})
        assert data == replacement and headers["ETag"] != etag, "Updated data/ETag mismatch"
        time.sleep(2)
        request("DELETE", path, 204, owner=share["edit"])
        deleted = True
        request("GET", path, 404)
        request("GET", path + "/data", 404)
        print("PASS: synthetic create/read/ETag, anonymous mutation denial, throttle, fixed expiry, owner update/delete, final 404.")
    finally:
        if not deleted:
            # This test owns exactly one record; never enumerate or remove others.
            request("DELETE", path, 204, owner=share["edit"])
            print("Synthetic test share cleaned after failure.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("4", "6"))
    args = parser.parse_args()
    if args.family:
        resolve = socket.getaddrinfo
        family = socket.AF_INET if args.family == "4" else socket.AF_INET6

        def selected_family(host, port, _family=0, type=0, proto=0, flags=0):
            return resolve(host, port, family, type, proto, flags)

        socket.getaddrinfo = selected_family
    exercise()
