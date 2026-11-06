"""Supply missing album artwork as shared cover.jpg files; never edit audio or replace artwork."""
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import signal
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET

import mutagen
from PIL import Image, ImageOps

LOG = logging.getLogger("music-cover-fallback")
STATE = Path(os.environ.get("STATE_DIR", "/state"))
MUSIC = Path(os.environ.get("MUSIC_ROOT", "/music"))
LIDARR_ROOT = PurePosixPath(os.environ.get("LIDARR_MUSIC_ROOT", "/data/media/music"))
INTERVAL = int(os.environ.get("INTERVAL", "86400"))
ENABLED = os.environ.get("ENABLED") == "1"
DRY = os.environ.get("DRY") == "1"
ONCE = os.environ.get("ONCE") == "1"
MAX_BYTES = 10 * 1024 * 1024
MAX_API_BYTES = 32 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PUBLIC_HOSTS = ("coverartarchive.org", "archive.org", "itunes.apple.com",
                "mzstatic.com", "api.deezer.com", "dzcdn.net")


class Unresolved(Exception):
    """Missing/ambiguous metadata: leave this album alone and report it."""


def norm(value):
    text = unicodedata.normalize("NFKD", value).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def public_url(url):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
            or not any(p.hostname == h or (p.hostname or "").endswith("." + h) for h in PUBLIC_HOSTS)):
        raise ValueError("untrusted public artwork URL")
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, public_url(newurl))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("refusing an authenticated API redirect")


class Web:
    def __init__(self):
        self.public = urllib.request.build_opener(PublicRedirect())
        self.private = urllib.request.build_opener(NoRedirect())
        self.last = 0.0

    def read(self, url, *, headers=None, method="GET", missing_ok=False):
        external = headers is None
        limit = MAX_BYTES if external else MAX_API_BYTES
        if external:
            public_url(url)
        for attempt in range(3):
            if external:
                # Below Apple's documented ~20 requests/minute search limit.
                time.sleep(max(0, 3.1 - (time.monotonic() - self.last)))
                self.last = time.monotonic()
            req = urllib.request.Request(url, method=method, headers=headers or {
                "User-Agent": "homeserver-music-cover-fallback/1.0 (https://danteb.com)",
            })
            try:
                with (self.public if external else self.private).open(req, timeout=45) as response:
                    data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError(f"response exceeds {limit // (1024 * 1024)} MiB")
                return data
            except urllib.error.HTTPError as e:
                if missing_ok and e.code == 404:
                    return None
                if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).hostname}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError(f"request failed for {urllib.parse.urlsplit(url).hostname}") from None
            time.sleep(2 ** (attempt + 1))

    def json(self, url, **kwargs):
        data = self.read(url, **kwargs)
        if data is None:
            return None
        result = json.loads(data)
        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"API error from {urllib.parse.urlsplit(url).hostname}")
        return result


class Lidarr:
    def __init__(self, web):
        self.web = web
        self.url = os.environ.get("LIDARR_URL", "http://lidarr:8686").rstrip("/") + "/api/v1"
        key = ET.parse(os.environ.get("LIDARR_CONFIG", "/lidarr/config.xml")).findtext("ApiKey")
        if not key:
            raise RuntimeError("Lidarr config has no API key")
        self.headers = {"X-Api-Key": key, "Accept": "application/json"}

    def get(self, path, **params):
        return self.web.json(self.url + path + "?" + urllib.parse.urlencode(params), headers=self.headers)

    def albums(self):
        # /album includes entire discographies (~190 MB here), not just downloaded music.
        for artist in self.get("/artist"):
            if artist.get("statistics", {}).get("trackFileCount"):
                for album in self.get("/album", artistId=artist["id"]):
                    if album.get("statistics", {}).get("trackFileCount"):
                        yield album


def load_state():
    try:
        with (STATE / "state.json").open() as f:
            state = json.load(f)
    except FileNotFoundError:
        return {"covers": {}}
    if not isinstance(state, dict) or not isinstance(state.get("covers"), dict):
        raise ValueError("invalid cover fallback state; refusing to discard provenance")
    return state


def save_state(name, value):
    tmp = STATE / (name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE / name)


def album_files(files):
    paths = []
    root = MUSIC.resolve(strict=True)
    for row in files:
        relative = PurePosixPath(row["path"]).relative_to(LIDARR_ROOT)
        if ".." in relative.parts or "\\" in str(relative):
            raise ValueError("unsafe library path")
        path = MUSIC.joinpath(*relative.parts)
        # Do not follow symlinks, including symlinks to other albums inside the library.
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("symlink in album path")
        path.resolve(strict=True).relative_to(root)
        if not path.is_file():
            raise ValueError("track is not a regular file")
        paths.append(path)
    folders = {p.parent for p in paths}
    if len(folders) != 1 or len(next(iter(folders)).relative_to(MUSIC).parts) != 2:
        raise Unresolved("expected one Artist/Album folder; no flat or multi-folder imports")
    return paths


def existing_art(paths):
    # Even nonstandard sidecar names might be a deliberately chosen cover.
    if any(p.suffix.casefold() in IMAGE_SUFFIXES for p in paths[0].parent.iterdir()):
        return True
    for path in paths:
        audio = mutagen.File(path)
        if audio is None:
            raise Unresolved(f"cannot inspect embedded artwork in {path.name}")
        if getattr(audio, "pictures", None):
            return True
        for key in audio.tags or {}:
            if str(key).casefold().split(":")[0] in {
                    "apic", "covr", "metadata_block_picture", "coverart", "wm/picture"}:
                return True
    return False


def image_data(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("image exceeds 10 MiB")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("unsupported artwork format")
            w, h = image.size
            if min(w, h) < 300 or max(w, h) > 8000 or not 0.5 <= w / h <= 2:
                raise ValueError("artwork dimensions outside safe limits")
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            small = list(image.resize((16, 16)).convert("L").tobytes())
            average = sum(small) / len(small)
            fingerprint = [p > average for p in small]
            image.thumbnail((1600, 1600))
            output = io.BytesIO()
            image.save(output, "JPEG", quality=95)
            return output.getvalue(), fingerprint


def track_match(expected, actual):
    if not expected or len(expected) != len(actual):
        return False
    return all(norm(e["title"]) == norm(a["title"]) and e["duration"] > 0 and a["duration"] > 0
               and abs(e["duration"] - a["duration"]) <= 5 for e, a in zip(expected, actual))


class Sources:
    def __init__(self, web):
        self.web = web

    def caa(self, album, release):
        for kind, mbid in (("release", release["foreignReleaseId"]),
                           ("release-group", album["foreignAlbumId"])):
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", mbid):
                raise ValueError("invalid MusicBrainz identifier")
            url = f"https://coverartarchive.org/{kind}/{mbid}"
            data = self.web.json(url, missing_ok=True)
            if data is not None and (not isinstance(data, dict) or not isinstance(data.get("images"), list)):
                raise ValueError("invalid Cover Art Archive response")
            for image in data["images"] if data is not None else []:
                if image.get("front") and image.get("approved"):
                    image_url = image.get("thumbnails", {}).get("1200") or image["image"]
                    # The CAA still publishes some http links; fetch the HTTPS equivalent only.
                    image_url = re.sub(r"^http:", "https:", image_url)
                    return {"source": "Cover Art Archive", "url": url, "image": image_url}
        return None

    def apple(self, artist, title, expected):
        url = "https://itunes.apple.com/search?" + urllib.parse.urlencode({
            "term": f"{artist} {title}", "entity": "album", "limit": 25, "country": "US"})
        data = self.web.json(url)
        results = data["results"]
        if len(results) >= 25:
            raise Unresolved("Apple search was truncated")
        hits = [h for h in results if norm(h["artistName"]) == norm(artist)
                and norm(re.sub(r" - (Single|EP)$", "", h["collectionName"])) == norm(title)
                and h.get("trackCount") == len(expected)]
        if len(hits) > 5:
            raise Unresolved("too many Apple editions")
        out = []
        for h in hits:
            data = self.web.json(f"https://itunes.apple.com/lookup?id={int(h['collectionId'])}&entity=song&country=US")
            tracks = sorted((t for t in data["results"] if t.get("wrapperType") == "track"),
                            key=lambda t: (t["discNumber"], t["trackNumber"]))
            actual = [{"title": t["trackName"], "duration": t["trackTimeMillis"] / 1000} for t in tracks]
            if track_match(expected, actual):
                out.append({"source": "Apple Music", "url": h["collectionViewUrl"],
                            "image": re.sub(r"/\d+x\d+bb\.", "/1400x1400bb.", h["artworkUrl100"])})
        return out

    def deezer(self, artist, title, expected):
        url = "https://api.deezer.com/search/album?" + urllib.parse.urlencode({
            "q": f'artist:"{artist}" album:"{title}"', "limit": 25})
        data = self.web.json(url)
        if data.get("next") or data["total"] > 25:
            raise Unresolved("Deezer search was truncated")
        hits = [h for h in data["data"] if norm(h["artist"]["name"]) == norm(artist)
                and norm(h["title"]) == norm(title) and h.get("nb_tracks") == len(expected)]
        if len(hits) > 5:
            raise Unresolved("too many Deezer editions")
        out = []
        for h in hits:
            data = self.web.json(f"https://api.deezer.com/album/{int(h['id'])}")
            tracks = data["tracks"]
            if tracks.get("next"):
                continue  # Never accept a partially fetched release.
            actual = [{"title": t["title"], "duration": t["duration"]} for t in tracks["data"]]
            if (norm(data["artist"]["name"]) == norm(artist) and norm(data["title"]) == norm(title)
                    and data["nb_tracks"] == len(expected) and track_match(expected, actual)):
                out.append({"source": "Deezer", "url": data["link"], "image": data["cover_xl"]})
        return out

    def choose(self, album, release, expected):
        candidate = self.caa(album, release)
        if candidate:
            return image_data(self.web.read(candidate["image"]))[0], [candidate]
        candidates, errors = [], []
        for name, source in (("Apple Music", self.apple), ("Deezer", self.deezer)):
            try:
                candidates += source(album["artist"]["artistName"], album["title"], expected)
            except Unresolved:
                raise  # An ambiguous search is not permission to pick the other store blindly.
            except (RuntimeError, ValueError, KeyError) as e:
                LOG.warning("%s lookup failed: %s", name, e)
                errors.append(str(e))
        if not candidates:
            if errors:
                raise RuntimeError("; ".join(errors))
            raise Unresolved("no exact store match (artist, edition, ordered titles and durations)")
        images = [image_data(self.web.read(c["image"])) for c in candidates]
        if any(sum(a != b for a, b in zip(images[0][1], image[1])) > 12 for image in images[1:]):
            raise Unresolved("matched stores/editions disagree on artwork")
        return images[0][0], candidates


def publish_cover(folder, data):
    """Publish a complete file atomically, without ever replacing another writer's cover."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".cover-fallback-", delete=False) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o644)
        os.link(tmp, folder / "cover.jpg")
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def refresh_plex(web, folder, album):
    """Refresh only missing-art items in this folder; leave chosen Plex posters locked/untouched."""
    url = os.environ.get("PLEX_URL", "http://plex:32400").rstrip("/")
    section = os.environ.get("PLEX_SECTION", "8")
    token = ET.parse(os.environ.get("PLEX_PREFS", "/plex/Preferences.xml")).getroot().get("PlexOnlineToken")
    if not token:
        raise RuntimeError("Plex preferences have no token")
    headers = {"Accept": "application/json", "X-Plex-Token": token}
    api = lambda path, **kw: web.json(url + path, headers=headers, **kw)
    library_path = str(LIDARR_ROOT.joinpath(*folder.relative_to(MUSIC).parts))
    prefs = api(f"/library/sections/{section}/prefs")["MediaContainer"]["Setting"]
    art = next((p for p in prefs if p["id"] == "albumPosters"), None)
    if not art or str(art["value"]) not in {"1", "3"}:
        raise RuntimeError("Plex Album Art must allow Local Files; cover.jpg is saved but refresh is pending")
    web.read(url + f"/library/sections/{section}/refresh?" + urllib.parse.urlencode({"path": library_path}),
             headers=headers)
    items = api(f"/library/sections/{section}/all?" + urllib.parse.urlencode(
        {"type": 9, "title": album["title"]}))["MediaContainer"].get("Metadata", [])
    for item in items:
        key = item["ratingKey"]
        if ((item.get("thumb") or "").startswith(f"/library/metadata/{key}/")
                or norm(item.get("parentTitle", "")) != norm(album["artist"]["artistName"])):
            continue
        full = api(f"/library/metadata/{key}")["MediaContainer"]["Metadata"][0]
        if any(f.get("name") == "thumb" and f.get("locked") for f in full.get("Field", [])):
            continue
        children = api(f"/library/metadata/{key}/children")["MediaContainer"].get("Metadata", [])
        paths = [p["file"] for t in children for m in t.get("Media", []) for p in m.get("Part", [])]
        if paths and all(str(PurePosixPath(p).parent) == library_path for p in paths):
            web.read(url + f"/library/metadata/{key}/refresh", headers=headers, method="PUT")


def run(lidarr=None, sources=None, refresher=None):
    web = Web()
    lidarr, sources = lidarr or Lidarr(web), sources or Sources(web)
    refresher = refresher or (lambda folder, album: refresh_plex(web, folder, album))
    state = load_state()
    if not DRY:
        save_state("state.json", state)  # Fail before touching the library if provenance isn't writable.
    albums = lidarr.albums()
    report, failures = [], []
    for album in albums:
        if not album.get("statistics", {}).get("trackFileCount"):
            continue
        label = f"{album['artist']['artistName']} - {album['title']}"
        try:
            files = lidarr.get("/trackfile", albumId=album["id"]) if not any(
                i.get("coverType") == "cover" for i in album.get("images", [])) else None
            if files is None:
                continue  # Lidarr owns the normal MusicBrainz artwork/retag path.
            paths = album_files(files)
            folder = paths[0].parent
            relative = folder.relative_to(MUSIC).as_posix()
            previous = state["covers"].get(relative)
            cover = folder / "cover.jpg"
            if (previous and not cover.is_symlink() and cover.is_file()
                    and hashlib.sha256(cover.read_bytes()).hexdigest() == previous["sha256"]):
                if previous.get("status") != "complete" and not DRY:
                    refresher(folder, album)
                    previous["status"] = "complete"
                    save_state("state.json", state)
                continue
            if existing_art(paths):
                continue
            releases = [r for r in album["releases"] if r.get("monitored")]
            if len(releases) != 1:
                raise Unresolved("no single selected Lidarr release")
            tracks = sorted(lidarr.get("/track", albumId=album["id"]),
                            key=lambda t: (t["mediumNumber"], t["absoluteTrackNumber"]))
            expected = [{"title": t["title"], "duration": t["duration"] / 1000} for t in tracks]
            if len(expected) != releases[0]["trackCount"]:
                raise Unresolved("incomplete Lidarr release track list")
            data, candidates = sources.choose(album, releases[0], expected)
            record = {"album": label, "mbid": album["foreignAlbumId"], "sources": candidates,
                      "sha256": hashlib.sha256(data).hexdigest(), "at": time.time(), "status": "pending"}
            LOG.info("%s %s: %s/cover.jpg (%s)", "DRY would write" if DRY else "writing",
                     label, relative, ", ".join(sorted({c["source"] for c in candidates})))
            if not DRY:
                # Recheck after network lookups; another importer may have added artwork meanwhile.
                if existing_art(paths):
                    LOG.info("artwork appeared during lookup; leaving %s alone", label)
                    continue
                state["covers"][relative] = record
                save_state("state.json", state)
                publish_cover(folder, data)
                refresher(folder, album)
                record["status"] = "complete"
                save_state("state.json", state)
            report.append({"album": label, "folder": relative, "result": "would-write" if DRY else "written",
                           "sources": candidates})
        except Unresolved as e:
            LOG.warning("needs review: %s: %s", label, e)
            report.append({"album": label, "result": "unresolved", "reason": str(e)})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, mutagen.MutagenError) as e:
            LOG.error("%s: %s: %s", label, type(e).__name__, e)
            failures.append(label)
            report.append({"album": label, "result": "error", "reason": f"{type(e).__name__}: {e}"})
    if not DRY:
        save_state("report.json", report)
        issues = sorted(r["album"] + ": " + r["reason"] for r in report if "reason" in r)
        if issues and (issues != state.get("issues") or time.time() - state.get("notified", 0) >= 7 * 86400):
            notify("Music cover fallback needs attention", "\n".join(issues[:12]))
            state["notified"] = time.time()
        state["issues"] = issues
        save_state("state.json", state)
    LOG.info("finished: %s proposals/writes, %s unresolved, %s errors",
             sum("sources" in r for r in report), sum(r["result"] == "unresolved" for r in report), len(failures))
    if failures:
        raise RuntimeError(f"artwork failed for {len(failures)} albums; see logs/report.json")
    return report


def notify(title, body):
    url, topic = os.environ.get("NTFY_URL"), os.environ.get("NTFY_TOPIC")
    if not (url and topic):
        return
    req = urllib.request.Request(url.rstrip("/") + "/" + topic, data=body.encode(),
                                 headers={"Title": title, "Tags": "musical_note,warning"})
    with urllib.request.urlopen(req, timeout=30):
        pass


def healthcheck():
    if not ENABLED:
        print("disabled; awaiting setup and preview")
        return 0
    try:
        with (STATE / "last_ok.json").open() as f:
            age = time.time() - json.load(f)["at"]
        return 0 if 0 <= age < 2 * INTERVAL + 900 else 1
    except (OSError, ValueError, KeyError, TypeError) as e:
        print("no valid successful run:", e)
        return 1


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))
    if not ENABLED and not DRY:
        LOG.info("disabled; set MUSIC_COVER_FALLBACK_ENABLED=1 after previewing (docs/MUSIC.md)")
        if ONCE:
            return 1
        while True:
            time.sleep(3600)
    if not DRY:
        import fcntl
        STATE.mkdir(parents=True, exist_ok=True)
        lock = (STATE / "run.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    while True:
        try:
            run()
            if not DRY:
                save_state("last_ok.json", {"at": time.time()})
        except Exception:
            LOG.exception("cover fallback run failed")
            if not DRY:
                try:
                    notify("Music cover fallback failed", "See docker logs music-cover-fallback; no existing artwork was replaced.")
                except Exception:
                    LOG.exception("failure notification could not be delivered")
            if ONCE:
                return 1
        else:
            if ONCE:
                return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
