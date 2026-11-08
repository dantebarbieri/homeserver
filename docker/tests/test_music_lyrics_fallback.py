import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

import yaml

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "music_lyrics_fallback", ROOT / "dockerfiles" / "music-lyrics-fallback" / "music_lyrics_fallback.py"
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

TRACK = {"artist": "Test Artist", "album": "Test Album", "title": "Test Track", "duration": 120.0}
DOC = {"version": "1.0", "metadata": {"artist": "Test Artist", "title": "Test Track"},
       "lines": [{"text": "Test words", "start_ms": 1000, "end_ms": 3000,
                  "words": [{"text": "Test ", "start_ms": 1000, "end_ms": 2000},
                            {"text": "words", "start_ms": 2000, "end_ms": 3000}]}]}
SOURCE = {"id": 123, "artistName": "Test Artist", "albumName": "Test Album", "trackName": "Test Track",
          "duration": 120, "instrumental": False, "hasWordSync": True,
          "syncedLyrics": "[00:01.00]Test words\n[00:03.00]\n", "plainLyrics": "Test words",
          "lyricsfile": yaml.safe_dump(DOC)}


class PayloadTests(unittest.TestCase):
    def test_exact_unicode_identity_and_duration(self):
        self.assertTrue(app.matched(TRACK, SOURCE))
        self.assertEqual(app.norm("Don't"), app.norm("DON’T"))
        self.assertNotEqual(app.norm("風の谷"), "")
        self.assertNotEqual(app.norm("風の谷"), app.norm("風立ちぬ"))
        for field in ("artistName", "albumName", "trackName"):
            self.assertFalse(app.matched(TRACK, {**SOURCE, field: SOURCE[field] + " (Live)"}))
        for duration, expected in ((118, True), (122, True), (122.001, False), (float("nan"), False)):
            self.assertEqual(app.matched(TRACK, {**SOURCE, "duration": duration}), expected)

    def test_word_cues_preserved_alongside_plex_lrc(self):
        files, quality = app.payloads(TRACK, SOURCE)
        self.assertEqual(quality, "word")
        self.assertEqual(set(files), {".lrc", ".yaml"})
        self.assertEqual(yaml.safe_load(files[".yaml"]), DOC)

    def test_plain_does_not_override_timed_plex_lyrics(self):
        source = {**SOURCE, "syncedLyrics": None, "hasWordSync": False,
                  "lyricsfile": yaml.safe_dump({"version": "1.0", "metadata": DOC["metadata"],
                                               "plain": "Synthetic plain text"})}
        self.assertEqual(set(app.payloads(TRACK, source, False)[0]), {".txt", ".yaml"})
        self.assertEqual(set(app.payloads(TRACK, source, True)[0]), {".yaml"})
        source["lyricsfile"] = None
        self.assertEqual(set(app.payloads(TRACK, source, True)[0]), {".yaml"})

    def test_instrumental_and_metadata_mismatch(self):
        self.assertEqual(app.payloads(TRACK, {**SOURCE, "instrumental": True}), ({}, "instrumental"))
        with self.assertRaises(app.Unmatched):
            app.payloads(TRACK, {**SOURCE, "trackName": "Test Track (remix)"})

    def test_invalid_lrc_rejected(self):
        for text in ("not timestamped", "[00:99.00]Synthetic", "[02:04.00]Synthetic", "bad\0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                app.payloads(TRACK, {**SOURCE, "syncedLyrics": text})

    def test_invalid_yaml_rejected(self):
        cases = [
            "version: 2.0", "!!python/object:danger {}", "x: &x [*x]",
            yaml.safe_dump({**DOC, "metadata": {"artist": "Wrong", "title": "Test Track"}}),
            yaml.safe_dump({**DOC, "lines": [{"text": "X", "start_ms": 200000}]}),
            yaml.safe_dump({**DOC, "lines": [{"text": "X", "start_ms": 2000, "end_ms": 1000}]}),
            yaml.safe_dump({**DOC, "lines": [{"text": "X", "start_ms": 1000}]}),
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises((ValueError, yaml.YAMLError)):
                app.payloads(TRACK, {**SOURCE, "lyricsfile": text})

    def test_retry_after(self):
        self.assertEqual(app.retry_delay("60", 0), 61)
        self.assertEqual(app.retry_delay(None, 1), 4)
        with self.assertRaises(ValueError):
            app.retry_delay("nan", 0)


class FileTests(unittest.TestCase):
    def test_atomic_publication_never_replaces_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "track.lrc"
            app.publish(target, b"synthetic")
            with self.assertRaises(FileExistsError):
                app.publish(target, b"replacement")
            self.assertEqual(target.read_bytes(), b"synthetic")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_path_escape_and_ambiguous_sidecar_case(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "MUSIC", Path(tmp)):
            track = Path(tmp) / "track.flac"
            track.write_bytes(b"synthetic")
            lyric = Path(tmp) / "TRACK.LRC"
            lyric.write_text("synthetic")
            self.assertEqual(app.existing(track), [lyric])
            self.assertEqual(app.path_for("/data/media/music/track.flac"), track)
            for name in ("/data/media/music/../outside", "/elsewhere/track.flac",
                         "/data/media/music/a\\b.flac"):
                with self.assertRaises(ValueError):
                    app.path_for(name)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.music, self.state = root / "music", root / "state"
        self.music.mkdir()
        self.state.mkdir()
        self.path = self.music / "track.flac"
        self.path.write_bytes(b"audio bytes must not change")
        self.item = {"ratingKey": "100", "parentRatingKey": "99", "grandparentTitle": TRACK["artist"],
                     "parentTitle": TRACK["album"], "title": TRACK["title"],
                     "Media": [{"Part": [{"file": "/data/media/music/track.flac"}]}]}
        self.plex, self.web = Mock(), Mock()
        self.plex.tracks.return_value = [self.item]
        self.web.lyrics.return_value = copy.deepcopy(SOURCE)
        self.args = SimpleNamespace(dry_run=False, limit=0, keys=set())
        for name, value in (("MUSIC", self.music), ("STATE", self.state)):
            p = patch.object(app, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(app.mutagen, "File",
                         return_value=SimpleNamespace(tags={}, info=SimpleNamespace(length=120)))
        self.audio = p.start()
        self.addCleanup(p.stop)

    def run_app(self):
        return app.run(self.plex, self.web, self.args)

    def test_apply_and_rerun_are_idempotent(self):
        self.assertEqual(self.run_app()["counts"]["word"], 1)
        self.assertEqual(self.path.read_bytes(), b"audio bytes must not change")
        self.plex.refresh.assert_called_once_with("99")
        self.assertEqual(self.run_app()["counts"]["existing"], 1)
        self.assertEqual(self.web.lyrics.call_count, 1)
        record = app.load_state()["tracks"]["track.flac"]
        for ext, digest in record["files"].items():
            self.assertEqual(app.digest(self.path.with_suffix(ext).read_bytes()), digest)

    def test_dry_run_does_not_write_or_refresh(self):
        self.args.dry_run = True
        self.assertEqual(self.run_app()["counts"]["word"], 1)
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertEqual(list(self.music.iterdir()), [self.path])
        self.plex.refresh.assert_not_called()

    def test_existing_and_embedded_are_untouched(self):
        self.path.with_suffix(".lrc").write_text("manual")
        self.assertEqual(self.run_app()["counts"]["existing"], 1)
        self.web.lyrics.assert_not_called()
        self.path.with_suffix(".lrc").unlink()
        self.audio.return_value.tags = {"USLT::eng": "embedded"}
        self.assertEqual(self.run_app()["counts"]["embedded"], 1)
        self.web.lyrics.assert_not_called()

    def test_misses_are_cached_but_errors_are_not(self):
        self.web.lyrics.return_value = None
        self.assertEqual(self.run_app()["counts"]["missing"], 1)
        self.assertEqual(self.run_app()["counts"]["cached"], 1)
        state = app.load_state()
        state["tracks"]["track.flac"]["retry_at"] = 0
        app.save("state.json", state)
        self.web.lyrics.side_effect = RuntimeError("HTTP 503")
        with self.assertRaisesRegex(RuntimeError, "503"):
            self.run_app()
        self.assertEqual(app.load_state()["tracks"]["track.flac"]["retry_at"], 0)

    def test_failed_plex_refresh_is_retried_without_rewriting(self):
        self.plex.refresh.side_effect = RuntimeError("Plex unavailable")
        with self.assertRaises(RuntimeError):
            self.run_app()
        self.assertEqual(app.load_state()["refresh"], ["99"])
        before = self.path.with_suffix(".lrc").stat().st_mtime_ns
        self.plex.refresh.side_effect = None
        self.run_app()
        self.assertEqual(app.load_state()["refresh"], [])
        self.assertEqual(before, self.path.with_suffix(".lrc").stat().st_mtime_ns)
        self.assertEqual(self.web.lyrics.call_count, 1)

    def test_interrupted_publication_resumes_missing_sibling_only(self):
        original = app.publish

        def partial(path, data):
            if path.suffix == ".yaml":
                raise OSError("interrupted")
            original(path, data)

        with patch.object(app, "publish", side_effect=partial), self.assertRaises(OSError):
            self.run_app()
        self.assertEqual(app.load_state()["tracks"]["track.flac"]["status"], "publishing")
        before = self.path.with_suffix(".lrc").stat().st_mtime_ns
        self.run_app()
        self.assertEqual(before, self.path.with_suffix(".lrc").stat().st_mtime_ns)
        self.assertTrue(self.path.with_suffix(".yaml").exists())

    def test_audio_change_or_new_sidecar_during_lookup_blocks_writes(self):
        def race(track):
            self.path.with_suffix(".txt").write_text("user supplied")
            return copy.deepcopy(SOURCE)
        self.web.lyrics.side_effect = race
        with self.assertRaisesRegex(ValueError, "appeared"):
            self.run_app()
        self.assertFalse(self.path.with_suffix(".lrc").exists())
        self.path.with_suffix(".txt").unlink()
        def change(track):
            self.path.write_bytes(b"new audio")
            return copy.deepcopy(SOURCE)
        self.web.lyrics.side_effect = change
        with self.assertRaisesRegex(ValueError, "audio changed"):
            self.run_app()

    def test_duplicate_basename_not_assigned_lyrics(self):
        self.plex.tracks.return_value = [self.item, copy.deepcopy(self.item)]
        self.assertEqual(self.run_app()["counts"]["unmatched"], 2)
        self.web.lyrics.assert_not_called()

    def test_filter_and_limit(self):
        self.args.keys = {"101"}
        self.assertEqual(self.run_app()["lookups"], 0)
        self.web.lyrics.assert_not_called()

    def test_album_refreshes_are_deduplicated(self):
        second = copy.deepcopy(self.item)
        second["ratingKey"] = "101"
        second["Media"][0]["Part"][0]["file"] = "/data/media/music/second.flac"
        (self.music / "second.flac").write_bytes(b"second synthetic audio")
        self.plex.tracks.return_value = [self.item, second]
        self.assertEqual(self.run_app()["counts"]["word"], 2)
        self.plex.refresh.assert_called_once_with("99")

    def test_bad_source_is_reported_without_blocking_other_tracks(self):
        self.web.lyrics.return_value["lyricsfile"] = "version: invalid"
        report = self.run_app()
        self.assertEqual(report["counts"]["unmatched"], 1)
        self.assertIn("invalid source", report["tracks"][0]["reason"])
        self.assertFalse(self.path.with_suffix(".lrc").exists())


class HttpTests(unittest.TestCase):
    def test_404_is_only_public_missing_case(self):
        web = app.Web()
        web.opener = Mock()
        web.opener.open.side_effect = urllib.error.HTTPError("https://lrclib.net/api/get", 404, "", {}, None)
        with patch.object(app.time, "sleep"):
            self.assertIsNone(web.lyrics(TRACK))
            with self.assertRaisesRegex(RuntimeError, "404"):
                web.request("http://plex:32400/library", headers={"X-Plex-Token": "synthetic"})

    def test_rate_limit_honors_retry_after(self):
        web = app.Web()
        web.opener = Mock()
        web.opener.open.side_effect = [
            urllib.error.HTTPError("https://lrclib.net/api/get", 429, "", {"Retry-After": "120"}, None),
            io.BytesIO(b'{"id": 123}'),
        ]
        with patch.object(app.time, "sleep") as sleep:
            self.assertEqual(web.lyrics(TRACK), {"id": 123})
        self.assertIn(unittest.mock.call(121), sleep.call_args_list)

    def test_compose_keeps_navidrome_read_only_and_helper_internal(self):
        config = yaml.safe_load((ROOT / "compose.media.yml").read_text())
        nav = config["services"]["navidrome"]
        self.assertIn("${RAID}/shared/media/music:/music:ro", nav["volumes"])
        helper = config["services"]["music-lyrics-fallback"]
        self.assertEqual(helper["networks"], ["music-maintenance"])
        self.assertIn("${MUSIC_LYRICS_FALLBACK_ENABLED:-0}", str(helper["environment"]))


if __name__ == "__main__":
    unittest.main()
