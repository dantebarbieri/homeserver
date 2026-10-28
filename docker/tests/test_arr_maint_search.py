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


def movie(id, **changes):
    return {"id": id, "monitored": True, "hasFile": False, "isAvailable": True, **changes}


class MissingSearchTests(unittest.TestCase):
    def app(self, movies, queue=()):
        app = radarr.App()
        app.api = Mock(side_effect=lambda path, *args: (
            {"records": list(queue)} if path.startswith("/queue") else
            movies if path == "/movie" else [] if not args else {"id": 123}
        ))
        return app

    def test_only_available_monitored_missing_unqueued_movies_are_searched(self):
        app = self.app([
            movie(461, isAvailable=False),
            movie(481),
            movie(3, monitored=False),
            movie(4, hasFile=True),
            movie(5),
        ], [{"movieId": 5}, {"movieId": None}])
        self.assertEqual(app.search_missing(), "MoviesSearch (1 available missing movies)")
        app.api.assert_any_call("/command", "POST", {"name": "MoviesSearch", "movieIds": [481]})
        self.assertEqual(sum(call.args[0] == "/command" for call in app.api.call_args_list), 1)

    def test_no_eligible_movies_never_falls_back_to_unrestricted_search(self):
        for movies in [[], [movie(461, isAvailable=False)], [movie(1, hasFile=True)]]:
            with self.subTest(movies=movies):
                app = self.app(movies)
                self.assertIsNone(app.search_missing())
                self.assertFalse(any(call.args[0] == "/command" for call in app.api.call_args_list))

    def test_missing_availability_fails_explicitly_without_searching(self):
        entry = movie(461)
        del entry["isAvailable"]
        app = self.app([entry])
        with self.assertRaises(KeyError):
            app.search_missing()
        self.assertFalse(any(call.args[0] == "/command" for call in app.api.call_args_list))

    def test_other_apps_keep_their_existing_missing_commands(self):
        app = engine.Arr()
        app.missing_command = {"name": "MissingAlbumSearch"}
        app.api = Mock()
        self.assertEqual(app.search_missing(), "MissingAlbumSearch")
        app.api.assert_called_once_with("/command", "POST", app.missing_command)

    def test_run_uses_guarded_search_and_records_empty_check(self):
        app = self.app([movie(461, isAvailable=False)])
        with patch.object(engine, "DRY", False), patch.object(engine, "QBIT_USER", ""), \
                patch.object(engine, "load_state", side_effect=lambda name, default: default), \
                patch.object(engine, "save_state") as save, patch.object(engine, "log"):
            app.run()
        self.assertFalse(any(call.args[0] == "/command" and len(call.args) > 1
                             for call in app.api.call_args_list))
        self.assertTrue(any(call.args[0] == "last_missing.json" for call in save.call_args_list))

    def test_dry_run_never_searches(self):
        app = self.app([movie(481)])
        with patch.object(engine, "DRY", True), patch.object(engine, "QBIT_USER", ""), \
                patch.object(engine, "load_state", side_effect=lambda name, default: default), \
                patch.object(engine, "save_state"), patch.object(engine, "log"):
            app.run()
        self.assertFalse(any(call.args[0] == "/command" and len(call.args) > 1
                             for call in app.api.call_args_list))


if __name__ == "__main__":
    unittest.main()
