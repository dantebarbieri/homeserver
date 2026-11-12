"""Two-way sync of ratings, hearts, play counts and regular playlists between Plex and Navidrome.

Tracks are matched by their path inside the music folder. Every INTERVAL seconds:
  - ratings: a change made on one side since the last run is copied to the other; if both changed,
    the newer change wins. Plex rates 0-10 (2 per star), Navidrome 0-5.
  - hearts: a Navidrome heart means "rated 2 stars or more" (Plex has no separate heart). Hearting an
    unrated or 1-star song rates it 3 stars on both sides; un-hearting clears the rating.
  - play counts: plays added on one side since the last run are added to the other
    (Plex /:/scrobble, Navidrome scrobble with external scrobbling off for this client).
  - playlists: regular (not smart) playlists, paired by name the first time and by ID after that.
    A changed track list replaces the other side's (both changed: the newer wins; first pairing:
    Plex wins). Renames and deletions are mirrored; a deleted playlist's tracks are saved under
    STATE_DIR/deleted-playlists first. Tracks the other app hasn't scanned yet are kept in place.
A track whose Plex or Navidrome ID changed (the item was re-created) gets its last synced rating back.
Last synced values are kept in STATE_DIR/state.json. DRY=1 only logs; ONCE=1 runs once.
"""
import os, re, sys, json, time, signal, traceback, unicodedata, urllib.request, urllib.parse
from datetime import datetime

PLEX_URL = os.environ.get("PLEX_URL", "http://plex:32400")
PLEX_PREFS = os.environ.get("PLEX_PREFS", "/plex/Preferences.xml")
PLEX_ROOT = os.environ.get("PLEX_MUSIC_ROOT", "/data/media/music").rstrip("/") + "/"
ND_URL = os.environ.get("NAVIDROME_URL", "http://navidrome:4533")
ND_USER, ND_PASS = os.environ.get("NAVIDROME_USER", ""), os.environ.get("NAVIDROME_PASSWORD", "")
NTFY_URL, NTFY_TOPIC = os.environ.get("NTFY_URL", ""), os.environ.get("NTFY_TOPIC", "")
STATE = os.environ.get("STATE_DIR", "/state")
INTERVAL = int(os.environ.get("INTERVAL", "900"))
# Refuse a run that would clear more ratings than this (e.g. a Plex library rebuilt without them).
MAX_CLEARS = int(os.environ.get("MAX_CLEARS", "50"))
DRY = os.environ.get("DRY") == "1"
ONCE = os.environ.get("ONCE") == "1"
CLIENT = "plex-navidrome-sync"
LOVED, LIKE = 4, 6          # Plex scale: a heart is 2 stars or more; hearting rates 3 stars
PLEX_BATCH = 200


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), re.sub(r"\b[0-9a-f]{32}\b", "***", msg), flush=True)


def nfc(s):
    return unicodedata.normalize("NFC", s)


def ts(v):
    """Epoch seconds from a Plex epoch or a Navidrome RFC 3339 time; 0 when unset."""
    if not v:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)?$", v)
    if not m or v.startswith("0001-"):
        return 0.0
    zone = m.group(2) or "Z"
    return datetime.fromisoformat(m.group(1) + ("+00:00" if zone == "Z" else zone)).timestamp()


def to_nd(r):
    return 0 if r <= 0 else min(5, max(1, int(r / 2 + 0.5)))


def load_state(name, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_state(name, value):
    if DRY:
        return
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(value, f)
    os.replace(tmp, os.path.join(STATE, name))


def configured():
    return bool(ND_USER and ND_PASS)


def healthcheck():
    if not configured():
        log("not configured; waiting for Navidrome credentials (not syncing)")
        return 0
    try:
        with open(os.path.join(STATE, "last_ok.json")) as f:
            age = time.time() - json.load(f)["at"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        log("unhealthy: cannot read last successful sync:", e)
        return 1
    if not 0 <= age < 2 * INTERVAL + 900:
        log("unhealthy: last successful sync is stale or has an invalid timestamp")
        return 1
    return 0


def start_ntfy():
    if not (NTFY_URL and NTFY_TOPIC):
        return None
    try:
        from ntfy_auth import start_outbox
        return start_outbox(STATE, NTFY_URL, NTFY_TOPIC)
    except (OSError, ValueError) as e:
        log("WARNING: ntfy outbox unavailable:", type(e).__name__)
        return None


def ntfy(title, body, priority="default", tags=""):
    outbox = start_ntfy()
    if outbox is None:
        return False
    try:
        outbox.submit(title, body, priority, tags)
        return True
    except (OSError, ValueError) as e:
        log("WARNING: ntfy queue failed:", type(e).__name__)
        return False


def http(method, url, params=None, headers=None, body=None, timeout=300):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        return (json.loads(data) if data and "json" in r.headers.get("Content-Type", "") else None), r.headers


# --- merge logic (pure) -------------------------------------------------------------------------

def plan_track(s, p, n):
    """s: last synced state for the track ({} if never synced); p: Plex track; n: Navidrome song.
    Returns the bases the decision was made against (stored before writing, so an interrupted run
    re-plans the same thing), the rating both sides should end up with, and plays to copy."""
    p_new = bool(s) and s.get("p") != p["key"]
    n_new = bool(s) and s.get("n") != n["id"]
    pr = 0 if p_new else s.get("pr", 0)
    nr = 0 if n_new else s.get("nr", 0)
    ns = False if n_new else s.get("ns", False)
    r = s.get("r", 0)
    p_changed = p["rating"] != pr
    n_changed = n["rating"] != nr or n["starred"] != ns
    if p_changed and (not n_changed or p["rated_at"] >= n["rated_at"]):
        r = p["rating"]
    elif n_changed:
        if n["rating"] != nr:
            r = n["rating"] * 2
        if n["starred"] != ns:
            if n["starred"] and r < LOVED:
                r = LIKE
            elif not n["starred"] and r >= LOVED:
                r = 0
    # A re-created item starts counting from its current plays; counts that went down reset the base.
    pv = p["views"] if p_new else min(p["views"], s.get("pv", 0))
    np = n["plays"] if n_new else min(n["plays"], s.get("np", 0))
    return {"r": r, "pr": pr, "nr": nr, "ns": ns, "pv": pv, "np": np,
            "to_nd": p["views"] - pv, "to_plex": n["plays"] - np}


def overlay(target, own, matched):
    """target (matched tracks only) with own's unmatched tracks kept after the track they followed."""
    extras, anchor = {}, None
    for x in own:
        if x in matched:
            anchor = x
        else:
            extras.setdefault(anchor, []).append(x)
    out, placed = list(extras.pop(None, [])), set()
    for x in target:
        out.append(x)
        if x not in placed:
            placed.add(x)
            out += extras.pop(x, [])
    for xs in extras.values():
        out += xs
    return out


def plan_playlists(pairs, px, nx, matched):
    """pairs: synced pairs from state ({p, n, name, tracks}); px/nx: {id: {name, updated, tracks}}.
    Returns (ops, new pairs). Create ops carry their pair, whose missing ID is filled in on success."""
    ops, out = [], []
    px_left, nx_left = dict(px), dict(nx)

    def common(tracks):
        return [x for x in tracks if x in matched]

    def sync(pair, p, n):
        name, base = pair["name"], pair.get("tracks")
        if p["name"] != name and (n["name"] == name or p["updated"] >= n["updated"]):
            name = p["name"]
        elif n["name"] != name:
            name = n["name"]
        for side, key, item in (("plex", pair["p"], p), ("nd", pair["n"], n)):
            if item["name"] != name:
                ops.append(("rename", side, key, name))
        cp, cn = common(p["tracks"]), common(n["tracks"])
        cb = None if base is None else common(base)
        p_changed, n_changed = cb is None or cp != cb, cb is not None and cn != cb
        if p_changed and (not n_changed or p["updated"] >= n["updated"]):
            target = cp
        elif n_changed:
            target = cn
        else:
            target = cb
        for side, key, item, mine in (("plex", pair["p"], p, cp), ("nd", pair["n"], n, cn)):
            if mine != target:
                ops.append(("set", side, key, overlay(target, item["tracks"], matched)))
        return {"p": pair["p"], "n": pair["n"], "name": name, "tracks": target}

    for pair in pairs:
        p, n = px_left.pop(pair["p"], None), nx_left.pop(pair["n"], None)
        if p and n:
            out.append(sync(pair, p, n))
        elif p and nx:
            ops.append(("delete", "plex", pair["p"], p["name"], p["tracks"]))
        elif n and px:
            ops.append(("delete", "nd", pair["n"], n["name"], n["tracks"]))
        elif p or n:
            out.append(pair)    # the other side listed no playlists at all: likelier an outage than deletions

    by_name = {}
    for nid, n in nx_left.items():
        by_name.setdefault(n["name"], []).append(nid)
    for pid in list(px_left):
        if by_name.get(px_left[pid]["name"]):
            nid = by_name[px_left[pid]["name"]].pop(0)
            p, n = px_left.pop(pid), nx_left.pop(nid)
            out.append(sync({"p": pid, "n": nid, "name": p["name"], "tracks": None}, p, n))

    for pid, p in px_left.items():
        pair = {"p": pid, "n": None, "name": p["name"], "tracks": common(p["tracks"])}
        ops.append(("create", "nd", pair))
        out.append(pair)
    for nid, n in nx_left.items():
        pair = {"p": None, "n": nid, "name": n["name"], "tracks": common(n["tracks"])}
        if pair["tracks"]:      # Plex can't create an empty playlist; it's created once it has tracks
            ops.append(("create", "plex", pair))
            out.append(pair)
    return ops, out


# --- clients ------------------------------------------------------------------------------------

def plex_file(t):
    try:
        return t["Media"][0]["Part"][0]["file"]
    except (KeyError, IndexError):
        return None


class Plex:
    name = "Plex"
    IDENT = "com.plexapp.plugins.library"

    def __init__(self):
        token = os.environ.get("PLEX_TOKEN")
        if not token:
            # Read on every run so a re-claimed server's new token is picked up without a restart.
            with open(PLEX_PREFS) as f:
                m = re.search(r'PlexOnlineToken="([^"]+)"', f.read())
            if not m:
                raise RuntimeError(f"PlexOnlineToken not found in {PLEX_PREFS}")
            token = m.group(1)
        self.headers = {"Accept": "application/json", "X-Plex-Token": token,
                        "X-Plex-Client-Identifier": CLIENT, "X-Plex-Product": CLIENT}
        self.machine = None
        self.keys = {}          # path -> ratingKey, for writing playlists

    def req(self, method, path, params=None):
        return http(method, PLEX_URL + path, params, self.headers)[0]

    def paged(self, path, params=None, page=1000):
        start = 0
        while True:
            mc = self.req("GET", path, {**(params or {}), "X-Plex-Container-Start": start,
                                        "X-Plex-Container-Size": page})["MediaContainer"]
            items = mc.get("Metadata", [])
            yield from items
            start += len(items)
            if len(items) < page or start >= mc.get("totalSize", sys.maxsize):
                return

    def path(self, t):
        f = plex_file(t)
        p = nfc(f[len(PLEX_ROOT):]) if f and f.startswith(PLEX_ROOT) else f"plex:{t['ratingKey']}"
        self.keys.setdefault(p, t["ratingKey"])
        return p

    def tracks(self):
        out = {}
        for sec in self.req("GET", "/library/sections")["MediaContainer"].get("Directory", []):
            if sec.get("type") != "artist":
                continue
            for t in self.paged(f"/library/sections/{sec['key']}/all", {"type": 10}):
                p = self.path(t)
                if not p.startswith("plex:"):
                    out[p] = {"key": t["ratingKey"], "rating": int(round(float(t.get("userRating", 0)))),
                              "rated_at": ts(t.get("lastRatedAt")), "views": int(t.get("viewCount", 0)),
                              "played_at": ts(t.get("lastViewedAt"))}
        return out

    def playlists(self):
        mc = self.req("GET", "/playlists", {"playlistType": "audio"})["MediaContainer"]
        return {p["ratingKey"]: {"name": p["title"], "updated": ts(p.get("updatedAt")),
                                 "tracks": [self.path(t) for t in self.paged(f"/playlists/{p['ratingKey']}/items")]}
                for p in mc.get("Metadata", []) if not p.get("smart")}

    def rate(self, key, r):
        self.req("PUT", "/:/rate", {"key": key, "identifier": self.IDENT, "rating": r if r > 0 else -1})

    def scrobble(self, key, at):
        self.req("GET", "/:/scrobble", {"key": key, "identifier": self.IDENT})

    def _uri(self, paths):
        if self.machine is None:
            self.machine = self.req("GET", "/")["MediaContainer"]["machineIdentifier"]
        keys = ",".join(str(self.keys[p]) for p in paths)
        return f"server://{self.machine}/{self.IDENT}/library/metadata/{keys}"

    def _append(self, pid, paths):
        for i in range(0, len(paths), PLEX_BATCH):
            self.req("PUT", f"/playlists/{pid}/items", {"uri": self._uri(paths[i:i + PLEX_BATCH])})

    def set_playlist(self, pid, paths):
        self.req("DELETE", f"/playlists/{pid}/items")
        self._append(pid, paths)

    def create_playlist(self, name, paths):
        mc = self.req("POST", "/playlists", {"type": "audio", "title": name, "smart": 0,
                                             "uri": self._uri(paths[:PLEX_BATCH])})["MediaContainer"]
        pid = mc["Metadata"][0]["ratingKey"]
        self._append(pid, paths[PLEX_BATCH:])
        return pid

    def rename_playlist(self, pid, name):
        self.req("PUT", f"/playlists/{pid}", {"title": name})

    def delete_playlist(self, pid):
        self.req("DELETE", f"/playlists/{pid}")


class Navidrome:
    name = "Navidrome"

    def __init__(self):
        if not configured():
            raise RuntimeError("NAVIDROME_USER and NAVIDROME_PASSWORD must be set")
        auth = http("POST", ND_URL + "/auth/login", headers={"Content-Type": "application/json"},
                    body=json.dumps({"username": ND_USER, "password": ND_PASS}).encode())[0]
        self.jwt, self.user_id = auth["token"], auth["id"]
        self.sub = [("u", ND_USER), ("t", auth["subsonicToken"]), ("s", auth["subsonicSalt"]),
                    ("v", "1.16.1"), ("c", CLIENT), ("f", "json")]
        self.ids = {}           # path -> media file ID, for writing playlists

    def api(self, method, path, params=None, body=None):
        return http(method, f"{ND_URL}/api{path}", params,
                    {"X-ND-Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"},
                    None if body is None else json.dumps(body).encode())

    def rest(self, method, params=()):
        r = http("POST", f"{ND_URL}/rest/{method}", headers={"Content-Type": "application/x-www-form-urlencoded"},
                 body=urllib.parse.urlencode(self.sub + list(params)).encode())[0]["subsonic-response"]
        if r.get("status") != "ok":
            raise RuntimeError(f"Navidrome {method} failed: {r.get('error')}")
        return r

    def quiet_player(self):
        """Copied plays already happened elsewhere: keep this client's scrobbles off Last.fm/ListenBrainz."""
        self.rest("ping")
        for p in self.api("GET", "/player", {"_start": 0, "_end": 1000})[0]:
            if p.get("client") == CLIENT and p.get("userId") == self.user_id and p.get("scrobbleEnabled", True):
                self.api("PUT", f"/player/{p['id']}", body={**p, "scrobbleEnabled": False})
                log(f"turned off external scrobbling for Navidrome player {p.get('name')}")

    def path(self, t, id_field="id"):
        p = nfc(t["path"])
        self.ids.setdefault(p, t[id_field])
        return p

    def tracks(self, page=1000):
        out, seen, start, total = {}, set(), 0, 0
        while True:
            data, h = self.api("GET", "/song", {"_start": start, "_end": start + page, "_sort": "id", "_order": "ASC"})
            total = int(h.get("X-Total-Count") or 0)
            for s in data:
                seen.add(s["id"])
                if s.get("missing"):
                    continue
                out[self.path(s)] = {"id": s["id"], "rating": int(s.get("rating") or 0),
                                     "starred": bool(s.get("starred")),
                                     "rated_at": max(ts(s.get("ratedAt")), ts(s.get("starredAt"))),
                                     "plays": int(s.get("playCount") or 0)}
            start += len(data)
            if len(data) < page:
                break
        if len(seen) != total:
            raise RuntimeError(f"Navidrome song list was inconsistent ({len(seen)} songs read, {total} expected)")
        return out

    def playlists(self):
        out = {}
        for p in self.api("GET", "/playlist", {"_start": 0, "_end": 10000})[0]:
            # Skip smart playlists and ones imported from .m3u files (a rescan would overwrite them).
            if p.get("ownerId") != self.user_id or p.get("rules") or p.get("path"):
                continue
            tracks = self.api("GET", f"/playlist/{p['id']}/tracks", {"_start": 0, "_end": 100000})[0]
            out[p["id"]] = {"name": p["name"], "updated": ts(p.get("updatedAt")),
                            "tracks": [self.path(t, "mediaFileId") for t in tracks]}
        return out

    def rate(self, sid, rating):
        self.rest("setRating", [("id", sid), ("rating", rating)])

    def star(self, sid, on):
        self.rest("star" if on else "unstar", [("id", sid)])

    def scrobble(self, sid, at):
        self.rest("scrobble", [("id", sid), ("submission", "true"), ("time", int((at or time.time()) * 1000))])

    def set_playlist(self, pid, paths):
        self.rest("createPlaylist", [("playlistId", pid)] + [("songId", self.ids[p]) for p in paths])

    def create_playlist(self, name, paths):
        return self.rest("createPlaylist", [("name", name)] + [("songId", self.ids[p]) for p in paths])["playlist"]["id"]

    def rename_playlist(self, pid, name):
        self.rest("updatePlaylist", [("playlistId", pid), ("name", name)])

    def delete_playlist(self, pid):
        self.rest("deletePlaylist", [("id", pid)])


# --- run ----------------------------------------------------------------------------------------

def sync_tracks(state, plex, nd, pt, nt, counts):
    matched = sorted(pt.keys() & nt.keys())
    prev = state.get("matched", 0)
    if prev and len(matched) < prev / 2:
        raise RuntimeError(f"only {len(matched)} tracks matched (last run {prev}); a library looks incomplete")
    log(f"tracks: Plex {len(pt)}, Navidrome {len(nt)}, matched {len(matched)}")
    tracks = state["tracks"]
    plans = {path: plan_track(tracks.get(path, {}), pt[path], nt[path]) for path in matched}
    clears = [path for path, pl in plans.items()
              if pl["r"] == 0 and (pt[path]["rating"] or nt[path]["rating"] or nt[path]["starred"])]
    if len(clears) > MAX_CLEARS:
        raise RuntimeError(f"refusing to clear {len(clears)} ratings (MAX_CLEARS={MAX_CLEARS}), e.g. {clears[:3]}")
    for path, pl in plans.items():
        p, n, r = pt[path], nt[path], pl["r"]
        writes = [("plex rating", p["rating"] != r), ("navidrome rating", n["rating"] != to_nd(r)),
                  ("heart", n["starred"] != (r >= LOVED)), ("plays to navidrome", pl["to_nd"]),
                  ("plays to plex", pl["to_plex"])]
        for what, k in writes:
            counts[what] = counts.get(what, 0) + int(k)
        if DRY:
            if any(k for _, k in writes) and counts.setdefault("_shown", 0) < 20:
                counts["_shown"] += 1
                log(f"DRY {path}: Plex {p['rating']}/{p['views']} plays, Navidrome {n['rating']}"
                    f"{' heart' if n['starred'] else ''}/{n['plays']} plays -> rating {r}, "
                    f"+{pl['to_nd']} plays to Navidrome, +{pl['to_plex']} to Plex")
            continue
        st = tracks.setdefault(path, {})
        st.update(p=p["key"], n=n["id"], r=r, pr=pl["pr"], nr=pl["nr"], ns=pl["ns"], pv=pl["pv"], np=pl["np"])
        if p["rating"] != r:
            plex.rate(p["key"], r)
        st["pr"] = r
        if n["rating"] != to_nd(r):
            nd.rate(n["id"], to_nd(r))
        st["nr"] = to_nd(r)
        if n["starred"] != (r >= LOVED):
            nd.star(n["id"], r >= LOVED)
        st["ns"] = r >= LOVED
        for _ in range(pl["to_nd"]):
            nd.scrobble(n["id"], p["played_at"])
            st["pv"] += 1
            st["np"] += 1
        for _ in range(pl["to_plex"]):
            plex.scrobble(p["key"], None)
            st["pv"] += 1
            st["np"] += 1
    state["matched"] = len(matched)
    return set(matched)


def sync_playlists(state, plex, nd, matched, counts):
    px, nx = plex.playlists(), nd.playlists()
    ops, pairs = plan_playlists(state.get("playlists", []), px, nx, matched)
    sides = {"plex": plex, "nd": nd}
    dry = "DRY " if DRY else ""
    for op in ops:
        kind, side = op[0], sides[op[1]]
        counts[f"playlist {kind}"] = counts.get(f"playlist {kind}", 0) + 1
        if kind == "create":
            pair = op[2]
            log(f"{dry}playlist '{pair['name']}': creating in {side.name} ({len(pair['tracks'])} tracks)")
            if not DRY:
                pair["p" if op[1] == "plex" else "n"] = side.create_playlist(pair["name"], pair["tracks"])
        elif kind == "set":
            log(f"{dry}playlist {op[2]}: replacing {side.name}'s tracks ({len(op[3])} tracks)")
            if not DRY:
                side.set_playlist(op[2], op[3])
        elif kind == "rename":
            log(f"{dry}playlist {op[2]}: renaming in {side.name} to '{op[3]}'")
            if not DRY:
                side.rename_playlist(op[2], op[3])
        elif kind == "delete":
            log(f"{dry}playlist '{op[3]}' was deleted on the other side: deleting it in {side.name}")
            if not DRY:
                backup = os.path.join(STATE, "deleted-playlists")
                os.makedirs(backup, exist_ok=True)
                safe = re.sub(r"[^\w.-]+", "_", op[3])[:60]
                with open(os.path.join(backup, f"{time.strftime('%Y%m%d-%H%M%S')}-{op[1]}-{safe}.json"), "w") as f:
                    json.dump({"name": op[3], "from": side.name, "tracks": op[4]}, f, indent=1)
                side.delete_playlist(op[2])
    state["playlists"] = [p for p in pairs if p["p"] and p["n"]]


def run(plex=None, nd=None):
    state = load_state("state.json", {})
    state.setdefault("tracks", {})
    # Fail before writing anything if state can't be saved: unsaved play counts would be copied again.
    save_state("state.json", state)
    plex, nd = plex or Plex(), nd or Navidrome()
    if not DRY:
        try:
            nd.quiet_player()
        except Exception as e:
            log("WARNING: couldn't turn off external scrobbling for this client:", e)
    counts = {}
    ok = False
    try:
        matched = sync_tracks(state, plex, nd, plex.tracks(), nd.tracks(), counts)
        sync_playlists(state, plex, nd, matched, counts)
        ok = True
    finally:
        # Saved even after a failure: per-track state reflects exactly the writes that happened.
        save_state("state.json", state)
        done = ", ".join(f"{k} {v}" for k, v in counts.items() if v and not k.startswith("_"))
        verb = "DRY would sync" if DRY else "synced" if ok else "failed partway through syncing"
        log(f"{verb}: {done or 'nothing to change'}")


def main():
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))      # run finally blocks on docker stop
    if not DRY and NTFY_URL and NTFY_TOPIC:
        start_ntfy()
    if not configured():
        log("NAVIDROME_USER/NAVIDROME_PASSWORD not set in docker/.env; not syncing (see docs/MUSIC.md)")
        signal.pause() if hasattr(signal, "pause") else time.sleep(sys.maxsize)
    os.makedirs(STATE, exist_ok=True)
    last = {}
    while True:
        try:
            run()
            save_state("last_ok.json", {"at": time.time()})
        except Exception as e:
            log("ERROR:", traceback.format_exc())
            msg = f"{type(e).__name__}: {e}"[:300]
            last = load_state("last_error.json", last)
            if last.get("msg") != msg or time.time() - last.get("at", 0) > 6 * 3600:
                if not DRY and ntfy("Plex/Navidrome sync failed",
                                    f"{type(e).__name__}; see the sync logs.",
                                    "high", "musical_note,rotating_light"):
                    last = {"msg": msg, "at": time.time()}
                    try:
                        save_state("last_error.json", last)
                    except OSError:
                        pass
        if ONCE:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
