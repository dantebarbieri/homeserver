"""Track-level Soulseek fallback for the Lidarr releases Soularr couldn't get.

Soularr searches "<artist> <album>" and needs one folder that matches the whole release.
That misses singles that only exist inside album folders, releases whose title search comes
back empty, and releases whose first peer never answers. For each release Soularr has failed
(its search_attempts.json / failed_imports.json) this:
  1. searches "<artist> <track title>" for the release's most distinctive tracks,
  2. browses each candidate folder and maps every Lidarr track to a file by title and
     duration (within LENGTH_TOLERANCE seconds), preferring FLAC,
  3. downloads only the matched files through slskd,
  4. once they are on disk, ManualImports them into Lidarr with explicit track ids (move).
A peer that doesn't deliver within STALE_HOURS is excluded and the next one is tried (up to
MAX_PEERS); releases with no match are searched again after MISS_RETRY_HOURS.
"""
import os, re, json, time, uuid, unicodedata, traceback, urllib.request, urllib.parse, urllib.error

LIDARR_URL = os.environ.get("LIDARR_URL", "http://lidarr:8686").rstrip("/")
LIDARR_CONFIG = os.environ.get("LIDARR_CONFIG", "/lidarr/config.xml")
SLSKD_URL = os.environ.get("SLSKD_URL", "http://slskd:5030").rstrip("/")
SLSKD_API_KEY = os.environ.get("SLSKD_API_KEY", "")
SOULARR_DIR = os.environ.get("SOULARR_DIR", "/soularr")
DOWNLOADS = os.environ.get("DOWNLOAD_DIR", "/data/soulseek/downloads").rstrip("/")
STATE_DIR = os.environ.get("STATE_DIR", "/state")
INTERVAL = int(os.environ.get("INTERVAL", "3600"))
MAX_ALBUMS = int(os.environ.get("MAX_ALBUMS_PER_RUN", "40"))
MISS_RETRY = float(os.environ.get("MISS_RETRY_HOURS", "72")) * 3600
STALE = float(os.environ.get("STALE_HOURS", "12")) * 3600
MAX_PEERS = int(os.environ.get("MAX_PEERS", "5"))
TOLERANCE = float(os.environ.get("LENGTH_TOLERANCE", "6"))
ONCE = os.environ.get("ONCE") == "1"

AUDIO = {"flac": 0, "alac": 1, "m4a": 2, "mp3": 3}
# Words a file name may only contain if the Lidarr track title does too.
VARIANT = {"remix", "rmx", "live", "instrumental", "acoustic", "karaoke", "demo", "cover", "mix",
           "edit", "version", "remaster", "remastered", "slowed", "reverb", "sped", "nightcore",
           "vip", "bootleg", "extended"}
ACTIVE = ("Queued", "Initializing", "InProgress", "Requested")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def call(base, hdr, key, path, method="GET", body=None, timeout=120):
    req = urllib.request.Request(base + path, method=method, headers={hdr: key, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    data = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(data) if data else None


def lidarr(path, method="GET", body=None):
    with open(LIDARR_CONFIG) as f:
        key = re.search(r"<ApiKey>(\w+)</ApiKey>", f.read()).group(1)
    return call(LIDARR_URL + "/api/v1", "X-Api-Key", key, path, method, body, 300)


def slskd(path, method="GET", body=None):
    return call(SLSKD_URL + "/api/v0", "X-API-Key", SLSKD_API_KEY, path, method, body)


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, value):
    tmp = os.path.join(STATE_DIR, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(value, f, indent=1)
    os.replace(tmp, os.path.join(STATE_DIR, name))


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", re.sub(r"['`]", "", s)).split())


def core_title(title):
    return norm(re.sub(r"\s*[\(\[](feat|ft|with)\b[^\)\]]*[\)\]]", "", title, flags=re.I))


def query_words(s):
    """Soulseek search words: no bracketed parts, no apostrophe words, no 1-char words."""
    s = re.sub(r"[\(\[].*?[\)\]]", " ", unicodedata.normalize("NFKC", s).replace("\u2019", "'"))
    return [w for w in re.split(r"[^\w']+", s) if len(w) > 1 and "'" not in w]


def ext(f):
    return f["filename"].rsplit(".", 1)[-1].lower()


def basename(path):
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def file_matches(f, track, artist):
    if ext(f) not in AUDIO:
        return False
    stem = norm(re.sub(r"\.[^.]+$", "", basename(f["filename"])))
    title = core_title(track["title"])
    if not title or not re.search(r"(^| )" + re.escape(title) + r"( |$)", stem):
        return False
    words = set(title.split())
    if (set(stem.split()) - words - set(norm(artist).split())) & (VARIANT - words):
        return False
    length, want = f.get("length"), (track.get("duration") or 0) / 1000
    return not length or not want or abs(length - want) <= TOLERANCE


def quality_key(f):
    return AUDIO[ext(f)], -(f.get("bitDepth") or 0), -(f.get("bitRate") or 0)


def search(text):
    sid = str(uuid.uuid4())
    for attempt in range(8):
        try:
            slskd("/searches", "POST", {"id": sid, "searchText": text, "searchTimeout": 15000,
                                        "filterResponses": True, "maximumPeerQueueLength": 50})
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 7:
                raise
            time.sleep(10 * (attempt + 1))
    time.sleep(6)
    for _ in range(60):
        if slskd(f"/searches/{sid}")["state"] != "InProgress":
            break
        time.sleep(1)
    responses = slskd(f"/searches/{sid}/responses")
    try:
        slskd(f"/searches/{sid}", "DELETE")
    except Exception:
        pass
    return responses


def browse(user, directory, sep):
    listing = slskd(f"/users/{urllib.parse.quote(user)}/directory", "POST", {"directory": directory})
    return [dict(f, filename=directory + sep + basename(f["filename"]))
            for d in (listing if isinstance(listing, list) else [listing]) for f in d.get("files", [])]


def assign(files, tracks, artist):
    """{trackId: file} using each file once, or None if any track has no match."""
    out, used = {}, set()
    for t in tracks:
        cands = [f for f in files if f["filename"] not in used and file_matches(f, t, artist)]
        if not cands:
            return None
        out[t["id"]] = min(cands, key=quality_key)
        used.add(out[t["id"]]["filename"])
    return out


def find(album, tracks, excluded):
    artist = album["artist"]["artistName"]
    artist_words = [] if artist.lower() in ("various artists", "soundtrack") else query_words(artist)
    probes = sorted(tracks, key=lambda t: (-len(query_words(t["title"])), -len(t["title"])))[:2]
    for probe in probes:
        words = query_words(probe["title"])
        if not words:
            continue
        folders = {}
        for r in search(" ".join(artist_words + words)):
            if r["username"] in excluded:
                continue
            for f in r.get("files", []):
                if file_matches(f, probe, artist):
                    folders[(r["username"], f["filename"].replace("\\", "/").rsplit("/", 1)[0])] = (r, f)
        ranked = sorted(folders.items(), key=lambda kv: (quality_key(kv[1][1]), not kv[1][0].get("hasFreeUploadSlot"),
                                                         kv[1][0].get("queueLength", 0), -kv[1][0].get("uploadSpeed", 0)))
        if len(tracks) == 1 and ranked:
            (user, _), (_, f) = ranked[0]
            return user, {probe["id"]: f}
        for (user, _), (_, f) in ranked[:6]:
            sep = "\\" if "\\" in f["filename"] else "/"
            try:
                match = assign(browse(user, f["filename"].rsplit(sep, 1)[0], sep), tracks, artist)
            except Exception:
                continue
            if match:
                return user, match
    return None


def import_pass(state):
    transfers = {(u["username"], f["filename"]): f
                 for u in slskd("/transfers/downloads") for d in u["directories"] for f in d["files"]}
    on_disk = {}  # keyed by norm() because slskd rewrites characters like ? and :
    for root, _, files in os.walk(DOWNLOADS):
        for f in files:
            on_disk.setdefault(norm(f), (root, f))
    for aid, e in state.items():
        if e.get("status") != "grabbed":
            continue
        try:
            album = lidarr(f"/album/{aid}")
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            e["status"] = "gone"
            continue
        if album["statistics"]["trackFileCount"] >= album["statistics"]["trackCount"]:
            e["status"] = "done"
            continue
        names = {tid: basename(fn) for tid, fn in e["files"].items()}
        if not all(norm(n) in on_disk for n in names.values()):
            mine = [transfers.get((e["user"], fn)) for fn in e["files"].values()]
            active = [t for t in mine if t and t["state"].startswith(ACTIVE)]
            if active and time.time() - e["at"] < STALE:
                continue
            for t in active:
                try:
                    slskd(f"/transfers/downloads/{urllib.parse.quote(e['user'])}/{t['id']}", "DELETE")
                except Exception:
                    pass
            e["excluded"] = e.get("excluded", []) + [e["user"]]
            e["status"] = "retry"
            log("peer did not deliver, will try another:", e["name"], "<-", e["user"])
            continue
        release = next(r["id"] for r in album["releases"] if r["monitored"])
        by_folder = {}
        for tid, name in names.items():
            root, real = on_disk[norm(name)]
            by_folder.setdefault(root, []).append((int(tid), real))
        files = []
        for root, items in by_folder.items():
            listed = {basename(x["path"]): x for x in
                      lidarr("/manualimport?folder=" + urllib.parse.quote(root) + "&filterExistingFiles=false")}
            files += [{"path": listed[real]["path"], "artistId": album["artistId"], "albumId": int(aid),
                       "albumReleaseId": release, "trackIds": [tid], "quality": listed[real]["quality"],
                       "disableReleaseSwitching": False, "indexerFlags": 0}
                      for tid, real in items if real in listed]
        if len(files) != len(names):
            log("WARNING: Lidarr did not list every downloaded file for", e["name"])
            continue
        cmd = lidarr("/command", "POST", {"name": "ManualImport", "files": files, "importMode": "move",
                                          "replaceExistingFiles": False})
        for _ in range(100):
            time.sleep(3)
            if lidarr(f"/command/{cmd['id']}")["status"] in ("completed", "failed"):
                break
        stats = lidarr(f"/album/{aid}")["statistics"]
        log("imported", e["name"], f"{stats['trackFileCount']}/{stats['trackCount']}")
        e["status"] = "done" if stats["trackFileCount"] >= stats["trackCount"] else "retry"
        for root in by_folder:
            try:
                if root != DOWNLOADS and not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass


def grab_pass(state):
    soularr = lambda n: load(os.path.join(SOULARR_DIR, n), {})
    soularr_failed = set(soularr("search_attempts.json")) | set(soularr("failed_imports.json"))
    bad_users = set(soularr("failed_users.json"))
    now = time.time()
    picks = []
    for a in lidarr("/wanted/missing?pageSize=2000&monitored=true&includeArtist=true")["records"]:
        e = state.get(str(a["id"]), {})
        status = e.get("status")
        if status == "retry":
            picks.append((0, a))
        elif status is None and str(a["id"]) in soularr_failed:
            picks.append((1, a))
        elif status in ("miss", "done") and now - e.get("at", 0) > MISS_RETRY:
            picks.append((2, a))
    picks.sort(key=lambda p: p[0])
    for _, a in picks[:MAX_ALBUMS]:
        aid, name = str(a["id"]), f"{a['artist']['artistName']} - {a['title']}"
        e = state.setdefault(aid, {})
        e["name"] = name
        if len(e.get("excluded", [])) >= MAX_PEERS:
            e.update(status="miss", at=now, excluded=[])
            log("giving up for now, no peer delivered:", name)
            continue
        tracks = lidarr(f"/track?albumId={aid}")
        found = find(a, tracks, bad_users | set(e.get("excluded", []))) if tracks else None
        if not found:
            e.update(status="miss", at=time.time())
            log("no match:", name)
            continue
        user, match = found
        slskd(f"/transfers/downloads/{urllib.parse.quote(user)}", "POST",
              [{"filename": f["filename"], "size": f["size"]} for f in match.values()])
        e.update(status="grabbed", at=time.time(), user=user, files={str(k): f["filename"] for k, f in match.items()})
        log("grabbed", name, "<-", user, f"{len(match)} x {ext(next(iter(match.values())))}")
        save("state.json", state)


def main():
    while True:
        try:
            state = load(os.path.join(STATE_DIR, "state.json"), {})
            import_pass(state)
            save("state.json", state)
            grab_pass(state)
            save("state.json", state)
            save("last_ok.json", {"at": time.time()})
        except Exception:
            log("ERROR:", traceback.format_exc())
        if ONCE:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
