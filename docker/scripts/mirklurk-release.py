#!/usr/bin/env python3
"""Homeserver-only, runtime-only release and native sitemap refresh."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def run(*args, timeout=60):
    environment = dict(os.environ)
    if args[0] == "git":
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_SSH_COMMAND"] = environment.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes"
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=environment)
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
    require({v["target"] for v in volumes} == {"/var/www/html/images", "/var/www/html/branding", SITEMAP},
            "Unexpected application volume set")
    require(not service.get("ports") and "command" not in service and "entrypoint" not in service,
            "Unexpected application ports or startup override")
    for volume in volumes:
        require(volume["type"] == "bind" and volume["bind"]["create_host_path"] is False,
                "Unsafe application bind mount")
        require(Path(volume["source"]).is_dir(), f"Missing directory for {volume['target']}")
        if volume["target"] != SITEMAP:
            actual = actual_mounts.get(volume["target"], {})
            require(actual.get("Source") == volume["source"]
                    and actual.get("RW") == (not volume.get("read_only", False)),
                    f"Existing mount changed: {volume['target']}")
    for secret in service["secrets"]:
        target = "/run/secrets/" + secret["target"]
        require(actual_mounts.get(target, {}).get("Source") == config["secrets"][secret["source"]]["file"],
                "Existing secret mount changed (values suppressed)")
    expected_mounts = {v["target"] for v in volumes} | {
        "/run/secrets/" + secret["target"] for secret in service["secrets"]}
    require(set(actual_mounts) - {SITEMAP} == expected_mounts - {SITEMAP},
            "Existing mount set changed")
    expected_networks = {config["networks"][name]["name"] for name in service["networks"]}
    require(set(live["NetworkSettings"]["Networks"]) == expected_networks, "Application networks changed")
    storage = Path(next(v["source"] for v in volumes if v["target"] == SITEMAP))
    for folder in (storage, storage / "public"):
        st = folder.stat()
        require(not folder.is_symlink() and (st.st_uid, st.st_gid, st.st_mode & 0o777) == (33, 33, 0o755),
                f"Sitemap directory must be UID/GID 33, mode 0755: {folder}")
    if live["Image"] == image:
        require(actual_mounts.get(SITEMAP, {}).get("Source") == str(storage),
                "Candidate is running without the reviewed sitemap mount")
    for name in ("mirklurk", "mirklurk-db", "mirklurk-backup"):
        healthy(name)
        if name != "mirklurk":
            require(inspect(name)["Config"]["Image"] == config["services"][name]["image"],
                    f"{name} pin differs from the running service")
    headroom(storage)
    siteinfo()
    print(f"Preflight OK: source={source} image={image}; live={live['Image']}", flush=True)
    return live, environment


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
    parser.add_argument("mode", choices=("preflight", "deploy", "refresh-sitemap"))
    parser.add_argument("--checkout", type=Path, default=CANONICAL, help="Alternate checkout for preflight only")
    parser.add_argument("--source", help="Reviewed full wiki source commit")
    parser.add_argument("--image", help="Reviewed full candidate sha256 image ID")
    parser.add_argument("--previous-image", help="Retained /w/-compatible predecessor image ID")
    args = parser.parse_args()
    try:
        require(args.mode == "preflight" or args.checkout.resolve() == CANONICAL,
                "Alternate checkout is only allowed for preflight")
        if args.mode != "refresh-sitemap":
            require(args.source and args.image and args.previous_image, "Explicit source, image and predecessor required")
        with locked():
            if args.mode == "preflight":
                preflight(args.checkout, args.source, args.image, args.previous_image)
                print("No activation performed. Pause updater BEFORE merge; preflight is not a merge lock.")
            elif args.mode == "deploy":
                deploy(args.checkout, args.source, args.image, args.previous_image)
            else:
                siteinfo()
                refresh_sitemap(args.checkout)
    except (ReleaseError, OSError, ValueError, KeyError, ET.ParseError) as error:
        message = str(error) if isinstance(error, ReleaseError) else f"Unexpected {type(error).__name__}; inspect locally"
        print(f"MirkLurk release FAILED: {message}. No automatic rollback. "
              "If activation began, keep updater paused and follow the reviewed recovery runbook.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
