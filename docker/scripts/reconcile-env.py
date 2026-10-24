#!/usr/bin/env python3
"""Reconcile a private Compose .env with sample.env without displaying values."""

import argparse
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


Assignment = namedtuple("Assignment", "key start end")
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
PREFIX = re.compile(r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*")
HOST_ID_RENAMES = {"UID": "HOST_UID", "GID": "HOST_GID"}


class ReconcileError(Exception):
    """Only static messages, validated key names and line numbers may go here."""


def assignments(text):
    """Locate literal value spans, never evaluate dotenv as shell code."""
    result = {}
    position = 0
    while position < len(text):
        end = text.find("\n", position)
        end = len(text) if end < 0 else end
        line = text[position:end].strip()
        if not line or line.startswith("#"):
            position = end + 1
            continue
        line_number = text.count("\n", 0, position) + 1
        match = PREFIX.match(text, position)
        if not match:
            raise ReconcileError(f"Unsupported assignment at line {line_number}; contents withheld")
        key = match[1]
        if key in result:
            raise ReconcileError(f"Duplicate key: {key}; resolve locally before migrating")
        start = match.end()
        stop = start
        if start < len(text) and text[start] in "'\"":
            quote = text[start]
            stop += 1
            while stop < len(text):
                if text[stop] == "\\":
                    stop += 2
                elif text[stop] == quote:
                    stop += 1
                    break
                else:
                    stop += 1
            else:
                raise ReconcileError(f"Unterminated quoted value for {key}; contents withheld")
            end = text.find("\n", stop)
            end = len(text) if end < 0 else end
            if not re.fullmatch(r"[ \t\r]*(?:#[^\n]*)?", text[stop:end]):
                raise ReconcileError(f"Unsupported trailing syntax for {key}; contents withheld")
        else:
            stop = end
            for index in range(start, end):
                if text[index] == "#" and (index == start or text[index - 1] in " \t"):
                    stop = index
                    break
            while stop > start and text[stop - 1] in " \t\r":
                stop -= 1
        result[key] = Assignment(key, start, stop)
        position = end + 1
    return result


def active_renames(existing, requested):
    result = {}
    for old, new in requested.items():
        if old in existing:
            if new in existing:
                raise ReconcileError(f"Both {old} and {new} exist; resolve locally before migrating")
            result[old] = new
        elif new not in existing:
            raise ReconcileError(f"Neither {old} nor {new} exists; cannot preserve its value")
    return result


def render(template, original, allowed_new, renames=None):
    renames = renames or {}
    desired = assignments(template)
    original_entries = assignments(original)
    existing = {renames.get(key, key): entry for key, entry in original_entries.items()}
    if len(existing) != len(original_entries):
        raise ReconcileError("Renaming would overwrite an existing key")
    unknown = existing.keys() - desired.keys()
    missing = desired.keys() - existing.keys()
    if unknown:
        raise ReconcileError("Production-only keys must be added to sample.env: " + ", ".join(sorted(unknown)))
    if missing - allowed_new:
        raise ReconcileError("Explicit --allow-new required for: " + ", ".join(sorted(missing - allowed_new)))
    if allowed_new - missing:
        raise ReconcileError("--allow-new must name only currently missing keys")
    rendered = template
    for key, entry in reversed(list(desired.items())):
        if key in existing:
            previous = existing[key]
            value = original[previous.start:previous.end]
            rendered = rendered[:entry.start] + value + rendered[entry.end:]
    final = assignments(rendered)
    if list(final) != list(desired):
        raise ReconcileError("Candidate key order does not match the template")
    for key, previous in existing.items():
        entry = final[key]
        if original[previous.start:previous.end] != rendered[entry.start:entry.end]:
            raise ReconcileError(f"Literal value preservation failed for {key}")
    return rendered, missing


def compose(directory, env_file, probe=False):
    command = [
        "docker", "compose", "--project-directory", str(directory),
        "--env-file", str(env_file),
    ]
    if probe:
        command += ["-p", "env-reconcile-check", "-f", "-"]
        document = {"services": {"probe": {"image": "busybox", "env_file": [str(env_file)]}}}
        stdin = json.dumps(document)
    else:
        command += ["-f", str(directory / "docker-compose.yml"), "--profile", "*"]
        stdin = None
    command += ["config", "--format", "json"]
    try:
        completed = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise ReconcileError("Compose unavailable or timed out; diagnostics withheld") from None
    if completed.returncode:
        raise ReconcileError("Compose rejected configuration; diagnostics withheld to protect values")
    try:
        model = json.loads(completed.stdout)
        return model["services"]["probe"]["environment"] if probe else model
    except (ValueError, KeyError, TypeError):
        raise ReconcileError("Unexpected Compose response; contents withheld") from None


def verify_values(before, after, new, renames=None):
    renames = renames or {}
    expected = {renames.get(key, key): value for key, value in before.items()}
    if len(expected) != len(before):
        raise ReconcileError("Renaming would overwrite an effective value")
    if set(after) != set(expected) | new:
        raise ReconcileError("Compose environment key set changed unexpectedly")
    changed = {key for key in expected if expected[key] != after[key]}
    if changed:
        raise ReconcileError("Effective values changed for: " + ", ".join(sorted(changed)))


def expected_model(before, old_values, new_values, added, renames=None):
    renames = renames or {}
    expected = json.loads(json.dumps(before))
    for service in expected["services"].values():
        environment = service.get("environment", {})
        # Only whole-file imports inherit additions and renamed host settings.
        if old_values and all(key in environment and environment[key] == value for key, value in old_values.items()):
            for old in renames:
                del environment[old]
            environment.update({key: new_values[key] for key in added | set(renames.values())})
    return expected


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.geteuid():
        raise ReconcileError("Backup directory must be owned by the current user and not a symlink")
    os.chmod(path, 0o700)


def backup(original, directory):
    private_directory(directory)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(tempfile.mkdtemp(prefix=stamp + ".", dir=directory)) / ".env"
    with target.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    if target.read_bytes() != original:
        raise ReconcileError("Backup verification failed")
    return target


@contextmanager
def candidate_file(directory, content, metadata):
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".env.reconcile-", dir=directory, delete=False) as stream:
            path = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        yield path
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def unchanged(path, original, metadata):
    current = path.lstat()
    return (
        stat.S_ISREG(current.st_mode)
        and (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns)
        == (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_ctime_ns)
        and path.read_bytes() == original
    )


def reconcile(args):
    if os.name != "posix":
        raise ReconcileError("Run migration on the Linux server; offline parser tests are portable")
    import fcntl

    directory = args.directory.resolve()
    source = directory / ".env"
    template_path = args.template.resolve() if args.template else directory / "sample.env"
    backup_dir = args.backup_dir.expanduser().absolute()
    if backup_dir.resolve().is_relative_to(directory.parent):
        raise ReconcileError("Backups must be outside the repository")
    private_directory(backup_dir)
    with (backup_dir / "reconcile.lock").open("a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ReconcileError("Production .env must be a regular file, not a symlink")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ReconcileError("Production .env must not be accessible to group or others")
        original = source.read_bytes()
        original_text = original.decode("utf-8")
        template = template_path.read_text(encoding="utf-8")
        existing, desired = assignments(original_text), assignments(template)
        print(f"Production keys: {len(existing)}; template keys: {len(desired)}")
        print("Production-only: " + (", ".join(sorted(existing.keys() - desired.keys())) or "(none)"))
        print("Template-only: " + (", ".join(sorted(desired.keys() - existing.keys())) or "(none)"))
        if args.inventory:
            return
        renames = active_renames(existing, HOST_ID_RENAMES if args.rename_host_ids else {})
        if renames:
            print("Renaming: " + ", ".join(f"{old} -> {new}" for old, new in renames.items()))
        replacement, added = render(template, original_text, set(args.allow_new), renames)
        content = replacement.encode("utf-8")
        # Even dry runs keep all resolved configuration exclusively in memory.
        with candidate_file(directory, content, metadata) as candidate:
            old_values = compose(directory, source, probe=True)
            new_values = compose(directory, candidate, probe=True)
            verify_values(old_values, new_values, added, renames)
            before = compose(directory, source)
            preview = compose(directory, candidate)
            if preview != before:
                raise ReconcileError("Resolved Compose settings would change; replacement refused")
            expected = expected_model(before, old_values, new_values, added, renames)
            if not unchanged(source, original, metadata):
                raise ReconcileError("Production .env changed concurrently; replacement refused")
            if not args.apply:
                print("Verified: retained values and Compose settings unchanged; no replacement made")
                return
            saved = backup(original, backup_dir)
            print(f"Verified private backup: {saved}")
            if not unchanged(source, original, metadata):
                raise ReconcileError("Production .env changed during backup; replacement refused")
            os.replace(candidate, source)
            try:
                if compose(directory, source) != expected:
                    raise ReconcileError("Post-replacement Compose settings differ from the verified model")
                if source.read_bytes() != content:
                    raise ReconcileError("Production .env changed during post-replacement verification")
            except (Exception, KeyboardInterrupt):
                if source.read_bytes() != content:
                    raise ReconcileError("Concurrent edit detected; backup retained, automatic rollback refused") from None
                with candidate_file(directory, original, metadata) as rollback:
                    os.replace(rollback, source)
                raise ReconcileError("Post-replacement verification failed; original .env restored") from None
            parent = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            print("Applied: template layout matches; all existing values preserved; no services restarted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/srv/homeserver/docker"))
    parser.add_argument("--template", type=Path, help="Reviewed sample.env, if not yet deployed")
    parser.add_argument("--backup-dir", type=Path, default=Path("~/.local/state/homeserver-env/backups"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inventory", action="store_true", help="Print variable names only")
    mode.add_argument("--apply", action="store_true", help="Back up and atomically replace .env")
    parser.add_argument("--allow-new", action="append", default=[], metavar="KEY",
                        help="Explicitly accept this missing key's template value")
    parser.add_argument("--rename-host-ids", action="store_true",
                        help="Preserve UID/GID values as HOST_UID/HOST_GID; reject collisions")
    args = parser.parse_args()
    if any(not KEY.fullmatch(key) for key in args.allow_new):
        parser.error("--allow-new accepts variable names, never values")
    try:
        reconcile(args)
    except ReconcileError as error:
        print(f"Blocked: {error}", file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt) as error:
        # Exception messages and tracebacks can contain dotenv values.
        print(f"Blocked: {type(error).__name__}; details withheld to protect values", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
