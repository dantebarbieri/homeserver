"""Lidarr rules. See docker/docs/MUSIC.md ("Queue maintenance").

  - importFailed/Pending/Blocked: if the file count matches another edition of the album and
    the titles match, ManualImport into it (copy for torrents to keep hardlinks, move for
    usenet); never switches editions on an album that already has files, since that unlinks them
  - a single/EP grabbed for an album (<=4 files for an 8+ track album) -> blocklist + re-search
  - "forget" moves torrents to QBIT_MANUAL_CATEGORY instead of using Lidarr's queue Remove,
    which throws a NullReferenceException (HTTP 500) for items without an artist
"""
import os, re, difflib, urllib.parse, urllib.error
from arr_maint import Arr, DRY, norm

AUD = (".flac", ".m4a", ".mp3", ".ape", ".wv")
QBIT_MANUAL_CATEGORY = os.environ.get("QBIT_MANUAL_CATEGORY", "music-manual")
QBIT_MANUAL_PATH = os.environ.get("QBIT_MANUAL_PATH", "/data/torrents/music-manual")


def strip(fname):
    return re.sub(r"^[\d\s.\-_]+", "", os.path.splitext(fname)[0])


def audio_files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs if f.lower().endswith(AUD))


class App(Arr):
    name = "Lidarr"
    url = "http://lidarr:8686"
    api_version = "v1"
    media_id = "albumId"
    media = "artist/album"
    queue_params = "includeArtist=true&includeAlbum=true&includeUnknownArtistItems=true"
    category_field = "musicCategory"
    missing_command = {"name": "MissingAlbumSearch"}
    missing_hours = 6.0
    tag = "musical_note"

    def label(self, rows):
        r = rows[0]
        return f"{(r.get('artist') or {}).get('artistName')} - {(r.get('album') or {}).get('title', '')[:50]}"

    def remove(self, rows):
        # Search explicitly rather than relying on Lidarr's "Redownload Failed" setting.
        if DRY:
            return
        self.api("/queue/bulk?removeFromClient=true&blocklist=true&skipRedownload=true", "DELETE", {"ids": [r["id"] for r in rows]})
        ids = sorted({r["albumId"] for r in rows if r.get("albumId")})
        if ids:
            self.api("/command", "POST", {"name": "AlbumSearch", "albumIds": ids})

    def forget(self, rows):
        if not (self.qbit and rows[0].get("protocol") == "torrent"):
            return super().forget(rows)
        if DRY:
            return
        # Same filesystem, so setLocation is a rename and keeps hardlinks.
        try:
            self.qbit.post("torrents/createCategory", {"category": QBIT_MANUAL_CATEGORY, "savePath": QBIT_MANUAL_PATH})
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
        h = rows[0]["downloadId"].lower()
        self.qbit.post("torrents/setCategory", {"hashes": h, "category": QBIT_MANUAL_CATEGORY})
        self.qbit.post("torrents/setLocation", {"hashes": h, "location": QBIT_MANUAL_PATH})

    def fix_import(self, rows, torrent):
        albums = sorted({r["albumId"] for r in rows})
        if len(albums) > 1:
            return None, f"download covers {len(albums)} albums"
        r = rows[0]
        nfiles = len(audio_files(r.get("outputPath")))
        counts = {x["trackCount"] for x in self.api(f"/album/{r['albumId']}")["releases"]}
        if nfiles and nfiles <= 4 and counts and min(counts) >= 8:
            self.remove(rows)
            return f"wrong release ({nfiles} files) -> blocklisted+re-search", None
        res = self.import_dir(r.get("outputPath") or "", r["albumId"], "copy" if torrent else "move", r["downloadId"])
        return (res, None) if res.startswith(("imported", "DRY")) else (None, res)

    def import_dir(self, folder, album_id, mode, download_id=None, min_score=0.45):
        if not os.path.isdir(folder):
            return "no folder"
        files = audio_files(folder)
        alb = self.api(f"/album/{album_id}")
        best = None
        for rel in [r for r in alb["releases"] if r["trackCount"] == len(files)]:
            tr = sorted(self.api(f"/track?albumReleaseId={rel['id']}"), key=lambda t: (t["mediumNumber"], t["absoluteTrackNumber"]))
            sc = sum(difflib.SequenceMatcher(None, norm(t["title"]), norm(strip(os.path.basename(f)))).ratio() for f, t in zip(files, tr)) / len(files)
            if not best or sc > best[0]:
                best = (sc, rel, tr)
        if not best:
            return f"{len(files)} files, no release with that count ({sorted({r['trackCount'] for r in alb['releases']})})"
        sc, rel, tr = best
        if sc < min_score:
            return f"low title match {sc:.2f}"
        if DRY:
            return f"DRY would import {len(files)} into {rel['format']} score {sc:.2f}"
        if not rel["monitored"]:
            # Switching the monitored edition unlinks files already imported on another edition.
            if (alb.get("statistics") or {}).get("trackFileCount"):
                return f"album already has {alb['statistics']['trackFileCount']} files on another release; not switching"
            for r in alb["releases"]:
                r["monitored"] = r["id"] == rel["id"]
            self.api(f"/album/{album_id}", "PUT", alb)
        q = {i["path"]: i for i in self.api("/manualimport?" + urllib.parse.urlencode({"folder": folder, "filterExistingFiles": "false"}))}
        payload = [dict({"path": f, "artistId": alb["artistId"], "albumId": album_id, "albumReleaseId": rel["id"], "trackIds": [t["id"]],
                         "quality": q[f]["quality"], "disableReleaseSwitching": True, "indexerFlags": 0},
                        **({"downloadId": download_id} if download_id else {})) for f, t in zip(files, tr)]
        cid = self.api("/command", "POST", {"name": "ManualImport", "files": payload, "importMode": mode, "replaceExistingFiles": False})["id"]
        self.wait(cid, 60)
        s = self.api(f"/album/{album_id}")["statistics"]
        return f"imported {s['trackFileCount']}/{s['trackCount']} (score {sc:.2f})" if s["trackFileCount"] else "import ran but 0 files"

    def summary(self):
        albums = self.api("/album")
        st = lambda a: a.get("statistics") or {}
        mon = [a for a in albums if a["monitored"]]
        complete = sum(1 for a in mon if st(a).get("trackCount") and st(a).get("trackFileCount", 0) >= st(a)["trackCount"])
        return f"library: complete {complete}/{len(mon)} | tracks {sum(st(a).get('trackFileCount', 0) for a in albums)}"
