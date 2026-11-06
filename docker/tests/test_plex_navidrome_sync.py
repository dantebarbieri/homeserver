import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1] / "dockerfiles" / "plex-navidrome-sync"
spec = importlib.util.spec_from_file_location("plex_navidrome_sync", ROOT / "plex_navidrome_sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def P(rating=0, views=0, key="1", rated_at=0):
    return {"key": key, "rating": rating, "rated_at": rated_at, "views": views, "played_at": 0}


def N(rating=0, starred=False, plays=0, sid="a", rated_at=0):
    return {"id": sid, "rating": rating, "starred": starred, "rated_at": rated_at, "plays": plays}


class HelperTests(unittest.TestCase):
    def test_ts(self):
        self.assertEqual(sync.ts(None), 0)
        self.assertEqual(sync.ts(1700000000), 1700000000)
        self.assertEqual(sync.ts("0001-01-01T00:00:00Z"), 0)
        self.assertEqual(sync.ts("2024-01-01T00:00:00Z"), 1704067200)
        self.assertEqual(sync.ts("2024-01-01T00:00:00.123456789Z"), 1704067200)
        self.assertEqual(sync.ts("2024-01-01T01:00:00+01:00"), 1704067200)

    def test_to_nd(self):
        self.assertEqual([sync.to_nd(r) for r in (-1, 0, 1, 2, 3, 6, 7, 10)], [0, 0, 1, 1, 2, 3, 4, 5])

    def test_overlay_keeps_own_unmatched_tracks_in_place(self):
        own = ["x0", "a", "x1", "b", "c", "x2"]
        self.assertEqual(sync.overlay(["c", "a", "d"], own, {"a", "b", "c", "d"}), ["x0", "c", "x2", "a", "x1", "d"])
        # Anchor removed from the target: its followers go at the end.
        self.assertEqual(sync.overlay(["a"], own, {"a", "b", "c"}), ["x0", "a", "x1", "x2"])


class PlanTrackTests(unittest.TestCase):
    def test_first_run_copies_plex_rating_and_all_plays(self):
        pl = sync.plan_track({}, P(rating=6, views=3), N(plays=2))
        self.assertEqual((pl["r"], pl["to_nd"], pl["to_plex"]), (6, 3, 2))

    def test_first_run_navidrome_heart_rates_three_stars(self):
        self.assertEqual(sync.plan_track({}, P(), N(starred=True))["r"], 6)

    def test_heart_keeps_a_higher_rating(self):
        s = {"p": "1", "n": "a", "r": 8, "pr": 8, "nr": 4, "ns": True}
        self.assertEqual(sync.plan_track({**s, "ns": False}, P(rating=8), N(rating=4, starred=True))["r"], 8)

    def test_unheart_clears_rating(self):
        s = {"p": "1", "n": "a", "r": 8, "pr": 8, "nr": 4, "ns": True}
        self.assertEqual(sync.plan_track(s, P(rating=8), N(rating=4, starred=False))["r"], 0)

    def test_navidrome_rating_change(self):
        s = {"p": "1", "n": "a", "r": 6, "pr": 6, "nr": 3, "ns": True}
        self.assertEqual(sync.plan_track(s, P(rating=6), N(rating=5, starred=True))["r"], 10)

    def test_both_changed_newer_wins(self):
        s = {"p": "1", "n": "a", "r": 6, "pr": 6, "nr": 3, "ns": True}
        self.assertEqual(sync.plan_track(s, P(rating=2, rated_at=200), N(rating=5, starred=True, rated_at=100))["r"], 2)
        self.assertEqual(sync.plan_track(s, P(rating=2, rated_at=100), N(rating=5, starred=True, rated_at=200))["r"], 10)

    def test_recreated_item_gets_rating_back_without_copying_plays(self):
        s = {"p": "1", "n": "a", "r": 6, "pr": 6, "nr": 3, "ns": True, "pv": 5, "np": 5}
        pl = sync.plan_track(s, P(key="2", views=1), N(rating=3, starred=True, plays=5))
        self.assertEqual((pl["r"], pl["to_nd"], pl["to_plex"]), (6, 0, 0))

    def test_only_new_plays_are_copied(self):
        s = {"p": "1", "n": "a", "r": 0, "pr": 0, "nr": 0, "ns": False, "pv": 5, "np": 5}
        pl = sync.plan_track(s, P(views=7), N(plays=6))
        self.assertEqual((pl["to_nd"], pl["to_plex"]), (2, 1))


class PlanPlaylistTests(unittest.TestCase):
    M = {"a", "b", "c", "d"}

    def test_first_pairing_by_name_plex_wins(self):
        px = {"1": {"name": "Mix", "updated": 1, "tracks": ["a", "b", "plex:9"]}}
        nx = {"x": {"name": "Mix", "updated": 9, "tracks": ["c", "zz"]}}
        ops, pairs = sync.plan_playlists([], px, nx, self.M)
        self.assertEqual(ops, [("set", "nd", "x", ["a", "b", "zz"])])
        self.assertEqual(pairs, [{"p": "1", "n": "x", "name": "Mix", "tracks": ["a", "b"]}])

    def test_navidrome_change_and_rename_copied_to_plex(self):
        pairs = [{"p": "1", "n": "x", "name": "Mix", "tracks": ["a", "b"]}]
        px = {"1": {"name": "Mix", "updated": 1, "tracks": ["a", "b"]}}
        nx = {"x": {"name": "Mix 2", "updated": 2, "tracks": ["b", "a", "c"]}}
        ops, out = sync.plan_playlists(pairs, px, nx, self.M)
        self.assertEqual(ops, [("rename", "plex", "1", "Mix 2"), ("set", "plex", "1", ["b", "a", "c"])])
        self.assertEqual(out[0]["tracks"], ["b", "a", "c"])

    def test_unmatched_tracks_alone_are_not_a_change(self):
        pairs = [{"p": "1", "n": "x", "name": "Mix", "tracks": ["a"]}]
        px = {"1": {"name": "Mix", "updated": 1, "tracks": ["a", "plex:5"]}}
        nx = {"x": {"name": "Mix", "updated": 2, "tracks": ["a", "new-unscanned"]}}
        self.assertEqual(sync.plan_playlists(pairs, px, nx, self.M)[0], [])

    def test_deletion_mirrored_only_when_other_side_listed_playlists(self):
        pairs = [{"p": "1", "n": "x", "name": "Mix", "tracks": ["a"]}]
        px = {"1": {"name": "Mix", "updated": 1, "tracks": ["a"]}}
        ops, out = sync.plan_playlists(pairs, px, {"y": {"name": "Other", "updated": 1, "tracks": []}}, self.M)
        self.assertEqual(ops[0], ("delete", "plex", "1", "Mix", ["a"]))
        self.assertNotIn(pairs[0], out)
        ops, out = sync.plan_playlists(pairs, px, {}, self.M)
        self.assertEqual((ops, out), ([], pairs))

    def test_create_both_ways(self):
        px = {"1": {"name": "P", "updated": 1, "tracks": ["a", "plex:5"]}}
        nx = {"x": {"name": "N", "updated": 1, "tracks": ["b"]}, "y": {"name": "Empty", "updated": 1, "tracks": []}}
        ops, out = sync.plan_playlists([], px, nx, self.M)
        self.assertEqual([(o[0], o[1], o[2]["name"], o[2]["tracks"]) for o in ops],
                         [("create", "nd", "P", ["a"]), ("create", "plex", "N", ["b"])])


class FakeSide:
    def __init__(self, name, tracks, playlists=None):
        self.name, self.t, self.pl, self.calls, self.fail_after = name, tracks, playlists or {}, [], None

    def _call(self, *c):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("boom")
        self.calls.append(c)

    def tracks(self):
        return json.loads(json.dumps(self.t))

    def playlists(self):
        return json.loads(json.dumps(self.pl))

    def quiet_player(self):
        pass

    def _by_id(self, field, i):
        return next(t for t in self.t.values() if t[field] == i)

    def set_playlist(self, pid, paths):
        self._call("set", pid, paths)
        self.pl[pid]["tracks"] = list(paths)

    def create_playlist(self, name, paths):
        self._call("create", name, paths)
        pid = f"new{len(self.pl)}"
        self.pl[pid] = {"name": name, "updated": 0, "tracks": list(paths)}
        return pid

    def rename_playlist(self, pid, name):
        self._call("rename", pid, name)
        self.pl[pid]["name"] = name

    def delete_playlist(self, pid):
        self._call("delete", pid)
        del self.pl[pid]


class FakePlex(FakeSide):
    def rate(self, key, r):
        self._call("rate", key, r)
        self._by_id("key", key)["rating"] = r

    def scrobble(self, key, at):
        self._call("scrobble", key)
        self._by_id("key", key)["views"] += 1


class FakeNavidrome(FakeSide):
    def rate(self, sid, r):
        self._call("rate", sid, r)
        self._by_id("id", sid)["rating"] = r

    def star(self, sid, on):
        self._call("star", sid, on)
        self._by_id("id", sid)["starred"] = on

    def scrobble(self, sid, at):
        self._call("scrobble", sid)
        self._by_id("id", sid)["plays"] += 1


class RunTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = patch.multiple(sync, STATE=self.dir.name, DRY=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plex = FakePlex("Plex", {"a.flac": P(rating=6, views=2, key="1"), "b.flac": P(key="2"),
                                      "c.flac": P(key="3", views=1)},
                             {"10": {"name": "Mix", "updated": 1, "tracks": ["a.flac", "b.flac"]}})
        self.nd = FakeNavidrome("Navidrome", {"a.flac": N(sid="a", plays=1), "b.flac": N(sid="b", starred=True),
                                              "c.flac": N(sid="c")})

    def run_sync(self):
        sync.run(self.plex, self.nd)
        self.plex.calls.clear()
        self.nd.calls.clear()

    def test_converges_and_second_run_is_a_no_op(self):
        self.run_sync()
        self.assertEqual(self.plex.t["b.flac"]["rating"], 6)
        self.assertEqual((self.nd.t["a.flac"]["rating"], self.nd.t["a.flac"]["starred"]), (3, True))
        self.assertEqual((self.plex.t["a.flac"]["views"], self.nd.t["a.flac"]["plays"]), (3, 3))
        self.assertEqual(self.nd.t["c.flac"]["plays"], 1)
        self.assertEqual([p["tracks"] for p in self.nd.pl.values()], [["a.flac", "b.flac"]])
        sync.run(self.plex, self.nd)
        self.assertEqual((self.plex.calls, self.nd.calls), ([], []))

    def test_interrupted_run_resumes_without_double_plays(self):
        self.nd.fail_after = 3
        with self.assertRaises(RuntimeError):
            sync.run(self.plex, self.nd)
        self.nd.fail_after = None
        self.run_sync()
        self.assertEqual((self.plex.t["a.flac"]["views"], self.nd.t["a.flac"]["plays"]), (3, 3))
        self.assertEqual((self.plex.t["c.flac"]["views"], self.nd.t["c.flac"]["plays"]), (1, 1))
        sync.run(self.plex, self.nd)
        self.assertEqual((self.plex.calls, self.nd.calls), ([], []))

    def test_later_changes_flow_both_ways(self):
        self.run_sync()
        self.nd.t["a.flac"]["starred"] = False
        self.plex.t["c.flac"]["rating"] = 9
        self.plex.t["c.flac"]["views"] += 1
        self.nd.pl["new0"]["tracks"] = ["b.flac"]
        self.nd.pl["new0"]["updated"] = 5
        self.run_sync()
        self.assertEqual(self.plex.t["a.flac"]["rating"], 0)
        self.assertEqual((self.nd.t["c.flac"]["rating"], self.nd.t["c.flac"]["starred"]), (5, True))
        self.assertEqual(self.nd.t["c.flac"]["plays"], 2)
        self.assertEqual(self.plex.pl["10"]["tracks"], ["b.flac"])

    def test_mass_clear_is_refused(self):
        self.run_sync()
        with patch.object(sync, "MAX_CLEARS", 1):
            for t in self.plex.t.values():
                t["rating"] = 0
            with self.assertRaisesRegex(RuntimeError, "refusing to clear 2"):
                sync.run(self.plex, self.nd)
        self.assertEqual((self.plex.calls, self.nd.calls), ([], []))

    def test_dry_run_writes_nothing(self):
        with patch.object(sync, "DRY", True):
            sync.run(self.plex, self.nd)
        self.assertEqual((self.plex.calls, self.nd.calls), ([], []))
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "state.json")))


if __name__ == "__main__":
    unittest.main()
