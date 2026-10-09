#!/usr/bin/env python3
"""Exercise one synthetic synced world over HTTPS; never print sync or share keys."""

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.request


ORIGIN = "https://map.mirklurk.danteb.com"
NAME = "Synthetic deployment check"
GRID = [[1] * 5 for _ in range(5)]
CONFIG = {"worldsPerLibrary": 5, "retentionDays": 30, "maxBytes": 64 * 1024 * 1024, "pollSeconds": 30}
WORLD_FIELDS = {"id", "name", "created", "updated", "expires", "version", "size", "share"}
RETENTION_MS = 30 * 24 * 60 * 60 * 1000
# Web nginx allows 2 requests/second per client; stay below it so every 429 is the backend's.
PACE_SECONDS = 0.6


def packet(name, extra=None):
    player = json.dumps([{"worldGrid": GRID, **(extra or {})}]).encode()
    manifest = json.dumps({
        "name": name,
        "entries": [{"path": "Player.save", "size": len(player), "modified": 0}],
    }).encode()
    return struct.pack(">I", len(manifest)) + manifest + player


def world_id(name, grid=GRID):
    """Same character name and zone layout = same world (src/sharing-format.ts worldId)."""
    text = "mirklurk/world\n" + json.dumps([name, grid], separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()[:22]


def new_key():
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exercise():
    opener = urllib.request.build_opener(NoRedirect)

    def request(method, path, expected, body=None, key=None, headers=None):
        time.sleep(PACE_SECONDS)
        values = {"Content-Type": "application/octet-stream", **(headers or {})}
        if key:
            values["Authorization"] = "Bearer " + key
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
            raise RuntimeError(f"{method} {path} returned {status}, expected {expected}; response withheld")
        return data, result_headers

    def check_world(info, expected_id):
        assert set(info) == WORLD_FIELDS, "World info exposed unexpected fields"
        assert info["id"] == expected_id and info["name"] == NAME, "Unexpected world identity"
        assert info["expires"] - info["updated"] == RETENTION_MS, "Retention is not 30 days after the last update"

    config, _ = request("GET", "/api/config", 200)
    assert json.loads(config) == CONFIG, "Unexpected sharing contract"
    request("GET", "/api/library", 401)

    sync = new_key()
    listing, _ = request("GET", "/api/library", 200, key=sync)
    assert json.loads(listing) == {"name": "", "worlds": [], "limits": CONFIG}, "Fresh library is not empty"

    wid = world_id(NAME)
    path = "/api/library/worlds/" + wid
    original = packet(NAME)
    replacement = packet(NAME, {"MDday": 2})
    created = None
    deleted = False
    try:
        data, _ = request("PUT", path, 201, original, sync, {
            "X-Forwarded-For": "198.51.100.111",
            "X-Real-IP": "198.51.100.112",
            "X-Upload-IP": "198.51.100.113",
        })
        created = json.loads(data)
        check_world(created, wid)
        assert created["size"] == len(original), "Stored size differs"
        listing, _ = request("GET", "/api/library", 200, key=sync)
        assert [w["id"] for w in json.loads(listing)["worlds"]] == [wid], "Library does not list exactly the synthetic world"

        data, headers = request("GET", path + "/data", 200, key=sync)
        assert data == original, "Read bytes differ"
        assert headers["Cache-Control"] == "no-store", "API data must not be cached"
        assert headers["Last-Modified"], "Missing Last-Modified"
        etag = headers["ETag"]
        request("GET", path + "/data", 304, key=sync, headers={"If-None-Match": etag})

        share = created["share"]
        data, _ = request("GET", "/api/view/data", 200, key=share)
        assert data == original, "Read-only share bytes differ"
        request("PUT", "/api/view/data", 405, replacement, share)
        listing, _ = request("GET", "/api/library", 200, key=share)
        assert json.loads(listing)["worlds"] == [], "A share key opened the owner's library"
        request("DELETE", path, 404, key=share)

        request("PUT", "/api/library/worlds/" + world_id("Synthetic mismatch"), 409, original, sync)
        data, _ = request("PUT", path, 429, original, sync)
        assert "30 seconds" in json.loads(data)["error"], "429 did not come from the per-world update throttle"
        time.sleep(31)
        data, _ = request("PUT", path, 200, replacement, sync, {"If-Match": "*"})
        updated = json.loads(data)
        check_world(updated, wid)
        assert updated["version"] != created["version"], "Update did not change version"
        assert updated["created"] == created["created"], "Update changed the creation time"
        assert updated["expires"] > created["expires"], "Update did not extend retention"
        data, headers = request("GET", path + "/data", 200, key=sync, headers={"If-None-Match": etag})
        assert data == replacement and headers["ETag"] != etag, "Updated data/ETag mismatch"

        data, _ = request("POST", path + "/share", 200, key=sync)
        reset = json.loads(data)["share"]
        assert reset != share, "Share reset kept the old key"
        request("GET", "/api/view/data", 404, key=share)
        data, _ = request("GET", "/api/view/data", 200, key=reset)
        assert data == replacement, "Reset share bytes differ"

        request("DELETE", path, 204, key=sync)
        deleted = True
        request("GET", path + "/data", 404, key=sync)
        request("GET", "/api/view/data", 404, key=reset)
        request("PUT", path, 412, replacement, sync, {"If-Match": "*"})
        listing, _ = request("GET", "/api/library", 200, key=sync)
        assert json.loads(listing)["worlds"] == [], "Deleted world is still listed"
        print("PASS: config, keyless 401, synced-world create/list/read/ETag, read-only share, share-key isolation, "
              "mismatch 409, throttle, 30-day update, share reset, delete, no re-add, final 404.")
    finally:
        if created and not deleted:
            # This test owns exactly one world in its own random library; never touch others.
            request("DELETE", path, 204, key=sync)
            print("Synthetic test world cleaned after failure.")


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
