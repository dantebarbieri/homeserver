import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).parents[1] / "scripts"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reorder = load("reorder_episodes", "reorder-episodes.py")
pin = load("pin_episode_metadata", "pin-episode-metadata.py")
KIM_POSSIBLE = SCRIPTS / "episode-orders" / "kim-possible.json"


class KimPossibleOrderTests(unittest.TestCase):
    def test_pinned_chronology(self):
        order, targets = reorder.load_order(KIM_POSSIBLE)
        seasons = {}
        for season, episode, title, _ in sorted(targets.values()):
            seasons.setdefault(season, []).append((episode, title))
        self.assertEqual({s: len(e) for s, e in seasons.items()},
                         {0: 1, 1: 21, 2: 34, 3: 12, 4: 23})
        for season, episodes in seasons.items():
            if season:
                self.assertEqual([e for e, _ in episodes],
                                 list(range(1, len(episodes) + 1)))
        titles = {s: [t for _, t in e] for s, e in seasons.items()}
        self.assertEqual(titles[0], ["Lilo and Stitch 2x19 Rufus"])
        self.assertEqual(titles[1][0], "Tick-Tick-Tick")
        self.assertEqual(titles[2][-2:], ["Showdown at the Crooked D", "Rewriting History"])
        self.assertEqual(titles[3][-4:], [
            "Rappin' Drakken", "Gorilla Fist", "Team Impossible", "So the Drama"
        ])
        self.assertEqual(titles[4][-2:], ["Graduation (1)", "Graduation (2)"])
        for before, after in [
            ("Car Alarm", "The Big Job"), ("Big Bother", "Clothes Minded"),
            ("Fashion Victim", "Clothes Minded"),
            ("Homecoming Upset", "Clean Slate"),
            ("Clean Slate", "The Cupid Effect"),
            ("Larry's Birthday", "Oh No! Yono!"),
        ]:
            self.assertLess(titles[4].index(before), titles[4].index(after))
        self.assertEqual(order["tvdb"]["seriesId"], 78259)

    def test_rejects_duplicate_order_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order.json"
            for episodes in (
                {"S01E01": {"tvdb": 1, "title": "A"}, "S01E02": {"tvdb": 1, "title": "B"}},
                {"S01E01": {"tvdb": 1, "title": "A"}, "S01E02": {"tvdb": 2, "title": "a"}},
                {"S1E1": {"tvdb": 1, "title": "A"}},
            ):
                path.write_text(json.dumps({"episodes": episodes}))
                with self.assertRaises(ValueError):
                    reorder.load_order(path)


class ReorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.show = self.root / "show"
        self.show.mkdir()

    def episode(self, name, number, title, tvdb=None):
        video = self.show / "Season 01" / f"Kim Possible - S01E{number:02d} - {name}.mkv"
        video.parent.mkdir(exist_ok=True)
        video.write_bytes(name.encode())
        uniqueid = f'<uniqueid type="tvdb">{tvdb}</uniqueid>' if tvdb else ""
        video.with_suffix(".nfo").write_text(
            f"<episodedetails><title>{title}</title><season>1</season>"
            f"<episode>{number}</episode><plot>Keep this</plot>{uniqueid}"
            "<displayepisode>99</displayepisode></episodedetails>"
        )
        return video

    def snapshot(self):
        return {p.relative_to(self.show): p.read_bytes()
                for p in self.show.rglob("*") if p.is_file()}

    def test_title_identity_sidecars_idempotence_and_restore(self):
        a = self.episode("First", 2, "First", tvdb=11)
        self.episode("Second", 1, "Second")
        a.with_suffix(".en.srt").write_text("subtitles")
        a.with_name(a.stem + "-thumb.jpg").write_bytes(b"thumb")
        (self.show / ".plexmatch").write_text(
            "Title: Kim Possible\nEpisode: S01E02: old.mkv\n"
        )
        originals = self.snapshot()
        targets = {"first": (1, 1, "First", 11), "second": (1, 2, "Second", 12)}
        operations = reorder.plan(self.show, targets)
        self.assertEqual(originals, self.snapshot())
        manifest = reorder.apply(self.show, self.root / "backup", operations)
        self.assertEqual(reorder.plan(self.show, targets), [])
        new_a = a.with_name(a.name.replace("E02", "E01"))
        self.assertTrue(new_a.with_suffix(".en.srt").exists())
        self.assertTrue(new_a.with_name(new_a.stem + "-thumb.jpg").exists())
        plexmatch = (self.show / ".plexmatch").read_text()
        self.assertIn(f"Episode: S01E01: Season 01/{new_a.name}", plexmatch)
        self.assertNotIn("old.mkv", plexmatch)
        nfo = ET.parse(new_a.with_suffix(".nfo")).getroot()
        self.assertEqual(nfo.findtext("episode"), "1")
        self.assertEqual(nfo.findtext("lockdata"), "true")
        self.assertEqual(nfo.findtext("plot"), "Keep this")
        self.assertIsNone(nfo.find("displayepisode"))
        reorder.restore(manifest)
        self.assertEqual(originals, self.snapshot())

    def test_rejects_missing_unknown_duplicate_mismatched_and_occupied(self):
        a = self.episode("First", 2, "First", tvdb=11)
        first = {"first": (1, 1, "First", 11)}
        destination = a.with_name(a.name.replace("E02", "E01"))
        destination.mkdir()
        with self.assertRaisesRegex(ValueError, "occupied"):
            reorder.plan(self.show, first)
        destination.rmdir()
        with self.assertRaisesRegex(ValueError, "disagrees"):
            reorder.plan(self.show, {"first": (1, 1, "First", 99)})
        with self.assertRaisesRegex(ValueError, "Unknown"):
            reorder.plan(self.show, {})
        with self.assertRaisesRegex(ValueError, "Missing episodes: Absent"):
            reorder.plan(self.show, {**first, "absent": (1, 2, "Absent", 12)})
        self.episode("Duplicate", 3, "First")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            reorder.plan(self.show, first)

    def test_apply_rolls_back_a_failed_link(self):
        self.episode("First", 2, "First")
        original = self.snapshot()
        targets = {"first": (1, 1, "First", 11)}
        operations = reorder.plan(self.show, targets)
        real_link = reorder.os.link

        def fail_destination(old, new):
            if Path(new).parent == self.show / "Season 01" and "E01" in Path(new).name:
                raise OSError("injected failure")
            return real_link(old, new)

        with patch.object(reorder.os, "link", side_effect=fail_destination):
            with self.assertRaisesRegex(OSError, "injected"):
                reorder.apply(self.show, self.root / "backup", operations)
        self.assertEqual(original, self.snapshot())

    def test_restore_refuses_changed_files(self):
        self.episode("First", 2, "First")
        targets = {"first": (1, 1, "First", 11)}
        manifest = reorder.apply(
            self.show, self.root / "backup", reorder.plan(self.show, targets)
        )
        next(self.show.rglob("*.mkv")).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            reorder.restore(manifest)


class PinTests(unittest.TestCase):
    META = {"title": "Upstream Name", "aired": "2002-06-07",
            "overview": "Kim & Ron <save> the day.", "image": None}

    def test_order_file_entries_feed_both_tools(self):
        order = json.loads(KIM_POSSIBLE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            show = Path(tmp)
            (show / "Season 02").mkdir()
            video = show / "Season 02" / "Kim Possible - S02E34 - Rewriting History.mkv"
            video.write_bytes(b"")
            (show / "Season 02" / "Kim Possible - S02E99 - Unknown.mkv").write_bytes(b"")
            files = pin.episode_files(show, order)
        self.assertEqual(files, [(video, 2, 34, 277817, "Rewriting History")])

    def test_nfo_uses_order_title_and_ignores_reformatting(self):
        want = pin.nfo_xml("Kim Possible", 2, 34, 277817, "Rewriting History", self.META)
        root = ET.fromstring(want.encode())
        self.assertEqual(root.findtext("title"), "Rewriting History")
        self.assertEqual(root.findtext("plot"), self.META["overview"])
        rewritten = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode()
        self.assertNotEqual(rewritten, want)
        self.assertEqual(pin.nfo_fields(rewritten), pin.nfo_fields(want))
        root.find("episode").text = "33"
        changed = ET.tostring(root, encoding="utf-8").decode()
        self.assertNotEqual(pin.nfo_fields(changed), pin.nfo_fields(want))
        self.assertIsNone(pin.nfo_fields("not xml"))

    def test_title_mismatch_is_reported(self):
        files = [(Path("a.mkv"), 1, 1, 7, "Tick-Tick-Tick"),
                 (Path("b.mkv"), 1, 2, 8, "Bueno Nacho")]
        metadata = {7: {"title": "Tick Tick Tick"}, 8: {"title": "Crush"}}
        with patch("builtins.print") as output:
            pin.check_titles(files, metadata)
        self.assertEqual(output.call_count, 1)
        self.assertIn("'Crush'", output.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
