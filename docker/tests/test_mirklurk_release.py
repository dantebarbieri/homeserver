from contextlib import ExitStack, nullcontext
import copy
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/mirklurk-release.py"
COMPOSE = Path(__file__).resolve().parents[1] / "compose.websites.yml"
SPEC = importlib.util.spec_from_file_location("release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
REAL_RUN = release.run
REAL_SUBPROCESS_RUN = subprocess.run
REAL_HEADROOM = release.headroom
IMAGE = "sha256:" + "a" * 64
PREVIOUS = "sha256:" + "b" * 64
SOURCE = "c" * 40
LIVE_SOURCE = "e" * 40


def runtime_env(mediawiki, php):
    return [f"MEDIAWIKI_VERSION={mediawiki}", f"PHP_VERSION={php}", "MEDIAWIKI_MAJOR_VERSION=1.43"]


class FakeDocker:
    """Local image tags as the helper sees them through `docker image ls/tag/rm`."""

    def __init__(self):
        self.tags = {}

    def handle(self, args):
        if args[:3] == ("docker", "image", "ls") and "--quiet" in args:
            return self.tags.get(args[-1], "")
        if args[:2] == ("docker", "tag"):
            self.tags[args[3]] = args[2]
            return ""
        return None


class MirklurkReleaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.environment = {"MW_SERVER_URL": release.ORIGIN, "MW_READ_ONLY": "", "MW_DB_SERVER": "mirklurk-db",
                            "MW_LOGO_URL": "", "MW_LOGO_ICON_URL": "", "MW_FAVICON_URL": ""}
        volumes = [{"type": "bind", "source": str(self.root / name), "target": target,
                    "read_only": name in ("branding", "backup-control"), "bind": {"create_host_path": False}}
                   for name, target in (("images", "/var/www/html/images"), ("branding", "/var/www/html/branding"),
                                        ("sitemap", release.SITEMAP), ("backup-control", release.BACKUP_CONTROL))]
        for name in ("images", "branding", "sitemap", "sitemap/public", "backup-control"):
            (self.root / name).mkdir(mode=0o755)
        self.config = {
            "services": {
                "mirklurk": {
                    "image": release.LIVE_TAG, "pull_policy": "never", "profiles": [release.PROFILE],
                    "command": None, "entrypoint": None,
                    "environment": self.environment, "volumes": volumes, "networks": {"proxy": {}},
                    "secrets": [{"target": "/run/secrets/PASSWORD", "source": "PASSWORD"}],
                },
                "mirklurk-db": {"image": "pinned-database"},
                "mirklurk-backup": {"image": "pinned-database"},
            },
            "networks": {"proxy": {"name": "compose_proxy"}},
            "secrets": {"PASSWORD": {"file": "/private/secret"}},
        }
        state = {"Running": True, "Health": {"Status": "healthy"}}
        self.live = {
            "Image": PREVIOUS, "State": state,
            "Config": {"Env": [f"{key}={value}" for key, value in self.environment.items()],
                       "Labels": {"com.docker.compose.project": "compose"}},
            "Mounts": [{"Destination": v["target"], "Source": v["source"], "RW": not v["read_only"]}
                       for v in volumes if v["target"] != release.SITEMAP]
                      + [{"Destination": "/run/secrets/PASSWORD", "Source": "/private/secret", "RW": False}],
            "NetworkSettings": {"Networks": {"compose_proxy": {}}},
        }
        self.objects = {
            IMAGE: {"Id": IMAGE, "Config": {"Env": runtime_env("1.43.12", "8.3.37"),
                                            "Labels": {"org.opencontainers.image.revision": SOURCE,
                                                       "org.opencontainers.image.source": release.SOURCE}}},
            PREVIOUS: {"Id": PREVIOUS, "Config": {"Env": runtime_env("1.43.11", "8.3.36"),
                                                  "Labels": {"org.opencontainers.image.source": release.SOURCE}}},
            "mirklurk": self.live,
            "mirklurk-db": {"State": state, "Config": {"Image": "pinned-database"}},
            "mirklurk-backup": {"State": state, "Config": {"Image": "pinned-database"}},
        }
        self.docker = FakeDocker()
        self.history = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(release, "AUTO_STATE", self.history))
        self.commands = []
        self.run_mock = self.stack.enter_context(patch.object(release, "run", side_effect=self.fake_run))
        self.compose_mock = self.stack.enter_context(patch.object(release, "compose", side_effect=self.fake_compose))
        self.stack.enter_context(patch.object(release, "inspect", side_effect=lambda name, **kw: self.objects[name]))
        self.stack.enter_context(patch.object(release, "headroom"))
        self.siteinfo = self.stack.enter_context(patch.object(release, "siteinfo"))
        real_stat = Path.stat
        self.sitemap_owner = (33, 33)

        def directory_stat(path, **kwargs):
            result = real_stat(path, **kwargs)
            if path in (self.root / "sitemap", self.root / "sitemap/public"):
                import os
                fields = list(result)
                fields[4], fields[5] = self.sitemap_owner
                return os.stat_result(fields)
            return result
        self.stack.enter_context(patch.object(Path, "stat", directory_stat))

    def fake_run(self, *args, **kwargs):
        self.commands.append(args)
        handled = self.docker.handle(args)
        if handled is not None:
            return handled
        if args[0] == "systemctl":
            return "inactive"
        if args[0] == "git":
            if "branch" in args:
                return "main"
            if "rev-parse" in args:
                return "d" * 40
        return ""

    def fake_compose(self, root, *args, **kwargs):
        self.commands.append(("compose", *args))
        if args[:2] == ("config", "--format"):
            return json.dumps(self.config)
        if args[0] == "up":
            self.live["Image"] = IMAGE
            self.live["Mounts"].append({"Destination": release.SITEMAP, "Source": str(self.root / "sitemap"), "RW": True})
        return ""

    def preflight(self):
        return release.preflight(self.root, SOURCE, IMAGE, PREVIOUS)

    def test_preflight_has_no_writes_and_does_not_read_page_revisions(self):
        self.preflight()
        self.assertTrue(all(command[0] == "git" or command[:2] == ("compose", "config")
                            or command[:3] == ("docker", "image", "ls") for command in self.commands))
        self.siteinfo.assert_called_once_with("1.43.11")

    def test_relative_secret_target_normalizes_without_changing_mount(self):
        self.config["services"]["mirklurk"]["secrets"][0]["target"] = "PASSWORD"
        self.preflight()

    def test_wrong_source_and_image_provenance_fail_closed(self):
        self.config["services"]["mirklurk"]["labels"] = {"org.opencontainers.image.revision": SOURCE}
        with self.assertRaisesRegex(release.ReleaseError, "must not override"):
            self.preflight()
        del self.config["services"]["mirklurk"]["labels"]
        self.objects[IMAGE]["Config"]["Labels"]["org.opencontainers.image.revision"] = "0" * 40
        with self.assertRaisesRegex(release.ReleaseError, "provenance"):
            self.preflight()
        self.objects[IMAGE]["Config"]["Labels"]["org.opencontainers.image.revision"] = SOURCE
        self.objects[IMAGE]["Config"]["Labels"]["org.opencontainers.image.source"] = "wrong"
        with self.assertRaisesRegex(release.ReleaseError, "provenance"):
            self.preflight()

    def test_frontend_must_be_profiled_and_run_the_helper_managed_tag(self):
        service = self.config["services"]["mirklurk"]
        for key, value in (("image", IMAGE), ("profiles", None), ("profiles", ["other"]), ("pull_policy", "missing")):
            with self.subTest(key=key, value=value):
                original = service[key] if key in service else None
                service[key] = value
                with self.assertRaisesRegex(release.ReleaseError, "helper-managed"):
                    self.preflight()
                service[key] = original
        service["profiles"] = [release.PROFILE]
        self.docker.tags[release.LIVE_TAG] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(release.ReleaseError, "unexpected image"):
            self.preflight()
        for tagged in (PREVIOUS, IMAGE):
            self.docker.tags[release.LIVE_TAG] = tagged
            self.preflight()

    def test_vulnerable_or_never_serve_candidate_is_refused(self):
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.9", "8.3.33")
        with self.assertRaisesRegex(release.ReleaseError, "PHP2Shell"):
            self.preflight()
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.12", "8.4.0")
        self.preflight()
        with patch.object(release, "NEVER_SERVE", {IMAGE}):
            with self.assertRaisesRegex(release.ReleaseError, "never-serve"):
                self.preflight()
        self.objects[IMAGE]["Config"]["Env"] = ["PHP_VERSION=8.3.37"]
        with self.assertRaisesRegex(release.ReleaseError, "MEDIAWIKI_VERSION"):
            self.preflight()
        self.assertIn("sha256:a1f303f573bcdeecce80992c6b5139e19bab07c6bed7b1eb02839b6e01a77b5a", release.NEVER_SERVE)

    def test_rejects_dirty_checkout_and_missing_backup_health(self):
        self.run_mock.side_effect = lambda *args, **kw: " M file" if "status" in args else ""
        with self.assertRaisesRegex(release.ReleaseError, "not clean"):
            self.preflight()
        self.run_mock.side_effect = self.fake_run
        self.objects["mirklurk-backup"] = copy.deepcopy(self.objects["mirklurk-backup"])
        self.objects["mirklurk-backup"]["State"]["Health"]["Status"] = "unhealthy"
        with self.assertRaisesRegex(release.ReleaseError, "mirklurk-backup"):
            self.preflight()

    def test_rejects_changed_environment_mounts_and_unknown_predecessor(self):
        original = copy.deepcopy(self.config)
        self.config["services"]["mirklurk"]["environment"]["MW_READ_ONLY"] = "freeze"
        with self.assertRaises(release.ReleaseError):
            self.preflight()
        self.config = copy.deepcopy(original)
        self.config["services"]["mirklurk"]["volumes"].pop(0)
        with self.assertRaisesRegex(release.ReleaseError, "volume set"):
            self.preflight()
        self.config = copy.deepcopy(original)
        self.config["services"]["mirklurk"]["environment"]["MW_UNREVIEWED"] = ""
        with self.assertRaisesRegex(release.ReleaseError, "Runtime environment differs"):
            self.preflight()
        self.config = original
        self.live["Image"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(release.ReleaseError, "neither expected"):
            self.preflight()

    def test_allows_only_reviewed_introduced_environment_keys(self):
        self.config["services"]["mirklurk"]["environment"]["MW_APPLE_TOUCH_ICON_URL"] = "/branding/x/icon.png"
        self.preflight()
        self.live["Config"]["Env"].append("MW_APPLE_TOUCH_ICON_URL=/branding/y/icon.png")
        with self.assertRaisesRegex(release.ReleaseError, "Runtime environment differs"):
            self.preflight()
        self.live["Config"]["Env"][-1] = "MW_APPLE_TOUCH_ICON_URL=/branding/x/icon.png"
        self.preflight()

    def deploy_mocks(self):
        self.stack.enter_context(patch.object(release, "CANONICAL", self.root))
        script = self.root / "docker/scripts/mirklurk-release.py"
        script.parent.mkdir(parents=True)
        script.write_text("fixture")
        self.stack.enter_context(patch.object(release, "__file__", str(script)))
        self.stack.enter_context(patch.object(release, "availability_monitor", return_value=nullcontext()))
        self.backups_mock = self.stack.enter_context(patch.object(release, "check_backups"))
        acceptance = self.stack.enter_context(patch.object(release, "public_acceptance"))
        refresh = self.stack.enter_context(patch.object(release, "refresh_sitemap"))
        return acceptance, refresh

    def test_deploy_scoped_order_and_idempotence(self):
        acceptance, refresh = self.deploy_mocks()
        release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        up = ("compose", "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "mirklurk")
        self.assertEqual(self.commands.count(up), 1)
        backup = next(i for i, call in enumerate(self.commands) if "--once" in call)
        retag = self.commands.index(("docker", "tag", IMAGE, release.LIVE_TAG))
        self.assertLess(backup, retag)
        self.assertLess(self.commands.index(("docker", "tag", PREVIOUS, release.PREVIOUS_TAG)), retag)
        self.assertLess(retag, self.commands.index(up))
        self.assertEqual(self.docker.tags, {release.LIVE_TAG: IMAGE, release.PREVIOUS_TAG: PREVIOUS})
        self.assertTrue(any("pull" in call and "--ff-only" in call for call in self.commands))
        acceptance.assert_called_with(self.environment, "1.43.12")
        release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        self.assertEqual(self.commands.count(up), 1)
        self.assertEqual(sum("--once" in call for call in self.commands), 1)
        self.assertEqual(self.backups_mock.call_count, 1)
        self.assertEqual(acceptance.call_count, 2)
        self.assertEqual(refresh.call_count, 2)
        self.assertFalse(any("start" in call or "stop" in call or "--remove-orphans" in call for call in self.commands))
        history = [json.loads(line) for line in (self.history / "history.jsonl").read_text().splitlines()]
        self.assertEqual([(entry["kind"], entry["source"], entry["image"], entry["previous"]) for entry in history],
                         [("manual", SOURCE, IMAGE, PREVIOUS)])

    def test_wrong_checkout_blocks_before_pull_and_updater_needs_no_pause(self):
        self.deploy_mocks()
        with self.assertRaisesRegex(release.ReleaseError, "only allowed"):
            release.deploy(Path("/wrong"), SOURCE, IMAGE, PREVIOUS)
        self.assertFalse(any("pull" in call for call in self.commands))
        release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        self.assertFalse(any(call[0] == "systemctl" for call in self.commands))

    def test_recover_serves_a_known_image_even_when_the_frontend_is_broken(self):
        acceptance, refresh = self.deploy_mocks()
        self.docker.tags[release.LIVE_TAG] = PREVIOUS
        self.objects[PREVIOUS]["Config"]["Labels"][release.REVISION_LABEL] = LIVE_SOURCE
        self.live["State"] = {"Running": True, "Health": {"Status": "unhealthy"}}
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.9", "8.3.33")
        with self.assertRaisesRegex(release.ReleaseError, "PHP2Shell"):
            release.recover(self.root, SOURCE, IMAGE)
        self.assertEqual(self.docker.tags, {release.LIVE_TAG: PREVIOUS})
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.11", "8.3.36")
        original = self.compose_mock.side_effect

        def compose(root, *args, **kwargs):
            if args[0] == "up":
                self.live["State"] = {"Running": True, "Health": {"Status": "healthy"}}
            return original(root, *args, **kwargs)
        self.compose_mock.side_effect = compose
        release.recover(self.root, SOURCE, IMAGE)
        self.assertEqual(self.docker.tags, {release.LIVE_TAG: IMAGE, release.PREVIOUS_TAG: PREVIOUS})
        up = ("compose", "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "mirklurk")
        self.assertLess(self.commands.index(("docker", "tag", IMAGE, release.LIVE_TAG)), self.commands.index(up))
        acceptance.assert_called_once_with(self.environment, "1.43.11")
        refresh.assert_called_once()
        self.assertEqual((self.history / "rejected").read_text().split(), [LIVE_SOURCE])
        entry = json.loads((self.history / "history.jsonl").read_text())
        self.assertEqual((entry["kind"], entry["image"], entry["previous"]), ("recovery", IMAGE, PREVIOUS))

    def test_recover_defaults_to_the_held_predecessor_and_refuses_rejected_revisions(self):
        self.deploy_mocks()
        self.docker.tags[release.LIVE_TAG] = PREVIOUS
        self.objects[PREVIOUS]["Config"]["Labels"][release.REVISION_LABEL] = LIVE_SOURCE
        with self.assertRaisesRegex(release.ReleaseError, "No hold"):
            release.recover(self.root)
        (self.history / "hold").write_text(json.dumps({"previous": IMAGE, "image": PREVIOUS}))
        (self.history / "rejected").write_text(SOURCE + "\n")
        with self.assertRaisesRegex(release.ReleaseError, "was rejected"):
            release.recover(self.root)
        self.assertNotIn(("docker", "tag", IMAGE, release.LIVE_TAG), self.commands)
        (self.history / "rejected").write_text("")
        release.recover(self.root)
        # Rerunning (for example after a partial failure) keeps serving the held predecessor.
        release.recover(self.root)
        self.assertEqual(self.docker.tags, {release.LIVE_TAG: IMAGE, release.PREVIOUS_TAG: PREVIOUS})
        self.assertEqual((self.history / "rejected").read_text().split(), [LIVE_SOURCE])

    def test_backup_failure_does_not_activate(self):
        self.deploy_mocks()
        self.backups_mock.side_effect = release.ReleaseError("backup failed")
        with self.assertRaisesRegex(release.ReleaseError, "backup failed"):
            release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        self.assertFalse(any("up" in call for call in self.commands))
        self.assertEqual(self.docker.tags, {})

    def test_acceptance_failure_does_not_rollback_or_resume_timer(self):
        acceptance, refresh = self.deploy_mocks()
        acceptance.side_effect = release.ReleaseError("metadata failed")
        with self.assertRaisesRegex(release.ReleaseError, "metadata failed"):
            release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        refresh.assert_not_called()
        self.assertEqual(sum("up" in call for call in self.commands), 1)
        self.assertFalse(any("start" in call for call in self.commands))
        self.assertEqual(self.docker.tags[release.LIVE_TAG], IMAGE)

    def test_sitemap_checks_jobs_and_fails_missing_initial_index(self):
        def refresh_compose(root, *args, **kwargs):
            self.commands.append(args)
            if "showJobs" in args:
                return "0"
            if "-r" in args:
                return "1"
            return ""
        self.compose_mock.side_effect = refresh_compose
        with patch.object(release, "get", side_effect=[
            b"Sitemap: https://mirklurk.wiki/sitemap.xml", release.ReleaseError("HTTP 404"),
        ]):
            with self.assertRaisesRegex(release.ReleaseError, "404"):
                release.refresh_sitemap(self.root)
        self.assertTrue(all("--user" in call and "www-data" in call for call in self.commands))
        self.compose_mock.side_effect = lambda root, *args, **kw: "1" if "showJobs" in args else ""
        with self.assertRaisesRegex(release.ReleaseError, "Pending content jobs"):
            release.refresh_sitemap(self.root)

    def test_sitemap_success_checks_each_shard_and_canonical_urls(self):
        self.compose_mock.side_effect = lambda root, *args, **kw: (
            "0" if "showJobs" in args else "1" if "-r" in args else "")
        index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://mirklurk.wiki/sitemap-wiki-a.xml</loc></sitemap></sitemapindex>"""
        shard = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://mirklurk.wiki/w/Items</loc></url></urlset>"""
        with patch.object(release, "get", side_effect=[
                b"Sitemap: https://mirklurk.wiki/sitemap.xml", index, shard]) as get:
            release.refresh_sitemap(self.root)
            self.assertEqual(get.call_args.args, ("/sitemap-wiki-a.xml",))
        with patch.object(release, "get", side_effect=[
                b"Sitemap: https://mirklurk.wiki/sitemap.xml", index,
                shard.replace(b"https://mirklurk.wiki", b"https://wrong.invalid")]):
            with self.assertRaisesRegex(release.ReleaseError, "noncanonical"):
                release.refresh_sitemap(self.root)

    def test_unrelated_container_change_is_not_accepted(self):
        self.deploy_mocks()
        with patch.object(release, "container_ids", side_effect=[["db first"], ["db replaced"]]):
            with self.assertRaisesRegex(release.ReleaseError, "Other container identities"):
                release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)

    def test_missing_storage_prevents_activation(self):
        (self.root / "sitemap/public").rmdir()
        with self.assertRaisesRegex(release.ReleaseError, "Missing sitemap directory"):
            self.preflight()
        self.assertFalse(any("up" in call for call in self.commands))

    def test_sitemap_inherited_setgid_is_allowed_but_unsafe_modes_are_rejected(self):
        for folder in (self.root / "sitemap", self.root / "sitemap/public"):
            folder.chmod(0o2755)
            self.preflight()
            for mode in (0o1755, 0o4755, 0o6755, 0o775, 0o757, 0o2775, 0o2757):
                with self.subTest(folder=folder.name, mode=oct(mode)):
                    folder.chmod(mode)
                    with self.assertRaisesRegex(release.ReleaseError, "mode 0755 or 2755"):
                        self.preflight()
                    folder.chmod(0o755)
        self.preflight()

    def test_sitemap_unexpected_owner_or_symlink_is_rejected(self):
        for owner in ((0, 33), (33, 0)):
            self.sitemap_owner = owner
            with self.assertRaisesRegex(release.ReleaseError, "UID/GID 33"):
                self.preflight()
        self.sitemap_owner = (33, 33)
        folder = self.root / "sitemap/public"
        folder.rmdir()
        folder.symlink_to(self.root / "images", target_is_directory=True)
        with self.assertRaisesRegex(release.ReleaseError, "UID/GID 33"):
            self.preflight()

    def test_resource_thresholds(self):
        with patch.object(Path, "read_text", return_value="MemAvailable: 2097152 kB\n"), \
             patch.object(release.os, "getloadavg", return_value=(3, 0, 0)), \
             patch.object(release.os, "cpu_count", return_value=4), \
             patch.object(release.shutil, "disk_usage", return_value=SimpleNamespace(free=5 * 1024**3)):
            REAL_HEADROOM(self.root)
            with patch.object(release.os, "getloadavg", return_value=(4, 0, 0)):
                with self.assertRaisesRegex(release.ReleaseError, "load"):
                    REAL_HEADROOM(self.root)
            with patch.object(Path, "read_text", return_value="MemAvailable: 2097151 kB\n"):
                with self.assertRaisesRegex(release.ReleaseError, "memory"):
                    REAL_HEADROOM(self.root)
            with patch.object(release.shutil, "disk_usage", return_value=SimpleNamespace(free=5 * 1024**3 - 1)):
                with self.assertRaisesRegex(release.ReleaseError, "storage"):
                    REAL_HEADROOM(self.root)

    def test_shared_lock_blocks_and_is_released(self):
        import fcntl
        lock = self.root / "compose.lock"
        lock.touch()
        with patch.object(release, "LOCK", lock):
            with release.locked():
                with lock.open("r") as second:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with lock.open("r") as second:
                fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_subprocess_failure_does_not_echo_secrets(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                ["docker", "compose"], 1, "private fixture", "private fixture")):
            with self.assertRaises(release.ReleaseError) as error:
                REAL_RUN("docker", "compose")
            self.assertNotIn("private fixture", str(error.exception))


class MirklurkSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(release, "DATA", self.root))
        self.stack.enter_context(patch.object(release.os, "geteuid", return_value=0))
        self.stack.enter_context(patch.object(release.shutil, "disk_usage",
                                             return_value=SimpleNamespace(free=100 * 1024**3)))
        self.stack.enter_context(patch.object(release.os, "statvfs",
                                             return_value=SimpleNamespace(f_files=1000000, f_favail=500000)))
        for name in ("images", "branding", "backup-control", "backups/daily"):
            (self.root / name).mkdir(parents=True)
        self.fixture = {
            "images/a/b/current.png": b"current image",
            "images/archive/old.png": b"previous version",
            "images/deleted/secret.png": b"private deleted version",
            "images/thumb/small.png": b"thumbnail",
            "images/temp/stash.png": b"upload stash",
            "images/import.png": b"existing imported artwork",
            "branding/2026-09/icon.png": b"existing approved branding",
        }
        for name, data in self.fixture.items():
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        (self.root / "images/deleted").chmod(0o700)
        (self.root / "images/deleted/secret.png").chmod(0o600)
        os.setxattr(self.root / "images/deleted/secret.png", b"user.backup-test", b"preserved")
        self.lock = self.root / "backup-control/read-only"
        self.live = {
            "Id": "app-id", "Image": IMAGE,
            "Config": {"Env": ["MW_DB_SERVER=mirklurk-db", "MW_DB_NAME=mirklurk", "MW_DB_USER=mirklurk"],
                       "Labels": {"com.docker.compose.project": "compose",
                                  "org.opencontainers.image.revision": SOURCE}},
            "State": {"Running": True, "Health": {"Status": "healthy"}, "ExitCode": 0, "OOMKilled": False},
            "Mounts": [
                {"Type": "bind", "Destination": target, "Source": str(self.root / folder), "RW": writable}
                for target, folder, writable in (
                    ("/var/www/html/images", "images", True), ("/var/www/html/branding", "branding", False),
                    (release.BACKUP_CONTROL, "backup-control", False))],
        }
        self.backup = {
            "Config": {"Env": ["MW_DB_SERVER=mirklurk-db", "MW_DB_NAME=mirklurk", "MW_DB_USER=mirklurk"]},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "Mounts": [{"Type": "bind", "Destination": "/backups",
                        "Source": str(self.root / "backups"), "RW": True}],
        }
        self.objects = {"mirklurk": self.live, "app-id": self.live,
                        "mirklurk-db": self.backup, "mirklurk-backup": self.backup}
        self.other = {"Id": "other", "Mounts": [{"Type": "tmpfs", "Destination": "/tmp", "RW": True}]}
        self.stack.enter_context(patch.object(release, "inspect", side_effect=lambda name: self.objects[name]))
        self.commands = []
        self.failure = None
        self.runner = self.stack.enter_context(patch.object(release, "run", side_effect=self.fake_run))
        self.sql = b"CREATE TABLE `page` (`page_id` int);\n"

    def fake_run(self, *args, **kwargs):
        self.commands.append(args)
        if args[:3] == ("docker", "ps", "-q"):
            return "app-id\nother"
        if args[:2] == ("docker", "inspect"):
            return "\n".join(json.dumps(container) for container in (self.live, self.other))
        if args[:2] == ("docker", "stop"):
            self.assertTrue(self.lock.is_file())
            self.assertEqual(self.lock.stat().st_mode & 0o777, 0o644)
            self.live["State"]["Running"] = False
            if self.failure == "stop":
                self.live["State"]["ExitCode"] = 137
            return ""
        if args[:2] == ("docker", "start"):
            if self.failure == "start":
                raise release.ReleaseError("start failed")
            self.live["State"]["Running"] = True
            return ""
        if "--snapshot" in args:
            self.assertFalse(self.live["State"]["Running"])
            if self.failure == "dump":
                raise release.ReleaseError("dump failed")
            self.assertIn("--snapshot)", kwargs["input"])
            snapshot_id = args[args.index("--snapshot") + 1]
            (self.root / f"backups/.mirklurk-snapshot-sql-{snapshot_id}.sql.gz").write_bytes(gzip.compress(self.sql))
            (self.root / "backups/daily/mirklurk-2026-10-02.sql.gz").write_bytes(b"unrelated online dump")
            return ""
        if "--healthcheck" in args:
            return ""
        if args[:2] == ("tar", "--create"):
            self.assertFalse(self.live["State"]["Running"])
            if self.failure == "tar":
                raise release.ReleaseError("tar failed")
            if self.failure == "replace-lock":
                self.lock.rename(self.lock.with_name("original-lock"))
                self.lock.write_text("operator maintenance")
        if args[:2] == ("tar", "--list"):
            self.assertTrue(self.live["State"]["Running"])
        return REAL_RUN(*args, **kwargs)

    def bundles(self):
        return list((self.root / "backups/snapshots/daily").glob("*.tar.gz"))

    def test_complete_snapshot_preserves_every_file_and_restores_app_before_validation(self):
        release.snapshot()
        self.assertEqual(len(self.bundles()), 1)
        bundle = self.bundles()[0]
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
        with tarfile.open(bundle) as archive:
            for name, data in self.fixture.items():
                self.assertEqual(archive.extractfile(name).read(), data)
                self.assertEqual((self.root / name).read_bytes(), data)
            self.assertEqual(gzip.decompress(archive.extractfile("database.sql.gz").read()), self.sql)
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertEqual(manifest["image"], IMAGE)
            self.assertEqual(manifest["source"], SOURCE)
            self.assertNotIn("backup-control/read-only", archive.getnames())
        self.assertTrue(self.live["State"]["Running"])
        self.assertFalse(self.lock.exists())
        self.assertFalse(list((self.root / "backups").glob(".mirklurk-snapshot-*")))
        recovery = self.root / "isolated-recovery"
        recovery.mkdir()
        REAL_RUN("tar", "--extract", "--gzip", "--acls", "--xattrs", "--numeric-owner",
                 "--file", str(bundle), "--directory", str(recovery))
        for name, data in self.fixture.items():
            self.assertEqual((recovery / name).read_bytes(), data)
            self.assertEqual((recovery / name).stat().st_uid, (self.root / name).stat().st_uid)
            self.assertEqual((recovery / name).stat().st_gid, (self.root / name).stat().st_gid)
            self.assertEqual((recovery / name).stat().st_mode, (self.root / name).stat().st_mode)
        self.assertEqual(os.getxattr(recovery / "images/deleted/secret.png", b"user.backup-test"), b"preserved")
        release.check_backups()

    def test_failures_restore_same_container_and_do_not_publish_or_replace_good_bundle(self):
        release.snapshot()
        good = self.bundles()[0].read_bytes()
        for failure in ("dump", "tar", "stop"):
            with self.subTest(failure=failure):
                self.failure = failure
                with self.assertRaises(release.ReleaseError):
                    release.snapshot()
                self.assertTrue(self.live["State"]["Running"])
                self.assertFalse(self.lock.exists())
                self.assertEqual(len(self.bundles()), 1)
                self.assertEqual(self.bundles()[0].read_bytes(), good)
                self.live["State"]["ExitCode"] = 0

    def test_restart_failure_keeps_lock_and_never_publishes(self):
        self.failure = "start"
        with self.assertRaisesRegex(release.ReleaseError, "start failed"):
            release.snapshot()
        self.assertTrue(self.lock.exists())
        self.assertEqual(self.bundles(), [])

    def test_operator_lock_and_replaced_marker_are_never_removed(self):
        self.lock.write_text("operator lock")
        with self.assertRaises(FileExistsError):
            release.snapshot()
        self.assertEqual(self.lock.read_text(), "operator lock")
        self.assertFalse(any("stop" in call for call in self.commands))
        self.lock.unlink()
        self.failure = "replace-lock"
        with self.assertRaisesRegex(release.ReleaseError, "replaced"):
            release.snapshot()
        self.assertEqual(self.lock.read_text(), "operator maintenance")

    def test_other_writer_and_changed_mount_block_before_stop(self):
        self.other["Mounts"] = [{"Type": "bind", "Source": str(self.root), "RW": True}]
        with self.assertRaisesRegex(release.ReleaseError, "Another running container"):
            release.snapshot()
        self.other["Mounts"] = []
        self.live["Mounts"][0]["Source"] = "/wrong"
        with self.assertRaisesRegex(release.ReleaseError, "Unexpected snapshot mount"):
            release.snapshot()
        self.assertFalse(any("stop" in call for call in self.commands))

    def test_known_administrative_parent_mount_is_reported_but_direct_writer_still_blocked(self):
        self.other.update(Name="/code-server", Mounts=[{"Type": "bind", "Source": str(self.root), "RW": True}])
        release.snapshot()
        self.other["Mounts"][0]["Source"] = str(self.root / "images")
        with self.assertRaisesRegex(release.ReleaseError, "Another running container"):
            release.snapshot()

    def test_unprivileged_invocation_is_rejected_before_inspection(self):
        with patch.object(release.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(release.ReleaseError, "as root"):
                release.snapshot()
        self.assertEqual(self.commands, [])

    def test_wrong_backup_database_or_missing_source_fails_before_stop(self):
        self.backup["Config"]["Env"][1] = "MW_DB_NAME=wrong"
        with self.assertRaisesRegex(release.ReleaseError, "database contract"):
            release.snapshot()
        self.backup["Config"]["Env"][1] = "MW_DB_NAME=mirklurk"
        del self.live["Config"]["Labels"]["org.opencontainers.image.revision"]
        with self.assertRaisesRegex(release.ReleaseError, "provenance"):
            release.snapshot()
        self.assertFalse(any("stop" in call for call in self.commands))

    def test_archive_validation_failure_is_not_published_and_clears_own_lock(self):
        original = self.fake_run
        def fail_validation(*args, **kwargs):
            if args[:2] == ("tar", "--list"):
                raise release.ReleaseError("archive corrupt")
            return original(*args, **kwargs)
        self.runner.side_effect = fail_validation
        with self.assertRaisesRegex(release.ReleaseError, "archive corrupt"):
            release.snapshot()
        self.assertTrue(self.live["State"]["Running"])
        self.assertFalse(self.lock.exists())
        self.assertEqual(self.bundles(), [])

    def test_retention_and_sunday_weekly_copy(self):
        from datetime import datetime, timezone
        real_datetime = release.datetime
        with patch.object(release, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 4, 3, 15, tzinfo=timezone.utc)
            release.snapshot()
        self.assertIs(release.datetime, real_datetime)
        weekly = list((self.root / "backups/snapshots/weekly").glob("*.tar.gz"))
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0].read_bytes(), self.bundles()[0].read_bytes())
        for tier, days in (("daily", 7), ("weekly", 28)):
            folder = self.root / "backups/snapshots" / tier
            old = folder / "mirklurk-20200101T000000000000Z.tar.gz"
            old.write_bytes(b"old")
            timestamp = time.time() - days * 86400 - 1
            os.utime(old, (timestamp, timestamp))
            (folder / "unrelated.tar.gz").write_bytes(b"preserve")
        release.snapshot()
        for tier in ("daily", "weekly"):
            folder = self.root / "backups/snapshots" / tier
            self.assertFalse((folder / "mirklurk-20200101T000000000000Z.tar.gz").exists())
            self.assertTrue((folder / "unrelated.tar.gz").exists())

    def test_storage_exact_thresholds_and_snapshot_freshness(self):
        with patch.object(release.shutil, "disk_usage", return_value=SimpleNamespace(free=5 * 1024**3)):
            release.storage_headroom()
        with patch.object(release.shutil, "disk_usage", return_value=SimpleNamespace(free=5 * 1024**3 - 1)):
            with self.assertRaisesRegex(release.ReleaseError, "5 GiB"):
                release.snapshot()
        with patch.object(release.os, "statvfs", return_value=SimpleNamespace(f_files=1000000, f_favail=49999)):
            with self.assertRaisesRegex(release.ReleaseError, "inodes"):
                release.snapshot()
        self.assertFalse(any("stop" in call for call in self.commands))
        with self.assertRaisesRegex(release.ReleaseError, "missing"):
            release.check_backups()
        release.snapshot()
        timestamp = time.time() - 26 * 3600
        os.utime(self.root / "backups/.last-snapshot", (timestamp, timestamp))
        with self.assertRaisesRegex(release.ReleaseError, "26 hours"):
            release.check_backups()


class ComposeContractTests(unittest.TestCase):
    def test_frontend_is_profiled_and_runs_only_the_helper_managed_tag(self):
        text = COMPOSE.read_text()
        block = text[text.index("\n  mirklurk:\n"):text.index("\n  mirklurk-db:\n")]
        self.assertIn(f'    profiles: ["{release.PROFILE}"]\n', block)
        self.assertIn(f"    image: {release.LIVE_TAG}\n", block)
        self.assertIn("    pull_policy: never\n", block)
        self.assertNotIn("build:", block)
        self.assertNotIn(release.REVISION_LABEL, block)
        self.assertNotIn("sha256:", block)
        # Backing services stay on the generic updater: only the frontend is profiled.
        self.assertEqual(text.count(f'profiles: ["{release.PROFILE}"]'), 1)


class GitRepo:
    def __init__(self, path):
        self.path = path
        self.clock = 1_800_000_000
        self.git("init", "--quiet", "-b", "main")

    def git(self, *args):
        environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                       "GIT_AUTHOR_DATE": f"@{self.clock} +0000", "GIT_COMMITTER_DATE": f"@{self.clock} +0000"}
        return subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True,
                              text=True, env=environment).stdout.strip()

    def commit(self, files, at=None):
        self.clock = at or self.clock + 3600
        for name, content in files.items():
            file = self.path / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "-m", "change")
        return self.git("rev-parse", "HEAD")


def dockerfile(base="FROM mediawiki:1.43.11@sha256:" + "1" * 64, extra=""):
    return f"{base}\n\nCOPY deploy/LocalSettings.template.php /var/www/html/LocalSettings.php\n{extra}" \
           "RUN a2enmod rewrite headers \\\n    && apache2ctl -t\n"


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = GitRepo(Path(self.temporary.name))
        self.live = self.repo.commit({"deploy/Dockerfile": dockerfile(), "deploy/LocalSettings.template.php": "<?php\n",
                                      "content/Items.wiki": "items"})

    def evaluate(self, candidate):
        return release.evaluate(self.repo.path, self.live, candidate, 42)

    def test_current_and_content_only_changes_need_no_image(self):
        self.assertEqual(self.evaluate(self.live).kind, "current")
        content = self.repo.commit({"content/Items.wiki": "more items", "docs/X.md": "x"})
        self.assertEqual(self.evaluate(content).kind, "current")
        changed = self.repo.commit({"deploy/LocalSettings.template.php": "<?php // x\n"})
        reverted = self.repo.commit({"deploy/LocalSettings.template.php": "<?php\n"})
        self.assertEqual(self.evaluate(changed).kind, "blocked")
        self.assertEqual(self.evaluate(reverted).kind, "current")

    def test_patch_and_same_tag_digest_bumps_are_eligible_since_their_merge(self):
        self.repo.commit({"content/Items.wiki": "edit"})
        line = "FROM mediawiki:1.43.12@sha256:" + "2" * 64
        bump = self.repo.commit({"deploy/Dockerfile": dockerfile(line)}, at=1_800_100_000)
        later = self.repo.commit({"content/Items.wiki": "edit again"})
        decision = self.evaluate(later)
        self.assertEqual((decision.kind, decision.since, decision.base), ("eligible", 1_800_100_000, line))
        self.assertIn("1.43.11 to 1.43.12", decision.reason)
        rebuilt = self.repo.commit({"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.11@sha256:" + "3" * 64)})
        self.assertEqual(self.evaluate(rebuilt).kind, "eligible")
        self.assertNotEqual(bump, rebuilt)

    def test_anything_beyond_the_1_43_base_line_is_blocked(self):
        cases = {
            "other Dockerfile line": {"deploy/Dockerfile": dockerfile(
                "FROM mediawiki:1.43.12@sha256:" + "2" * 64, "COPY deploy/new.php /var/www/html/new.php\n")},
            "other deploy file": {"deploy/LocalSettings.template.php": "<?php // changed\n"},
            "minor upgrade": {"deploy/Dockerfile": dockerfile("FROM mediawiki:1.44.0@sha256:" + "2" * 64)},
            "downgrade": {"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.10@sha256:" + "2" * 64)},
            "unpinned base": {"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.12")},
        }
        for name, files in cases.items():
            with self.subTest(name):
                self.repo.git("reset", "--quiet", "--hard", self.live)
                candidate = self.repo.commit(files, at=1_800_200_000)
                decision = self.evaluate(candidate)
                self.assertEqual((decision.kind, decision.since), ("blocked", 1_800_200_000))

    def test_stall_clock_starts_when_deploy_last_diverged_from_the_live_tree(self):
        # The live revision reaches main by merge commit long before the next bump.
        self.repo.git("checkout", "--quiet", "-b", "pr")
        live = self.repo.commit({"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.12@sha256:" + "2" * 64)})
        self.repo.git("checkout", "--quiet", "main")
        self.repo.clock = 1_800_300_000
        self.repo.git("merge", "--quiet", "--no-ff", "-m", "merge", "pr")
        bump = self.repo.commit({"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.13@sha256:" + "3" * 64)},
                                at=1_800_900_000)
        decision = release.evaluate(self.repo.path, live, bump, 42)
        self.assertEqual((decision.kind, decision.since), ("eligible", 1_800_900_000))
        # Nor does a reverted deploy/ change age a later bump.
        self.repo.commit({"deploy/LocalSettings.template.php": "<?php // x\n"}, at=1_801_000_000)
        self.repo.commit({"deploy/LocalSettings.template.php": "<?php\n"}, at=1_801_100_000)
        later = self.repo.commit({"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.13@sha256:" + "4" * 64)},
                                 at=1_801_200_000)
        decision = release.evaluate(self.repo.path, live, later, 42)
        self.assertEqual((decision.kind, decision.since), ("eligible", 1_800_900_000))
        decision = release.evaluate(self.repo.path, bump, later, 42)
        self.assertEqual((decision.kind, decision.since), ("eligible", 1_801_200_000))

    def test_live_revision_off_main_is_blocked_since_the_live_build(self):
        self.repo.git("checkout", "--quiet", "-b", "pr")
        pr_head = self.repo.commit({"deploy/Dockerfile": dockerfile("FROM mediawiki:1.43.12@sha256:" + "2" * 64)})
        self.repo.git("checkout", "--quiet", "main")
        main = self.repo.commit({"content/Items.wiki": "edit"})
        decision = release.evaluate(self.repo.path, pr_head, main, 42)
        self.assertEqual((decision.kind, decision.since), ("blocked", 42))
        decision = release.evaluate(self.repo.path, "f" * 40, main, 42)
        self.assertEqual((decision.kind, decision.since), ("blocked", 42))

    def test_dockerfile_reading_outside_deploy_is_blocked(self):
        self.live = self.repo.commit({"deploy/Dockerfile": dockerfile(extra="COPY content/ /var/www/html/content/\n")})
        candidate = self.repo.commit({"deploy/Dockerfile": dockerfile(
            "FROM mediawiki:1.43.12@sha256:" + "2" * 64, "COPY content/ /var/www/html/content/\n")})
        decision = self.evaluate(candidate)
        self.assertEqual(decision.kind, "blocked")
        self.assertIn("outside deploy/", decision.reason)

    def test_clone_main_reads_the_remote_branch_head(self):
        head = self.repo.commit({"content/Items.wiki": "edit"})
        self.assertEqual(release.image_input(self.repo.path, head), release.image_input(self.repo.path, self.live))
        self.assertIsNone(release.image_input(self.repo.path, "f" * 40))
        with tempfile.TemporaryDirectory() as workspace, \
                patch.object(release, "REPOSITORY", str(self.repo.path)):
            repo, candidate = release.clone_main(Path(workspace))
            self.assertEqual(candidate, head)
            self.assertEqual(release.evaluate(repo, self.live, candidate, 0).kind, "current")


class ImageHelperTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.docker = FakeDocker()
        self.commands = []
        self.objects = {}
        self.outputs = {}
        self.stack.enter_context(patch.object(release, "run", side_effect=self.fake_run))
        self.stack.enter_context(patch.object(release, "inspect", side_effect=lambda name, **kw: self.objects[name]))

    def fake_run(self, *args, **kwargs):
        self.commands.append(args)
        handled = self.docker.handle(args)
        if handled is not None:
            return handled
        if args[:2] == ("docker", "run"):
            return self.outputs[args[args.index("--entrypoint") + 2]]
        if args[:3] == ("docker", "image", "ls"):
            return "\n".join(f"{tag.split(':')[1]} {image}" for tag, image in self.docker.tags.items())
        if args[:3] == ("docker", "image", "rm"):
            if args[3] == "mirklurk-wiki:auto-busy":
                raise release.ReleaseError("docker image failed")
            del self.docker.tags[args[3]]
            return ""
        return REAL_RUN(*args, **kwargs)

    def test_schema_fingerprint_detects_changes_and_rejects_incomplete_output(self):
        updater = "includes/installer/MysqlUpdater.php"
        base = f"{'1' * 64}  {updater}\n{'2' * 64}  extensions/Echo/sql/echo.json\n"
        self.outputs = {PREVIOUS: base, IMAGE: base}
        self.assertEqual(release.schema_changes(PREVIOUS, IMAGE), [])
        self.outputs[IMAGE] = base.replace("2" * 64, "3" * 64) + f"{'4' * 64}  maintenance/archives/patch-new.sql\n"
        self.assertEqual(release.schema_changes(PREVIOUS, IMAGE),
                         ["extensions/Echo/sql/echo.json", "maintenance/archives/patch-new.sql"])
        run = next(call for call in self.commands if call[:2] == ("docker", "run"))
        for flag in ("--rm", "--read-only", "--network", "none", "--pull", "never", "--cap-drop", "ALL"):
            self.assertIn(flag, run)
        self.outputs[IMAGE] = f"{'2' * 64}  extensions/Echo/sql/echo.json\n"
        with self.assertRaisesRegex(release.ReleaseError, "incomplete"):
            release.schema_changes(PREVIOUS, IMAGE)
        self.outputs[IMAGE] = "find: permission denied\n"
        with self.assertRaisesRegex(release.ReleaseError, "Unexpected"):
            release.schema_changes(PREVIOUS, IMAGE)

    def test_retention_only_drops_old_unprotected_automatic_builds(self):
        created = {}
        for index in range(6):
            image = f"sha256:{index:064d}"
            self.docker.tags[f"mirklurk-wiki:auto-{index:012d}"] = image
            created[image] = f"2026-10-{10 + index:02d}T00:00:00Z"
        self.docker.tags.update({"mirklurk-wiki:auto-busy": "sha256:" + "9" * 64,
                                 "mirklurk-wiki:release-81e73d29a21b": "sha256:" + "8" * 64,
                                 release.LIVE_TAG: f"sha256:{5:064d}", release.PREVIOUS_TAG: f"sha256:{0:064d}"})
        created["sha256:" + "9" * 64] = "2026-10-01T00:00:00Z"
        self.objects = {image: {"Created": stamp} for image, stamp in created.items()}
        release.retain()
        remaining = sorted(tag for tag in self.docker.tags if tag.startswith("mirklurk-wiki:auto-"))
        self.assertEqual(remaining, ["mirklurk-wiki:auto-000000000000", "mirklurk-wiki:auto-000000000003",
                                     "mirklurk-wiki:auto-000000000004", "mirklurk-wiki:auto-000000000005",
                                     "mirklurk-wiki:auto-busy"])
        self.assertIn("mirklurk-wiki:release-81e73d29a21b", self.docker.tags)

    def test_build_uses_exact_clean_source_reuses_tag_and_alerts_on_failure(self):
        with tempfile.TemporaryDirectory() as path:
            repo = GitRepo(Path(path))
            candidate = repo.commit({"deploy/Dockerfile": dockerfile()})
            tag = f"mirklurk-wiki:auto-{candidate[:12]}"
            labels = {release.SOURCE_LABEL: release.SOURCE, release.REVISION_LABEL: candidate}
            self.objects[IMAGE] = {"Config": {"Labels": labels}}
            builds = []

            def docker_build(status):
                def handler(command, **kwargs):
                    if list(command[:2]) != ["docker", "build"]:
                        return REAL_SUBPROCESS_RUN(command, **kwargs)
                    builds.append(command)
                    self.assertEqual(command[-1], str(repo.path))
                    # docker build resolves --file against the caller's cwd, not the context.
                    self.assertEqual(command[command.index("--file") + 1], str(repo.path / "deploy/Dockerfile"))
                    self.assertIn(f"{release.REVISION_LABEL}={candidate}", command)
                    self.assertEqual(REAL_SUBPROCESS_RUN(["git", "-C", str(repo.path), "rev-parse", "HEAD"],
                                                         capture_output=True, text=True).stdout.strip(), candidate)
                    if status == 0:
                        self.docker.tags[tag] = IMAGE
                    return subprocess.CompletedProcess(command, status)
                return handler
            with patch.object(release.subprocess, "run", side_effect=docker_build(0)):
                self.assertEqual(release.build(repo.path, candidate), IMAGE)
                self.assertEqual(release.build(repo.path, candidate), IMAGE)
            self.assertEqual(len(builds), 1)
            labels[release.REVISION_LABEL] = "0" * 40
            with self.assertRaisesRegex(release.ReleaseError, "provenance"):
                release.build(repo.path, candidate)
            del self.docker.tags[tag]
            builds.clear()
            with patch.object(release.subprocess, "run", side_effect=docker_build(1)), \
                    patch.object(release.time, "sleep"):
                with self.assertRaisesRegex(release.ReleaseError, "docker build failed"):
                    release.build(repo.path, candidate)
            self.assertEqual(len(builds), 2)

    def test_required_ci_checks_use_the_latest_run_of_each(self):
        def response(runs):
            body = json.dumps({"check_runs": runs}).encode()
            return patch.object(release, "urlopen", return_value=nullcontext(SimpleNamespace(
                read=lambda *a: body)))

        def check(name, conclusion, identifier):
            return {"name": name, "conclusion": conclusion, "id": identifier}
        passing = [check("publication", "success", 1), check("docker-smoke", "success", 2), check("publish", None, 3)]
        with response(passing):
            self.assertTrue(release.checks_passed(SOURCE))
        with response(passing + [check("docker-smoke", "failure", 9)]):
            self.assertFalse(release.checks_passed(SOURCE))
        with response(passing[:1]):
            self.assertFalse(release.checks_passed(SOURCE))
        with patch.object(release, "urlopen", side_effect=release.URLError("offline")):
            with self.assertRaisesRegex(release.ReleaseError, "CI results"):
                release.checks_passed(SOURCE)


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        lock = self.state / "compose.lock"
        lock.touch()
        self.stack.enter_context(patch.object(release, "AUTO_STATE", self.state))
        self.stack.enter_context(patch.object(release, "LOCK", lock))
        self.stack.enter_context(patch.object(release.os, "geteuid", return_value=0))
        self.docker = FakeDocker()
        self.commands = []
        self.live = {"Image": PREVIOUS}
        self.objects = {
            "mirklurk": self.live,
            PREVIOUS: {"Created": "2026-10-21T18:27:11.123456789Z", "Config": {
                "Env": runtime_env("1.43.11", "8.3.36"),
                "Labels": {release.SOURCE_LABEL: release.SOURCE, release.REVISION_LABEL: LIVE_SOURCE}}},
            IMAGE: {"Config": {"Env": runtime_env("1.43.12", "8.3.37"),
                               "Labels": {release.SOURCE_LABEL: release.SOURCE, release.REVISION_LABEL: SOURCE}}},
        }
        self.stack.enter_context(patch.object(release, "inspect", side_effect=lambda name, **kw: self.objects[name]))
        self.stack.enter_context(patch.object(release, "run", side_effect=self.fake_run))
        self.clone = self.stack.enter_context(patch.object(
            release, "clone_main", side_effect=lambda workspace: (workspace / "source", SOURCE)))
        self.decision = release.Decision(
            "eligible", time.time() - 3600, "MediaWiki base 1.43.11 to 1.43.12",
            "FROM mediawiki:1.43.12@sha256:" + "2" * 64)
        self.evaluate = self.stack.enter_context(patch.object(
            release, "evaluate", side_effect=lambda *a: self.decision))
        self.checks = self.stack.enter_context(patch.object(release, "checks_passed", return_value=True))
        self.build = self.stack.enter_context(patch.object(release, "build", return_value=IMAGE))
        self.schema = self.stack.enter_context(patch.object(release, "schema_changes", return_value=[]))
        self.preflight = self.stack.enter_context(patch.object(
            release, "preflight", return_value=(self.live, {"MW_SERVER_URL": release.ORIGIN}, "1.43.12")))
        self.activate = self.stack.enter_context(patch.object(release, "activate", side_effect=self.fake_activate))
        self.activation_error = None
        self.backup_error = None

    def fake_run(self, *args, **kwargs):
        self.commands.append(args)
        handled = self.docker.handle(args)
        return "" if handled is None else handled

    def fake_activate(self, root, live, environment, image, mediawiki, on_activation=None):
        if self.backup_error:
            raise self.backup_error
        on_activation()
        self.assertTrue((self.state / "hold").exists())
        if self.activation_error:
            raise self.activation_error
        self.docker.tags[release.LIVE_TAG] = image
        self.live["Image"] = image

    def status(self):
        return json.loads((self.state / "status.json").read_text())

    def test_eligible_base_update_deploys_unattended_and_is_recorded(self):
        release.auto_update()
        self.preflight.assert_called_once_with(release.CANONICAL, SOURCE, IMAGE, PREVIOUS)
        self.assertEqual(self.activate.call_args.args[3:5], (IMAGE, "1.43.12"))
        self.assertFalse((self.state / "hold").exists())
        entry = json.loads((self.state / "history.jsonl").read_text())
        self.assertEqual((entry["kind"], entry["source"], entry["image"], entry["previous"]),
                         ("automatic", SOURCE, IMAGE, PREVIOUS))
        self.assertEqual((self.status()["outcome"], self.status()["decision"]), ("ok", "eligible"))
        self.schema.assert_called_once_with(PREVIOUS, IMAGE)
        self.assertEqual(list(self.state.glob("mirklurk-wiki-*")), [])

    def test_current_main_only_adopts_the_running_image_as_the_live_tag(self):
        self.decision = release.Decision("current", None, "the live wiki runs mirklurk-wiki main", None)
        release.auto_update()
        self.assertEqual(self.docker.tags, {release.LIVE_TAG: PREVIOUS})
        self.build.assert_not_called()
        self.activate.assert_not_called()
        self.assertEqual(self.status()["outcome"], "ok")

    def test_blocked_and_waiting_updates_alert_only_when_stalled(self):
        for kind, days, prepare in (("blocked", release.BLOCKED_STALL_DAYS, lambda: None),
                                    ("eligible", release.ELIGIBLE_STALL_DAYS,
                                     lambda: setattr(self.checks, "return_value", False))):
            with self.subTest(kind):
                prepare()
                self.decision = self.decision._replace(kind=kind, since=time.time() - (days - 0.5) * 86400)
                release.auto_update()
                self.decision = self.decision._replace(since=time.time() - (days + 0.5) * 86400)
                with self.assertRaisesRegex(release.ReleaseError, "stalled"):
                    release.auto_update()
                self.assertIn("stalled", self.status()["outcome"])
        self.build.assert_not_called()
        self.activate.assert_not_called()

    def test_schema_change_vulnerable_or_downgrading_candidate_alerts_without_activation(self):
        self.schema.return_value = ["maintenance/archives/patch-new.sql"]
        with self.assertRaisesRegex(release.ReleaseError, "update.php"):
            release.auto_update()
        self.schema.return_value = []
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.12", "8.3.33")
        with self.assertRaisesRegex(release.ReleaseError, "PHP2Shell"):
            release.auto_update()
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.10", "8.3.37")
        self.decision = self.decision._replace(base="FROM mediawiki:1.43.10@sha256:" + "2" * 64)
        with self.assertRaisesRegex(release.ReleaseError, "downgrade"):
            release.auto_update()
        self.objects[IMAGE]["Config"]["Env"] = runtime_env("1.43.12", "8.3.37")
        self.decision = self.decision._replace(base="FROM mediawiki:1.43.13@sha256:" + "2" * 64)
        with self.assertRaisesRegex(release.ReleaseError, "does not match"):
            release.auto_update()
        self.activate.assert_not_called()
        self.assertFalse((self.state / "hold").exists())

    def test_build_or_pre_activation_failure_alerts_without_holding(self):
        self.build.side_effect = release.ReleaseError("docker build failed")
        with self.assertRaisesRegex(release.ReleaseError, "build failed"):
            release.auto_update()
        self.build.side_effect = None
        self.backup_error = release.ReleaseError("backup failed")
        with self.assertRaisesRegex(release.ReleaseError, "backup failed"):
            release.auto_update()
        self.assertFalse((self.state / "hold").exists())
        self.backup_error = None
        release.auto_update()

    def test_failed_activation_holds_and_later_runs_alert_before_doing_anything(self):
        self.activation_error = release.ReleaseError("Responsive viewport missing")
        with self.assertRaisesRegex(release.ReleaseError, "viewport"):
            release.auto_update()
        hold = json.loads((self.state / "hold").read_text())
        self.assertIn("viewport", hold["reason"])
        self.assertEqual((hold["source"], hold["image"], hold["previous"]), (SOURCE, IMAGE, PREVIOUS))
        self.assertFalse((self.state / "history.jsonl").exists())
        self.clone.reset_mock()
        with self.assertRaisesRegex(release.ReleaseError, "held"):
            release.auto_update()
        self.clone.assert_not_called()
        self.assertEqual(self.activate.call_count, 1)

    def test_interrupted_activation_keeps_the_hold(self):
        self.activation_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            release.auto_update()
        self.assertIn("unexpected KeyboardInterrupt", (self.state / "hold").read_text())

    def test_failed_candidate_is_not_retried_after_the_hold_is_cleared(self):
        inputs = {SOURCE: "deploy-tree-1", "d" * 40: "deploy-tree-1", "f" * 40: "deploy-tree-2"}
        self.stack.enter_context(patch.object(release, "image_input", side_effect=lambda repo, rev: inputs.get(rev)))
        self.activation_error = release.ReleaseError("Responsive viewport missing")
        with self.assertRaises(release.ReleaseError):
            release.auto_update()
        self.assertEqual((self.state / "rejected").read_text().split(), [SOURCE])
        (self.state / "hold").unlink()
        self.activation_error = None
        release.auto_update()
        self.assertEqual(self.activate.call_count, 1)
        self.assertEqual((self.status()["decision"], self.status()["outcome"]), ("blocked", "ok"))
        # A later content-only commit builds the same image input: still blocked.
        self.clone.side_effect = lambda workspace: (workspace / "source", "d" * 40)
        release.auto_update()
        self.assertEqual((self.activate.call_count, self.status()["decision"]), (1, "blocked"))
        self.decision = self.decision._replace(since=time.time() - 8 * 86400)
        with self.assertRaisesRegex(release.ReleaseError, "activation failed"):
            release.auto_update()
        # A new deploy/ input is eligible again.
        self.decision = self.decision._replace(since=time.time() - 3600)
        self.clone.side_effect = lambda workspace: (workspace / "source", "f" * 40)
        release.auto_update()
        self.assertEqual(self.activate.call_count, 2)

    def test_deployment_hold_appearing_mid_run_stops_activation_quietly(self):
        hold = self.state / "deployment-hold"
        hold.write_text("attended maintenance")
        with patch.object(release, "DEPLOYMENT_HOLD", hold):
            release.auto_update()
        self.preflight.assert_not_called()
        self.activate.assert_not_called()

    def test_moved_tag_or_missing_provenance_refuses_before_fetching(self):
        self.docker.tags[release.LIVE_TAG] = IMAGE
        with self.assertRaisesRegex(release.ReleaseError, "does not name the running"):
            release.auto_update()
        self.docker.tags.clear()
        del self.objects[PREVIOUS]["Config"]["Labels"][release.REVISION_LABEL]
        with self.assertRaisesRegex(release.ReleaseError, "revision labels"):
            release.auto_update()
        self.clone.assert_not_called()

    def test_identical_rebuild_is_a_quiet_no_op(self):
        self.build.return_value = PREVIOUS
        release.auto_update()
        self.schema.assert_not_called()
        self.activate.assert_not_called()
        self.assertEqual(self.status()["outcome"], "ok")

    def test_live_change_during_build_aborts_before_activation(self):
        def changed(*args):
            self.live["Image"] = "sha256:" + "0" * 64
            return IMAGE
        self.build.side_effect = changed
        with self.assertRaisesRegex(release.ReleaseError, "changed while"):
            release.auto_update()
        self.activate.assert_not_called()

    def test_dry_run_preflights_but_never_changes_tags_state_or_containers(self):
        release.auto_update(dry_run=True)
        self.preflight.assert_called_once_with(release.CANONICAL, SOURCE, IMAGE, PREVIOUS)
        self.activate.assert_not_called()
        self.assertEqual(self.docker.tags, {})
        self.assertEqual(sorted(path.name for path in self.state.iterdir()), ["compose.lock"])
        (self.state / "hold").write_text("operator investigating")
        release.auto_update(dry_run=True)

    def test_unattended_mode_requires_root(self):
        with patch.object(release.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(release.ReleaseError, "as root"):
                release.auto_update()
            release.auto_update(dry_run=True)


if __name__ == "__main__":
    unittest.main()
