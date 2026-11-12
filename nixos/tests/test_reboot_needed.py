"""Exercise reboot-need detection against temporary NixOS system profiles."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("reboot_needed", ROOT / "nixos/reboot-needed.py")
reboot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reboot)


class RebootNeededTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.booted = self.make_system("booted-system")
        for name in ("BOOTED", "CURRENT", "STAGED"):
            path = self.root / name.lower()
            path.symlink_to(self.booted, target_is_directory=True)
            patcher = patch.object(reboot, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_system(self, name, **changes):
        system = self.root / name
        system.mkdir()
        for part in ("kernel", "initrd", "kernel-modules"):
            target = self.root / changes.get(part, part)
            if part == "kernel-modules":
                target.mkdir(exist_ok=True)
            else:
                target.touch()
            (system / part).symlink_to(target, target_is_directory=part == "kernel-modules")
        (system / "kernel-params").write_text(
            changes.get("kernel-params", "root=fstab loglevel=4"), encoding="utf-8"
        )
        return system

    def point(self, profile, system):
        profile.unlink()
        profile.symlink_to(system, target_is_directory=True)

    def run_check(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = reboot.main([])
        return status, out.getvalue(), err.getvalue()

    def test_unchanged_or_live_switched_userland_needs_no_reboot(self):
        for system in (self.booted, self.make_system("switched-userland")):
            with self.subTest(system=system.name):
                self.point(reboot.CURRENT, system)
                self.point(reboot.STAGED, system)
                status, output, error = self.run_check()
                self.assertEqual(status, 0, error)
                self.assertIn("No reboot needed", output)
                self.assertEqual(error, "")

    def test_staged_userland_needs_activation(self):
        self.point(reboot.STAGED, self.make_system("staged-userland"))
        status, output, error = self.run_check()
        self.assertEqual(status, 1, error)
        self.assertIn("staged but not active", output)
        self.assertNotIn("changed since boot", output)
        self.assertIn("sudo safe-reboot", output)

    def test_boot_changes_still_need_reboot_after_switch(self):
        for part, label in (
            ("kernel", "Kernel changed"),
            ("initrd", "Initrd changed"),
            ("kernel-modules", "Kernel modules/drivers (including NVIDIA) changed"),
            ("kernel-params", "Kernel boot parameters changed"),
        ):
            with self.subTest(part=part):
                system = self.make_system(f"updated-{part}", **{part: f"new-{part}"})
                self.point(reboot.CURRENT, system)
                self.point(reboot.STAGED, system)
                status, output, error = self.run_check()
                self.assertEqual(status, 1, error)
                self.assertIn(label, output)
                self.assertNotIn("staged but not active", output)

    def test_staged_kernel_reports_boot_and_generation_changes(self):
        self.point(reboot.STAGED, self.make_system("staged-kernel", kernel="new-kernel"))
        status, output, error = self.run_check()
        self.assertEqual(status, 1, error)
        self.assertIn("Kernel changed", output)
        self.assertIn("staged but not active", output)

    def test_equivalent_links_and_trailing_newline_are_not_updates(self):
        system = self.make_system("equivalent", **{"kernel-params": "root=fstab loglevel=4\n"})
        (system / "kernel").unlink()
        (system / "kernel").symlink_to(os.path.relpath(self.root / "kernel", system))
        self.point(reboot.CURRENT, system)
        self.point(reboot.STAGED, system)
        status, output, error = self.run_check()
        self.assertEqual(status, 0, error)
        self.assertIn("No reboot needed", output)

    def test_quoted_parameter_whitespace_changes_are_detected(self):
        (self.booted / "kernel-params").write_text('example="a b"', encoding="utf-8")
        system = self.make_system("changed-params", **{"kernel-params": 'example="a  b"'})
        self.point(reboot.CURRENT, system)
        self.point(reboot.STAGED, system)
        status, output, error = self.run_check()
        self.assertEqual(status, 1, error)
        self.assertIn("Kernel boot parameters changed", output)

    def test_missing_state_is_unknown_not_up_to_date(self):
        for path in (
            reboot.BOOTED, reboot.CURRENT, reboot.STAGED,
            self.root / "kernel", self.root / "initrd", self.root / "kernel-modules",
            self.booted / "kernel-params",
        ):
            with self.subTest(path=path):
                saved = path.with_name(path.name + ".saved")
                path.rename(saved)
                try:
                    status, output, error = self.run_check()
                    self.assertEqual(status, 2)
                    self.assertEqual(output, "")
                    self.assertIn("cannot determine", error)
                finally:
                    saved.rename(path)

    def test_unreadable_state_is_unknown(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("permission denied")):
            status, output, error = self.run_check()
        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("permission denied", error)

    def test_invalid_profile_and_symlink_loop_are_unknown(self):
        for target in (self.root / "kernel", reboot.STAGED):
            with self.subTest(target=target):
                self.point(reboot.STAGED, target)
                status, output, error = self.run_check()
                self.assertEqual(status, 2)
                self.assertEqual(output, "")
                self.assertIn("cannot determine", error)


if __name__ == "__main__":
    unittest.main()
