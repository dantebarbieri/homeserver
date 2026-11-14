import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "map_isolated", Path(__file__).resolve().parents[1] / "scripts/mirklurk-map-isolated.py")
isolated = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(isolated)


class IsolatedPeerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.canonical = self.root / "canonical"
        self.source = self.root / "source"
        self.canonical.mkdir()
        self.git(self.canonical, "init", "--quiet", "--initial-branch=main")
        self.git(self.canonical, "config", "user.name", "Test")
        self.git(self.canonical, "config", "user.email", "test@example.invalid")
        self.git(self.canonical, "config", "core.autocrlf", "false")
        for name in isolated.PRESERVED + ("docker/nginx/mirklurk-map.conf",
                                          "docker/scripts/mirklurk-map-isolated.py"):
            p = self.canonical / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("tracked\n")
        self.config = "set_real_ip_from 192.168.128.23;\nset_real_ip_from fd2b:92df:1a5b:1::17;\n"
        (self.canonical / "docker/nginx/mirklurk-map.conf").write_text(self.config)
        self.git(self.canonical, "add", ".")
        self.git(self.canonical, "commit", "--quiet", "-m", "base")
        self.base = self.git(self.canonical, "rev-parse", "HEAD")
        self.git(self.root, "clone", "--quiet", str(self.canonical), str(self.source))
        self.git(self.source, "config", "user.name", "Test")
        self.git(self.source, "config", "user.email", "test@example.invalid")
        self.git(self.source, "config", "core.autocrlf", "false")
        (self.source / "docker/nginx/mirklurk-map.conf").write_text(
            self.config.replace(".23;", ".36;").replace("::17;", "::24;"))
        self.git(self.source, "commit", "--quiet", "-am", "exact peer")
        self.revision = self.git(self.source, "rev-parse", "HEAD")
        for name in isolated.PRESERVED:
            (self.canonical / name).write_text("operator edit\n")

    def cleanup(self):
        # Windows may retain Git pack-process handles briefly after git exits.
        for attempt in range(6):
            try:
                self.temp.cleanup()
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.2)

    @staticmethod
    def git(root, *args):
        p = subprocess.run(["git", "-c", "maintenance.auto=false", "-c", "gc.auto=0",
                            "-C", str(root), *args], capture_output=True, text=True)
        if p.returncode:
            raise AssertionError(p.stderr)
        return p.stdout.strip()

    def source_guard(self):
        with patch.object(isolated, "__file__", str(self.source / "docker/scripts/mirklurk-map-isolated.py")):
            isolated.source_guard(self.source, self.canonical, self.base, self.revision)

    def test_exact_clean_clone_can_fast_forward_without_touching_edit_identities(self):
        before = isolated.state(self.canonical)
        self.source_guard()
        isolated.config_guard(self.canonical, self.source, "192.168.128.36", "fd2b:92df:1a5b:1::24")
        self.git(self.canonical, "fetch", "--quiet", str(self.source), self.revision)
        self.git(self.canonical, "merge", "--ff-only", self.revision)
        isolated.same_edits(self.canonical, before)
        self.assertEqual(self.git(self.canonical, "rev-parse", "HEAD"), self.revision)

    def test_extra_or_staged_canonical_edits_fail_closed(self):
        self.git(self.canonical, "config", "status.showUntrackedFiles", "no")
        (self.canonical / "extra").write_text("unexpected")
        with self.assertRaisesRegex(RuntimeError, "exactly the two"):
            isolated.state(self.canonical)
        (self.canonical / "extra").unlink()
        self.git(self.canonical, "add", isolated.PRESERVED[0])
        with self.assertRaisesRegex(RuntimeError, "exactly the two"):
            isolated.state(self.canonical)

    def test_same_bytes_replaced_inode_and_changed_bytes_are_rejected(self):
        expected = isolated.state(self.canonical)
        name = self.canonical / isolated.PRESERVED[0]
        replacement = name.with_suffix(".replacement")
        replacement.write_bytes(name.read_bytes())
        replacement.replace(name)
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            isolated.same_edits(self.canonical, expected)
        expected = isolated.state(self.canonical)
        name.write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            isolated.same_edits(self.canonical, expected)

    def test_upstream_touching_preserved_path_or_compose_is_rejected(self):
        (self.source / isolated.PRESERVED[0]).write_text("conflict")
        self.git(self.source, "commit", "--quiet", "-am", "conflict")
        self.revision = self.git(self.source, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "scope"):
            self.source_guard()

    def test_reverted_upstream_edit_is_still_a_preservation_conflict(self):
        name = self.source / isolated.PRESERVED[0]
        name.write_text("intermediate change")
        self.git(self.source, "commit", "--quiet", "-am", "touch edit")
        name.write_text("tracked\n")
        self.git(self.source, "commit", "--quiet", "-am", "revert edit")
        self.revision = self.git(self.source, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "history touches"):
            self.source_guard()

    def test_merged_touch_and_revert_branch_is_a_preservation_conflict(self):
        self.git(self.source, "checkout", "--quiet", "-b", "side")
        name = self.source / isolated.PRESERVED[0]
        name.write_text("side branch touch")
        self.git(self.source, "commit", "--quiet", "-am", "touch")
        name.write_text("tracked\n")
        self.git(self.source, "commit", "--quiet", "-am", "revert")
        self.git(self.source, "checkout", "--quiet", "main")
        self.git(self.source, "merge", "--quiet", "--no-ff", "-m", "merge", "side")
        self.revision = self.git(self.source, "rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "history touches"):
            self.source_guard()

    def test_ignored_or_untracked_candidate_files_and_wrong_sha_are_rejected(self):
        (self.source / ".env").write_text("unexpected")
        with self.assertRaisesRegex(RuntimeError, "wholly clean"):
            self.source_guard()
        (self.source / ".env").unlink()
        self.revision = self.base
        with self.assertRaisesRegex(RuntimeError, "exact reviewed revision"):
            self.source_guard()

    def test_config_rejects_subnet_extra_peer_or_unrelated_change(self):
        path = self.source / "docker/nginx/mirklurk-map.conf"
        path.write_text(self.config + "set_real_ip_from 10.0.0.0/8;\n")
        with self.assertRaisesRegex(RuntimeError, "Exactly two"):
            isolated.config_guard(self.canonical, self.source, "192.168.128.36", "fd2b:92df:1a5b:1::24")
        path.write_text(self.config.replace(".23;", ".36;").replace("::17;", "::24;") + "# unrelated\n")
        with self.assertRaisesRegex(RuntimeError, "more than"):
            isolated.config_guard(self.canonical, self.source, "192.168.128.36", "fd2b:92df:1a5b:1::24")

    def models(self):
        volume = {"type": "bind", "source": str(self.canonical / "docker/nginx/mirklurk-map.conf"),
                  "target": "/etc/nginx/conf.d/default.conf", "read_only": True,
                  "bind": {"create_host_path": False}}
        live = {"name": "compose", "services": {
            "mirklurk-map": {"volumes": [volume], "networks": {"proxy": {}},
                             "depends_on": {"mirklurk-map-uploads": {}}},
            "mirklurk-map-uploads": {"volumes": [{"type": "volume", "source": "shares"}]}},
            "networks": {"proxy": {"name": "compose_proxy"}},
            "volumes": {"shares": {"name": "compose_shares"}}}
        clean = copy.deepcopy(live)
        clean["services"]["mirklurk-map"]["volumes"][0]["source"] = str(
            self.source / "docker/nginx/mirklurk-map.conf")
        return clean, live

    def test_model_rebases_only_source_paths_and_preserves_project_volume_and_bind(self):
        clean, live = self.models()
        isolated.models_guard(clean, live, self.source, self.canonical)
        live["volumes"]["shares"]["name"] = "duplicate_shares"
        with self.assertRaisesRegex(RuntimeError, "identity differs"):
            isolated.models_guard(clean, live, self.source, self.canonical)

    def test_model_rejects_unrelated_dependency_and_dirty_path_bind_overlap(self):
        clean, live = self.models()
        for model in (clean, live):
            model["services"]["mirklurk-map"]["depends_on"]["homepage"] = {}
        with self.assertRaisesRegex(RuntimeError, "dependency outside"):
            isolated.models_guard(clean, live, self.source, self.canonical)
        clean, live = self.models()
        for model in (clean, live):
            model["services"]["mirklurk-map-uploads"]["volumes"] = [
                {"type": "bind", "source": str(self.canonical / "homepage"), "target": "/unexpected"}]
        with self.assertRaisesRegex(RuntimeError, "overlaps"):
            isolated.models_guard(clean, live, self.source, self.canonical)
        clean, live = self.models()
        for model in (clean, live):
            model["services"]["mirklurk-map"]["env_file"] = [{"path": "/unexpected", "required": True}]
        with self.assertRaisesRegex(RuntimeError, "environment-file"):
            isolated.models_guard(clean, live, self.source, self.canonical)

    def test_render_keeps_unrelated_service_env_files_unresolved(self):
        import json
        clean, _ = self.models()
        with patch.object(isolated, "command", return_value=json.dumps(clean).encode()) as call:
            isolated.model(self.source, self.canonical)
        self.assertIn("--no-env-resolution", call.call_args.args)
        self.assertIn(str(self.canonical / "docker/.env"), call.call_args.args)

    def test_real_compose_renders_a_clone_without_unrelated_required_env_file(self):
        import shutil
        if not shutil.which("docker"):
            self.skipTest("Docker Compose CLI unavailable")
        probe = subprocess.run(["docker", "compose", "version"], capture_output=True)
        if probe.returncode:
            self.skipTest("Docker Compose plugin unavailable")
        docker = self.source / "docker"
        (self.canonical / "docker/.env").write_text("TEST_VALUE=canonical\n")
        (docker / "docker-compose.yml").write_text(
            "name: compose\ninclude:\n  - category.yml\n")
        (docker / "category.yml").write_text(
            "services:\n  unrelated:\n    image: alpine\n    env_file: .env\n"
            "  mirklurk-map:\n    image: alpine\n    environment:\n      VALUE: ${TEST_VALUE}\n")
        data = isolated.model(self.source, self.canonical)
        self.assertEqual(data["services"]["mirklurk-map"]["environment"]["VALUE"], "canonical")
        self.assertFalse((docker / ".env").exists())

    def test_prepare_and_verify_mode_keep_edits_and_verify_mode_never_mutates_git(self):
        self.git(self.canonical, "config", "merge.autoStash", "true")
        expected = isolated.state(self.canonical)
        fingerprints = self.root / "fingerprints.json"
        fingerprints.write_text(json.dumps(expected))
        args = SimpleNamespace(source=self.source, base=self.base, revision=self.revision,
                               edits=fingerprints, proxy_id="a" * 64, ipv4="192.168.128.36",
                               ipv6="fd2b:92df:1a5b:1::24", verify_only=False, review_base=None)
        clean, live = self.models()
        with patch.object(isolated, "CANONICAL", self.canonical), \
                patch.object(isolated, "__file__", str(self.source / "docker/scripts/mirklurk-map-isolated.py")), \
                patch.object(isolated, "lock_guard"), patch.object(isolated, "runtime_guard"), \
                patch.object(isolated, "proxy_guard"), \
                patch.object(isolated, "model", side_effect=lambda root, _: clean if root == self.source else live):
            isolated.prepare(args)
            isolated.same_edits(self.canonical, expected)
            stash = subprocess.run(["git", "-C", str(self.canonical), "rev-parse",
                                    "--verify", "refs/stash"], capture_output=True)
            self.assertNotEqual(stash.returncode, 0)
            args.verify_only = True
            original = isolated.git
            calls = []

            def recorded(root, *values):
                calls.append(values[0])
                return original(root, *values)

            with patch.object(isolated, "git", side_effect=recorded):
                isolated.prepare(args)
            self.assertNotIn("fetch", calls)
            self.assertNotIn("merge", calls)

    def test_pinned_review_base_preserves_prior_reviewed_upstream_without_broadening_candidate_scope(self):
        self.git(self.source, "checkout", "--quiet", "--detach", self.base)
        (self.source / "unrelated.txt").write_text("already reviewed upstream\n")
        self.git(self.source, "add", "unrelated.txt")
        self.git(self.source, "commit", "--quiet", "-m", "upstream")
        review_base = self.git(self.source, "rev-parse", "HEAD")
        (self.source / "docker/nginx/mirklurk-map.conf").write_text(
            self.config.replace(".23;", ".36;").replace("::17;", "::24;"))
        self.git(self.source, "commit", "--quiet", "-am", "candidate peers")
        revision = self.git(self.source, "rev-parse", "HEAD")
        with patch.object(isolated, "__file__", str(self.source / "docker/scripts/mirklurk-map-isolated.py")):
            isolated.source_guard(self.source, self.canonical, self.base, revision, review_base)
            with self.assertRaisesRegex(RuntimeError, "scope"):
                isolated.source_guard(self.source, self.canonical, self.base, revision, self.base)

    def runtime_fixture(self):
        containers = []
        for name, image in zip(isolated.SERVICES, isolated.IMAGES):
            containers.append({
                "Image": image, "Config": {"Labels": {
                    "org.opencontainers.image.revision": isolated.SOURCE,
                    "com.docker.compose.project": "compose", "com.docker.compose.service": name}},
                "State": {"Running": True, "Health": {"Status": "healthy"}}, "Mounts": []})
        containers[0]["Mounts"] = [{"Type": "bind", "RW": False,
                                    "Source": str(isolated.CANONICAL / "docker/nginx/mirklurk-map.conf"),
                                    "Destination": "/etc/nginx/conf.d/default.conf"}]
        volume = {"Name": "compose_mirklurk-map-shares", "Mountpoint": "/volume/_data",
                  "Labels": {"com.docker.compose.project": "compose",
                             "com.docker.compose.volume": "mirklurk-map-shares"}}
        containers[1]["Mounts"] = [{"Type": "volume", "RW": True, "Name": volume["Name"],
                                    "Source": volume["Mountpoint"], "Destination": "/data"}]
        containers.append({
            "Image": "sha256:5d90e74b09219f239bf54ead1371fd82574a4de469b4a01d9a10cb78b8fc473e",
            "Config": {"Labels": {"org.opencontainers.image.revision":
                                  "0111204dd4d8625763c7fec6c57e37357e654333"}},
            "State": {"Running": True, "Health": {"Status": "healthy"}}})
        return containers, volume

    def check_runtime(self, containers, volume, active=False, marker=False):
        def response(*args):
            if args[0] == "systemctl":
                return b"active\n" if active else b"inactive\n"
            if args[:3] == ("docker", "volume", "inspect"):
                return json.dumps([volume]).encode()
            self.assertEqual(args[:2], ("docker", "inspect"))
            return json.dumps(containers).encode()

        with patch.object(isolated, "command", side_effect=response), \
                patch.object(isolated.os.path, "lexists", return_value=marker):
            isolated.runtime_guard()

    def test_runtime_guard_rejects_stopped_targets_wrong_image_storage_and_active_jobs(self):
        containers, volume = self.runtime_fixture()
        self.check_runtime(containers, volume)
        for index in range(3):
            with self.subTest(stopped=index):
                changed = copy.deepcopy(containers)
                changed[index]["State"]["Running"] = False
                with self.assertRaisesRegex(RuntimeError, "stopped"):
                    self.check_runtime(changed, volume)
        changed = copy.deepcopy(containers)
        changed[1]["Image"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(RuntimeError, "source/image changed"):
            self.check_runtime(changed, volume)
        changed = copy.deepcopy(containers)
        changed[1]["Mounts"][0]["Name"] = "wrong_shares"
        with self.assertRaisesRegex(RuntimeError, "storage differs"):
            self.check_runtime(changed, volume)
        with self.assertRaisesRegex(RuntimeError, "Active maintenance"):
            self.check_runtime(containers, volume, active=True)
        with self.assertRaisesRegex(RuntimeError, "hold/marker"):
            self.check_runtime(containers, volume, marker=True)

    def test_proxy_guard_rejects_wrong_owner_for_either_address(self):
        identity = "a" * 64
        ipv4, ipv6 = "192.168.128.36", "fd2b:92df:1a5b:1::24"
        npm = [{"Id": identity, "State": {"Running": True}}]
        good = {"Containers": {identity: {"IPv4Address": ipv4 + "/20", "IPv6Address": ipv6 + "/64"}}}
        with patch.object(isolated, "command", side_effect=[json.dumps(npm).encode(),
                                                          json.dumps([good]).encode()]):
            isolated.proxy_guard(identity, ipv4, ipv6)
        for field in ("IPv4Address", "IPv6Address"):
            changed = copy.deepcopy(good)
            address = changed["Containers"][identity][field]
            changed["Containers"][identity][field] = ""
            changed["Containers"]["b" * 64] = {"IPv4Address": "", "IPv6Address": "", field: address}
            with self.subTest(field=field), patch.object(isolated, "command", side_effect=[
                    json.dumps(npm).encode(), json.dumps([changed]).encode()]):
                with self.assertRaisesRegex(RuntimeError, "exclusive"):
                    isolated.proxy_guard(identity, ipv4, ipv6)

    @unittest.skipIf(os.name == "nt", "Real flock descriptor checks run on Linux")
    def test_lock_guard_uses_existing_descriptor_and_rejects_contention_and_wrong_inode(self):
        import fcntl
        import sys
        lock = self.root / "lock"
        other = self.root / "other"
        lock.touch()
        other.touch()
        script = (
            "import importlib.util,os,pathlib,sys;"
            "s=importlib.util.spec_from_file_location('isolated',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "m.LOCK=pathlib.Path(sys.argv[2]);"
            "fd=os.open(sys.argv[3],os.O_RDONLY);os.dup2(fd,9);m.lock_guard()")

        def child(opened):
            return subprocess.run([sys.executable, "-B", "-c", script,
                                   isolated.__file__, str(lock), str(opened)], capture_output=True)

        self.assertEqual(child(lock).returncode, 0)
        self.assertNotEqual(child(other).returncode, 0)
        with lock.open("rb") as owned:
            fcntl.flock(owned, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(child(lock).returncode, 0)


if __name__ == "__main__":
    unittest.main()
