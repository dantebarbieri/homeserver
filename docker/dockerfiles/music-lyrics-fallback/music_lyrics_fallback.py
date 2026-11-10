"""Shared LRCLIB sidecars for Plex and Navidrome; never write audio or replace lyrics."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import mutagen
import yaml

LOG = logging.getLogger("music-lyrics-fallback")
STATE = Path(os.environ.get("STATE_DIR", "/state"))
MUSIC = Path(os.environ.get("MUSIC_ROOT", "/music"))
PLEX_ROOT = PurePosixPath("/data/media/music")
INTERVAL = 86400
RECHECK = 30 * 86400
MAX_BYTES = 2 * 1024 * 1024
SIDECARS = {".lrc", ".txt", ".yaml", ".yml", ".ttml", ".elrc", ".srt"}
STAMP = re.compile(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]")


class Unmatched(Exception):
    """Source metadata does not establish a safe match."""


def norm(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    with tempfile.NamedTemporaryFile(dir=STATE, prefix=".lyrics-state-", mode="w",
                                     encoding="utf-8", delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, STATE / name)
    finally:
        tmp.unlink(missing_ok=True)


def load_state():
    try:
        state = json.loads((STATE / "state.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"tracks": {}, "refresh": []}
    if not isinstance(state.get("tracks"), dict) or not isinstance(state.get("refresh"), list):
        raise ValueError("invalid lyrics state; refusing to discard provenance")
    return state


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("API redirects are not allowed")


def retry_delay(value, attempt):
    if value:
        try:
            delay = float(value)
        except ValueError:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        if not math.isfinite(delay):
            raise ValueError("invalid Retry-After")
        return max(0, delay) + 1
    return 2 ** (attempt + 1)


class Web:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())
        self.last = 0.0

    def request(self, url, *, headers=None, method="GET", public=False):
        for attempt in range(3):
            if public:
                time.sleep(max(0, 1.0 - (time.monotonic() - self.last)))
                self.last = time.monotonic()
            req = urllib.request.Request(url, method=method, headers=headers or {
                "User-Agent": "homeserver-music-lyrics/1.0 (https://github.com/dantebarbieri/homeserver)",
                "Accept": "application/json",
            })
            try:
                with self.opener.open(req, timeout=45) as r:
                    limit = MAX_BYTES if public else 32 * 1024 * 1024
                    body = r.read(limit + 1)
                if len(body) > limit:
                    raise ValueError("API response too large")
                return json.loads(body) if body else None
            except urllib.error.HTTPError as error:
                if public and error.code == 404:
                    return None
                if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise RuntimeError(f"HTTP {error.code} from {urllib.parse.urlsplit(url).hostname}") from None
                delay = retry_delay(error.headers.get("Retry-After"), attempt)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError(f"request failed for {urllib.parse.urlsplit(url).hostname}") from None
                delay = retry_delay(None, attempt)
            LOG.warning("retrying %s in %.1fs", urllib.parse.urlsplit(url).hostname, delay)
            time.sleep(delay)

    def lyrics(self, track):
        params = dict(zip(("artist_name", "album_name", "track_name", "duration"),
                          (track["artist"], track["album"], track["title"], track["duration"])))
        return self.request("https://lrclib.net/api/get?" + urllib.parse.urlencode(params), public=True)


class Plex:
    def __init__(self, web):
        self.web = web
        self.url = os.environ.get("PLEX_URL", "http://plex:32400").rstrip("/")
        self.section = os.environ.get("PLEX_SECTION", "8")
        token = ET.parse("/plex/Preferences.xml").getroot().get("PlexOnlineToken")
        if not token:
            raise RuntimeError("Plex token missing")
        self.headers = {"X-Plex-Token": token, "Accept": "application/json"}

    def api(self, path, method="GET"):
        return self.web.request(self.url + path, headers=self.headers, method=method)

    def tracks(self):
        start, tracks = 0, []
        while True:
            page = self.api(f"/library/sections/{self.section}/all?type=10&"
                            f"X-Plex-Container-Start={start}&X-Plex-Container-Size=500")["MediaContainer"]
            items = page.get("Metadata", [])
            tracks.extend(items)
            start += len(items)
            if start >= page.get("totalSize", 0):
                break
            if not items:
                raise RuntimeError("truncated Plex library response")
        if not tracks:
            raise RuntimeError("Plex music library is empty")
        return sorted(tracks, key=lambda t: (-float(t.get("userRating", 0)), int(t["ratingKey"])))

    def timed(self, key):
        track = self.api(f"/library/metadata/{key}")["MediaContainer"]["Metadata"][0]
        return any(s.get("streamType") == 4 and (s.get("timed") or s.get("format") == "lrc")
                   for m in track.get("Media", []) for p in m.get("Part", [])
                   for s in p.get("Stream", []))

    def refresh(self, album_key):
        # Plex's music agent discovers local lyrics during album, not track, refresh.
        self.api(f"/library/metadata/{album_key}/refresh", method="PUT")


def path_for(filename):
    relative = PurePosixPath(filename).relative_to(PLEX_ROOT)
    if ".." in relative.parts or "\\" in filename:
        raise ValueError("unsafe music path")
    path = MUSIC.joinpath(*relative.parts)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise Unmatched("symlink in audio path")
    path.resolve(strict=True).relative_to(MUSIC.resolve(strict=True))
    if not stat.S_ISREG(path.stat().st_mode):
        raise Unmatched("not a regular audio file")
    return path


def existing(path):
    return [p for p in path.parent.iterdir()
            if p.stem.casefold() == path.stem.casefold() and p.suffix.casefold() in SIDECARS]


def describe(item, path):
    audio = mutagen.File(path)
    if audio is None:
        raise Unmatched("unsupported audio format")
    embedded = any(str(k).casefold().split(":")[0] in {
        "uslt", "sylt", "lyrics", "unsyncedlyrics", "\u00a9lyr", "wm/lyrics",
    } for k in audio.tags or {})
    track = {
        "artist": item.get("originalTitle") or item.get("grandparentTitle"),
        "album": item.get("parentTitle"), "title": item.get("title"),
        "duration": round(audio.info.length, 3),
    }
    if not all(isinstance(track[k], str) and norm(track[k]) for k in ("artist", "album", "title")):
        raise Unmatched("missing artist/album/title")
    if not 1 <= track["duration"] <= 3600:
        raise Unmatched("duration outside source API range")
    info = path.stat()
    fingerprint = digest(json.dumps([track, info.st_size, info.st_mtime_ns]).encode())
    return track, fingerprint, embedded


def matched(track, source):
    return (isinstance(source, dict)
            and all(isinstance(source.get(b), str) and norm(track[a]) == norm(source[b])
                    for a, b in (("artist", "artistName"), ("album", "albumName"), ("title", "trackName")))
            and isinstance(source.get("duration"), (int, float))
            and abs(track["duration"] - source["duration"]) <= 2)


class LyricsLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        # Navidrome decodes these into strings; YAML 1.1 otherwise turns lyrics
        # such as unquoted "no" or "on" into booleans in PyYAML.
        for key, value in node.value:
            if (key.value in {"text", "plain", "artist", "title", "album", "language", "version"}
                    and isinstance(value, yaml.ScalarNode) and value.tag != "tag:yaml.org,2002:null"):
                mapping[key.value] = value.value
        return mapping


def validate_yaml(text, track):
    if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
        raise ValueError("lyrics YAML aliases are not allowed")
    doc = yaml.load(text, Loader=LyricsLoader)
    if not isinstance(doc, dict) or str(doc.get("version")) != "1.0":
        raise ValueError("invalid Lyricsfile version")
    metadata = doc.get("metadata", {})
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(k), str) or norm(metadata[k]) != norm(track[k])
        for k in ("artist", "title")
    ):
        raise ValueError("Lyricsfile metadata mismatch")
    lines = doc.get("lines") or []
    if not isinstance(lines, list) or len(lines) > 20000:
        raise ValueError("invalid Lyricsfile lines")
    words = 0
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            raise ValueError("invalid lyric line")
        cues = line.get("words") or []
        if not isinstance(cues, list) or len(cues) > 20000:
            raise ValueError("invalid lyric cues")
        words += len(cues)
        for entry in [line, *cues]:
            if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
                raise ValueError("invalid cue")
            for field in ("start_ms", "end_ms"):
                value = entry.get(field)
                if value is None and field == "end_ms":
                    continue
                if type(value) is not int or not 0 <= value <= (track["duration"] + 3) * 1000:
                    raise ValueError("lyric timestamp outside recording")
            if entry.get("end_ms", entry["start_ms"]) is not None and (
                    entry.get("end_ms", entry["start_ms"]) < entry["start_ms"]):
                raise ValueError("lyric ends before it starts")
    if not lines and not (isinstance(doc.get("plain"), str) and doc["plain"].strip()):
        raise ValueError("empty Lyricsfile")
    return words


def payloads(track, source, plex_timed=False):
    if not matched(track, source):
        raise Unmatched("source artist/title/album/duration mismatch")
    if source.get("instrumental"):
        return {}, "instrumental"
    result = {}
    lrc, plain, structured = (source.get(k) for k in ("syncedLyrics", "plainLyrics", "lyricsfile"))
    for text in (lrc, plain, structured):
        if text is not None and (not isinstance(text, str) or len(text.encode()) > MAX_BYTES or "\0" in text):
            raise ValueError("invalid lyrics payload")
    if lrc and lrc.strip():
        stamps = STAMP.findall(lrc)
        times = [int(m) * 60 + int(s) + float("0." + (frac or "0")) for m, s, frac in stamps]
        if not times or any(int(s) >= 60 for _, s, _ in stamps) or max(times) > track["duration"] + 3:
            raise ValueError("invalid LRC timestamps")
        result[".lrc"] = lrc.encode("utf-8")
    elif plain and plain.strip() and not plex_timed:
        result[".txt"] = plain.encode("utf-8")
    if structured and structured.strip():
        words = validate_yaml(structured, track)
        if source.get("hasWordSync") and not words:
            raise ValueError("word-synced source has no word cues")
        result[".yaml"] = structured.encode("utf-8")
    elif plain and plain.strip() and plex_timed:
        result[".yaml"] = yaml.safe_dump({
            "version": "1.0", "metadata": {"title": track["title"], "artist": track["artist"]},
            "plain": plain,
        }, allow_unicode=True).encode("utf-8")
    if not result:
        raise Unmatched("source has no usable lyrics")
    return result, "word" if source.get("hasWordSync") else "timed" if ".lrc" in result else "plain"


def publish(path, data):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".lyrics-", delete=False) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o644)
        os.link(tmp, path)  # Atomic, and refuses an existing file or symlink.
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def flush_refresh(plex, state):
    for key in state["refresh"][:]:
        plex.refresh(key)
        state["refresh"].remove(key)
        save("state.json", state)


def run(plex, web, args):
    state = load_state()
    counts, report, lookups = Counter(), [], 0
    if not args.dry_run:
        save("state.json", state)
        flush_refresh(plex, state)
    items = plex.tracks()
    paths = Counter(
        str(PurePosixPath(p["file"]).with_suffix("")).casefold()
        for item in items for m in item.get("Media", []) for p in m.get("Part", []) if p.get("file")
    )
    for item in items:
        key = str(item["ratingKey"])
        if args.keys and key not in args.keys:
            continue
        for media in item.get("Media", []):
            for part in media.get("Part", []):
                if not part.get("file"):
                    continue
                try:
                    path = path_for(part["file"])
                    relative = path.relative_to(MUSIC).as_posix()
                    if paths[str(PurePosixPath(part["file"]).with_suffix("")).casefold()] != 1:
                        raise Unmatched("multiple audio files share a sidecar stem")
                    previous = state["tracks"].get(relative, {})
                    sidecars = existing(path)
                    pending = previous.get("status") == "publishing"
                    if sidecars and not pending:
                        counts["existing"] += 1
                        continue
                    track, fingerprint, embedded = describe(item, path)
                    if embedded:
                        counts["embedded"] += 1
                        continue
                    if (not pending and previous.get("fingerprint") == fingerprint
                            and previous.get("retry_at", 0) > time.time()):
                        counts["cached"] += 1
                        continue
                    if args.limit and lookups >= args.limit:
                        counts["deferred"] += 1
                        continue
                    source = web.lyrics(track)
                    lookups += 1
                    result = "missing"
                    files = {}
                    if source is not None:
                        if not isinstance(source, dict):
                            raise ValueError("unexpected LRCLIB response shape")
                        timed = plex.timed(key) if not source.get("syncedLyrics") else False
                        try:
                            files, result = payloads(track, source, timed)
                        except yaml.YAMLError:
                            raise Unmatched("invalid source Lyricsfile YAML") from None
                        except ValueError as error:
                            raise Unmatched(f"invalid source lyrics: {error}") from None
                    if not args.dry_run:
                        record = {"fingerprint": fingerprint, "source_id": source.get("id") if source else None,
                                  "result": result, "retry_at": time.time() + RECHECK,
                                  "files": {ext: digest(data) for ext, data in files.items()},
                                  "status": "publishing" if files else "complete"}
                        if pending and (previous["fingerprint"] != fingerprint or previous["files"] != record["files"]):
                            raise ValueError("interrupted publication changed; manual review required")
                        if any(p.is_symlink() or p.suffix not in previous.get("files", {})
                               or digest(p.read_bytes()) != previous["files"][p.suffix] for p in sidecars):
                            raise ValueError("existing sidecar changed; refusing publication")
                        if not pending and existing(path):
                            raise ValueError("lyrics appeared during lookup; leaving them untouched")
                        if describe(item, path)[1] != fingerprint:
                            raise ValueError("audio changed during lookup")
                        album_key = str(item.get("parentRatingKey", ""))
                        if set(files) & {".lrc", ".txt"}:
                            if not album_key.isdigit():
                                raise ValueError("Plex track has no album refresh target")
                            if album_key not in state["refresh"]:
                                state["refresh"].append(album_key)
                        state["tracks"][relative] = record
                        save("state.json", state)
                        for ext, data in files.items():
                            target = path.with_suffix(ext)
                            if target not in sidecars:
                                publish(target, data)
                        record["status"] = "complete"
                        save("state.json", state)
                    counts[result] += 1
                    report.append({"path": relative, "result": result,
                                   "source_id": source.get("id") if source else None})
                    LOG.info("%s%s: %s", "DRY " if args.dry_run else "", result, relative)
                except Unmatched as error:
                    counts["unmatched"] += 1
                    LOG.warning("%s: %s", part["file"], error)
                    report.append({"path": part["file"], "result": "unmatched", "reason": str(error)})
                if not args.dry_run:
                    save("progress.json", {"at": time.time(), "counts": dict(counts), "lookups": lookups})
                    if lookups and lookups % 50 == 0:
                        flush_refresh(plex, state)
    summary = {"at": time.time(), "counts": dict(counts), "lookups": lookups, "tracks": report}
    if not args.dry_run:
        flush_refresh(plex, state)
        save("report.json", summary)
    LOG.info("finished: %s", json.dumps(dict(counts)))
    return summary


def healthcheck():
    if os.environ.get("ENABLED") != "1":
        return 0
    try:
        heartbeat = json.loads((STATE / "health.json").read_text())
        return int(not heartbeat["ok"] or not 0 <= time.time() - heartbeat["at"] < INTERVAL + 3600)
    except (OSError, ValueError, KeyError) as error:
        print("lyrics health unavailable:", error)
        return 1


def notify_failure():
    url, topic = os.environ.get("NTFY_URL"), os.environ.get("NTFY_TOPIC")
    if url and topic:
        req = urllib.request.Request(url.rstrip("/") + "/" + topic,
                                     data=b"See docker logs music-lyrics-fallback. Existing audio and lyrics were not replaced.",
                                     headers={"Title": "Music lyrics fallback failed", "Tags": "warning"})
        with urllib.request.urlopen(req, timeout=30):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Maximum new lookups (0 = whole library)")
    parser.add_argument("--keys", default="", help="Comma-separated Plex track IDs for a targeted preview/run")
    args = parser.parse_args()
    args.keys = set(args.keys.split(",")) if args.keys else set()
    if args.limit < 0 or any(not k.isdigit() for k in args.keys):
        parser.error("limit must be nonnegative and keys must be numeric")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *unused: sys.exit(0))
    if os.environ.get("ENABLED") != "1" and not args.dry_run:
        LOG.info("disabled; set MUSIC_LYRICS_FALLBACK_ENABLED=1 after previewing")
        if args.once:
            return 1
        while True:
            time.sleep(3600)
    if not args.dry_run:
        import fcntl
        STATE.mkdir(parents=True, exist_ok=True)
        lock = (STATE / "run.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    while True:
        try:
            if not args.dry_run:
                save("health.json", {"at": time.time(), "ok": True})
            web = Web()
            run(Plex(web), web, args)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, mutagen.MutagenError, yaml.YAMLError):
            LOG.exception("lyrics run failed")
            if not args.dry_run:
                save("health.json", {"at": time.time(), "ok": False})
                try:
                    notify_failure()
                except (OSError, ValueError):
                    LOG.exception("lyrics failure notification failed")
            if args.once:
                return 1
        else:
            if not args.dry_run:
                save("health.json", {"at": time.time(), "ok": True})
            if args.once:
                return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
