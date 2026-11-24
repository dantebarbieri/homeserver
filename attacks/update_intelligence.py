"""Refresh public bulk datasets; never transmit observed addresses or log events."""

import argparse
from datetime import datetime, timezone
import gzip
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler, Request

import maxminddb

from networks import FEEDS, prefix


LOG = logging.getLogger("attacks-intelligence")
OPENER = build_opener(ProxyHandler({}))


def fetch(url):
    with OPENER.open(Request(url, headers={"User-Agent": "homeserver-attacks/1.0"}), timeout=60) as response:
        body = response.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise ValueError("Dataset download exceeds 64 MiB")
        return body.decode("utf-8")


def ranges(name, download=fetch):
    url = FEEDS[name][2]
    if name == "azure":
        links = re.findall(r'https://download\.microsoft\.com/download/[^"\'<>\s]+/ServiceTags_Public_\d{8}\.json', download(url))
        if not links:
            raise ValueError("Microsoft download page has no recognized public service-tag link")
        data = json.loads(download(sorted(set(links))[-1]))
        values = [value for record in data["values"] if record["name"] == "AzureCloud"
                  for value in record["properties"]["addressPrefixes"]]
    elif name == "nordvpn":
        values, seen = [], set()
        for offset in range(0, 32000, 1000):
            page = json.loads(download(f"{url}?limit=1000&offset={offset}"))
            if not isinstance(page, list):
                raise ValueError("Unexpected NordVPN server list")
            ids = {record["id"] for record in page}
            if page and ids <= seen:
                raise ValueError("NordVPN pagination repeated a page")
            seen.update(ids)
            values.extend(record[key] for record in page if record["status"] == "online"
                          for key in ("station", "ipv6_station") if record.get(key))
            if len(page) < 1000:
                break
        else:
            raise ValueError("NordVPN server list exceeds page budget")
    elif name == "tor":
        values = [line.strip() for line in download(url).splitlines() if line.strip() and not line.startswith("#")]
    else:
        data = json.loads(download(url))
        if name == "aws":
            values = [record["ip_prefix"] for record in data["prefixes"]]
            values += [record["ipv6_prefix"] for record in data["ipv6_prefixes"]]
        elif name == "google":
            values = [record.get("ipv4Prefix") or record["ipv6Prefix"] for record in data["prefixes"]]
        elif name == "oracle":
            values = [record["cidr"] for region in data["regions"] for record in region["cidrs"]]
        elif name == "mullvad":
            values = [record[key] for record in data if record["active"]
                      for key in ("ipv4_addr_in", "ipv6_addr_in") if record.get(key)]
        else:
            raise ValueError("Unknown network dataset")
    if not values or len(values) > 250000:
        raise ValueError("Empty or oversized network dataset")
    return sorted({str(prefix(value)) for value in values})


def atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".intelligence-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(data, target, allow_nan=False)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh_prefixes(directory, download=fetch):
    path = Path(directory) / "networks.json"
    data = {"version": 1, "feeds": {}}
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved["version"] != 1 or not isinstance(saved["feeds"], dict):
                raise ValueError("Unexpected snapshot format")
            data = saved
        except (ValueError, KeyError, TypeError) as error:
            LOG.error("Discarding invalid network snapshot: %s", error)
    success = True
    for name in FEEDS:
        try:
            values = ranges(name, download)
            data["feeds"][name] = {"checkedAt": time.time(), "networks": values}
            LOG.info("%s: refreshed %d prefixes / addresses", name, len(values))
        except (OSError, ValueError, KeyError, TypeError) as error:
            success = False
            data["feeds"].setdefault(name, {})["error"] = f"{type(error).__name__}: {error}"
            LOG.error("%s: refresh failed; previous timestamp retained: %s", name, error)
    atomic_json(path, data)
    return success


def refresh_database(directory, kind):
    filename = {"city": "GeoIP.mmdb", "asn": "ASN.mmdb"}[kind]
    destination = Path(directory) / filename
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    release_path = Path(directory) / "database-releases.json"
    releases = {}
    if release_path.exists():
        try:
            releases = json.loads(release_path.read_text(encoding="utf-8"))
            if not isinstance(releases, dict):
                raise ValueError("Invalid database release metadata")
        except ValueError as error:
            LOG.error("Discarding invalid release metadata: %s", error)
            releases = {}
    if destination.exists():
        try:
            with maxminddb.open_database(str(destination)) as reader:
                valid = kind in reader.metadata().database_type.lower()
        except (ValueError, maxminddb.InvalidDatabaseError) as error:
            LOG.error("%s: replacing an invalid local database: %s", kind, error)
            valid = False
        if valid and releases.get(kind) == month:
            LOG.info("%s: current monthly release already installed", kind)
            return
    url = f"https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"
    fd, temporary = tempfile.mkstemp(prefix=".mmdb-", dir=directory)
    try:
        request = Request(url, headers={"User-Agent": "homeserver-attacks/1.0"})
        with os.fdopen(fd, "wb") as target, OPENER.open(request, timeout=60) as response:
            with gzip.GzipFile(fileobj=response) as stream:
                total = 0
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > 512 * 1024 * 1024:
                        raise ValueError("MMDB exceeds 512 MiB")
                    target.write(chunk)
        with maxminddb.open_database(temporary) as reader:
            if kind not in reader.metadata().database_type.lower():
                raise ValueError(f"Expected a {kind} MMDB")
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
        releases[kind] = month
        atomic_json(release_path, releases)
        LOG.info("%s: installed DB-IP Lite %s", kind, month)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    success = refresh_prefixes(directory)
    for kind in ("city", "asn"):
        try:
            refresh_database(directory, kind)
        except (OSError, ValueError, EOFError, URLError, maxminddb.InvalidDatabaseError) as error:
            success = False
            LOG.error("%s: database refresh failed: %s", kind, error)
    return 0 if success else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    raise SystemExit(main(parser.parse_args().directory))
