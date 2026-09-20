import importlib.util
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "adguard_quad9_dot", Path(__file__).parents[1] / "scripts/adguard-quad9-dot.py",
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class Quad9MigrationTests(unittest.TestCase):
    def setUp(self):
        self.config = (
            "dns:\n"
            "  upstream_dns:\n"
            "    - https://cloudflare-dns.com/dns-query\n"
            "    - https://dns.google/dns-query\n"
            "    - https://dns10.quad9.net/dns-query\n"
            "  upstream_mode: load_balance\n"
            "  upstream_timeout: 10s\n"
            "  fallback_dns:\n"
            "    - 9.9.9.9\n"
            "unrelated: unchanged\n"
        )

    def test_changes_only_unfiltered_quad9_transport(self):
        self.assertEqual(
            migration.migrate(self.config),
            self.config.replace(migration.OLD, migration.NEW),
        )

    def test_preserves_quoted_entry(self):
        quoted = self.config.replace(migration.OLD, f'"{migration.OLD}"')
        self.assertEqual(migration.migrate(quoted), quoted.replace(migration.OLD, migration.NEW))

    def test_rejects_missing_duplicate_already_changed_or_wrong_section(self):
        cases = [
            self.config.replace(migration.OLD, migration.NEW),
            self.config.replace(migration.OLD, "https://dns.quad9.net/dns-query"),
            self.config + f"# {migration.OLD}\n",
            self.config.replace("  upstream_dns:", "  fallback_upstreams:"),
            self.config.replace("dns:\n", "unrelated:\n", 1),
            self.config.replace(f"- {migration.OLD}", f"- # {migration.OLD}"),
        ]
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ValueError):
                migration.migrate(config)

    def test_apply_preserves_metadata_and_private_rollback_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "AdGuardHome.yaml"
            config.write_text(self.config)
            config.chmod(0o640)
            before = config.stat()
            with patch("sys.argv", ["migration", "--config", str(config), "--apply"]), \
                    patch.object(migration.subprocess, "check_output", return_value="false\n"), \
                    patch("sys.stdout", new_callable=io.StringIO):
                migration.main()
            self.assertEqual(config.read_text(), migration.migrate(self.config))
            after = config.stat()
            self.assertEqual(
                (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)),
                (before.st_uid, before.st_gid, 0o640),
            )
            backups = list(config.parent.glob("*.pre-quad9-dot.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), self.config)
            self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
            self.assertEqual(len(list(config.parent.iterdir())), 2)

    def test_running_service_is_not_edited(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "AdGuardHome.yaml"
            config.write_text(self.config)
            with patch("sys.argv", ["migration", "--config", str(config), "--apply"]), \
                    patch.object(migration.subprocess, "check_output", return_value="true\n"), \
                    self.assertRaises(RuntimeError):
                migration.main()
            self.assertEqual(config.read_text(), self.config)
            self.assertEqual(len(list(config.parent.iterdir())), 1)

    def test_default_mode_does_not_write_or_inspect_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "AdGuardHome.yaml"
            config.write_text(self.config)
            with patch("sys.argv", ["migration", "--config", str(config)]), \
                    patch.object(migration.subprocess, "check_output") as inspect, \
                    patch("sys.stdout", new_callable=io.StringIO):
                migration.main()
                inspect.assert_not_called()
            self.assertEqual(config.read_text(), self.config)
            self.assertEqual(len(list(config.parent.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
