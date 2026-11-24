"""Offline network ownership and narrowly evidenced relay associations."""

import ipaddress
import json
import logging
import math
from pathlib import Path
import re
import time

import maxminddb

from events import public, text


LOG = logging.getLogger("attacks")
FEEDS = {
    "aws": ("AWS", "cloud", "https://ip-ranges.amazonaws.com/ip-ranges.json"),
    "azure": ("Azure", "cloud", "https://www.microsoft.com/en-us/download/details.aspx?id=56519"),
    "google": ("Google Cloud", "cloud", "https://www.gstatic.com/ipranges/cloud.json"),
    "oracle": ("Oracle Cloud", "cloud", "https://docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json"),
    "mullvad": ("Mullvad", "vpn_server", "https://api.mullvad.net/www/relays/all/"),
    "nordvpn": ("NordVPN", "vpn_server", "https://api.nordvpn.com/v1/servers"),
    "tor": ("Tor", "tor_exit", "https://check.torproject.org/torbulkexitlist"),
}
PRIVACY_EVIDENCE = {
    "vpn_server": "Provider-listed VPN server address. The entry-server list does not prove that this request used a VPN exit.",
    "tor_exit": "Address appeared in the Tor Project's exit list. This does not identify a person or establish malicious intent.",
}


def prefix(value):
    network = ipaddress.ip_network(value, strict=True)
    if not network.is_global or network.prefixlen == 0:
        raise ValueError("Expected a public network prefix")
    return network


class Networks:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.reader = None
        self.modified = None
        self.index = {4: {}, 6: {}}
        self.checked = {}
        self.status = {"asn": {"state": "unavailable", "message": "Local ASN database not installed"},
                       "feeds": {}}

    def reload(self):
        try:
            path = self.directory / "ASN.mmdb"
            modified = path.stat().st_mtime
            if modified != self.modified:
                reader = maxminddb.open_database(str(path))
                if self.reader:
                    self.reader.close()
                self.reader, self.modified = reader, modified
            built = self.reader.metadata().build_epoch
            stale = time.time() - built > 62 * 86400
            self.status["asn"] = {
                "state": "stale" if stale else "ready", "updatedAt": built,
                "message": "ASN database is over 62 days old" if stale else "Offline DB-IP ASN ownership",
            }
        except (OSError, ValueError, maxminddb.InvalidDatabaseError) as error:
            if self.reader:
                self.reader.close()
            self.reader, self.modified = None, None
            self.status["asn"] = {"state": "unavailable", "message": f"ASN unavailable ({type(error).__name__})"}
            LOG.warning(self.status["asn"]["message"])
        self.reload_prefixes()

    def reload_prefixes(self):
        now = time.time()
        try:
            path = self.directory / "networks.json"
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Network snapshot exceeds limit")
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["version"] != 1 or not isinstance(data["feeds"], dict):
                raise ValueError("Unexpected network snapshot format")
            index, checked, statuses = {4: {}, 6: {}}, {}, {}
            for name, (label, kind, _) in FEEDS.items():
                record = data["feeds"].get(name, {})
                updated = record.get("checkedAt", 0)
                if not isinstance(updated, (int, float)) or not math.isfinite(updated) or not 0 <= updated <= now + 300:
                    raise ValueError("Invalid network snapshot timestamp")
                networks = record.get("networks", [])
                if not isinstance(networks, list) or len(networks) > 250000:
                    raise ValueError("Invalid network prefix list")
                expired = now - updated > (7 if kind == "cloud" else 2) * 86400
                state = "unavailable" if not networks else "stale" if expired else "error" if record.get("error") else "ready"
                message = (record.get("error") or
                           ("Dataset expired; associations withheld" if expired and networks else
                            "Dataset not installed" if not networks else f"{len(networks):,} published prefixes / addresses"))
                statuses[name] = {"state": state, "message": text(str(message), 240), "updatedAt": updated}
                if expired or not networks:
                    continue
                checked[name] = updated
                for value in networks:
                    network = prefix(value)
                    table = index[network.version].setdefault(network.prefixlen, {})
                    table.setdefault(int(network.network_address), []).append(name)
            self.index, self.checked = index, checked
            self.status["feeds"] = statuses
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.index, self.checked = {4: {}, 6: {}}, {}
            message = f"Network datasets unavailable ({type(error).__name__})"
            self.status["feeds"] = {name: {"state": "unavailable", "message": message} for name in FEEDS}
            LOG.warning(message)

    def enrich(self, item):
        if not public(item["ip"]):
            return {**item, "networkLookup": "not-public"}
        result = {**item, "networkLookup": "partial" if self.reader or self.checked else "unavailable"}
        if self.reader:
            try:
                record = self.reader.get(item["ip"]) or {}
            except (ValueError, maxminddb.InvalidDatabaseError) as error:
                self.reader.close()
                self.reader, self.modified = None, None
                self.status["asn"] = {"state": "unavailable", "message": f"ASN lookup failed ({type(error).__name__})"}
                LOG.error(self.status["asn"]["message"])
                record = {}
                result["networkLookup"] = "partial" if self.checked else "unavailable"
            asn = record.get("autonomous_system_number")
            organization = record.get("autonomous_system_organization")
            if isinstance(asn, int) and not isinstance(asn, bool) and 0 < asn < 2**32:
                result["asn"] = asn
            if isinstance(organization, str) and organization:
                result["networkOrganization"] = text(organization, 160)
                if re.search(r"\bvercel\b", organization, re.I):
                    result["networkProvider"] = "Vercel"
            if self.reader:
                result["asnUpdatedAt"] = self.status["asn"]["updatedAt"]
        address = ipaddress.ip_address(item["ip"])
        matches = {}
        for bits, table in sorted(self.index[address.version].items(), reverse=True):
            shift = address.max_prefixlen - bits
            base = int(address) >> shift << shift
            for name in table.get(base, []):
                matches.setdefault(name, str(ipaddress.ip_network((address.__class__(base), bits))))
        clouds = [name for name in matches if FEEDS[name][1] == "cloud"]
        if clouds:
            result.update(
                networkProvider=" / ".join(FEEDS[name][0] for name in clouds),
                networkEvidence="Published ranges: " + "; ".join(f"{FEEDS[name][0]} {matches[name]}" for name in clouds),
                networkUpdatedAt=min(self.checked[name] for name in clouds),
                networkSources=[FEEDS[name][2] for name in clouds],
            )
        result["privacyServices"] = [
            {"name": FEEDS[name][0], "kind": FEEDS[name][1], "source": FEEDS[name][2],
             "evidence": PRIVACY_EVIDENCE[FEEDS[name][1]], "updatedAt": self.checked[name]}
            for name in matches if FEEDS[name][1] in PRIVACY_EVIDENCE
        ]
        if self.status["asn"]["state"] == "ready" and all(
                self.status["feeds"].get(name, {}).get("state") == "ready" for name in FEEDS):
            result["networkLookup"] = "ready"
        return result
