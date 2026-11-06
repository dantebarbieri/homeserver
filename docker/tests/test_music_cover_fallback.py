import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

from PIL import Image

ROOT = Path(__file__).parents[1] / "dockerfiles" / "music-cover-fallback"
spec = importlib.util.spec_from_file_location("music_cover_fallback", ROOT / "music_cover_fallback.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

ALBUM = {
    "id": 407, "title": "Girl from the Sidewalk", "artist": {"artistName": "Noah Floersch"},
    "foreignAlbumId": "74348996-c258-4dcb-8e73-279de447ced7", "images": [],
    "statistics": {"trackFileCount": 1},
    "releases": [{"monitored": True, "trackCount": 1,
                  "foreignReleaseId": "14c3533f-78a3-4955-be51-b3b3e1b0c6d8"}],
}
EXPECTED = [{"title": "Girl from the Sidewalk", "duration": 404}]
SOURCE = {"source": "Apple Music", "url": "https://music.apple.com/us/album/1757448022",
          "image": "https://is1-ssl.mzstatic.com/image/1400x1400bb.jpg"}
RELATIVE = "Noah Floersch/Girl from the Sidewalk (2018)"
TRACK_PATH = "/data/media/music/" + RELATIVE + "/01 - Girl from the Sidewalk.flac"


def picture(size=(500, 500), flip=False):
    image = Image.new("RGB", size, "black")
    image.paste("white", (size[0] // 2, 0, size[0], size[1]) if flip else (0, 0, size[0] // 2, size[1]))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


class MatchingTests(unittest.TestCase):
    def test_lidarr_enumeration_is_bounded_to_downloaded_artists(self):
        lidarr = app.Lidarr.__new__(app.Lidarr)
        lidarr.get = Mock(side_effect=[
            [{"id": 50, "statistics": {"trackFileCount": 1}},
             {"id": 99, "statistics": {"trackFileCount": 0}}],
            [ALBUM, {**ALBUM, "statistics": {"trackFileCount": 0}}],
        ])
        self.assertEqual(list(lidarr.albums()), [ALBUM])
        self.assertEqual(lidarr.get.call_args_list[1].kwargs, {"artistId": 50})
        self.assertEqual(lidarr.get.call_count, 2)

    def test_normalization_preserves_non_latin_and_edition_words(self):
        self.assertEqual(app.norm("Ūla"), app.norm("Ula"))
        self.assertEqual(app.norm("Déjà Vu"), app.norm("De\u0301ja\u0300 Vu"))
        self.assertNotEqual(app.norm("風の谷"), "")
        self.assertNotEqual(app.norm("Album"), app.norm("Album (Deluxe)"))

    def test_order_count_duration_and_title_must_match(self):
        self.assertTrue(app.track_match(EXPECTED, EXPECTED))
        for actual in ([], EXPECTED * 2, [{"title": "Girl from the Sidewalk (Live)", "duration": 404}],
                       [{"title": EXPECTED[0]["title"], "duration": 410}],
                       [{"title": EXPECTED[0]["title"], "duration": 0}]):
            self.assertFalse(app.track_match(EXPECTED, actual))
        two = EXPECTED + [{"title": "Other", "duration": 100}]
        self.assertFalse(app.track_match(two, two[::-1]))
        for difference, accepted in ((5, True), (5.01, False)):
            self.assertEqual(app.track_match(EXPECTED, [{"title": EXPECTED[0]["title"],
                                                        "duration": 404 + difference}]), accepted)

    def test_apple_exact_match_and_only_store_suffix_is_removed(self):
        hit = {"artistName": "Noah Floersch", "collectionName": "Girl from the Sidewalk - Single",
               "trackCount": 1, "collectionId": 1757448022, "collectionViewUrl": SOURCE["url"],
               "artworkUrl100": SOURCE["image"].replace("1400x", "100x").replace("1400bb", "100bb")}
        track = {"wrapperType": "track", "discNumber": 1, "trackNumber": 1,
                 "trackName": EXPECTED[0]["title"], "trackTimeMillis": 404211}
        web = Mock()
        web.json.side_effect = [{"results": [hit]}, {"results": [hit, track]}]
        self.assertEqual(app.Sources(web).apple("Noah Floersch", ALBUM["title"], EXPECTED), [SOURCE])
        for field, value in (("artistName", "Someone Else"), ("collectionName", "Girl from the Sidewalk (Live)"),
                             ("collectionName", "Girl from the Sidewalk Extended"), ("trackCount", 2)):
            web.json.side_effect = None
            web.json.return_value = {"results": [{**hit, field: value}]}
            self.assertEqual(app.Sources(web).apple("Noah Floersch", ALBUM["title"], EXPECTED), [])

    def test_search_truncation_is_not_no_match(self):
        web = Mock()
        web.json.return_value = {"results": [{}] * 25}
        with self.assertRaises(app.Unresolved):
            app.Sources(web).apple("Artist", "Album", EXPECTED)
        web.json.return_value = {"total": 26, "data": []}
        with self.assertRaises(app.Unresolved):
            app.Sources(web).deezer("Artist", "Album", EXPECTED)

    def test_deezer_uses_full_album_and_refuses_partial_track_lists(self):
        hit = {"artist": {"name": "Noah Floersch"}, "title": ALBUM["title"], "nb_tracks": 1, "id": 615868942}
        album = {**hit, "link": "https://www.deezer.com/album/615868942",
                 "cover_xl": "https://cdn-images.dzcdn.net/cover.jpg",
                 "tracks": {"data": EXPECTED}}
        web = Mock()
        web.json.side_effect = [{"total": 1, "data": [hit]}, album]
        self.assertEqual(len(app.Sources(web).deezer("Noah Floersch", ALBUM["title"], EXPECTED)), 1)
        for bad in ({**album, "tracks": {"data": EXPECTED, "next": "more"}},
                    {**album, "artist": {"name": "Different artist"}},
                    {**album, "tracks": {"data": [{"title": "Different song", "duration": 404}]}}):
            web.json.side_effect = [{"total": 1, "data": [hit]}, bad]
            self.assertEqual(app.Sources(web).deezer("Noah Floersch", ALBUM["title"], EXPECTED), [])

    def test_caa_preferred_and_only_confirmed_missing_art_uses_stores(self):
        web = Mock()
        web.read.return_value = picture()
        sources = app.Sources(web)
        sources.apple = Mock(return_value=[SOURCE])
        sources.deezer = Mock(return_value=[])
        web.json.return_value = {"images": [{"front": True, "approved": True,
                                             "image": "http://archive.org/cover.jpg"}]}
        data, matches = sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)
        self.assertEqual(matches[0]["source"], "Cover Art Archive")
        self.assertTrue(data.startswith(b"\xff\xd8"))
        sources.apple.assert_not_called()
        web.json.side_effect = RuntimeError("HTTP 503")
        with self.assertRaisesRegex(RuntimeError, "503"):
            sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)
        sources.apple.assert_not_called()
        web.json.side_effect = None
        web.json.return_value = None
        self.assertEqual(sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)[1], [SOURCE])

    def test_caa_ignores_back_and_unapproved_images(self):
        web = Mock()
        web.json.return_value = {"images": [{"front": False, "approved": True},
                                           {"front": True, "approved": False}]}
        self.assertIsNone(app.Sources(web).caa(ALBUM, ALBUM["releases"][0]))
        for invalid in ({}, [], {"images": None}):
            web.json.return_value = invalid
            with self.assertRaises(ValueError):
                app.Sources(web).caa(ALBUM, ALBUM["releases"][0])

    def test_store_conflicts_are_not_guessed(self):
        web = Mock()
        web.json.return_value = None
        web.read.side_effect = [picture(), picture(flip=True)]
        sources = app.Sources(web)
        sources.apple = Mock(return_value=[SOURCE])
        sources.deezer = Mock(return_value=[{**SOURCE, "source": "Deezer"}])
        with self.assertRaisesRegex(app.Unresolved, "disagree"):
            sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)

    def test_one_unavailable_store_can_use_the_other_exact_match(self):
        web = Mock()
        web.json.return_value = None
        web.read.return_value = picture()
        sources = app.Sources(web)
        sources.apple = Mock(side_effect=RuntimeError("HTTP 503"))
        sources.deezer = Mock(return_value=[{**SOURCE, "source": "Deezer"}])
        self.assertEqual(sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)[1][0]["source"], "Deezer")
        sources.deezer.return_value = []
        with self.assertRaises(RuntimeError):
            sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)

    def test_ambiguous_search_does_not_fall_through(self):
        sources = app.Sources(Mock())
        sources.caa = Mock(return_value=None)
        sources.apple = Mock(side_effect=app.Unresolved("truncated"))
        sources.deezer = Mock(return_value=[SOURCE])
        with self.assertRaises(app.Unresolved):
            sources.choose(ALBUM, ALBUM["releases"][0], EXPECTED)
        sources.deezer.assert_not_called()


class ImageAndHTTPTests(unittest.TestCase):
    def test_image_validation_and_resize(self):
        data, fingerprint = app.image_data(picture((2000, 2000)))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (1600, 1600))
        self.assertEqual(len(fingerprint), 256)
        for data in (b"<html>not an image</html>", picture((100, 100)), picture((500, 2000))):
            with self.assertRaises((ValueError, OSError)):
                app.image_data(data)
        with patch.object(app, "MAX_BYTES", 10), self.assertRaises(ValueError):
            app.image_data(picture())

    def test_public_urls_reject_credentials_private_hosts_and_lookalikes(self):
        for url in ("http://archive.org/a", "https://archive.org.evil.test/a", "https://localhost/a",
                    "https://127.0.0.1/a", "file:///etc/passwd", "https://x:secret@archive.org/a",
                    "https://archive.org:444/a"):
            with self.assertRaises(ValueError, msg=url):
                app.public_url(url)
        self.assertEqual(app.public_url("https://ia800.us.archive.org/a"), "https://ia800.us.archive.org/a")
        with self.assertRaises(ValueError):
            app.PublicRedirect().redirect_request(None, None, 302, "", {}, "https://127.0.0.1/a")
        with self.assertRaises(RuntimeError):
            app.NoRedirect().redirect_request(None, None, 302, "", {}, "https://archive.org/a")

    def test_only_404_is_missing_and_transient_errors_are_retried(self):
        web = app.Web()
        web.public = Mock()
        with patch.object(app.time, "sleep"):
            web.public.open.side_effect = urllib.error.HTTPError("url", 404, "", {}, None)
            self.assertIsNone(web.read("https://coverartarchive.org/x", missing_ok=True))
            web.public.open.reset_mock()
            web.public.open.side_effect = urllib.error.HTTPError("url", 503, "", {}, None)
            with self.assertRaisesRegex(RuntimeError, "503"):
                web.read("https://coverartarchive.org/x", missing_ok=True)
            self.assertEqual(web.public.open.call_count, 3)

    def test_deezer_error_body_is_not_an_empty_search(self):
        web = app.Web()
        with patch.object(web, "read", return_value=b'{"error":{"code":4,"message":"quota"}}'):
            with self.assertRaises(RuntimeError):
                web.json("https://api.deezer.com/search/album")


class FileAndRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.music, self.state = root / "music", root / "state"
        self.folder = self.music / RELATIVE
        self.folder.mkdir(parents=True)
        self.audio = self.folder / "01 - Girl from the Sidewalk.flac"
        self.audio.write_bytes(b"untouched audio")
        self.state.mkdir()
        p = patch.multiple(app, MUSIC=self.music, STATE=self.state, DRY=False)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(app.mutagen, "File", return_value=SimpleNamespace(tags={}, pictures=[]))
        self.tags = p.start()
        self.addCleanup(p.stop)
        p = patch.object(app, "notify")
        self.notify = p.start()
        self.addCleanup(p.stop)
        self.album = copy.deepcopy(ALBUM)
        self.files = [{"path": TRACK_PATH}]
        self.tracks = [{"title": EXPECTED[0]["title"], "duration": 404000,
                        "mediumNumber": 1, "absoluteTrackNumber": 1}]
        self.lidarr = Mock()
        self.lidarr.albums.return_value = [self.album]
        self.lidarr.get.side_effect = lambda path, **params: {
            "/album": [self.album], "/trackfile": self.files, "/track": self.tracks,
        }[path]
        self.sources = Mock()
        self.jpeg = app.image_data(picture())[0]
        self.sources.choose.return_value = (self.jpeg, [SOURCE])
        self.refresh = Mock()

    def run_job(self):
        return app.run(self.lidarr, self.sources, self.refresh)

    def test_apply_and_repeated_runs_do_not_overwrite_or_repeat_lookup(self):
        self.assertEqual(self.run_job()[0]["result"], "written")
        self.assertEqual((self.folder / "cover.jpg").read_bytes(), self.jpeg)
        self.assertEqual(self.audio.read_bytes(), b"untouched audio")
        self.refresh.assert_called_once()
        provenance = app.load_state()["covers"][RELATIVE]
        self.assertEqual(provenance["sha256"], hashlib.sha256(self.jpeg).hexdigest())
        self.assertEqual(provenance["status"], "complete")
        self.run_job()
        self.sources.choose.assert_called_once()
        self.refresh.assert_called_once()

    def test_dry_run_writes_nothing_or_refreshes(self):
        with patch.object(app, "DRY", True):
            self.assertEqual(self.run_job()[0]["result"], "would-write")
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertEqual(list(self.folder.iterdir()), [self.audio])
        self.refresh.assert_not_called()
        self.notify.assert_not_called()

    def test_any_existing_sidecar_or_embedded_art_is_preserved(self):
        cover = self.folder / "Chosen Cover.PNG"
        cover.write_bytes(b"user art")
        self.run_job()
        self.assertEqual(cover.read_bytes(), b"user art")
        self.sources.choose.assert_not_called()
        cover.unlink()
        for tags, pictures in (({"APIC:front": 1}, []), ({"covr": 1}, []),
                               ({"metadata_block_picture": 1}, []), ({}, [1])):
            self.tags.return_value = SimpleNamespace(tags=tags, pictures=pictures)
            self.run_job()
            self.sources.choose.assert_not_called()

    def test_lidarr_art_uses_normal_tagging_not_store_fallback(self):
        self.album["images"] = [{"coverType": "cover"}]
        self.run_job()
        self.sources.choose.assert_not_called()
        self.lidarr.get.assert_not_called()

    def test_wrong_root_traversal_flat_and_split_folders_are_refused(self):
        for files in ([{"path": "/elsewhere/a.flac"}],
                      [{"path": "/data/media/music/../../secret"}], [],
                      [{"path": "/data/media/music/a.flac"}]):
            with self.assertRaises((ValueError, OSError, app.Unresolved)):
                app.album_files(files)
        flat = self.music / "flat.flac"
        flat.write_bytes(b"x")
        with self.assertRaises(app.Unresolved):
            app.album_files([{"path": "/data/media/music/flat.flac"}])
        with self.assertRaises(app.Unresolved):
            app.album_files(self.files + [{"path": "/data/media/music/flat.flac"}])

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows admin rights")
    def test_symlinks_even_inside_the_library_are_refused(self):
        link = self.folder / "linked.flac"
        link.symlink_to(self.audio)
        with self.assertRaises(ValueError):
            app.album_files([{"path": str(app.LIDARR_ROOT) + "/" + RELATIVE + "/linked.flac"}])

    def test_existing_destination_wins_an_atomic_publish_race(self):
        target = self.folder / "cover.jpg"
        target.write_bytes(b"another writer")
        with self.assertRaises(FileExistsError):
            app.publish_cover(self.folder, self.jpeg)
        self.assertEqual(target.read_bytes(), b"another writer")
        self.assertFalse(list(self.folder.glob(".cover-fallback-*")))

    def test_artwork_appearing_during_lookup_is_not_overridden(self):
        def choose(*args):
            (self.folder / "folder.jpg").write_bytes(b"new")
            return self.jpeg, [SOURCE]
        self.sources.choose.side_effect = choose
        self.run_job()
        self.assertFalse((self.folder / "cover.jpg").exists())
        self.refresh.assert_not_called()

    def test_failed_plex_refresh_is_retried_without_rewriting(self):
        self.refresh.side_effect = RuntimeError("Plex unavailable")
        with self.assertRaises(RuntimeError):
            self.run_job()
        target = self.folder / "cover.jpg"
        stamp = target.stat().st_mtime_ns
        self.assertEqual(app.load_state()["covers"][RELATIVE]["status"], "pending")
        self.refresh.side_effect = None
        self.run_job()
        self.sources.choose.assert_called_once()
        self.assertEqual(target.stat().st_mtime_ns, stamp)
        self.assertEqual(app.load_state()["covers"][RELATIVE]["status"], "complete")

    def test_readonly_or_corrupt_state_stops_before_library_access(self):
        with patch.object(app, "save_state", side_effect=PermissionError("read-only")):
            with self.assertRaises(PermissionError):
                self.run_job()
        self.lidarr.get.assert_not_called()
        (self.state / "state.json").write_text("not json")
        with self.assertRaises(ValueError):
            self.run_job()
        self.lidarr.get.assert_not_called()

    def test_unresolved_is_reported_but_alert_is_deduplicated(self):
        self.sources.choose.side_effect = app.Unresolved("no exact release")
        self.assertEqual(self.run_job()[0]["result"], "unresolved")
        self.run_job()
        self.notify.assert_called_once()
        self.assertFalse((self.folder / "cover.jpg").exists())

    def test_incomplete_release_metadata_is_not_searched(self):
        self.album["releases"][0]["trackCount"] = 2
        self.assertEqual(self.run_job()[0]["result"], "unresolved")
        self.sources.choose.assert_not_called()

    def test_health_is_disabled_or_requires_real_success(self):
        with patch.object(app, "ENABLED", False):
            self.assertEqual(app.healthcheck(), 0)
        with patch.object(app, "ENABLED", True):
            self.assertEqual(app.healthcheck(), 1)
            app.save_state("last_ok.json", {"at": 100})
            with patch.object(app.time, "time", return_value=100):
                self.assertEqual(app.healthcheck(), 0)
            with patch.object(app.time, "time", return_value=100 + 2 * app.INTERVAL + 900):
                self.assertEqual(app.healthcheck(), 1)


class PlexTests(unittest.TestCase):
    def test_refresh_only_missing_art_in_matching_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Path(tmp) / "Preferences.xml"
            prefs.write_text('<Preferences PlexOnlineToken="test"/>')
            root = Path(tmp) / "music"
            web = Mock()
            items = [{"ratingKey": "1", "parentTitle": "Noah Floersch", "thumb": "/library/metadata/1/thumb/1"},
                     {"ratingKey": "2", "parentTitle": "Noah Floersch"},
                     {"ratingKey": "3", "parentTitle": "Noah Floersch"},
                     {"ratingKey": "4", "parentTitle": "Different Artist"}]
            def answer(url, **kw):
                if url.endswith("/prefs"):
                    return {"MediaContainer": {"Setting": [{"id": "albumPosters", "value": "1"}]}}
                if "/all?" in url:
                    return {"MediaContainer": {"Metadata": items}}
                if url.endswith("/metadata/2"):
                    return {"MediaContainer": {"Metadata": [{"Field": [{"name": "thumb", "locked": True}]}]}}
                if url.endswith("/metadata/3"):
                    return {"MediaContainer": {"Metadata": [{}]}}
                if url.endswith("/3/children"):
                    return {"MediaContainer": {"Metadata": [{"Media": [{"Part": [{"file": TRACK_PATH}]}]}]}}
                return None
            web.json.side_effect = answer
            with patch.object(app, "MUSIC", root), patch.dict(os.environ, {"PLEX_PREFS": str(prefs)}):
                app.refresh_plex(web, root / RELATIVE, ALBUM)
            mutations = [c.args[0] for c in web.read.call_args_list if c.kwargs.get("method") == "PUT"]
            self.assertEqual(mutations, ["http://plex:32400/library/metadata/3/refresh"])
            self.assertEqual(web.read.call_count, 2)
            self.assertFalse(any("posters" in c.args[0] or "thumb.locked" in c.args[0]
                                 for c in web.json.call_args_list))


if __name__ == "__main__":
    unittest.main()
