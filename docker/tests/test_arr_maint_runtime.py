import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1] / "dockerfiles" / "arr-maint"
spec = importlib.util.spec_from_file_location("arr_maint", ROOT / "arr_maint.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
with patch.dict(sys.modules, {"arr_maint": engine}):
    spec = importlib.util.spec_from_file_location("radarr_rules", ROOT / "radarr.py")
    radarr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(radarr)

HASH = "E43AE60250A49EF49474395D43962EBDA00809F3"
PATH = "/data/media/movies/The Odyssey (2026) {tmdb-1368337}/The Odyssey.mkv"


def movie(run_time="1:26:03", runtime=173, available=False):
    return {"id": 461, "title": "The Odyssey", "year": 2026, "runtime": runtime, "isAvailable": available,
            "movieFile": {"id": 802, "path": PATH, "relativePath": "The Odyssey.mkv",
                          "dateAdded": "2026-10-30T23:46:00Z", "mediaInfo": {"runTime": run_time}}}


def history(imported_path=PATH, imported_at="2026-10-30T23:46:00Z", grabbed=True):
    events = [{"id": 1921, "eventType": "downloadFolderImported", "date": imported_at, "downloadId": HASH,
               "data": {"importedPath": imported_path}}]
    if grabbed:
        events.append({"id": 1920, "eventType": "grabbed", "date": "2026-10-30T23:43:44Z", "downloadId": HASH,
                       "data": {}})
    return events


class RuntimeGuardTests(unittest.TestCase):
    def app(self, movies, events=()):
        app = radarr.App()
        app.qbit = Mock()
        app.api = Mock(side_effect=lambda path, *args: (
            movies if path == "/movie" else list(events) if path.startswith("/history/movie") else
            {"records": []} if path.startswith("/queue") else [] if not args else None
        ))
        return app

    def mutations(self, app):
        return [c.args for c in app.api.call_args_list if len(c.args) > 1]

    def test_minutes_parses_radarr_run_times(self):
        self.assertAlmostEqual(radarr.minutes("1:26:03"), 86.05)
        self.assertAlmostEqual(radarr.minutes("26:30"), 26.5)
        for blank in (None, "", "n/a"):
            self.assertIsNone(radarr.minutes(blank))

    def test_short_unreleased_movie_is_rejected_without_searching(self):
        app = self.app([movie()], history())
        with patch.object(radarr, "DRY", False):
            actions, ask = app.check_library()
        self.assertEqual(self.mutations(app), [("/history/failed/1920", "POST", {}), ("/moviefile/802", "DELETE")])
        app.qbit.delete.assert_called_once_with(HASH)
        self.assertEqual(ask, {})
        self.assertIn("search waits for release", actions[0])

    def test_short_available_movie_is_rejected_and_searched(self):
        app = self.app([movie(available=True)], history())
        with patch.object(radarr, "DRY", False):
            actions, _ = app.check_library()
        self.assertEqual(self.mutations(app)[-1], ("/command", "POST", {"name": "MoviesSearch", "movieIds": [461]}))
        self.assertIn("re-searching", actions[0])

    def test_renamed_file_matches_import_by_date(self):
        app = self.app([movie()], history(imported_path="/old/name.mkv", imported_at="2026-10-30T23:45:58Z"))
        with patch.object(radarr, "DRY", False):
            app.check_library()
        self.assertIn(("/history/failed/1920", "POST", {}), self.mutations(app))

    def test_without_a_grab_it_alerts_instead_of_deleting(self):
        for events in ([], history(grabbed=False), history(imported_path="/x.mkv", imported_at="2026-01-01T00:00:00Z")):
            with self.subTest(events=events):
                app = self.app([movie()], events)
                with patch.object(radarr, "DRY", False):
                    actions, ask = app.check_library()
                self.assertEqual((actions, self.mutations(app)), ([], []))
                app.qbit.delete.assert_not_called()
                self.assertIn("short:802", ask)

    def test_normal_or_unknown_runtimes_are_left_alone(self):
        cases = [movie(run_time="2:52:40"), movie(run_time="2:01:30"), movie(run_time=""),
                 movie(run_time="0:00:00"), movie(runtime=0), {"id": 1, "runtime": 120, "movieFile": None}]
        app = self.app(cases, history())
        with patch.object(radarr, "DRY", False):
            self.assertEqual(app.check_library(), ([], {}))
        self.assertEqual(self.mutations(app), [])

    def test_dry_run_only_reports(self):
        app = self.app([movie()], history())
        with patch.object(radarr, "DRY", True):
            actions, _ = app.check_library()
        self.assertEqual(self.mutations(app), [])
        app.qbit.delete.assert_not_called()
        self.assertTrue(actions[0].startswith("DRY would reject"))

    def test_qbit_delete_only_sends_torrent_hashes(self):
        q = engine.Qbit.__new__(engine.Qbit)
        q.post = Mock()
        q.delete("SABnzbd_nzo_abc123")
        q.delete(None)
        q.post.assert_not_called()
        q.delete(HASH)
        q.post.assert_called_once_with("torrents/delete", {"hashes": HASH.lower(), "deleteFiles": "true"})

    def test_other_apps_have_no_library_rules(self):
        self.assertEqual(engine.Arr().check_library(), ([], {}))

    def test_run_reports_library_actions(self):
        app = self.app([movie()], history())
        app.qbit = None
        app.missing_hours = 0
        with patch.object(engine, "DRY", False), patch.object(radarr, "DRY", False), \
                patch.object(engine, "QBIT_USER", ""), \
                patch.object(engine, "load_state", side_effect=lambda name, default: default), \
                patch.object(engine, "save_state"), patch.object(engine, "log") as log:
            app.run()
        self.assertTrue(any("blocklisted, deleted" in str(c.args) for c in log.call_args_list))


if __name__ == "__main__":
    unittest.main()
