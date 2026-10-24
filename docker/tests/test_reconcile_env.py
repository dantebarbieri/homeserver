import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "reconcile_env", Path(__file__).parents[1] / "scripts/reconcile-env.py",
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class ParserTests(unittest.TestCase):
    def test_values_quotes_multiline_and_comments(self):
        text = (
            "# not an assignment\n"
            "A='literal$! # value' # private comment\n"
            'B="double\\"quote\\\\slash"\n'
            "C=unquoted#literal # comment\n"
            "EMPTY=  # deliberately empty\n"
            "export MULTI='first\nKEY=not-a-key\nlast'\n"
            "APOSTROPHE='it\\'s literal'\n"
        )
        entries = migration.assignments(text)
        self.assertEqual(list(entries), ["A", "B", "C", "EMPTY", "MULTI", "APOSTROPHE"])
        self.assertEqual(text[entries["C"].start:entries["C"].end], "unquoted#literal")
        self.assertEqual(text[entries["EMPTY"].start:entries["EMPTY"].end], "")
        self.assertEqual(text[entries["MULTI"].start:entries["MULTI"].end], "'first\nKEY=not-a-key\nlast'")

    def test_reorder_preserves_literals_but_not_private_comments(self):
        original = "A='first\nsecond' # private comment\nB=  raw#text  # old\nEMPTY=\n"
        template = "# canonical\nEMPTY=''\nB='' # public note\nA=''\n"
        result, added = migration.render(template, original, set())
        self.assertEqual(result, "# canonical\nEMPTY=\nB=raw#text # public note\nA='first\nsecond'\n")
        self.assertEqual(added, set())
        self.assertEqual(migration.render(template, result, set())[0], result)

    def test_new_values_require_exact_explicit_opt_in(self):
        with self.assertRaisesRegex(migration.ReconcileError, "allow-new"):
            migration.render("A=''\nB=info\n", "A=old\n", set())
        self.assertEqual(
            migration.render("A=''\nB=info\n", "A=old\n", {"B"}),
            ("A=old\nB=info\n", {"B"}),
        )
        with self.assertRaises(migration.ReconcileError):
            migration.render("A=''\n", "A=old\n", {"A"})

    def test_unknown_keys_are_never_dropped(self):
        with self.assertRaisesRegex(migration.ReconcileError, "Production-only"):
            migration.render("A=''\n", "A=one\nLEGACY=two\n", set())

    def test_unsupported_syntax_and_duplicates_fail_without_values(self):
        for text in ("A=private\nA=private\n", "INVALID private\n", "A='private\n", "A='private' trailing\n"):
            with self.subTest(case=text[:2]), self.assertRaises(migration.ReconcileError) as error:
                migration.assignments(text)
            self.assertNotIn("private", str(error.exception))

    def test_effective_value_changes_and_removals_are_blocked(self):
        for candidate in ({"A": "changed"}, {}, {"A": "same", "UNEXPECTED": ""}):
            with self.assertRaises(migration.ReconcileError):
                migration.verify_values({"A": "same"}, candidate, set())
        migration.verify_values({"A": "same"}, {"A": "same", "NEW": ""}, {"NEW"})

    def test_only_whole_file_imports_accept_added_keys(self):
        before = {"services": {
            "whole": {"environment": {"A": "one", "B": "two"}},
            "narrow": {"environment": {"A": "one"}},
        }}
        after = migration.expected_model(
            before, {"A": "one", "B": "two"}, {"A": "one", "B": "two", "NEW": ""}, {"NEW"},
        )
        self.assertEqual(after["services"]["whole"]["environment"]["NEW"], "")
        self.assertNotIn("NEW", after["services"]["narrow"]["environment"])
        self.assertNotIn("NEW", before["services"]["whole"]["environment"])

    def test_compose_failure_diagnostics_never_escape(self):
        result = subprocess.CompletedProcess([], 1, stdout="private", stderr="private")
        with patch.object(migration.subprocess, "run", return_value=result), \
                self.assertRaises(migration.ReconcileError) as error:
            migration.compose(Path("/example"), Path("/example/.env"))
        self.assertNotIn("private", str(error.exception))

    def test_canonical_template_covers_all_compose_references(self):
        directory = Path(__file__).parents[1]
        keys = migration.assignments((directory / "sample.env").read_text(encoding="utf-8")).keys()
        references = set()
        for path in directory.glob("*.yml"):
            references.update(migration.re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", path.read_text(encoding="utf-8")))
        self.assertEqual(references - keys, set())


@unittest.skipUnless(os.name == "posix", "Server file ownership and permission semantics")
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "repository" / "docker"
        self.directory.mkdir(parents=True)
        self.source = self.directory / ".env"
        self.original = b"A='unchanged$value'\nB=\n"
        self.source.write_bytes(self.original)
        self.source.chmod(0o600)
        (self.directory / "sample.env").write_text("# canonical\nB=''\nA=''\n")
        self.args = argparse.Namespace(
            directory=self.directory, template=None, backup_dir=self.root / "backups",
            inventory=False, apply=False, allow_new=[],
        )
        self.model = {"services": {"probe": {"environment": {"A": "unchanged$value", "B": ""}}}}

    def fake_compose(self, directory, path, probe=False):
        return {"A": "unchanged$value", "B": ""} if probe else self.model

    def run_migration(self):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            migration.reconcile(self.args)
        self.assertNotIn("unchanged$value", output.getvalue())

    def test_dry_run_does_not_replace_and_cleans_candidates(self):
        with patch.object(migration, "compose", side_effect=self.fake_compose):
            self.run_migration()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.directory.glob(".env.reconcile-*")), [])
        self.assertEqual(list(self.args.backup_dir.glob("*/.env")), [])

    def test_apply_makes_private_exact_backup_and_preserves_owner(self):
        self.args.apply = True
        metadata = self.source.stat()
        with patch.object(migration, "compose", side_effect=self.fake_compose):
            self.run_migration()
        self.assertEqual(self.source.read_text(), "# canonical\nB=\nA='unchanged$value'\n")
        backups = list(self.args.backup_dir.glob("*/.env"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(backups[0].parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o600)
        self.assertEqual((self.source.stat().st_uid, self.source.stat().st_gid), (metadata.st_uid, metadata.st_gid))
        self.assertEqual(list(self.directory.glob(".env.reconcile-*")), [])

    def test_post_apply_failure_restores_original(self):
        self.args.apply = True
        calls = 0

        def failing_compose(directory, path, probe=False):
            nonlocal calls
            calls += 1
            if calls == 5:
                raise migration.ReconcileError("Synthetic validation failure")
            return self.fake_compose(directory, path, probe)

        with patch.object(migration, "compose", side_effect=failing_compose), \
                self.assertRaisesRegex(migration.ReconcileError, "original .env restored"):
            self.run_migration()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(len(list(self.args.backup_dir.glob("*/.env"))), 1)
        self.assertEqual(list(self.directory.glob(".env.reconcile-*")), [])

    def test_changed_preview_never_replaces(self):
        calls = 0

        def changed_compose(directory, path, probe=False):
            nonlocal calls
            calls += 1
            return {"services": {}} if calls == 4 else self.fake_compose(directory, path, probe)

        self.args.apply = True
        with patch.object(migration, "compose", side_effect=changed_compose), \
                self.assertRaisesRegex(migration.ReconcileError, "settings would change"):
            self.run_migration()
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_concurrent_edit_is_not_overwritten(self):
        def concurrent_compose(directory, path, probe=False):
            self.source.write_text("A=external-edit\nB=\n")
            return self.fake_compose(directory, path, probe)

        with patch.object(migration, "compose", side_effect=concurrent_compose), \
                self.assertRaisesRegex(migration.ReconcileError, "concurrently"):
            self.run_migration()
        self.assertEqual(self.source.read_text(), "A=external-edit\nB=\n")

    def test_insecure_permissions_and_symlinks_are_refused(self):
        self.source.chmod(0o644)
        with self.assertRaisesRegex(migration.ReconcileError, "group or others"):
            self.run_migration()
        self.source.unlink()
        self.source.symlink_to(self.directory / "sample.env")
        with self.assertRaisesRegex(migration.ReconcileError, "symlink"):
            self.run_migration()

    @unittest.skipUnless(os.environ.get("RUN_COMPOSE_ENV_TESTS") == "1", "Opt-in real Compose integration")
    def test_real_compose_preserves_quoted_multiline_and_new_defaults(self):
        self.source.write_text(
            "A='literal$ # token'\nMULTI='one\ntwo'\nDOUBLE=\"back\\\\slash\\\"quote\"\nEMPTY=\n"
        )
        (self.directory / "sample.env").write_text(
            "# canonical\nEMPTY=''\nMULTI=''\nDOUBLE=''\nA=''\nLOG_LEVEL=info\n"
        )
        (self.directory / "docker-compose.yml").write_text(json.dumps({
            "name": "env-reconcile-test",
            "services": {
                "whole": {"image": "busybox", "env_file": [".env"]},
                "narrow": {"image": "busybox", "environment": {"LOG_LEVEL": "${LOG_LEVEL:-info}"}},
            },
        }))
        before = migration.compose(self.directory, self.source, probe=True)
        self.args.allow_new = ["LOG_LEVEL"]
        self.args.apply = True
        self.run_migration()
        after = migration.compose(self.directory, self.source, probe=True)
        migration.verify_values(before, after, {"LOG_LEVEL"})
        self.assertEqual(list(migration.assignments(self.source.read_text())), ["EMPTY", "MULTI", "DOUBLE", "A", "LOG_LEVEL"])


if __name__ == "__main__":
    unittest.main()
