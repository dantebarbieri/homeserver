#!/usr/bin/env python3
"""Homeserver-only wiki runtime releases, unattended base-image patching and sitemap refresh."""

import argparse
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


CANONICAL = Path("/srv/homeserver")
LOCK = Path("/run/lock/homeserver-compose.lock")
ORIGIN = "https://mirklurk.wiki"
SOURCE = "https://github.com/dantebarbieri/mirklurk-wiki"
REPOSITORY = SOURCE + ".git"
CHECK_RUNS = "https://api.github.com/repos/dantebarbieri/mirklurk-wiki/commits/{}/check-runs?per_page=100"
REQUIRED_CHECKS = ("publication", "docker-smoke")
SOURCE_LABEL = "org.opencontainers.image.source"
REVISION_LABEL = "org.opencontainers.image.revision"
USER_AGENT = "MirkLurkDeploymentCheck/1.0"
SITEMAP = "/var/lib/mirklurk-sitemap"
BACKUP_CONTROL = "/var/lib/mirklurk-backup"
DATA = Path("/srv/docker/data/mirklurk")
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
# The frontend runs whatever LIVE_TAG names, and only this helper moves it. The
# Compose profile keeps the nightly updater, dcu and dcupdate off the frontend.
IMAGE_REPOSITORY = "mirklurk-wiki"
LIVE_TAG = IMAGE_REPOSITORY + ":live"
PREVIOUS_TAG = IMAGE_REPOSITORY + ":previous"
PROFILE = "mirklurk-release"
AUTO_STATE = Path("/var/lib/mirklurk-auto-update")
DEPLOYMENT_HOLD = Path("/var/lib/mirklurk-upload-deployment/hold")
AUTO_KEEP = 3
ELIGIBLE_STALL_DAYS = 3
BLOCKED_STALL_DAYS = 7
# PHP2Shell (CVE-2026-109618/109619) is fixed in PHP 8.3.36: never serve an older runtime.
MIN_PHP = (8, 3, 36)
NEVER_SERVE = {"sha256:a1f303f573bcdeecce80992c6b5139e19bab07c6bed7b1eb02839b6e01a77b5a"}
BASE = re.compile(r"FROM mediawiki:(1\.43\.\d+)@sha256:[0-9a-f]{64}")
# Files whose change means a base update may need update.php: core schema and
# updaters, extension/skin schema directories and schema-update hook handlers.
SCHEMA_FILES = r"""
cd /var/www/html || exit 1
{
  for path in sql maintenance/abstractSchemaChanges maintenance/archives maintenance/mysql \
      maintenance/postgres maintenance/sqlite includes/installer; do
    if [ -d "$path" ]; then find "$path" -type f; fi
  done
  find maintenance -maxdepth 1 -type f -name 'tables*'
  find extensions skins -mindepth 2 -maxdepth 2 -type d \
    \( -name sql -o -name db_patches -o -name schema -o -name patches \) -exec find {} -type f \;
  grep -rl --include='*.php' LoadExtensionSchemaUpdates extensions skins || true
} | LC_ALL=C sort -u | xargs -d '\n' -r sha256sum
"""
BRANDING_KEYS = ("MW_LOGO_URL", "MW_LOGO_ICON_URL", "MW_FAVICON_URL", "MW_APPLE_TOUCH_ICON_URL")
# Optional runtime keys that a reviewed candidate may add before the live predecessor has them.
INTRODUCED_ENV = {"MW_APPLE_TOUCH_ICON_URL"}


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def run(*args, timeout=60, input=None):
    environment = dict(os.environ)
    if args[0] == "git":
        environment["GIT_TERMINAL_PROMPT"] = "0"
        # Root must not rewrite the index of a checkout another user owns.
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        environment["GIT_SSH_COMMAND"] = environment.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes"
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=environment, input=input)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseError(f"{args[0]} unavailable or timed out") from error
    # Compose/inspect output can contain secrets. Never echo captured output on failure.
    require(result.returncode == 0, f"{args[0]} {args[1]} failed (exit {result.returncode})")
    return result.stdout.strip()


def compose(root, *args, timeout=60):
    return run(
        "docker", "compose", "--project-name", "compose",
        "--project-directory", str(root / "docker"),
        "--env-file", str(CANONICAL / "docker/.env"),
        "--file", str(root / "docker/docker-compose.yml"), "--profile", PROFILE, *args, timeout=timeout,
    )


def git(root, *args, timeout=60):
    # Root (the systemd units) may operate on a checkout another user owns.
    return run("git", "-c", f"safe.directory={Path(root).resolve()}", "-C", str(root), *args, timeout=timeout)


def inspect(name, image=False):
    args = ("docker", "image", "inspect", name) if image else ("docker", "inspect", name)
    return json.loads(run(*args))[0]


def tag_target(reference):
    """Full image ID a local tag currently names, or None."""
    found = set(run("docker", "image", "ls", "--no-trunc", "--quiet", reference).split())
    require(len(found) <= 1, f"Ambiguous image reference {reference}")
    return found.pop() if found else None


def version(text):
    require(re.fullmatch(r"\d+(\.\d+){1,3}", text or ""), f"Unexpected version {text!r}")
    return tuple(int(part) for part in text.split("."))


def runtime(image):
    """(MediaWiki, PHP) versions that the official base image records in its environment."""
    environment = dict(item.split("=", 1) for item in inspect(image, image=True)["Config"].get("Env") or [])
    mediawiki, php = environment.get("MEDIAWIKI_VERSION", ""), environment.get("PHP_VERSION", "")
    require(re.fullmatch(r"\d+\.\d+\.\d+", mediawiki) and re.fullmatch(r"\d+\.\d+\.\d+", php),
            "Image does not record MEDIAWIKI_VERSION and PHP_VERSION")
    return mediawiki, php


def servable(image):
    """Refuse known-vulnerable runtimes; return the image's MediaWiki version."""
    require(image not in NEVER_SERVE, "Image is on the never-serve list")
    mediawiki, php = runtime(image)
    require(version(php) >= MIN_PHP, f"PHP {php} is vulnerable to PHP2Shell; never serve it")
    return mediawiki


def healthy(name):
    state = inspect(name)["State"]
    require(state["Running"] and state.get("Health", {}).get("Status") == "healthy",
            f"{name} is not running and healthy")


@contextmanager
def locked(wait=30):
    import fcntl

    # Open the existing root-owned lock read-only; do not replace its inode.
    with LOCK.open("r") as handle:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, f"Compose lock busy for {wait} seconds")
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def get(path, timeout=15):
    require(path.startswith("/") and not path.startswith("//"), "Invalid public probe path")
    request = Request(ORIGIN + path, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            require(response.status == 200 and response.url.startswith(ORIGIN + "/"),
                    f"Unexpected public response for {path}")
            return response.read()
    except (OSError, URLError) as error:
        raise ReleaseError(f"Public probe failed: {path}") from error


def siteinfo(mediawiki):
    data = json.loads(get("/api.php?action=query&meta=siteinfo&siprop=general&format=json"))
    general = data["query"]["general"]
    require(general["server"] == ORIGIN and general["scriptpath"] == ""
            and general["articlepath"] == "/w/$1"
            and general["generator"] == f"MediaWiki {mediawiki}"
            and "readonly" not in general, "Unexpected live origin, paths, version or read-only policy")


def running_mediawiki():
    return runtime(inspect("mirklurk")["Image"])[0]


def headroom(storage):
    available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    require(available >= 2 * 1024 * 1024, "Less than 2 GiB memory available")
    require(os.getloadavg()[0] < (os.cpu_count() or 1), "Host load exceeds logical CPU count")
    require(shutil.disk_usage(storage).free >= 5 * 1024**3, "Less than 5 GiB storage available")


def preflight(root, source, image, previous):
    require(re.fullmatch(r"[0-9a-f]{40}", source), "Expected explicit full wiki source SHA")
    for identifier in (image, previous):
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", identifier), "Expected full immutable image IDs")
    require(image != previous, "Candidate and predecessor must differ")
    require(not git(root, "status", "--porcelain"), "Checkout is not clean")
    if root.resolve() == CANONICAL:
        compose(root, "config", "--quiet")
    # Other stacks' env_file contents are not needed to verify this app.
    config = json.loads(compose(root, "config", "--format", "json", "--no-env-resolution"))
    service = config["services"]["mirklurk"]
    require(service["image"] == LIVE_TAG and service["pull_policy"] == "never" and "build" not in service
            and service.get("profiles") == [PROFILE],
            f"Compose must run the helper-managed {LIVE_TAG} only in profile {PROFILE}")
    require(REVISION_LABEL not in (service.get("labels") or {}),
            "Compose must not override the image's source revision label")
    candidate = inspect(image, image=True)
    labels = candidate["Config"].get("Labels") or {}
    require(candidate["Id"] == image and labels.get(REVISION_LABEL) == source
            and labels.get(SOURCE_LABEL) == SOURCE, "Candidate provenance mismatch")
    mediawiki = servable(image)
    predecessor = inspect(previous, image=True)
    require(predecessor["Id"] == previous
            and (predecessor["Config"].get("Labels") or {}).get(SOURCE_LABEL) == SOURCE,
            "Retained predecessor is missing or has unexpected provenance")
    live = inspect("mirklurk")
    require(live["Image"] in (previous, image), "Live image is neither expected predecessor nor candidate")
    require(tag_target(LIVE_TAG) in (None, previous, image), f"{LIVE_TAG} names an unexpected image")
    require(live["Config"]["Labels"].get("com.docker.compose.project") == "compose",
            "Unexpected live Compose project")
    environment = service["environment"]
    require(environment["MW_SERVER_URL"] == ORIGIN and environment["MW_READ_ONLY"] == "",
            "Canonical origin or literal empty MW_READ_ONLY was changed")
    live_env = dict(value.split("=", 1) for value in live["Config"]["Env"])
    live_mw = {key: value for key, value in live_env.items() if key.startswith("MW_")}
    require(live_mw == {key: value for key, value in environment.items()
                        if key in live_mw or key not in INTRODUCED_ENV},
            "Runtime environment differs; review separately (values suppressed)")
    actual_mounts = {mount["Destination"]: mount for mount in live["Mounts"]}
    volumes = service["volumes"]
    require({v["target"] for v in volumes} == {
        "/var/www/html/images", "/var/www/html/branding", SITEMAP, BACKUP_CONTROL},
            "Unexpected application volume set")
    require(not service.get("ports") and service.get("command") is None and service.get("entrypoint") is None,
            "Unexpected application ports or startup override")
    for volume in volumes:
        require(volume["type"] == "bind" and volume["bind"]["create_host_path"] is False,
                "Unsafe application bind mount")
        if volume["target"] != SITEMAP:
            require(Path(volume["source"]).is_dir(), f"Missing directory for {volume['target']}")
            actual = actual_mounts.get(volume["target"], {})
            require(actual.get("Source") == volume["source"]
                    and actual.get("RW") == (not volume.get("read_only", False)),
                    f"Existing mount changed: {volume['target']}")
    for secret in service["secrets"]:
        target = str(Path("/run/secrets") / secret["target"])
        actual = actual_mounts.get(target, {})
        require(actual.get("Source") == config["secrets"][secret["source"]]["file"] and actual.get("RW") is False,
                "Existing secret mount changed (values suppressed)")
    expected_mounts = {v["target"] for v in volumes} | {
        str(Path("/run/secrets") / secret["target"]) for secret in service["secrets"]}
    require(set(actual_mounts) - {SITEMAP} == expected_mounts - {SITEMAP},
            "Existing mount set changed")
    expected_networks = {config["networks"][name]["name"] for name in service["networks"]}
    require(set(live["NetworkSettings"]["Networks"]) == expected_networks, "Application networks changed")
    storage = Path(next(v["source"] for v in volumes if v["target"] == SITEMAP))
    if live["Image"] == image:
        require(actual_mounts.get(SITEMAP, {}).get("Source") == str(storage),
                "Candidate is running without the reviewed sitemap mount")
    for name in ("mirklurk", "mirklurk-db", "mirklurk-backup"):
        healthy(name)
        if name != "mirklurk":
            require(inspect(name)["Config"]["Image"] == config["services"][name]["image"],
                    f"{name} pin differs from the running service")
    headroom(storage.parent)
    siteinfo(runtime(live["Image"])[0])
    for folder in (storage, storage / "public"):
        require(folder.is_dir(), f"Missing sitemap directory: {folder}")
        st = folder.stat()
        require(not folder.is_symlink() and (st.st_uid, st.st_gid) == (33, 33)
                and stat.S_IMODE(st.st_mode) in (0o755, 0o2755),
                f"Sitemap directory must be UID/GID 33, mode 0755 or 2755: {folder}")
    print(f"Preflight OK: source={source} image={image} (MediaWiki {mediawiki}); live={live['Image']}", flush=True)
    return live, environment, mediawiki


def storage_headroom():
    for folder in (DATA / "images", DATA / "branding", DATA / "backups", DATA / "backup-control"):
        require(folder.is_dir() and not folder.is_symlink(), f"Missing or symlinked storage: {folder}")
        require(shutil.disk_usage(folder).free >= 5 * 1024**3, f"Less than 5 GiB free: {folder}")
        usage = os.statvfs(folder)
        require(usage.f_files > 0 and usage.f_favail >= max(10000, usage.f_files // 20),
                f"Less than 5% or 10000 free inodes: {folder}")


def check_backups():
    storage_headroom()
    require(not os.path.lexists(DATA / "backup-control/read-only"), "Wiki backup/operator read-only marker remains")
    marker = DATA / "backups/.last-snapshot"
    require(marker.is_file() and 0 <= time.time() - marker.stat().st_mtime < 26 * 3600,
            "Complete SQL/files snapshot missing or older than 26 hours")
    name = marker.read_text().strip()
    require(re.fullmatch(r"mirklurk-\d{8}T\d{12}Z\.tar\.gz", name)
            and (DATA / "backups/snapshots/daily" / name).is_file(), "Snapshot marker has no matching bundle")
    run("docker", "exec", "mirklurk-backup", "bash", "/opt/mirklurk-backup.sh", "--healthcheck")
    print("Wiki SQL/files backup freshness and storage headroom OK.", flush=True)


def snapshot_mounts():
    storage_headroom()
    for name in ("mirklurk", "mirklurk-db", "mirklurk-backup"):
        healthy(name)
    live = inspect("mirklurk")
    require(live["Config"]["Labels"].get("com.docker.compose.project") == "compose",
            "Unexpected wiki Compose project")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", live["Image"])
            and re.fullmatch(r"[0-9a-f]{40}", live["Config"]["Labels"].get("org.opencontainers.image.revision", "")),
            "Wiki image/source provenance missing")
    mounts = {mount["Destination"]: mount for mount in live["Mounts"]}
    for target, folder, writable in (
        ("/var/www/html/images", "images", True),
        ("/var/www/html/branding", "branding", False),
        (BACKUP_CONTROL, "backup-control", False),
    ):
        actual = mounts.get(target, {})
        require(actual.get("Type") == "bind" and actual.get("Source") == str(DATA / folder)
                and actual.get("RW") is writable, f"Unexpected snapshot mount: {target}")
    backup = inspect("mirklurk-backup")
    for container in (live, backup):
        environment = dict(value.split("=", 1) for value in container["Config"]["Env"])
        require(environment.get("MW_DB_SERVER") == "mirklurk-db"
                and environment.get("MW_DB_NAME") == "mirklurk"
                and environment.get("MW_DB_USER") == "mirklurk",
                "App/backup database contract differs (values suppressed)")
    require(any(m.get("Destination") == "/backups" and m.get("Source") == str(DATA / "backups")
                and m.get("Type") == "bind" and m.get("RW") for m in backup["Mounts"]),
            "Backup client does not use the expected backup directory")
    # Only the frontend may write upload storage. Operator CLI imports must also
    # take the Compose lock; never run independent writers against the wiki DB.
    containers = [json.loads(line) for line in run(
        "docker", "inspect", "--format", '{"Id":{{json .Id}},"Name":{{json .Name}},"Mounts":{{json .Mounts}}}',
        *run("docker", "ps", "-q").split()).splitlines()]
    for container in containers:
        if container["Id"] == live["Id"]:
            continue
        for mount in container["Mounts"]:
            if mount.get("Type") != "bind":
                continue
            source = Path(mount.get("Source", "/"))
            images = DATA / "images"
            if mount.get("RW") and source in images.parents and container.get("Name") == "/code-server":
                print("Administrative code-server mount present: wiki file changes must obey the Compose lock.",
                      flush=True)
                continue
            require(not (mount.get("RW") and (source == images or source in images.parents
                                               or images in source.parents)),
                    "Another running container can write wiki images")
    return live


def wait_healthy(name):
    deadline = time.monotonic() + 120
    while inspect(name)["State"].get("Health", {}).get("Status") != "healthy":
        require(time.monotonic() < deadline, f"{name} readiness timeout")
        time.sleep(2)


def snapshot():
    """Called with the shared Compose lock held; never changes app/DB images."""
    require(os.geteuid() == 0, "Run the snapshot as root to preserve all file ownership, ACLs and private images")
    live = snapshot_mounts()
    identifier = live["Id"]
    backups = DATA / "backups"
    owner = backups.stat()
    snapshots = backups / "snapshots"
    for folder in (snapshots, snapshots / "daily", snapshots / "weekly"):
        if not folder.exists():
            folder.mkdir(mode=0o700)
            os.chown(folder, owner.st_uid, owner.st_gid)
        require(folder.is_dir() and not folder.is_symlink(), f"Unsafe snapshot directory: {folder}")
    size = sum(int(line.split()[0]) for line in run(
        "du", "--summarize", "--apparent-size", "--block-size=1",
        str(DATA / "images"), str(DATA / "branding"), str(backups / "daily")).splitlines())
    require(shutil.disk_usage(backups).free >= size + 5 * 1024**3,
            "Insufficient space for a complete snapshot plus 5 GiB reserve")
    now = datetime.now(timezone.utc)
    snapshot_id = now.strftime("%Y%m%dT%H%M%S%fZ")
    name = "mirklurk-" + snapshot_id + ".tar.gz"
    dump = backups / f".mirklurk-snapshot-sql-{snapshot_id}.sql.gz"
    require(not os.path.lexists(dump), "Snapshot SQL identifier already exists")
    lock = DATA / "backup-control/read-only"
    # Exclusive creation refuses an existing operator lock, including symlinks.
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w") as handle:
        os.fchmod(handle.fileno(), 0o644)
        handle.write("Scheduled backup: editing and uploads will resume shortly.\n")
        identity = os.fstat(handle.fileno())
    stopped = False
    restored = False
    try:
        with tempfile.TemporaryDirectory(prefix=".mirklurk-snapshot-", dir=backups) as temporary:
            staging = Path(temporary)
            try:
                # Apache's SIGWINCH drains requests. A forced stop is not a
                # consistency barrier and must never produce a "good" bundle.
                stopped = True
                run("docker", "stop", "--signal=SIGWINCH", "--timeout=120", identifier, timeout=140)
                state = inspect(identifier)["State"]
                require(not state["Running"] and state["ExitCode"] == 0 and not state.get("OOMKilled"),
                        "Frontend did not stop cleanly; no consistent snapshot taken")
                # Stream the reviewed script: a file bind may still reference
                # its old inode after git updates, without recreating the sidecar.
                run("docker", "exec", "-i", "mirklurk-backup", "timeout", "--kill-after=5s", "280s",
                    "bash", "-s", "--", "--snapshot", snapshot_id, timeout=300,
                    input=Path(__file__).with_name("mirklurk-backup.sh").read_text())
                require(dump.is_file() and not dump.is_symlink(), "Backup client did not publish snapshot SQL")
                os.replace(dump, staging / "database.sql.gz")
                (staging / "manifest.json").write_text(json.dumps({
                    "format": 1, "created_utc": now.isoformat(), "image": live["Image"],
                    "source": live["Config"]["Labels"].get("org.opencontainers.image.revision"),
                    "database": "mirklurk", "quiescence": "frontend gracefully stopped under Compose lock",
                    "files": ["images", "branding"], "secrets": "separately encrypted offsite",
                }, indent=2) + "\n")
                run("tar", "--create", "--gzip", "--acls", "--xattrs", "--numeric-owner",
                    "--file", str(staging / name), "--directory", str(staging),
                    "database.sql.gz", "manifest.json", "--directory", str(DATA), "images", "branding",
                    timeout=600)
            finally:
                if stopped:
                    run("docker", "start", identifier, timeout=60)
                    wait_healthy(identifier)
                    restored = True
            run("tar", "--list", "--gzip", "--file", str(staging / name), timeout=600)
            (staging / name).chmod(0o600)
            os.chown(staging / name, owner.st_uid, owner.st_gid)
            destination = snapshots / "daily" / name
            os.replace(staging / name, destination)
            if now.isoweekday() == 7:
                os.link(destination, snapshots / "weekly" / name)
            (staging / "last-snapshot").write_text(name + "\n")
            os.chown(staging / "last-snapshot", owner.st_uid, owner.st_gid)
            os.replace(staging / "last-snapshot", backups / ".last-snapshot")
            for tier, days in (("daily", 7), ("weekly", 28)):
                for path in (snapshots / tier).iterdir():
                    if (re.fullmatch(r"mirklurk-\d{8}T\d{12}Z\.tar\.gz", path.name)
                            and not path.is_symlink() and path.is_file()
                            and path.stat().st_mtime < time.time() - days * 86400):
                        path.unlink()
    finally:
        if dump.exists() and not dump.is_symlink():
            dump.unlink()
        if not stopped or restored:
            current = lock.lstat()
            require((current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino),
                    "Read-only marker was replaced; leaving it for operator review")
            lock.unlink()
        else:
            print("Frontend recovery failed; read-only marker retained. Operator intervention required.",
                  file=sys.stderr)
    print(f"Complete SQL/files snapshot: snapshots/daily/{name}", flush=True)


def refresh_sitemap(root):
    healthy("mirklurk")
    # Bounded processing of already queued derived-data work, never publication or migration.
    compose(root, "exec", "-T", "--user", "www-data", "mirklurk", "timeout", "--kill-after=5s", "75s", "php",
            "maintenance/run.php", "runJobs", "--maxjobs=500", "--maxtime=60", timeout=90)
    jobs = compose(root, "exec", "-T", "--user", "www-data", "mirklurk", "timeout", "--kill-after=5s", "45s", "php",
                   "maintenance/run.php", "showJobs")
    require(jobs == "0", "Pending content jobs remain; finish them before refreshing sitemap")
    compose(root, "exec", "-T", "--user", "www-data", "mirklurk", "timeout", "--kill-after=5s", "160s", "php",
            "maintenance/run.php", "/usr/local/lib/mirklurk/refresh-sitemap.php", timeout=180)
    age = int(compose(root, "exec", "-T", "--user", "www-data", "mirklurk", "php", "-r",
                      "echo time() - filemtime('/var/lib/mirklurk-sitemap/public/sitemap.xml');"))
    require(0 <= age < 300, "Published sitemap is missing or stale")
    require(f"Sitemap: {ORIGIN}/sitemap.xml" in get("/robots.txt").decode(), "Robots sitemap directive missing")
    index = ET.fromstring(get("/sitemap.xml"))
    shards = index.findall("s:sitemap/s:loc", NS)
    require(shards, "Public sitemap index is empty")
    urls = []
    for shard in shards:
        url = shard.text or ""
        require(re.fullmatch(re.escape(ORIGIN) + r"/sitemap-[A-Za-z0-9_-]+\.xml", url),
                "Unexpected sitemap shard URL")
        document = ET.fromstring(get(url[len(ORIGIN):]))
        urls.extend(loc.text or "" for loc in document.findall("s:url/s:loc", NS))
    require(ORIGIN + "/w/Items" in urls and all(url.startswith(ORIGIN + "/w/") for url in urls),
            "Sitemap missing Items or contains noncanonical article URLs")
    print(f"Sitemap refreshed: {len(shards)} shards, {len(urls)} URLs, local age {age}s", flush=True)


def public_acceptance(environment, mediawiki):
    siteinfo(mediawiki)
    html = get("/w/Items").decode()
    require('name="viewport"' in html and "width=device-width" in html, "Responsive viewport missing")
    require('property="og:url" content="https://mirklurk.wiki/w/Items"' in html,
            "Canonical Items metadata missing")
    require('property="og:title"' in html, "Article metadata missing")
    get("/load.php?lang=en&modules=site.styles&only=styles&skin=vector-2022")
    for key in BRANDING_KEYS:
        if environment.get(key):
            require(get(environment[key]).startswith(b"\x89PNG\r\n\x1a\n"), f"Branding PNG failed: {key}")


def container_ids():
    return sorted(line for line in run("docker", "ps", "-a", "--no-trunc", "--format",
                                      "{{.Names}} {{.ID}}").splitlines()
                  if not line.startswith("mirklurk "))


@contextmanager
def availability_monitor():
    stop = threading.Event()
    samples = []

    def monitor():
        while not stop.is_set():
            started = time.monotonic()
            try:
                get("/api.php?action=query&meta=siteinfo&format=json", timeout=2)
                ok = True
            except ReleaseError:
                ok = False
            samples.append((started, time.monotonic(), ok))
            stop.wait(0.5)

    thread = threading.Thread(target=monitor)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        failures = [sample for sample in samples if not sample[2]]
        if failures:
            first = failures[0][0]
            recovered = next((end for start, end, ok in samples if ok and start > failures[-1][0]), None)
            print(f"Public probe failures: {len(failures)}; "
                  + (f"first failure to recovery {recovered - first:.1f}s (sampled, not exact outage)"
                     if recovered else "no recovery observed"), flush=True)
        else:
            print("No failure sampled at 0.5s intervals; brief interruptions may be missed.", flush=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(kind, source, image, previous):
    """Host-side release record; the image's own labels carry the same source provenance."""
    entry = {"at": now_iso(), "kind": kind, "source": source, "image": image, "previous": previous}
    print("Deployed " + json.dumps(entry), flush=True)
    try:
        with (AUTO_STATE / "history.jsonl").open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError:
        print(f"Could not append to {AUTO_STATE}/history.jsonl; the line above is the record.", file=sys.stderr)


def activate(root, live, environment, image, mediawiki, on_activation=None):
    """Back up, point LIVE_TAG at the candidate and recreate only the frontend, then accept it."""
    before = container_ids()
    if live["Image"] != image:
        check_backups()
        run("docker", "exec", "mirklurk-backup", "timeout", "--kill-after=5s", "280s",
            "bash", "/opt/mirklurk-backup.sh", "--once", timeout=300)
        run("docker", "exec", "mirklurk-backup", "bash", "/opt/mirklurk-backup.sh", "--healthcheck")
        if on_activation:
            on_activation()
        started = time.monotonic()
        with availability_monitor():
            run("docker", "tag", live["Image"], PREVIOUS_TAG)
            run("docker", "tag", image, LIVE_TAG)
            compose(root, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "mirklurk",
                    timeout=120)
            wait_healthy("mirklurk")
            require(inspect("mirklurk")["Image"] == image, "Running candidate image mismatch")
            public_acceptance(environment, mediawiki)
        print(f"Activation-to-readiness upper bound: {time.monotonic() - started:.1f}s", flush=True)
    else:
        print("Candidate already active: no recreation or backup repeated.", flush=True)
        if tag_target(LIVE_TAG) != image:
            run("docker", "tag", image, LIVE_TAG)
        public_acceptance(environment, mediawiki)
    refresh_sitemap(root)
    require(container_ids() == before, "Other container identities changed; investigate before acceptance")


def deploy(root, source, image, previous):
    require(root.resolve() == CANONICAL, "Activation is only allowed from /srv/homeserver")
    require(Path(__file__).resolve() == CANONICAL / "docker/scripts/mirklurk-release.py",
            "Run the merged helper from the canonical checkout")
    require(git(root, "branch", "--show-current") == "main", "Canonical branch must be main")
    require(not git(root, "status", "--porcelain"), "Canonical checkout is not clean")
    script = Path(__file__).read_bytes()
    git(root, "pull", "--ff-only", "origin", "main", timeout=120)
    require(Path(__file__).read_bytes() == script, "Release helper changed during pull; rerun the updated command")
    require(git(root, "rev-parse", "HEAD") == git(root, "rev-parse", "origin/main"),
            "Checkout is not fetched origin/main")
    live, environment, mediawiki = preflight(root, source, image, previous)
    was = live["Image"]
    activate(root, live, environment, image, mediawiki)
    if was != image:
        record("manual", source, image, was)
    print("Runtime accepted; content was not published/restored.")


Decision = namedtuple("Decision", "kind since reason base")


def clone_main(workspace):
    repo = workspace / "source"
    run("git", "clone", "--quiet", "--no-checkout", "--single-branch", "--branch", "main",
        REPOSITORY, str(repo), timeout=300)
    return repo, git(repo, "rev-parse", "refs/remotes/origin/main")


def evaluate(repo, live, candidate, live_since):
    """Classify main against the live revision. The Dockerfile reads only deploy/, so that is the image input."""
    if live == candidate:
        return Decision("current", None, "the live wiki runs mirklurk-wiki main", None)
    try:
        git(repo, "merge-base", "--is-ancestor", live, candidate)
    except ReleaseError:
        return Decision("blocked", live_since, f"live revision {live[:12]} is not on mirklurk-wiki main", None)
    changed = git(repo, "diff", "--name-only", live, candidate, "--", "deploy").splitlines()
    if not changed:
        return Decision("current", None, "main has no deploy/ changes since the live revision", None)
    # Count from when main's deploy/ last diverged from the live tree, so a merge
    # that brought in the live revision itself, or a reverted change, does not age it.
    live_tree, diverged = git(repo, "rev-parse", f"{live}:deploy"), None
    for line in git(repo, "log", "--first-parent", "--reverse", "--format=%H %ct",
                    f"{live}..{candidate}", "--", "deploy").splitlines():
        commit, stamp = line.split()
        if git(repo, "rev-parse", f"{commit}:deploy") == live_tree:
            diverged = None
        elif diverged is None:
            diverged = int(stamp)
    since = live_since if diverged is None else diverged
    removed, added, hunk = [], [], False
    for line in git(repo, "diff", "--unified=0", "--no-color", "--no-ext-diff", live, candidate,
                    "--", "deploy/Dockerfile").splitlines():
        hunk = hunk or line.startswith("@@")
        if hunk and line[:1] == "-":
            removed.append(line[1:])
        elif hunk and line[:1] == "+":
            added.append(line[1:])
    old = BASE.fullmatch(removed[0]) if len(removed) == 1 else None
    new = BASE.fullmatch(added[0]) if len(added) == 1 else None
    if changed != ["deploy/Dockerfile"] or not old or not new:
        return Decision("blocked", since, "main changes deploy/ beyond the MediaWiki 1.43 base line", None)
    if version(new[1]) < version(old[1]):
        return Decision("blocked", since, f"main downgrades MediaWiki {old[1]} to {new[1]}", None)
    for line in git(repo, "show", f"{candidate}:deploy/Dockerfile").splitlines():
        words = line.split()
        if words and words[0].upper() in ("ADD", "COPY") and (words[0].upper() == "ADD" or any(
                not word.startswith(("deploy/", "--chown=", "--chmod=")) for word in words[1:-1])):
            return Decision("blocked", since, "deploy/Dockerfile reads files outside deploy/", None)
    return Decision("eligible", since, f"MediaWiki base {old[1]} to {new[1]}", added[0])


def checks_passed(sha):
    request = Request(CHECK_RUNS.format(sha),
                      headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            runs = json.load(response)["check_runs"]
    except (OSError, URLError, ValueError, KeyError) as error:
        raise ReleaseError("Could not read mirklurk-wiki CI results") from error
    latest = {}
    for check in runs:
        name = check.get("name")
        if name in REQUIRED_CHECKS and check.get("id", 0) >= latest.get(name, {}).get("id", 0):
            latest[name] = check
    return all(latest.get(name, {}).get("conclusion") == "success" for name in REQUIRED_CHECKS)


def build(repo, candidate):
    """Build the exact candidate from its clean clone, reusing an earlier night's build of it."""
    tag = f"{IMAGE_REPOSITORY}:auto-{candidate[:12]}"
    image = tag_target(tag)
    if image is None:
        git(repo, "checkout", "--quiet", "--detach", candidate)
        require(git(repo, "rev-parse", "HEAD") == candidate and not git(repo, "status", "--porcelain"),
                "Build checkout is not the exact clean candidate")
        command = ["docker", "build", "--progress=plain", "--file", str(Path(repo) / "deploy/Dockerfile"),
                   "--label", f"{SOURCE_LABEL}={SOURCE}", "--label", f"{REVISION_LABEL}={candidate}",
                   "--tag", tag, str(repo)]
        for attempt in (1, 2):
            # Public source and no build secrets: let the build log reach the journal.
            try:
                status = subprocess.run(command, timeout=1800).returncode
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ReleaseError("docker build unavailable or timed out") from error
            if status == 0:
                break
            require(attempt == 1, f"docker build failed for {candidate[:12]} (log above)")
            print("docker build failed; retrying once in 60 seconds.", flush=True)
            time.sleep(60)
        image = tag_target(tag)
    labels = (inspect(image, image=True)["Config"].get("Labels") or {}) if image else {}
    require(labels.get(REVISION_LABEL) == candidate and labels.get(SOURCE_LABEL) == SOURCE,
            f"{tag} provenance mismatch")
    return image


def schema_fingerprint(image):
    output = run("docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "33:33",
                 "--entrypoint", "sh", image, "-c", SCHEMA_FILES, timeout=300)
    files = {}
    for line in output.splitlines():
        digest, _, path = line.partition("  ")
        require(re.fullmatch(r"[0-9a-f]{64}", digest) and path, "Unexpected schema fingerprint output")
        files[path] = digest
    require("includes/installer/MysqlUpdater.php" in files, "Schema fingerprint is incomplete")
    return files


def schema_changes(live_image, image):
    """Paths whose change could require update.php, which unattended deploys never run."""
    old, new = schema_fingerprint(live_image), schema_fingerprint(image)
    return sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))


def retain():
    """Drop automatic build tags beyond the newest few. Never live, previous or manual release tags."""
    protected = {tag_target(LIVE_TAG), tag_target(PREVIOUS_TAG)}
    builds = []
    for row in run("docker", "image", "ls", "--no-trunc", "--format", "{{.Tag}} {{.ID}}",
                   IMAGE_REPOSITORY).splitlines():
        tag, _, image = row.partition(" ")
        if tag.startswith("auto-"):
            builds.append((inspect(image, image=True)["Created"], tag, image))
    for _created, tag, image in sorted(builds, reverse=True)[AUTO_KEEP:]:
        if image in protected:
            continue
        try:
            run("docker", "image", "rm", f"{IMAGE_REPOSITORY}:{tag}")
            print(f"Retention removed {IMAGE_REPOSITORY}:{tag}", flush=True)
        except ReleaseError:
            print(f"Retention kept {IMAGE_REPOSITORY}:{tag}: still in use", flush=True)


def overdue(decision, days):
    age = (time.time() - decision.since) / 86400
    require(age <= days, f"MirkLurk wiki base updates stalled for {age:.1f} days: {decision.reason}")
    print(f"Not alerting yet: {age:.1f} of {days} days.", flush=True)


def rejected():
    """Source revisions whose activation failed or was rolled back; never retried automatically."""
    try:
        return set((AUTO_STATE / "rejected").read_text().split())
    except FileNotFoundError:
        return set()


def image_input(repo, revision):
    """The deploy/ tree, which is everything an image is built from (None if unknown here)."""
    try:
        return git(repo, "rev-parse", f"{revision}:deploy")
    except ReleaseError:
        return None


def reject(source):
    try:
        with (AUTO_STATE / "rejected").open("a") as handle:
            handle.write(source + "\n")
    except OSError:
        print(f"Could not record {source} in {AUTO_STATE}/rejected", file=sys.stderr)


def deploy_automatically(source, image, previous):
    hold = AUTO_STATE / "hold"

    def write_hold(reason, flags):
        descriptor = os.open(hold, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | flags, 0o664)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps({"since": now_iso(), "reason": reason, "source": source,
                                     "image": image, "previous": previous}) + "\n")

    with locked(wait=600):
        # The timer's start condition does not stop a run already building.
        if os.path.lexists(DEPLOYMENT_HOLD):
            print(f"{DEPLOYMENT_HOLD} appeared; not activating.", flush=True)
            return
        require(inspect("mirklurk")["Image"] == previous, "The live wiki changed while the candidate was built")
        live, environment, mediawiki = preflight(CANONICAL, source, image, previous)
        # From here the frontend may change: an interrupted or failed activation keeps this hold.
        activation = lambda: write_hold("activation started but did not finish", os.O_EXCL)
        try:
            activate(CANONICAL, live, environment, image, mediawiki, on_activation=activation)
        except BaseException as error:
            if os.path.lexists(hold):
                message = str(error) if isinstance(error, ReleaseError) else f"unexpected {type(error).__name__}"
                write_hold(f"activation failed: {message}", os.O_TRUNC)
                reject(source)
            raise
        record("automatic", source, image, previous)
        if os.path.lexists(hold):
            hold.unlink()


def recover(root, source=None, image=None):
    """Attended recovery: serve a known image even when the current frontend is broken.

    Defaults to the predecessor recorded in the automatic updater's hold, which,
    unlike the movable tags, still names it if an earlier recovery stopped partway.
    """
    require(root.resolve() == CANONICAL, "Recovery is only allowed from /srv/homeserver")
    if image is None:
        try:
            image = json.loads((AUTO_STATE / "hold").read_text())["previous"]
        except (OSError, ValueError, KeyError) as error:
            raise ReleaseError("No hold names a predecessor; pass --image and --source") from error
    labels = inspect(image, image=True)["Config"].get("Labels") or {}
    source = source or labels.get(REVISION_LABEL, "")
    require(re.fullmatch(r"[0-9a-f]{40}", source) and re.fullmatch(r"sha256:[0-9a-f]{64}", image),
            "Expected full source SHA and image ID")
    require(source not in rejected(), f"{source[:12]} was rejected; remove it from {AUTO_STATE}/rejected to serve it")
    require(not git(root, "status", "--porcelain"), "Canonical checkout is not clean")
    require(labels.get(REVISION_LABEL) == source and labels.get(SOURCE_LABEL) == SOURCE,
            "Recovery image provenance mismatch")
    mediawiki = servable(image)
    service = json.loads(compose(root, "config", "--format", "json", "--no-env-resolution"))["services"]["mirklurk"]
    require(service["image"] == LIVE_TAG and service.get("profiles") == [PROFILE],
            f"Compose must run the helper-managed {LIVE_TAG} only in profile {PROFILE}")
    for name in ("mirklurk-db", "mirklurk-backup"):
        healthy(name)
    before = container_ids()
    replaced = tag_target(LIVE_TAG)
    if replaced and replaced != image:
        run("docker", "tag", replaced, PREVIOUS_TAG)
        revision = (inspect(replaced, image=True)["Config"].get("Labels") or {}).get(REVISION_LABEL)
        if revision and revision != source:
            reject(revision)
    run("docker", "tag", image, LIVE_TAG)
    compose(root, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "mirklurk",
            timeout=120)
    wait_healthy("mirklurk")
    require(inspect("mirklurk")["Image"] == image, "Running recovery image mismatch")
    public_acceptance(service["environment"], mediawiki)
    refresh_sitemap(root)
    require(container_ids() == before, "Other container identities changed; investigate")
    record("recovery", source, image, replaced)
    print(f"Recovered to {image}. Remove {AUTO_STATE}/hold once you are satisfied.", flush=True)


def auto_update(dry_run=False):
    """Deploy mirklurk-wiki main only when it differs from the live revision by the MediaWiki 1.43 base line."""
    status = {"checked_at": now_iso()}
    try:
        evaluate_and_deploy(dry_run, status)
        status["outcome"] = "ok"
    except BaseException as error:
        status["outcome"] = "failed: " + (str(error) if isinstance(error, ReleaseError) else type(error).__name__)
        raise
    finally:
        print("Status " + json.dumps(status), flush=True)
        if not dry_run:
            try:
                (AUTO_STATE / ".status.json").write_text(json.dumps(status, indent=2) + "\n")
                os.replace(AUTO_STATE / ".status.json", AUTO_STATE / "status.json")
            except OSError:
                print(f"Could not write {AUTO_STATE}/status.json", file=sys.stderr)


def evaluate_and_deploy(dry_run, status):
    require(dry_run or os.geteuid() == 0, "Unattended updates run as root from mirklurk-auto-update.service")
    hold = AUTO_STATE / "hold"
    if os.path.lexists(hold):
        message = f"Automatic wiki updates are held: {hold.read_text().strip()}. Recover, then delete {hold}"
        require(dry_run, message)
        print(message, flush=True)
    live = inspect("mirklurk")
    live_image = live["Image"]
    details = inspect(live_image, image=True)
    labels = details["Config"].get("Labels") or {}
    source = labels.get(REVISION_LABEL, "")
    require(labels.get(SOURCE_LABEL) == SOURCE and re.fullmatch(r"[0-9a-f]{40}", source),
            "The live wiki image lacks mirklurk-wiki source/revision labels")
    status.update(live_source=source, live_image=live_image)
    tagged = tag_target(LIVE_TAG)
    require(tagged in (None, live_image),
            f"{LIVE_TAG} does not name the running wiki image; an activation was interrupted or changed by hand")
    if tagged is None and not dry_run:
        run("docker", "tag", live_image, LIVE_TAG)
        print(f"Adopted the running image as {LIVE_TAG}.", flush=True)
    created = datetime.fromisoformat(re.sub(r"\.\d+", "", details["Created"]).replace("Z", "+00:00")).timestamp()
    with tempfile.TemporaryDirectory(prefix="mirklurk-wiki-", dir=None if dry_run else AUTO_STATE) as workspace:
        repo, candidate = clone_main(Path(workspace))
        decision = evaluate(repo, source, candidate, created)
        # Content-only commits do not change the image: compare inputs, not commit SHAs.
        if decision.kind == "eligible" and image_input(repo, candidate) in {
                image_input(repo, revision) for revision in rejected()} - {None}:
            decision = decision._replace(kind="blocked", reason=f"main {candidate[:12]} builds an image whose "
                                         "activation failed; it needs a deploy/ change or a manual release")
        status.update(main=candidate, decision=decision.kind, reason=decision.reason)
        print(f"Live {source[:12]} ({live_image}); main {candidate[:12]}: {decision.kind}, {decision.reason}",
              flush=True)
        if decision.kind == "blocked":
            overdue(decision, BLOCKED_STALL_DAYS)
        elif decision.kind == "eligible":
            if not checks_passed(candidate):
                print(f"Waiting for mirklurk-wiki CI ({', '.join(REQUIRED_CHECKS)}) on {candidate[:12]}.", flush=True)
                overdue(decision, ELIGIBLE_STALL_DAYS)
            else:
                release_candidate(repo, candidate, decision, live_image, dry_run, status)
    if not dry_run:
        retain()


def release_candidate(repo, candidate, decision, live_image, dry_run, status):
    image = build(repo, candidate)
    status["candidate_image"] = image
    if image == live_image:
        print("The candidate build is identical to the live image; nothing to deploy.", flush=True)
        return
    mediawiki = servable(image)
    require(decision.base.startswith(f"FROM mediawiki:{mediawiki}@"),
            "Built MediaWiki version does not match the FROM line")
    live_mediawiki, live_php = runtime(live_image)
    require(version(mediawiki) >= version(live_mediawiki) and version(runtime(image)[1]) >= version(live_php),
            "Candidate would downgrade MediaWiki or PHP")
    changed = schema_changes(live_image, image)
    require(not changed, f"MediaWiki {live_mediawiki} to {mediawiki} changes schema/updater files "
            f"({', '.join(changed[:5])}); it needs update.php, so release it manually")
    if dry_run:
        with locked():
            preflight(CANONICAL, candidate, image, live_image)
        print("Dry run: eligible; the nightly run would deploy this image.", flush=True)
    else:
        deploy_automatically(candidate, image, live_image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "deploy", "recover", "auto-update", "refresh-sitemap",
                                         "snapshot", "check-backups"))
    parser.add_argument("--checkout", type=Path, default=CANONICAL, help="Alternate checkout for preflight only")
    parser.add_argument("--source", help="Reviewed full wiki source commit")
    parser.add_argument("--image", help="Reviewed full candidate sha256 image ID")
    parser.add_argument("--previous-image", help="Retained /w/-compatible predecessor image ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="auto-update only: decide, build and preflight, but never deploy or write state")
    args = parser.parse_args()
    try:
        require(args.mode == "preflight" or args.checkout.resolve() == CANONICAL,
                "Alternate checkout is only allowed for preflight")
        require(not args.dry_run or args.mode == "auto-update", "--dry-run applies only to auto-update")
        if args.mode in ("preflight", "deploy"):
            require(args.source and args.image and args.previous_image, "Explicit source, image and predecessor required")
        if args.mode in ("snapshot", "auto-update"):
            def interrupted(signum, frame):
                raise ReleaseError(f"{args.mode} interrupted by signal {signum}")
            signal.signal(signal.SIGTERM, interrupted)
            signal.signal(signal.SIGINT, interrupted)
        if args.mode == "auto-update":
            # Builds run unlocked; only the activation takes the Compose lock.
            auto_update(args.dry_run)
            return 0
        with locked():
            if args.mode == "preflight":
                preflight(args.checkout, args.source, args.image, args.previous_image)
                print("No activation performed.")
            elif args.mode == "deploy":
                deploy(args.checkout, args.source, args.image, args.previous_image)
            elif args.mode == "recover":
                recover(args.checkout, args.source, args.image)
            elif args.mode == "refresh-sitemap":
                siteinfo(running_mediawiki())
                refresh_sitemap(args.checkout)
            elif args.mode == "snapshot":
                snapshot()
            else:
                check_backups()
    except (ReleaseError, OSError, ValueError, KeyError, ET.ParseError) as error:
        message = str(error) if isinstance(error, ReleaseError) else f"Unexpected {type(error).__name__}; inspect locally"
        print(f"MirkLurk release FAILED: {message}. No automatic rollback. If activation began, follow "
              "'Failures, holds and recovery' in docker/docs/MIRKLURK.md.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
