"""Unattended *arr queue maintenance: shared engine. APP selects the rules (lidarr, radarr, sonarr).

Every INTERVAL seconds, for downloads (queue rows grouped by download) stuck for GRACE_MINUTES:
  - "not grabbed" entries -> forgotten (removed from the queue, download kept)
  - unmatched (no artist/movie/series) completed torrents whose files are already hardlinked
    into the library, i.e. imported by hand -> forgotten, so they keep seeding outside the *arr
  - failed downloads -> blocklist + remove (the *arr re-searches)
  - import problems -> the app's fix_import rules (see lidarr.py, radarr.py, sonarr.py)
  - other usenet warnings/errors -> ntfy (torrent warnings are left to the dead-torrent rule)
  - dead torrents in the app's qBit categories: 0 connected seeds for STALL_HOURS and either
    below 5% (including stuck on metadata) or availability below 1 with no activity -> blocklist
  - the app's missing search at most every MISSING_SEARCH_HOURS (0 disables)
Anything it can't fix is sent to ntfy once (deduplicated across runs).
"""
import os, re, json, time, importlib, traceback, unicodedata, urllib.request, urllib.parse, http.cookiejar
from collections import Counter

QBIT_URL = os.environ.get("QBIT_URL", "http://qbittorrent:8080")
QBIT_USER, QBIT_PASS = os.environ.get("QBIT_USER", ""), os.environ.get("QBIT_PASS", "")
NTFY_URL, NTFY_TOPIC = os.environ.get("NTFY_URL", ""), os.environ.get("NTFY_TOPIC", "")
STATE = os.environ.get("STATE_DIR", "/state")
INTERVAL = int(os.environ.get("INTERVAL", "1800"))
GRACE = float(os.environ.get("GRACE_MINUTES", "20")) * 60
STALL = float(os.environ.get("STALL_HOURS", "24")) * 3600
DRY = os.environ.get("DRY") == "1"
ONCE = os.environ.get("ONCE") == "1"
NOT_UPGRADE = re.compile(r"not an? (custom format |quality revision )?upgrade|equal or higher", re.I)
HEALTHY = {"downloading", "importing", "imported"}
IMPORT_STATES = ("importFailed", "importPending", "importBlocked")


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), re.sub(r"\b[0-9a-f]{32}\b", "***", msg), flush=True)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", (s or "").lower()))


def stem(path):
    return norm(os.path.splitext(os.path.basename(path or ""))[0])


def files_under(path):
    if not path:
        return []
    if os.path.isfile(path):
        return [path]
    return [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs]


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


def ntfy(title, body, priority="default", tags=""):
    if not (NTFY_URL and NTFY_TOPIC):
        return
    try:
        req = urllib.request.Request(f"{NTFY_URL}/{NTFY_TOPIC}", data=body.encode(),
                                     headers={"Title": title, "Priority": priority, "Tags": tags})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log("WARNING: ntfy send failed:", e)


class Qbit:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        # qBittorrent 5.x answers 204 with an empty body on success, so only "Fails." is checked.
        if self.post("auth/login", {"username": QBIT_USER, "password": QBIT_PASS}).strip() == b"Fails.":
            raise RuntimeError("qBittorrent login failed (check QBIT_USER/QBIT_PASS)")

    def post(self, path, data):
        return self.op.open(f"{QBIT_URL}/api/v2/{path}", urllib.parse.urlencode(data).encode(), timeout=60).read()

    def torrents(self, category):
        return json.loads(self.op.open(f"{QBIT_URL}/api/v2/torrents/info?" + urllib.parse.urlencode({"category": category}), timeout=60).read())


def dead(t, now):
    if t["progress"] >= 1 or t["num_seeds"] > 0 or now - t["added_on"] < STALL:
        return False
    if t["progress"] < 0.05:
        return True
    # Partly downloaded, but nobody has the missing pieces and nothing has moved for a day.
    return t.get("availability", 1) < 1 and now - (t.get("last_activity") or t["added_on"]) > STALL


class Arr:
    """Base rules. Subclasses set the attributes below and implement fix_import."""
    name = ""                 # "Lidarr"
    url = ""                  # default base URL
    api_version = "v3"
    media_id = ""             # queue field linking a row to the library: albumId / movieId / seriesId
    media = ""                # "album" / "movie" / "series", for messages
    queue_params = ""         # include* flags for /queue
    category_field = ""       # qBit download client field holding the category
    missing_command = {}      # body for POST /command
    missing_hours = 24.0
    tag = ""                  # ntfy emoji tag

    def __init__(self):
        key = self.name.upper()
        self.base = os.environ.get(f"{key}_URL", self.url)
        self.config = os.environ.get(f"{key}_CONFIG", f"/{self.name.lower()}/config.xml")
        self.missing_hours = float(os.environ.get("MISSING_SEARCH_HOURS", self.missing_hours))
        self.qbit = None

    def key(self):
        # Read on every call so a rotated key is picked up without a restart.
        return re.search(r"<ApiKey>([^<]+)", open(self.config).read()).group(1)

    def api(self, p, m="GET", b=None):
        r = urllib.request.Request(f"{self.base}/api/{self.api_version}{p}", method=m,
                                   data=None if b is None else json.dumps(b).encode(),
                                   headers={"X-Api-Key": self.key(), "Content-Type": "application/json"})
        t = urllib.request.urlopen(r, timeout=600).read()
        return json.loads(t) if t else None

    def wait(self, cid, tries=120):
        for _ in range(tries):
            time.sleep(5)
            if self.api(f"/command/{cid}")["status"] in ("completed", "failed"):
                return

    def remove(self, rows):
        """Remove a download from the client and blocklist it; the *arr then searches again."""
        if not DRY:
            self.api("/queue/bulk?removeFromClient=true&blocklist=true&skipRedownload=false", "DELETE",
                     {"ids": [r["id"] for r in rows]})

    def forget(self, rows):
        """Stop tracking a download but keep it in the client."""
        if not DRY:
            self.api("/queue/bulk?removeFromClient=false&blocklist=false", "DELETE", {"ids": [r["id"] for r in rows]})

    def label(self, rows):
        return rows[0].get("title", "?")[:60]

    def fix_import(self, rows, torrent):
        """Returns (action, None) when handled or (None, reason) when it needs the user."""
        return None, "no import rules"

    def summary(self):
        return None

    def run(self):
        actions, needs_user = [], {}
        now = time.time()
        seen = load_state("seen.json", {})
        q = self.api(f"/queue?pageSize=2000&{self.queue_params}")["records"]
        groups = {}
        for r in q:
            groups.setdefault(r.get("downloadId") or str(r["id"]), []).append(r)
        log("queue", len(q), "rows,", len(groups), "downloads",
            dict(Counter(f"{rs[0].get('trackedDownloadState')}/{rs[0].get('trackedDownloadStatus')}" for rs in groups.values())))
        self.qbit = Qbit() if QBIT_USER else None
        stuck = set()
        for did, rows in groups.items():
            r = rows[0]
            state, status = r.get("trackedDownloadState"), r.get("trackedDownloadStatus")
            if r.get("status") == "delay" or (state in HEALTHY and status == "ok"):
                continue
            stuck.add(did)
            # Give the *arr's own import/failure handling a chance before stepping in.
            if now - seen.setdefault(did, now) < GRACE:
                continue
            name = self.label(rows)
            msgs = "; ".join(m for s in r.get("statusMessages", []) for m in [s.get("title", "")] + s.get("messages", []))
            torrent = r.get("protocol") == "torrent"
            try:
                if not r.get(self.media_id) and re.search(r"(wasn't|was not|not) grabbed", msgs, re.I):
                    self.forget(rows)
                    actions.append(f"removed stale: {r['title'][:60]}")
                elif state in ("failedPending", "failed"):
                    self.remove(rows)
                    actions.append(f"failed -> blocklisted: {name}")
                elif not r.get(self.media_id):
                    files = files_under(r.get("outputPath")) if state in IMPORT_STATES else []
                    linked = sum(1 for f in files if os.stat(f).st_nlink > 1)
                    if torrent and linked:
                        self.forget(rows)
                        actions.append(f"unmatched, {linked}/{len(files)} files already in library -> forgotten: {r['title'][:60]}")
                    else:
                        needs_user[f"unmatched:{did}"] = f"no {self.media} match, {state}/{status} ({msgs[:100]}): {r['title'][:80]}"
                elif state in IMPORT_STATES:
                    done, why = self.fix_import(rows, torrent)
                    if done:
                        actions.append(f"{name}: {done}")
                    else:
                        needs_user[f"import:{did}"] = f"{name}: {why} | {r['title'][:80]}"
                # Torrent warnings ("stalled", "no connections") are left to the dead-torrent rule below.
                elif status in ("warning", "error") and not torrent:
                    needs_user[f"warn:{did}"] = f"{name}: {state}/{status} {msgs[:150]}"
            except Exception as e:
                needs_user[f"err:{did}"] = f"{name}: {type(e).__name__}: {e}"[:200]

        if self.qbit:
            cats = {f.get("value") for c in self.api("/downloadclient") if c["implementation"] == "QBittorrent"
                    for f in c["fields"] if f["name"] == self.category_field} - {None, ""}
            byhash = {k.lower(): v for k, v in groups.items()}
            for cat in sorted(cats):
                for t in self.qbit.torrents(cat):
                    if not dead(t, now):
                        continue
                    rows = byhash.get(t["hash"].lower())
                    if rows and rows[0].get(self.media_id):
                        self.remove(rows)
                        actions.append(f"dead torrent ({t['state']}, {t['progress']:.0%}) -> blocklisted: {t['name'][:60]}")
                    else:
                        needs_user[f"stalled:{t['hash']}"] = f"dead torrent not matched in {self.name}: {t['name'][:80]}"

        if self.missing_hours > 0:
            cmd = self.missing_command["name"]
            cutoff = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - self.missing_hours * 3600))
            recent = now - load_state("last_missing.json", {}).get("at", 0) < self.missing_hours * 3600
            recent = recent or any(c["name"] == cmd and (c.get("started") or c.get("queued") or "") >= cutoff
                                   for c in self.api("/command"))
            if not recent and not DRY:
                self.api("/command", "POST", self.missing_command)
                save_state("last_missing.json", {"at": now})
                actions.append(f"triggered {cmd}")

        for a in actions:
            log("ACTION:", a)
        for v in needs_user.values():
            log("NEEDS USER:", v)
        s = self.summary()
        if s:
            log(s)
        save_state("seen.json", {k: v for k, v in seen.items() if k in stuck})

        notified = load_state("notified.json", {})
        new = [v for k, v in needs_user.items() if k not in notified]
        if new and not DRY:
            ntfy(f"{self.name}: needs attention", "\n".join(new), "default", f"{self.tag},warning")
        save_state("notified.json", {k: notified.get(k, now) for k in needs_user})


def main():
    app = importlib.import_module(os.environ["APP"].lower()).App()
    os.makedirs(STATE, exist_ok=True)
    while True:
        try:
            app.run()
            save_state("last_ok.json", {"at": time.time()})
        except Exception as e:
            log("ERROR:", traceback.format_exc())
            err = load_state("last_error.json", {})
            msg = f"{type(e).__name__}: {e}"[:300]
            if err.get("msg") != msg or time.time() - err.get("at", 0) > 6 * 3600:
                if not DRY:
                    ntfy(f"{app.name} maintenance: run failed", msg, "high", f"{app.tag},rotating_light")
                save_state("last_error.json", {"msg": msg, "at": time.time()})
        if ONCE:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
