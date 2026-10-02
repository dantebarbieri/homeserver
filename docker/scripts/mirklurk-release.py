#!/usr/bin/env python3
"""Homeserver-only, runtime-only release and native sitemap refresh."""

import argparse
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
USER_AGENT = "MirkLurkDeploymentCheck/1.0"
SITEMAP = "/var/lib/mirklurk-sitemap"
BACKUP_CONTROL = "/var/lib/mirklurk-backup"
DATA = Path("/srv/docker/data/mirklurk")
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def run(*args, timeout=60, input=None):
    environment = dict(os.environ)
    if args[0] == "git":
        environment["GIT_TERMINAL_PROMPT"] = "0"
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
        "--file", str(root / "docker/docker-compose.yml"), *args, timeout=timeout,
    )


def inspect(name, image=False):
    args = ("docker", "image", "inspect", name) if image else ("docker", "inspect", name)
    return json.loads(run(*args))[0]


def healthy(name):
    state = inspect(name)["State"]
    require(state["Running"] and state.get("Health", {}).get("Status") == "healthy",
            f"{name} is not running and healthy")


def updater_paused():
    for unit in ("docker-compose-update.timer", "docker-compose-update.service"):
        require(run("systemctl", "show", unit, "--property=ActiveState", "--value") == "inactive",
                f"{unit} must be inactive; coordinate the merge window first")


@contextmanager
def locked():
    import fcntl

    # Open the existing root-owned lock read-only; do not replace its inode.
    with LOCK.open("r") as handle:
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, "Compose lock busy for 30 seconds")
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


def siteinfo():
    data = json.loads(get("/api.php?action=query&meta=siteinfo&siprop=general&format=json"))
    general = data["query"]["general"]
    require(general["server"] == ORIGIN and general["scriptpath"] == ""
            and general["articlepath"] == "/w/$1"
            and general["generator"] == "MediaWiki 1.43.9"
            and "readonly" not in general, "Unexpected live origin, paths, version or read-only policy")


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
    require(not run("git", "-C", str(root), "status", "--porcelain"), "Checkout is not clean")
    if root.resolve() == CANONICAL:
        compose(root, "config", "--quiet")
    # Other stacks' env_file contents are not needed to verify this app.
    config = json.loads(compose(root, "config", "--format", "json", "--no-env-resolution"))
    service = config["services"]["mirklurk"]
    require(service["image"] == image and service["pull_policy"] == "never"
            and "build" not in service, "Candidate does not match reviewed Compose image pin")
    require(service.get("labels", {}).get("org.opencontainers.image.revision") == source,
            "Source SHA does not match reviewed Compose revision label")
    candidate = inspect(image, image=True)
    labels = candidate["Config"].get("Labels", {})
    require(candidate["Id"] == image and labels.get("org.opencontainers.image.revision") == source
            and labels.get("org.opencontainers.image.source") == SOURCE, "Candidate provenance mismatch")
    predecessor = inspect(previous, image=True)
    require(predecessor["Id"] == previous
            and predecessor["Config"].get("Labels", {}).get("org.opencontainers.image.source") == SOURCE,
            "Retained predecessor is missing or has unexpected provenance")
    live = inspect("mirklurk")
    require(live["Image"] in (previous, image), "Live image is neither expected predecessor nor candidate")
    require(live["Config"]["Labels"].get("com.docker.compose.project") == "compose",
            "Unexpected live Compose project")
    environment = service["environment"]
    require(environment["MW_SERVER_URL"] == ORIGIN and environment["MW_READ_ONLY"] == "",
            "Canonical origin or literal empty MW_READ_ONLY was changed")
    live_env = dict(value.split("=", 1) for value in live["Config"]["Env"])
    require({key: value for key, value in live_env.items() if key.startswith("MW_")} == environment,
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
    siteinfo()
    for folder in (storage, storage / "public"):
        require(folder.is_dir(), f"Missing sitemap directory: {folder}")
        st = folder.stat()
        require(not folder.is_symlink() and (st.st_uid, st.st_gid) == (33, 33)
                and stat.S_IMODE(st.st_mode) in (0o755, 0o2755),
                f"Sitemap directory must be UID/GID 33, mode 0755 or 2755: {folder}")
    print(f"Preflight OK: source={source} image={image}; live={live['Image']}", flush=True)
    return live, environment


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


def public_acceptance(environment):
    siteinfo()
    html = get("/w/Items").decode()
    require('name="viewport"' in html and "width=device-width" in html, "Responsive viewport missing")
    require('property="og:url" content="https://mirklurk.wiki/w/Items"' in html,
            "Canonical Items metadata missing")
    require('property="og:title"' in html, "Article metadata missing")
    get("/load.php?lang=en&modules=site.styles&only=styles&skin=vector-2022")
    for key in ("MW_LOGO_URL", "MW_LOGO_ICON_URL", "MW_FAVICON_URL"):
        if environment[key]:
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


def deploy(root, source, image, previous):
    require(root.resolve() == CANONICAL, "Activation is only allowed from /srv/homeserver")
    require(Path(__file__).resolve() == CANONICAL / "docker/scripts/mirklurk-release.py",
            "Run the merged helper from the canonical checkout")
    updater_paused()
    require(run("git", "-C", str(root), "branch", "--show-current") == "main", "Canonical branch must be main")
    require(not run("git", "-C", str(root), "status", "--porcelain"), "Canonical checkout is not clean")
    script = Path(__file__).read_bytes()
    run("git", "-C", str(root), "pull", "--ff-only", "origin", "main", timeout=120)
    require(Path(__file__).read_bytes() == script, "Release helper changed during pull; rerun the updated command")
    require(run("git", "-C", str(root), "rev-parse", "HEAD")
            == run("git", "-C", str(root), "rev-parse", "origin/main"), "Checkout is not fetched origin/main")
    live, environment = preflight(root, source, image, previous)
    before = container_ids()
    if live["Image"] != image:
        check_backups()
        run("docker", "exec", "mirklurk-backup", "timeout", "--kill-after=5s", "280s",
            "bash", "/opt/mirklurk-backup.sh", "--once", timeout=300)
        run("docker", "exec", "mirklurk-backup", "bash", "/opt/mirklurk-backup.sh", "--healthcheck")
        updater_paused()
        started = time.monotonic()
        with availability_monitor():
            compose(root, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "mirklurk", timeout=120)
            deadline = time.monotonic() + 120
            while inspect("mirklurk")["State"].get("Health", {}).get("Status") != "healthy":
                require(time.monotonic() < deadline, "Application readiness timeout")
                time.sleep(2)
            require(inspect("mirklurk")["Image"] == image, "Running candidate image mismatch")
            public_acceptance(environment)
        print(f"Activation-to-readiness upper bound: {time.monotonic() - started:.1f}s", flush=True)
    else:
        print("Candidate already active: no recreation or backup repeated.", flush=True)
        public_acceptance(environment)
    refresh_sitemap(root)
    require(container_ids() == before, "Other container identities changed; investigate before acceptance")
    print("Runtime accepted; content was not published/restored. Resume updater only after operator acceptance.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "deploy", "refresh-sitemap", "snapshot", "check-backups"))
    parser.add_argument("--checkout", type=Path, default=CANONICAL, help="Alternate checkout for preflight only")
    parser.add_argument("--source", help="Reviewed full wiki source commit")
    parser.add_argument("--image", help="Reviewed full candidate sha256 image ID")
    parser.add_argument("--previous-image", help="Retained /w/-compatible predecessor image ID")
    args = parser.parse_args()
    try:
        require(args.mode == "preflight" or args.checkout.resolve() == CANONICAL,
                "Alternate checkout is only allowed for preflight")
        if args.mode in ("preflight", "deploy"):
            require(args.source and args.image and args.previous_image, "Explicit source, image and predecessor required")
        if args.mode == "snapshot":
            def interrupted(signum, frame):
                raise ReleaseError(f"Snapshot interrupted by signal {signum}")
            signal.signal(signal.SIGTERM, interrupted)
            signal.signal(signal.SIGINT, interrupted)
        with locked():
            if args.mode == "preflight":
                preflight(args.checkout, args.source, args.image, args.previous_image)
                print("No activation performed. Pause updater BEFORE merge; preflight is not a merge lock.")
            elif args.mode == "deploy":
                deploy(args.checkout, args.source, args.image, args.previous_image)
            elif args.mode == "refresh-sitemap":
                siteinfo()
                refresh_sitemap(args.checkout)
            elif args.mode == "snapshot":
                snapshot()
            else:
                check_backups()
    except (ReleaseError, OSError, ValueError, KeyError, ET.ParseError) as error:
        message = str(error) if isinstance(error, ReleaseError) else f"Unexpected {type(error).__name__}; inspect locally"
        print(f"MirkLurk release FAILED: {message}. No automatic rollback. "
              "If activation began, keep updater paused and follow the reviewed recovery runbook.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
