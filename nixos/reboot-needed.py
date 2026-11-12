"""Read-only check for installed NixOS changes waiting for a reboot."""

import argparse
from pathlib import Path
import sys


BOOTED = Path("/run/booted-system")
CURRENT = Path("/run/current-system")
STAGED = Path("/nix/var/nix/profiles/system")


def reboot_reasons(booted: Path, current: Path, staged: Path) -> list[str]:
    # Resolve each profile once, then compare immutable store contents.
    booted, current, staged = (
        path.resolve(strict=True) for path in (booted, current, staged)
    )
    for path in (booted, current, staged):
        if not path.is_dir():
            raise NotADirectoryError(f"Not a NixOS system directory: {path}")

    reasons = []
    for part, label in (
        ("kernel", "Kernel"),
        ("initrd", "Initrd"),
        ("kernel-modules", "Kernel modules/drivers (including NVIDIA)"),
    ):
        running = (booted / part).resolve(strict=True)
        next_boot = (staged / part).resolve(strict=True)
        if running != next_boot:
            reasons.append(f"{label} changed since boot.")

    running_params = (booted / "kernel-params").read_text(encoding="utf-8").strip()
    next_params = (staged / "kernel-params").read_text(encoding="utf-8").strip()
    if running_params != next_params:
        reasons.append("Kernel boot parameters changed since boot.")

    if current != staged:
        reasons.append(
            "A different system generation is staged but not active "
            "(OS/service updates or a rollback)."
        )
    return reasons


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="reboot-needed",
        description=(
            "Check installed NixOS updates without sudo or changing anything. "
            "Does not check reboot safety or whether a reboot is queued."
        ),
        epilog="Exit codes: 0 = no reboot needed, 1 = reboot needed, 2 = cannot determine.",
    )
    parser.parse_args(argv)
    try:
        reasons = reboot_reasons(BOOTED, CURRENT, STAGED)
    except (OSError, RuntimeError, UnicodeError) as error:
        print(f"reboot-needed: cannot determine reboot need: {error}", file=sys.stderr)
        return 2
    if not reasons:
        print("No reboot needed for installed updates.")
        return 0
    print("Reboot needed to activate installed changes:")
    for reason in reasons:
        print(f"- {reason}")
    print("Run sudo safe-reboot when ready; reboot safety and queue status were not checked.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
