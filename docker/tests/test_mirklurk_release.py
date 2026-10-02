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
SPEC = importlib.util.spec_from_file_location("release", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
REAL_RUN = release.run
REAL_HEADROOM = release.headroom
IMAGE = "sha256:" + "a" * 64
PREVIOUS = "sha256:" + "b" * 64
SOURCE = "c" * 40


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
                    "image": IMAGE, "pull_policy": "never",
                    "command": None, "entrypoint": None,
                    "labels": {"org.opencontainers.image.revision": SOURCE},
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
            IMAGE: {"Id": IMAGE, "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE,
                                                      "org.opencontainers.image.source": release.SOURCE}}},
            PREVIOUS: {"Id": PREVIOUS, "Config": {"Labels": {"org.opencontainers.image.source": release.SOURCE}}},
            "mirklurk": self.live,
            "mirklurk-db": {"State": state, "Config": {"Image": "pinned-database"}},
            "mirklurk-backup": {"State": state, "Config": {"Image": "pinned-database"}},
        }
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
                            for command in self.commands))

    def test_relative_secret_target_normalizes_without_changing_mount(self):
        self.config["services"]["mirklurk"]["secrets"][0]["target"] = "PASSWORD"
        self.preflight()

    def test_wrong_source_and_image_provenance_fail_closed(self):
        self.config["services"]["mirklurk"]["labels"]["org.opencontainers.image.revision"] = "0" * 40
        with self.assertRaisesRegex(release.ReleaseError, "Source SHA"):
            self.preflight()
        self.config["services"]["mirklurk"]["labels"]["org.opencontainers.image.revision"] = SOURCE
        self.objects[IMAGE]["Config"]["Labels"]["org.opencontainers.image.source"] = "wrong"
        with self.assertRaisesRegex(release.ReleaseError, "provenance"):
            self.preflight()

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
        self.config = original
        self.live["Image"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(release.ReleaseError, "neither expected"):
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
        up = ("compose", "up", "-d", "--no-deps", "--no-build", "--pull", "never", "mirklurk")
        self.assertEqual(self.commands.count(up), 1)
        backup = next(i for i, call in enumerate(self.commands) if "--once" in call)
        self.assertLess(backup, self.commands.index(up))
        self.assertTrue(any("pull" in call and "--ff-only" in call for call in self.commands))
        release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        self.assertEqual(self.commands.count(up), 1)
        self.assertEqual(sum("--once" in call for call in self.commands), 1)
        self.assertEqual(self.backups_mock.call_count, 1)
        self.assertEqual(acceptance.call_count, 2)
        self.assertEqual(refresh.call_count, 2)
        self.assertFalse(any("start" in call or "stop" in call or "--remove-orphans" in call for call in self.commands))

    def test_running_updater_or_wrong_checkout_blocks_before_pull(self):
        self.deploy_mocks()
        with self.assertRaisesRegex(release.ReleaseError, "only allowed"):
            release.deploy(Path("/wrong"), SOURCE, IMAGE, PREVIOUS)
        self.run_mock.side_effect = lambda *args, **kw: "active"
        with self.assertRaisesRegex(release.ReleaseError, "must be inactive"):
            release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        self.assertFalse(any("pull" in call for call in self.commands))

    def test_backup_failure_does_not_activate(self):
        self.deploy_mocks()
        self.backups_mock.side_effect = release.ReleaseError("backup failed")
        with self.assertRaisesRegex(release.ReleaseError, "backup failed"):
            release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        self.assertFalse(any("up" in call for call in self.commands))

    def test_acceptance_failure_does_not_rollback_or_resume_timer(self):
        acceptance, refresh = self.deploy_mocks()
        acceptance.side_effect = release.ReleaseError("metadata failed")
        with self.assertRaisesRegex(release.ReleaseError, "metadata failed"):
            release.deploy(self.root, SOURCE, IMAGE, PREVIOUS)
        refresh.assert_not_called()
        self.assertEqual(sum("up" in call for call in self.commands), 1)
        self.assertFalse(any("start" in call for call in self.commands))

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
        if "--once" in args:
            self.assertFalse(self.live["State"]["Running"])
            if self.failure == "dump":
                raise release.ReleaseError("dump failed")
            (self.root / "backups/daily/mirklurk-2026-10-02.sql.gz").write_bytes(gzip.compress(self.sql))
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


if __name__ == "__main__":
    unittest.main()
