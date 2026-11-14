"""Opt-in exact-peer source preparation; the caller retains the deployment lock."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess


CANONICAL = Path("/srv/homeserver")
LOCK = Path("/run/lock/homeserver-compose.lock")
PRESERVED = ("docker/monitoring/prometheus.yml", "homepage/services.yaml")
CHANGES = {
    "docker/scripts/mirklurk-map-isolated.py",
    "docker/tests/test_mirklurk_map_isolated.py",
    "docker/tests/test_mirklurk_map.py",
    "docker/docs/MIRKLURK-MAP.md",
    "docker/nginx/mirklurk-map.conf",
}
SERVICES = ("mirklurk-map", "mirklurk-map-uploads")
SOURCE = "21abd3af0a56fe7325c8311fd705ee0191d1efeb"
IMAGES = (
    "sha256:288de4ed5b6e94ffc2ef367f46843317d819db77ae394d8d89d71eb228740c33",
    "sha256:2e63715ea4fbf67100f4138cebe44f950fedff09abf2e0c74f5c75412a1a56bf",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=90)
    require(result.returncode == 0, f"{args[0]} operation failed (exit {result.returncode}); no output retained")
    return result.stdout


def git(root, *args):
    return command("git", "-c", "maintenance.auto=false", "-c", "gc.auto=0", "-C", str(root), *args)


def state(root):
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z").decode().split("\0")
    require(sorted(s for s in status if s) == sorted(" M " + p for p in PRESERVED),
            "Canonical edits are not exactly the two authorized unstaged paths")
    result = {}
    for name in PRESERVED:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "Preserved edit is not a regular file")
        before = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
        require((before.st_dev, before.st_ino, before.st_mode, before.st_size,
                 before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_mode, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns), "Preserved edit changed while fingerprinting")
        result[name] = {
            "sha256": digest, "device": after.st_dev, "inode": after.st_ino,
            "mode": after.st_mode, "size": after.st_size, "mtime_ns": after.st_mtime_ns,
            "index": git(root, "ls-files", "--stage", "--", name).decode().strip(),
        }
    return result


def same_edits(root, expected):
    require(state(root) == expected, "Authorized canonical edits or their index/identity changed")


def source_guard(source, canonical, base, revision, review_base=None):
    review_base = base if review_base is None else review_base
    require(all(re.fullmatch("[0-9a-f]{40}", value) for value in (base, revision, review_base)),
            "Full exact source revisions required")
    require(source.resolve() != canonical.resolve()
            and not source.resolve().is_relative_to(canonical.resolve())
            and not canonical.resolve().is_relative_to(source.resolve()),
            "Isolated source must be separate from canonical")
    require(git(source, "rev-parse", "HEAD").decode().strip() == revision,
            "Isolated source is not the exact reviewed revision")
    require(not git(source, "status", "--porcelain", "--untracked-files=all", "--ignored"),
            "Isolated source is not wholly clean (including ignored files)")
    require((source / ".git").is_dir(), "Use a standalone clone, not a shared-index worktree")
    command("git", "-C", str(source), "merge-base", "--is-ancestor", base, review_base)
    command("git", "-C", str(source), "merge-base", "--is-ancestor", review_base, revision)
    changed = set(git(source, "diff", "--name-only", review_base, revision).decode().splitlines())
    require(changed <= CHANGES, "Candidate changes exceed exact-peer mechanism scope")
    require("docker/nginx/mirklurk-map.conf" in changed, "Candidate does not correct exact peers")
    require(not git(source, "log", "--full-history", "--diff-merges=separate", "--format=",
                    "--name-only", base + ".." + revision, "--", *PRESERVED),
            "Upstream history touches a preserved canonical path")
    for name in PRESERVED:
        require(git(source, "rev-parse", f"{base}:{name}")
                == git(source, "rev-parse", f"{revision}:{name}"),
                "Reviewed source conflicts with a preserved canonical path")
    script = source / "docker/scripts/mirklurk-map-isolated.py"
    require(Path(__file__).resolve() == script.resolve(), "Run the exact clean isolated helper")


def peers(config):
    entries = re.findall(r"^\s*set_real_ip_from\s+([^;]+);$", config, re.MULTILINE)
    require(len(entries) == 2, "Exactly two trusted peers required")
    addresses = [ipaddress.ip_address(value) for value in entries]
    require([a.version for a in addresses] == [4, 6], "Exact IPv4/IPv6 hosts required, not subnets")
    return entries


def config_guard(canonical, source, ipv4, ipv6):
    old = (canonical / "docker/nginx/mirklurk-map.conf").read_text()
    new = (source / "docker/nginx/mirklurk-map.conf").read_text()
    current = peers(old)
    require(peers(new) == [ipv4, ipv6], "Reviewed config does not trust the requested exact peers")
    require(old.replace(f"set_real_ip_from {current[0]};", f"set_real_ip_from {ipv4};")
            .replace(f"set_real_ip_from {current[1]};", f"set_real_ip_from {ipv6};") == new,
            "Nginx candidate changes more than the two exact peers")


def proxy_guard(proxy_id, ipv4, ipv6):
    npm = json.loads(command("docker", "inspect", "nginxproxymanager"))[0]
    require(npm["Id"] == proxy_id and npm["State"]["Running"], "NPM identity/running state changed")
    network = json.loads(command("docker", "network", "inspect", "compose_proxy"))[0]
    for field, address in (("IPv4Address", ipv4), ("IPv6Address", ipv6)):
        owners = [cid for cid, row in network["Containers"].items()
                  if row[field].split("/")[0] == address]
        require(owners == [proxy_id], "Actual NPM exclusive peer ownership changed")


def normalized(value, source, canonical):
    if isinstance(value, str):
        prefix = str(source.resolve()) + os.sep
        return str(canonical.resolve()) + os.sep + value[len(prefix):] if value.startswith(prefix) else value
    if isinstance(value, list):
        return [normalized(v, source, canonical) for v in value]
    if isinstance(value, dict):
        return {k: normalized(v, source, canonical) for k, v in value.items()}
    return value


def model(root, canonical):
    data = json.loads(command(
        "docker", "compose", "--project-name", "compose",
        "--env-file", str(canonical / "docker/.env"),
        "--project-directory", str(root / "docker"),
        "-f", str(root / "docker/docker-compose.yml"), "config", "--no-env-resolution", "--format", "json",
    ))
    require(data["name"] == "compose", "Unexpected Compose project")
    return data


def models_guard(clean, live, source, canonical):
    clean = normalized(clean, source, canonical)
    require(clean["name"] == live["name"] == "compose", "Compose project mismatch")
    for service in SERVICES:
        require(clean["services"][service] == live["services"][service],
                f"Canonical {service} model differs from clean reviewed source")
        require(set(clean["services"][service].get("depends_on", {})) <= set(SERVICES),
                "Map acquired a dependency outside its two-service boundary")
        require(not clean["services"][service].get("env_file"),
                "Map service acquired an unresolved environment-file dependency")
        for volume in clean["services"][service].get("volumes", []):
            if volume["type"] == "bind":
                bound = Path(volume["source"]).resolve()
                require(not any(bound == canonical / p
                                or (canonical / p).is_relative_to(bound) for p in PRESERVED),
                        "A preserved dirty path overlaps a map bind dependency")
    for section in ("networks", "volumes", "secrets"):
        used = set()
        for service in SERVICES:
            values = clean["services"][service].get(section, {})
            if section == "volumes":
                used.update(v["source"] for v in values if v["type"] == "volume")
            elif section == "secrets":
                used.update(v["source"] for v in values)
            else:
                used.update(values)
        for name in used:
            require(clean.get(section, {}).get(name) == live.get(section, {}).get(name),
                    f"Referenced {section} identity differs")
    mount = next(v for v in live["services"]["mirklurk-map"]["volumes"]
                 if v["target"] == "/etc/nginx/conf.d/default.conf")
    require(mount["type"] == "bind" and mount["read_only"]
            and mount["source"] == str(canonical / "docker/nginx/mirklurk-map.conf")
            and not mount["bind"]["create_host_path"], "Canonical nginx bind contract changed")


def lock_guard():
    import fcntl
    path = LOCK
    require(not path.is_symlink(), "Shared lock is unexpectedly a symlink")
    opened, named = os.fstat(9), path.stat()
    require((opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino),
            "Caller must retain the existing lock inode on descriptor9")
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)


def runtime_guard():
    for name in ("docker-compose-update", "mirklurk-auto-update", "mirklurk-snapshot",
                 "postgres-backup", "mirklurk-sitemap", "rclone-offsite-daily", "nixos-upgrade"):
        status = command("systemctl", "show", name + ".service", "-p", "ActiveState", "--value")
        require(status.strip() in (b"inactive", b"failed"), f"Active maintenance unit: {name}")
    for name in ("/var/lib/mirklurk-upload-deployment/hold", "/var/lib/mirklurk-auto-update/hold",
                 "/srv/docker/data/mirklurk/backup-control/read-only",
                 "/srv/docker/data/mirklurk/backup-control/web-edit-freeze"):
        require(not os.path.lexists(name), "Maintenance hold/marker exists")
    containers = json.loads(command("docker", "inspect", *SERVICES, "mirklurk"))
    for container, service, image in zip(containers, SERVICES, IMAGES):
        labels = container["Config"]["Labels"]
        require(container["Image"] == image and labels["org.opencontainers.image.revision"] == SOURCE,
                "Accepted immutable map source/image changed")
        require(labels["com.docker.compose.project"] == "compose"
                and labels["com.docker.compose.service"] == service,
                "Existing map Compose identity differs")
        require(container["State"]["Running"] and container["State"]["Health"]["Status"] == "healthy",
                "Map target is stopped or unhealthy")
    mount = next(v for v in containers[0]["Mounts"] if v["Destination"] == "/etc/nginx/conf.d/default.conf")
    require(mount["Type"] == "bind" and not mount["RW"]
            and mount["Source"] == str(CANONICAL / "docker/nginx/mirklurk-map.conf"),
            "Live nginx bind source differs")
    storage = next(v for v in containers[1]["Mounts"] if v["Destination"] == "/data")
    volume = json.loads(command("docker", "volume", "inspect", "compose_mirklurk-map-shares"))[0]
    require(storage["Type"] == "volume" and storage["RW"]
            and storage["Name"] == volume["Name"] == "compose_mirklurk-map-shares"
            and storage["Source"] == volume["Mountpoint"]
            and volume["Labels"]["com.docker.compose.project"] == "compose"
            and volume["Labels"]["com.docker.compose.volume"] == "mirklurk-map-shares",
            "Live uploads storage differs from canonical named-volume contract")
    wiki = containers[2]
    require(wiki["Image"] == "sha256:5d90e74b09219f239bf54ead1371fd82574a4de469b4a01d9a10cb78b8fc473e"
            and wiki["Config"]["Labels"]["org.opencontainers.image.revision"]
            == "0111204dd4d8625763c7fec6c57e37357e654333"
            and wiki["State"]["Running"] and wiki["State"]["Health"]["Status"] == "healthy",
            "Accepted wiki runtime changed, stopped or unhealthy")


def prepare(args):
    lock_guard()
    runtime_guard()
    canonical = CANONICAL
    source = args.source.resolve()
    require(args.edits.is_file() and not args.edits.is_symlink(),
            "Prior edit fingerprints must be a regular private file")
    expected = json.loads(args.edits.read_text())
    require(git(canonical, "branch", "--show-current").decode().strip() == "main",
            "Canonical branch is not main")
    require(git(canonical, "rev-parse", "HEAD").decode().strip()
            == (args.revision if args.verify_only else args.base),
            "Canonical base changed")
    same_edits(canonical, expected)
    source_guard(source, canonical, args.base, args.revision, args.review_base)
    config_guard(canonical, source, args.ipv4, args.ipv6)
    proxy_guard(args.proxy_id, args.ipv4, args.ipv6)
    clean = model(source, canonical)
    models_guard(clean, model(canonical, canonical), source, canonical)
    if args.verify_only:
        print("Exact isolated source, canonical contracts and frozen edit identities verified.")
        return
    # Fetch only already-reviewed objects from the clean clone; never reset or
    # overwrite tracked files directly. Git refuses conflicting local changes.
    git(canonical, "fetch", "--no-tags", "--no-write-fetch-head", str(source),
        args.revision + ":refs/remotes/origin/main")
    same_edits(canonical, expected)
    require(git(canonical, "rev-parse", "HEAD").decode().strip() == args.base,
            "Canonical base changed before fast-forward")
    proxy_guard(args.proxy_id, args.ipv4, args.ipv6)
    git(canonical, "merge", "--no-autostash", "--ff-only", args.revision)
    require(git(canonical, "rev-parse", "HEAD").decode().strip() == args.revision,
            "Canonical fast-forward did not reach exact reviewed source")
    same_edits(canonical, expected)
    source_guard(source, canonical, args.base, args.revision, args.review_base)
    models_guard(clean, model(canonical, canonical), source, canonical)
    runtime_guard()
    proxy_guard(args.proxy_id, args.ipv4, args.ipv6)
    print("Exact clean isolated source validated; canonical fast-forwarded; both edit identities unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--review-base", help="Exact already-reviewed upstream main used as this PR's base; defaults to canonical base")
    parser.add_argument("--edits", required=True, type=Path,
                        help="Private prior fingerprint JSON; no edit contents")
    parser.add_argument("--proxy-id", required=True)
    parser.add_argument("--ipv4", required=True)
    parser.add_argument("--ipv6", required=True)
    parser.add_argument("--verify-only", action="store_true",
                        help="After preparation/activation: require exact canonical revision; never fetch/merge")
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{64}", args.proxy_id), "Exact container ID required")
    require(ipaddress.ip_address(args.ipv4).version == 4
            and ipaddress.ip_address(args.ipv6).version == 6, "Exact host peers required")
    prepare(args)


if __name__ == "__main__":
    main()
