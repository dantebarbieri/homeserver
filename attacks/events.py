"""Conservative source-specific parsers. Never retain raw messages or credentials."""

from datetime import datetime
import hashlib
import ipaddress
import json
import math
import re
import shlex
from urllib.parse import unquote


KINDS = {
    "endlessh_open": ("endlessh", "Stuck in Endlessh", "observed"),
    "endlessh_close": ("endlessh", "Left Endlessh", "observed"),
    "ssh_failure": ("ssh", "SSH authentication failed", "failure"),
    "ssh_accepted": ("ssh", "SSH login accepted", "accepted"),
    "ssh_accepted_unknown": ("ssh", "SSH accepted: unregistered credential", "accepted"),
    "ssh_disconnect": ("ssh", "SSH disconnected before login", "incomplete"),
    "ssh_probe": ("ssh", "Targeted real SSH port", "unclassified"),
    "ssh_ban": ("ssh", "Banned by fail2ban", "blocked"),
    "auth_failure": ("authelia", "Authelia sign-in failed", "failure"),
    "http_probe": ("web", "Suspicious web request", "suspected"),
    "http_denied": ("web", "HTTP access denied", "unclassified"),
    "service_connection": ("service", "Service connection", "unclassified"),
}
REASONS = {
    "endlessh_open": "Endlessh logged ACCEPT on the decoy SSH service; this does not establish a human attacker's intent.",
    "endlessh_close": "Endlessh logged CLOSE and the completed connection duration.",
    "ssh_failure": "sshd reported an invalid username or a rejected authentication attempt.",
    "ssh_accepted": "sshd accepted this credential. A recognized public key identifies the credential, not the person using it.",
    "ssh_accepted_unknown": "sshd accepted a credential absent from this dashboard's Nix-managed key registry. Runtime authorized_keys files or certificates may legitimately authorize it; investigate rather than assuming compromise.",
    "ssh_disconnect": "sshd logged a pre-authentication disconnect. This alone does not establish a rejection or an attempted authentication method.",
    "ssh_probe": "An inbound packet targeted the real SSH port, or sshd logged a failed protocol handshake. This does not prove a successful connection or login.",
    "ssh_ban": "The sshd fail2ban jail recorded a ban under its configured retry threshold.",
    "auth_failure": "Authelia explicitly logged an unsuccessful authentication attempt, not an ordinary login-page redirect.",
    "http_probe": "The requested path matches a common credential-file, exploit, or administration-endpoint probe pattern.",
    "http_denied": "NPM returned HTTP 401, 403, or 429. This can be legitimate unauthenticated traffic.",
    "service_connection": "An inbound TCP SYN or representative UDP datagram reached a configured service port; no payload was analyzed.",
}
PORTS = {
    28: ("ssh", "SSH"), 2222: ("git", "Forgejo SSH"),
    32400: ("plex", "Plex"), 8324: ("plex", "Plex companion"),
    32469: ("plex", "Plex DLNA"),
    36676: ("minecraft", "Minecraft"), 36677: ("minecraft", "RLCraft"),
    5205: ("game", "Hytale"), 7778: ("game", "Satisfactory"),
    8888: ("game", "Satisfactory"),
}
TYPES = frozenset({"endlessh", "ssh", "authelia", "web", "git", "plex", "minecraft", "game"})
VERDICTS = frozenset(value[2] for value in KINDS.values())
NPM = re.compile(
    r'^\[(?P<time>[^]]+)\] \S+ \S+ (?P<status>\d{3}) - '
    r'(?P<method>[A-Z]+) (?P<scheme>https?) (?P<host>\S+) "(?P<path>[^"]*)" '
    r'\[Client (?P<ip>[^]]+)\]'
)
PROBE = re.compile(
    r"(?i)(?:^|/)(?:\.env(?:[./]|$)|\.git(?:/|$)|wp-login\.php|xmlrpc\.php|"
    r"phpmyadmin(?:/|$)|vendor/phpunit|cgi-bin/(?:.*)|actuator(?:/|$))|"
    r"(?:\.\./|/etc/passwd|/proc/self/)"
)


def text(value, limit=160):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value))[:limit]


def address(value):
    try:
        ip = ipaddress.ip_address(str(value).strip("[]"))
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return str(ip)
    except ValueError:
        return None


def public(value):
    ip = ipaddress.ip_address(value)
    return ip.is_global and not ip.is_multicast


def event(kind, ip, timestamp, **fields):
    ip = address(ip)
    if not ip or kind not in KINDS or not math.isfinite(timestamp):
        return None
    category, title, verdict = KINDS[kind]
    return {"timestamp": timestamp, "kind": kind, "type": category, "reason": REASONS[kind],
            "title": title, "verdict": verdict, "ip": ip, **fields}


def parse_endlessh(line, timestamp):
    match = re.search(r"\b(ACCEPT|CLOSE) host=(\S+) port=(\d+)(.*)", line)
    if not match:
        return None
    action, ip, port, tail = match.groups()
    ip = address(ip)
    if not ip or not public(ip):
        return None
    fields = {"service": "Endlessh", "port": 22, "sourcePort": int(port)}
    if action == "CLOSE":
        duration = re.search(r"\btime=([\d.]+)\b", tail)
        if duration:
            value = float(duration[1])
            if math.isfinite(value) and value >= 0:
                fields["duration"] = value
    return event("endlessh_open" if action == "ACCEPT" else "endlessh_close", ip, timestamp, **fields)


def parse_ssh(line, timestamp):
    accepted = re.search(r"Accepted (\S+) for (.+?) from (\S+) port (\d+)", line)
    if accepted:
        fingerprint = re.search(r"\b(SHA256:[A-Za-z0-9+/=]+|MD5:[a-f0-9:]+)", line)
        return event("ssh_accepted", accepted[3], timestamp, service="SSH", port=28,
                     user=text(accepted[2], 64), sourcePort=int(accepted[4]),
                     authMethod=text(accepted[1], 32),
                     keyFingerprint=fingerprint[1] if fingerprint else None)
    invalid = re.search(r"Invalid user (.+?) from (\S+) port (\d+)", line)
    if invalid:
        return event("ssh_failure", invalid[2], timestamp, service="SSH", port=28,
                     user=text(invalid[1], 64), sourcePort=int(invalid[3]),
                     rejectionReason="Username does not exist", authMethod="unknown")
    failed = re.search(r"Failed (\S+) for (invalid user )?(.+?) from (\S+) port (\d+)", line)
    if failed:
        reason = "Username does not exist; authentication rejected" if failed[2] else {
            "publickey": "Public key rejected", "password": "Password authentication rejected",
            "keyboard-interactive/pam": "Interactive authentication rejected",
        }.get(failed[1], "Authentication rejected")
        return event("ssh_failure", failed[4], timestamp, service="SSH", port=28,
                     user=text(failed[3], 64), sourcePort=int(failed[5]),
                     authMethod=text(failed[1], 32), rejectionReason=reason)
    exceeded = re.search(r"maximum authentication attempts exceeded for (?:invalid user )?(.+?) from (\S+) port (\d+)", line)
    if exceeded:
        return event("ssh_failure", exceeded[2], timestamp, service="SSH", port=28,
                     user=text(exceeded[1], 64), sourcePort=int(exceeded[3]),
                     rejectionReason="Maximum authentication attempts exceeded", authMethod="unknown")
    disconnected = re.search(r"(?:Connection (?:closed|reset) by|Disconnected from) (?:(?:invalid|authenticating) user (.+?) )?(\S+) port (\d+).*\[preauth\]", line)
    if disconnected:
        return event("ssh_disconnect", disconnected[2], timestamp, service="SSH", port=28,
                     user=text(disconnected[1], 64) if disconnected[1] else None,
                     sourcePort=int(disconnected[3]), authMethod="unknown")
    # Generic established-session disconnects and PQ warnings are not failures.
    match = re.search(r"(?:banner exchange|kex_exchange_identification):.*(?:from|with) (\S+) port (\d+)", line)
    if match:
        return event("ssh_probe", match[1], timestamp, port=28, service="SSH",
                     sourcePort=int(match[2]))
    return None


def parse_fail2ban(line, timestamp):
    match = re.search(r"\[sshd\]\s+Ban (\S+)", line)
    return event("ssh_ban", match[1], timestamp, port=28, service="SSH") if match else None


def parse_authelia(line, timestamp):
    try:
        if line.startswith("{"):
            fields = json.loads(line)
        else:
            fields = dict(item.split("=", 1) for item in shlex.split(line) if "=" in item)
    except (ValueError, TypeError):
        return None
    if not isinstance(fields, dict):
        return None
    message = str(fields.get("msg", fields.get("message", "")))
    # Authorization redirects to the login page are NOT failed sign-ins.
    match = re.search(r"Unsuccessful (.+?) authentication attempt by user ['\"](.*?)['\"]", message, re.I)
    if not match:
        return None
    return event("auth_failure", fields.get("remote_ip"), timestamp,
                 service="Authelia", port=443, user=text(match[2], 64),
                 factor=text(match[1], 32))


def parse_npm(line):
    match = NPM.match(line)
    if not match:
        return None
    fields = match.groupdict()
    ip = address(fields["ip"])
    if not ip or not public(ip):
        return None
    status = int(fields["status"])
    path = unquote(unquote(fields["path"].split("?", 1)[0].split("#", 1)[0]))
    kind = "http_probe" if PROBE.search(path) else "http_denied" if status in (401, 403, 429) else None
    if not kind:
        return None
    timestamp = datetime.strptime(fields["time"], "%d/%b/%Y:%H:%M:%S %z").timestamp()
    # Long capability/token-like path components are not useful on this page.
    path = re.sub(r"[A-Za-z0-9_=-]{40,}", "[redacted]", path)
    return event(kind, ip, timestamp, service="NPM", port=443 if fields["scheme"] == "https" else 80,
                 host=text(fields["host"], 253), path=text(path, 240),
                 method=fields["method"], status=status)


def parse_flow(line, timestamp):
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != "attacks-flow-v1":
        return None
    if data.get("heartbeat") is True:
        return {"heartbeat": True, "timestamp": timestamp,
                "suppressed": max(0, int(data.get("suppressed", 0)))}
    port, ip = data.get("port"), address(data.get("ip"))
    if port not in PORTS or not ip or not public(ip) or data.get("protocol") not in ("tcp", "udp"):
        return None
    category, service = PORTS[port]
    return event("ssh_probe" if port == 28 else "service_connection", ip, timestamp,
                 type=category, service=service, port=port,
                 protocol=data["protocol"], sourcePort=int(data["sourcePort"]))


PARSERS = {"endlessh": parse_endlessh, "authelia": parse_authelia,
           "ssh": parse_ssh, "fail2ban": parse_fail2ban, "connections": parse_flow}


def identity(source, key):
    return hashlib.sha256(f"{source}\0{key}".encode()).hexdigest()[:32]
