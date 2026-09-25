import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docker/scripts/mirklurk-backup.sh"
PASSWORD = "private-fixture-not-for-output"
SQL = "CREATE TABLE `page` (`page_id` int);\nINSERT INTO `page` VALUES (1);\n"


class MirklurkBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mirklurk-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.bin = self.workspace / "bin"
        self.bin.mkdir()
        self.backups = self.workspace / "backups"
        self.secret = self.workspace / "password"
        self.secret.write_text(PASSWORD)
        self.call_log = self.workspace / "arguments"
        self.make_executable(
            "mariadb-dump",
            """#!/usr/bin/env bash
set -eu
[[ "$MYSQL_PWD" == private-fixture-not-for-output ]]
printf '%s\\n' "$@" > "$CALL_LOG"
case "${DUMP_MODE:-ok}" in
  fail) echo "simulated connection failure" >&2; exit 42 ;;
  empty) echo "-- empty database" ;;
  *) printf 'CREATE TABLE `page` (`page_id` int);\\nINSERT INTO `page` VALUES (1);\\n' ;;
esac
""",
        )
        self.make_executable(
            "date",
            """#!/usr/bin/env bash
set -eu
case "$*" in
  '-u +%F') echo 2026-09-27 ;;
  '-u +%u') echo "${BACKUP_TEST_WEEKDAY:-7}" ;;
  *) echo "unexpected date arguments" >&2; exit 2 ;;
esac
""",
        )
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "BACKUP_DIR": str(self.backups),
            "MW_DB_SERVER": "mirklurk-db",
            "MW_DB_NAME": "mirklurk",
            "MW_DB_USER": "mirklurk",
            "MW_DB_PASSWORD_FILE": str(self.secret),
            "CALL_LOG": str(self.call_log),
        }
        for name in ("DUMP_MODE", "BACKUP_TEST_WEEKDAY"):
            self.env.pop(name, None)

    def make_executable(self, name, content):
        executable = self.bin / name
        executable.write_text(content)
        executable.chmod(0o755)

    def run_script(self, argument="--once", **overrides):
        result = subprocess.run(
            ["bash", str(SCRIPT), argument],
            env={**self.env, **overrides},
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        return result

    def test_consistent_private_dump_and_weekly_copy(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        for directory in ("daily", "weekly"):
            dump = self.backups / directory / "mirklurk-2026-09-27.sql.gz"
            self.assertEqual(gzip.decompress(dump.read_bytes()).decode(), SQL)
            self.assertEqual(dump.stat().st_mode & 0o777, 0o600)
        arguments = self.call_log.read_text().splitlines()
        self.assertEqual(
            arguments,
            [
                "--host=mirklurk-db", "--port=3306", "--user=mirklurk",
                "--single-transaction", "--quick", "--skip-lock-tables",
                "--no-tablespaces", "--default-character-set=utf8mb4",
                "--hex-blob", "mirklurk",
            ],
        )
        self.assertNotIn(PASSWORD, self.call_log.read_text())
        self.assertFalse(list(self.backups.glob(".mirklurk-backup.*")))
        self.assertEqual(self.run_script("--healthcheck").returncode, 0)

    def test_weekday_has_no_weekly_copy(self):
        result = self.run_script(BACKUP_TEST_WEEKDAY="5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list((self.backups / "weekly").iterdir()), [])

    def test_failed_dump_preserves_last_good_file_and_recovers(self):
        self.assertEqual(self.run_script().returncode, 0)
        dump = self.backups / "daily/mirklurk-2026-09-27.sql.gz"
        previous = dump.read_bytes()
        result = self.run_script(DUMP_MODE="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("simulated connection failure", result.stderr)
        self.assertIn("existing complete dumps were preserved", result.stderr)
        self.assertEqual(dump.read_bytes(), previous)
        self.assertNotEqual(self.run_script("--healthcheck").returncode, 0)
        self.assertFalse(list(self.backups.glob(".mirklurk-backup.*")))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.run_script("--healthcheck").returncode, 0)

    def test_empty_database_is_not_success(self):
        result = self.run_script(DUMP_MODE="empty")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dump has no tables", result.stderr)
        self.assertFalse(list(self.backups.glob("**/*.sql.gz")))
        self.assertNotEqual(self.run_script("--healthcheck").returncode, 0)

    def test_missing_or_empty_secret_fails_before_database_access(self):
        for content in (None, ""):
            with self.subTest(content=content):
                if content is None:
                    self.secret.unlink()
                else:
                    self.secret.write_text(content)
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.call_log.exists())
                self.assertIn("password file", result.stderr)

    def test_healthcheck_requires_recent_success(self):
        self.assertNotEqual(self.run_script("--healthcheck").returncode, 0)
        self.assertEqual(self.run_script().returncode, 0)
        marker = self.backups / ".last-success"
        stale = time.time() - 391 * 60
        os.utime(marker, (stale, stale))
        self.assertNotEqual(self.run_script("--healthcheck").returncode, 0)

    def test_retention_only_deletes_expired_wiki_dumps(self):
        for directory, expired_age, retained_age in (
            ("daily", 7, 6), ("weekly", 28, 27)
        ):
            folder = self.backups / directory
            folder.mkdir(parents=True)
            for name, age in (
                ("mirklurk-expired.sql.gz", expired_age),
                ("mirklurk-retained.sql.gz", retained_age),
                ("unrelated.sql.gz", expired_age),
            ):
                file = folder / name
                file.write_bytes(b"fixture")
                timestamp = time.time() - age * 86400
                os.utime(file, (timestamp, timestamp))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        for directory in ("daily", "weekly"):
            folder = self.backups / directory
            self.assertFalse((folder / "mirklurk-expired.sql.gz").exists())
            self.assertTrue((folder / "mirklurk-retained.sql.gz").exists())
            self.assertTrue((folder / "unrelated.sql.gz").exists())

    def test_compression_failure_does_not_publish_dump(self):
        self.make_executable("gzip", "#!/usr/bin/env bash\nexit 43\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(self.backups.glob("**/*.sql.gz")))
        self.assertTrue((self.backups / ".last-failure").exists())

    def test_successful_loop_waits_six_hours(self):
        self.make_executable(
            "sleep",
            '#!/usr/bin/env bash\n[[ "$1" == 21600 ]] || exit 97\nexit 98\n',
        )
        result = self.run_script("")
        self.assertEqual(result.returncode, 98, result.stderr)
        self.assertEqual(self.run_script("--healthcheck").returncode, 0)

    def test_failed_loop_reports_error_and_retries_in_five_minutes(self):
        self.make_executable(
            "sleep",
            '#!/usr/bin/env bash\n[[ "$1" == 300 ]] || exit 97\nexit 98\n',
        )
        result = self.run_script("", DUMP_MODE="fail")
        self.assertEqual(result.returncode, 98, result.stderr)
        self.assertIn("retrying in five minutes", result.stderr)
        self.assertNotEqual(self.run_script("--healthcheck").returncode, 0)


if __name__ == "__main__":
    unittest.main()
