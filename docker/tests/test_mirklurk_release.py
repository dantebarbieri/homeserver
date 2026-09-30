from contextlib import ExitStack, nullcontext
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
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
                    "read_only": name == "branding", "bind": {"create_host_path": False}}
                   for name, target in (("images", "/var/www/html/images"), ("branding", "/var/www/html/branding"),
                                        ("sitemap", release.SITEMAP))]
        for name in ("images", "branding", "sitemap", "sitemap/public"):
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

        def directory_stat(path, **kwargs):
            result = real_stat(path, **kwargs)
            if path in (self.root / "sitemap", self.root / "sitemap/public"):
                import os
                fields = list(result)
                fields[4] = fields[5] = 33
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
        def fail_backup(*args, **kwargs):
            if "--once" in args:
                raise release.ReleaseError("backup failed")
            return self.fake_run(*args, **kwargs)
        self.run_mock.side_effect = fail_backup
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


if __name__ == "__main__":
    unittest.main()
