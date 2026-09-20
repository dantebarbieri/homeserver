"""Exercise hash-verified upstream conversion, validation and cleanup eligibility."""

import ast
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch as mock_patch
from urllib.request import urlopen

from pytimeparse2 import parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import patch_inactivity_policy as patch


NOW = 2_000_000_000
DAY = 24 * 60 * 60
POLICY = {
    "priority": 1,
    "include_all_tags": ["noHL"],
    "max_ratio": -1,
    "max_seeding_time": -1,
    "max_last_active": "7d",
    "min_seeding_time": "14d",
    "min_num_seeds": 2,
    "cleanup": True,
    "add_group_to_tag": True,
}


@lru_cache(maxsize=1)
def sources():
    root = os.environ.get("QBIT_MANAGE_SOURCE_ROOT")
    result = {}
    for name in patch.SOURCE_HASHES:
        if root:
            text = (Path(root) / name).read_bytes().decode("utf-8")
        else:
            url = f"https://raw.githubusercontent.com/StuffAnThings/qbit_manage/{patch.REVISION}/{name}"
            with urlopen(url, timeout=30) as response:
                text = response.read().decode("utf-8")
        if name == "modules/config.py" and patch.REPLACEMENT in text:
            if text.count(patch.REPLACEMENT) != 1:
                raise ValueError("Expected exactly one patched validator")
            original = text.replace(patch.REPLACEMENT, patch.ORIGINAL, 1)
            patch.verify_source(name, original)
            if patch.patched_config(original) != text:
                raise ValueError("Unexpected changes outside the validator")
            text = original
        elif name == "modules/config.py" and os.environ.get("QBIT_MANAGE_REQUIRE_PATCHED") == "1":
            raise ValueError("Build-time tests require the actual image source to be patched")
        patch.verify_source(name, text)
        result[name] = text
    return result


def definitions(source, names, namespace, class_name=None):
    """Compile actual definitions without importing application startup/API clients."""
    nodes = ast.parse(source).body
    if class_name:
        nodes = next(node.body for node in nodes if isinstance(node, ast.ClassDef) and node.name == class_name)
    selected = []
    found = set()
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            node_names = {node.name}
        elif isinstance(node, ast.Assign):
            node_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        else:
            continue
        if node_names & names:
            selected.append(node)
            found.update(node_names & names)
    if found != names:
        raise AssertionError(f"Missing upstream definitions: {names - found}")
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<pinned-upstream>", "exec"), namespace)


def upstream_namespace(patched=True):
    log = Mock()
    log.insert_space.side_effect = lambda message, *args: str(message)
    log.print_line.side_effect = lambda message, *args: [str(message)]
    namespace = {
        "logger": log,
        "parse": parse,
        "os": os,
        "re": re,
        "timedelta": timedelta,
        "time": lambda: NOW,
        "GROUP_NOTIFICATION_LIMIT": 10,
        "YAML": Mock(side_effect=AssertionError("Tests must not read or write application configuration")),
    }
    definitions(
        sources()["modules/util.py"],
        {"Failed", "get_list", "is_tag_in_torrent", "check", "path_replace"},
        namespace,
    )
    namespace["util"] = SimpleNamespace(path_replace=namespace["path_replace"])
    config_source = sources()["modules/config.py"]
    if patched:
        config_source = patch.patched_config(config_source)
    definitions(
        config_source,
        {"SHARE_LIMIT_ACTIONS", "DESTRUCTIVE_SHARE_LIMIT_ACTIONS", "validate_share_limit_action"},
        namespace,
    )
    definitions(config_source, {"process_config_share_limits"}, namespace, "Config")
    definitions(
        sources()["modules/core/share_limits.py"],
        {"has_reached_seed_limit", "process_share_limits_for_torrent", "cleanup_torrents_for_group"},
        namespace,
        "ShareLimits",
    )
    return namespace


def converted_policy(namespace, **overrides):
    policy = {**deepcopy(POLICY), **overrides}
    config = SimpleNamespace(
        data={"share_limits": {"noHL": policy}},
        commands={"share_limits": True},
        dry_run=True,
        notify=Mock(),
        share_limits_custom_tags=[],
        default_ignore_tags=[],
    )
    config.util = namespace["check"](config)
    namespace["process_config_share_limits"](config)
    return config.share_limits["noHL"]


class Torrent(SimpleNamespace):
    def __getitem__(self, key):
        return getattr(self, key)


class InactivityPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = upstream_namespace()

    def test_original_upstream_rejects_the_existing_policy(self):
        original = upstream_namespace(patched=False)
        with self.assertRaisesRegex(original["Failed"], "max_ratio must be greater than 0"):
            converted_policy(original)

    def test_actual_conversion_preserves_all_policy_values(self):
        group = converted_policy(self.upstream)
        self.assertEqual(group["min_seeding_time"], 20160)
        self.assertEqual(group["max_last_active"], 10080)
        self.assertEqual(group["max_ratio"], -1)
        self.assertEqual(group["max_seeding_time"], -1)
        self.assertEqual(group["min_num_seeds"], 2)
        self.assertEqual(group["include_all_tags"], ["noHL"])
        self.assertTrue(group["cleanup"])

    def test_other_invalid_combinations_still_fail(self):
        cases = [
            {"max_ratio": 0},
            {"max_ratio": -2},
            {"max_seeding_time": "30d"},
            {"max_seeding_time": -2},
            {"max_last_active": -1},
            {"max_last_active": 0},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(self.upstream["Failed"]):
                    converted_policy(self.upstream, **overrides)

    def test_existing_min_max_validation_still_fails(self):
        with self.assertRaisesRegex(self.upstream["Failed"], "greater than max_seeding_time"):
            converted_policy(self.upstream, max_ratio=2, max_seeding_time="7d")

    def test_malformed_duration_still_fails(self):
        with self.assertRaisesRegex(self.upstream["Failed"], "Unable to parse"):
            converted_policy(self.upstream, min_seeding_time="not-a-duration")

    def test_destructive_qbittorrent_action_with_cleanup_still_fails(self):
        with self.assertRaises(self.upstream["Failed"]):
            converted_policy(self.upstream, share_limit_action="RemoveWithContent")

    def test_previously_valid_ratio_policy_is_unchanged(self):
        before = converted_policy(upstream_namespace(patched=False), max_ratio=2)
        after = converted_policy(self.upstream, max_ratio=2)
        self.assertEqual(before, after)

    def evaluate(self, seeded, inactive, seeds, ratio=0, content_exists=False, cross_seed=False):
        group = converted_policy(self.upstream)
        torrent = Torrent(
            name="synthetic torrent",
            hash="synthetic-hash",
            content_path="/data/torrents/synthetic",
            tags="noHL",
            seeding_time=seeded,
            last_activity=NOW - inactive,
            num_complete=seeds,
            ratio=ratio,
            state_enum=SimpleNamespace(is_complete=True),
            category="synthetic",
            trackers=[],
        )
        mutation_names = ("add_tags", "remove_tags", "set_share_limits", "set_upload_limit", "resume")
        for name in mutation_names:
            setattr(torrent, name, Mock(side_effect=AssertionError("dry-run must not mutate qBittorrent")))
        runtime = SimpleNamespace(
            config=SimpleNamespace(dry_run=True, loglevel="INFO", send_notifications=Mock()),
            min_seeding_time_tag="MinSeedTimeNotReached",
            min_num_seeds_tag="MinSeedsNotMet",
            last_active_tag="LastActiveLimitNotReached",
            tdel_dict={},
            root_dir="/data/torrents",
            remote_dir=None,
            stats_deleted=0,
            stats_deleted_contents=0,
            qbt=SimpleNamespace(
                torrentinfo={torrent.name: {"msg": [""], "status": []}},
                get_tracker_urls=Mock(return_value=[]),
                get_tags=Mock(return_value={"url": "https://tracker.example/announce", "notifiarr": None}),
                has_cross_seed=Mock(return_value=cross_seed),
                tor_delete_recycle=Mock(side_effect=AssertionError("dry-run must not delete torrents or files")),
            ),
        )
        body, _ = self.upstream["has_reached_seed_limit"](
            runtime,
            torrent=torrent,
            max_ratio=group["max_ratio"],
            max_seeding_time=group["max_seeding_time"],
            max_last_active=group["max_last_active"],
            min_seeding_time=group["min_seeding_time"],
            min_num_seeds=group["min_num_seeds"],
            min_last_active=group["min_last_active"],
            resume_torrent=group["resume_torrent_after_change"],
            tracker="https://tracker.example/announce",
            reset_upload_speed_on_unmet_minimums=group["reset_upload_speed_on_unmet_minimums"],
        )
        if body:
            self.upstream["process_share_limits_for_torrent"](runtime, torrent, group, body, -1)
            self.assertIn(torrent.hash, runtime.tdel_dict)
            with mock_patch("os.path.exists", return_value=content_exists):
                self.upstream["cleanup_torrents_for_group"](runtime, "noHL", 1)
            self.assertEqual(runtime.stats_deleted + runtime.stats_deleted_contents, 1)
        for name in mutation_names:
            getattr(torrent, name).assert_not_called()
        runtime.qbt.tor_delete_recycle.assert_not_called()
        return bool(body)

    def test_under_fourteen_days_is_protected_even_with_large_ratio(self):
        self.assertFalse(self.evaluate(14 * DAY - 1, 8 * DAY, 10, ratio=1_000_000))

    def test_activity_within_seven_days_is_protected(self):
        self.assertFalse(self.evaluate(30 * DAY, 7 * DAY - 60, 10, ratio=1_000_000))

    def test_fewer_than_two_seeders_is_protected(self):
        self.assertFalse(self.evaluate(30 * DAY, 8 * DAY, 1))

    def test_all_three_gates_at_boundary_are_eligible_without_a_ratio_requirement(self):
        self.assertTrue(self.evaluate(14 * DAY, 7 * DAY, 2))

    def test_all_three_gates_exceeded_are_eligible(self):
        self.assertTrue(self.evaluate(30 * DAY, 8 * DAY, 10))

    def test_dry_run_does_not_delete_existing_content(self):
        self.assertTrue(self.evaluate(30 * DAY, 8 * DAY, 10, content_exists=True))

    def test_dry_run_does_not_delete_cross_seeded_torrent(self):
        self.assertTrue(self.evaluate(30 * DAY, 8 * DAY, 10, content_exists=True, cross_seed=True))

    def test_patch_rejects_unexpected_or_already_patched_source(self):
        original = sources()["modules/config.py"]
        for text in (original + "\n", patch.patched_config(original)):
            with self.subTest(text_length=len(text)):
                with self.assertRaisesRegex(ValueError, "expected pinned"):
                    patch.patched_config(text)

    def test_patch_changes_only_the_one_condition(self):
        original = sources()["modules/config.py"]
        patched = patch.patched_config(original)
        self.assertEqual(patched.replace(patch.REPLACEMENT, patch.ORIGINAL, 1), original)


if __name__ == "__main__":
    unittest.main()
