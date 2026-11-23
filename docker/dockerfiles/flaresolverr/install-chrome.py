"""Install Chrome for Testing stable and its matching chromedriver into FlareSolverr.

Usage: install-chrome.py <last-known-good-versions-with-downloads.json> <minimum version>

Chrome and chromedriver come from the same versioned directory, so they cannot drift apart.
"""
import io
import json
import os
import sys
import urllib.request
import zipfile

CHROME_DIR = "/opt/chrome"
DRIVER_PATH = "/app/chromedriver"
HOST = "https://storage.googleapis.com/chrome-for-testing-public/"


def version_key(version):
    return tuple(int(part) for part in version.split("."))


def linux64_url(downloads, kind, version):
    urls = [item["url"] for item in downloads[kind] if item["platform"] == "linux64"]
    if len(urls) != 1 or not urls[0].startswith(f"{HOST}{version}/"):
        sys.exit(f"Unexpected {kind} download for {version}: {urls}")
    return urls[0]


def fetch_zip(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return zipfile.ZipFile(io.BytesIO(response.read()))


def extract(archive, destination):
    root = os.path.realpath(destination) + os.sep
    for member in archive.infolist():
        if not os.path.realpath(os.path.join(destination, member.filename)).startswith(root):
            sys.exit(f"Refusing to extract outside {destination}: {member.filename}")
    archive.extractall(destination)


def main(catalog_path, minimum):
    with open(catalog_path, encoding="utf-8") as catalog:
        stable = json.load(catalog)["channels"]["Stable"]
    version = stable["version"]
    if version_key(version) < version_key(minimum):
        sys.exit(f"Chrome for Testing stable {version} is older than {minimum}")

    extract(fetch_zip(linux64_url(stable["downloads"], "chrome", version)), "/opt")
    os.rename("/opt/chrome-linux64", CHROME_DIR)
    for name in ("chrome", "chrome_crashpad_handler"):
        os.chmod(os.path.join(CHROME_DIR, name), 0o755)

    extract(fetch_zip(linux64_url(stable["downloads"], "chromedriver", version)), "/tmp")
    os.replace("/tmp/chromedriver-linux64/chromedriver", DRIVER_PATH)
    os.chmod(DRIVER_PATH, 0o755)
    print(f"Installed Chrome and chromedriver {version}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
