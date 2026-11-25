"""Conservative source-specific parsers. Never retain raw messages or credentials."""

from datetime import datetime, timezone
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
    "port_scan": ("service", "Port scan: not a game client", "suspected"),
    "plex_client": ("plex", "Plex client request", "observed"),
    "plex_reachability": ("plex", "Probable Plex remote-access check", "observed"),
    "plex_public": ("plex", "Public Plex endpoint request", "observed"),
    "plex_probe": ("plex", "Unauthenticated Plex request", "suspected"),
    "hytale_rejected": ("game", "Hytale identity token rejected", "failure"),
}
# Evidence of hostile intent, lowest first. A pure function of the kind, so history is covered at read time.
SEVERITIES = ("info", "low", "suspicious", "high", "critical")
SEVERITY = {
    "endlessh_open": "low", "endlessh_close": "low",
    "ssh_failure": "high", "ssh_accepted": "info", "ssh_accepted_unknown": "critical",
    "ssh_disconnect": "suspicious", "ssh_probe": "low", "ssh_ban": "high",
    "auth_failure": "high", "http_probe": "high", "http_denied": "low", "service_connection": "low",
    "port_scan": "low", "plex_client": "info", "plex_reachability": "info", "plex_public": "low", "plex_probe": "suspicious",
    "hytale_rejected": "suspicious",
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
    "port_scan": "A TCP SYN reached the game's messaging port, but this address had not contacted the game port in the previous 10 minutes. Real clients always reach the game port first, so this is consistent with a port scanner.",
    "plex_client": "Plex logged a request carrying a Plex token (or an in-progress streaming session). Looks like a signed-in client; this does not identify the person.",
    "plex_reachability": "Unauthenticated GET /identity from an AWS-published address range. Plex.tv checks remote access this way, but any AWS customer can send the same request, so this is an inference.",
    "plex_public": "A request without a token for an endpoint Plex serves publicly (/identity, the web app, or a streaming session). These expose no library data.",
    "plex_probe": "A request without a Plex token for a path that is not a public endpoint. Plex normally answers these 401 or 403; consistent with internet scanners, not evidence of access.",
    "hytale_rejected": "Hytale refused the client's identity token (invalidIdentityToken). The client was not a signed-in player: it may be a server-list poller, a scanner speaking the game protocol, or an outdated client.",
}
PORTS = {
    28: ("ssh", "SSH"), 2222: ("git", "Forgejo SSH"),
    32400: ("plex", "Plex"), 8324: ("plex", "Plex companion"),
    32469: ("plex", "Plex DLNA"),
    36676: ("minecraft", "Minecraft"), 36677: ("minecraft", "RLCraft"),
    5205: ("game", "Hytale"), 7778: ("game", "Satisfactory"),
    29778: ("game", "Satisfactory messaging"),
}
# Ports a real client reaches only after contacting a companion port (Satisfactory's
# reliable-messaging port follows the game port); a lone connection is a port scan.
COMPANIONS = {29778: 7778}
COMPANION_WINDOW = 600
TYPES = frozenset({"endlessh", "ssh", "authelia", "web", "git", "plex", "minecraft", "game"})
VERDICTS = frozenset(value[2] for value in KINDS.values())
OWN_NETWORKS = ("10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
                "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7", "fe80::/10")
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


def home_networks(values):
    if not isinstance(values, list) or len(values) > 16:
        raise ValueError("Expected a bounded list of home IPv6 networks")
    result = []
    for value in values:
        network = ipaddress.ip_network(value)
        if network.version != 6 or network.prefixlen != 64 or not public(str(network.network_address)):
            raise ValueError("Expected global home IPv6 /64 networks")
        result.append(str(network))
    return sorted(set(result))


def traffic_origin(ip, networks=()):
    value = ipaddress.ip_address(ip)
    return "own" if any(value in ipaddress.ip_network(cidr) for cidr in (*OWN_NETWORKS, *networks)) else "external"


def event(kind, ip, timestamp, **fields):
    ip = address(ip)
    if not ip or kind not in KINDS or not math.isfinite(timestamp):
        return None
    category, title, verdict = KINDS[kind]
    return {"timestamp": timestamp, "kind": kind, "type": category, "reason": REASONS[kind],
            "title": title, "verdict": verdict, "ip": ip, **fields}


def parse_endlessh(line, timestamp):
    if re.search(r"\bListening on \[ipv[46]\]:\d+", line):
        return {"restart": True, "timestamp": timestamp}
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


def kinds_at_least(level):
    floor = SEVERITIES.index(level)
    return sorted(kind for kind, value in SEVERITY.items() if SEVERITIES.index(value) >= floor)


def retag(item, kind):
    category, title, verdict = KINDS[kind]
    return {**item, "kind": kind, "title": title, "verdict": verdict, "reason": REASONS[kind]}


def refine(item):
    """Reclassify using enrichment that the raw parser did not have."""
    if (item["kind"] == "plex_public" and item.get("path") in ("/identity", "/identity/")
            and "AWS" in str(item.get("networkProvider", "")).split(" / ")):
        return retag(item, "plex_reachability")
    return item


SSH_LINE = re.compile(
    r"(?:error: |fatal: )?(?:Accepted |Failed |Invalid user |User \S+ from \S+ not allowed because |"
    r"Connection (?:closed|reset) by |Disconnected from |Timeout before authentication for connection from |"
    r"Unable to negotiate with |maximum authentication attempts|banner exchange:|kex_exchange_identification:|"
    r"ssh_dispatch_run_fatal: Connection from )")


def parse_ssh(line, timestamp, service="SSH", port=28, category=None):
    where = {"service": service, "port": port, **({"type": category} if category else {})}
    accepted = re.search(r"Accepted (\S+) for (.+?) from (\S+) port (\d+)", line)
    if accepted:
        fingerprint = re.search(r"\b(SHA256:[A-Za-z0-9+/=]+|MD5:[a-f0-9:]+)", line)
        return event("ssh_accepted", accepted[3], timestamp, **where,
                     user=text(accepted[2], 64), sourcePort=int(accepted[4]),
                     authMethod=text(accepted[1], 32),
                     keyFingerprint=fingerprint[1] if fingerprint else None)
    invalid = re.search(r"Invalid user (.+?) from (\S+) port (\d+)", line)
    if invalid:
        return event("ssh_failure", invalid[2], timestamp, **where,
                     user=text(invalid[1], 64), sourcePort=int(invalid[3]),
                     rejectionReason="Username does not exist", authMethod="unknown")
    failed = re.search(r"Failed (\S+) for (invalid user )?(.+?) from (\S+) port (\d+)", line)
    if failed:
        reason = "Username does not exist; authentication rejected" if failed[2] else {
            "publickey": "Public key rejected", "password": "Password authentication rejected",
            "keyboard-interactive/pam": "Interactive authentication rejected",
        }.get(failed[1], "Authentication rejected")
        return event("ssh_failure", failed[4], timestamp, **where,
                     user=text(failed[3], 64), sourcePort=int(failed[5]),
                     authMethod=text(failed[1], 32), rejectionReason=reason)
    exceeded = re.search(r"maximum authentication attempts exceeded for (?:invalid user )?(.+?) from (\S+) port (\d+)", line)
    if exceeded:
        return event("ssh_failure", exceeded[2], timestamp, **where,
                     user=text(exceeded[1], 64), sourcePort=int(exceeded[3]),
                     rejectionReason="Maximum authentication attempts exceeded", authMethod="unknown")
    not_allowed = re.search(r"User (.+?) from (\S+) not allowed because", line)
    if not_allowed:
        return event("ssh_failure", not_allowed[2], timestamp, **where,
                     user=text(not_allowed[1], 64), authMethod="unknown",
                     rejectionReason="Account is not permitted to log in over SSH")
    disconnected = re.search(r"(?:Connection (?:closed|reset) by|Disconnected from) (?:(?:invalid|authenticating) user (.+?) )?(\S+) port (\d+).*\[preauth\]", line)
    if disconnected:
        return event("ssh_disconnect", disconnected[2], timestamp, **where,
                     user=text(disconnected[1], 64) if disconnected[1] else None,
                     sourcePort=int(disconnected[3]), authMethod="unknown")
    timeout = re.search(r"Timeout before authentication for connection from (\S+) to ", line)
    if timeout:
        return event("ssh_disconnect", timeout[1], timestamp, **where, authMethod="unknown")
    # Generic established-session disconnects and PQ warnings are not failures.
    match = re.search(r"(?:banner exchange|kex_exchange_identification):.*(?:from|with) (\S+) port (\d+)", line)
    match = match or re.search(r"(?:Unable to negotiate with|ssh_dispatch_run_fatal: Connection from) (\S+) port (\d+)", line)
    if match:
        return event("ssh_probe", match[1], timestamp, **where, sourcePort=int(match[2]))
    return None


def parse_forgejo_ssh(line, timestamp):
    # The container also logs application lines that can echo request text; only accept bare sshd messages.
    if not SSH_LINE.match(line):
        return None
    return parse_ssh(line, timestamp, "Forgejo SSH", 2222, "git")


HYTALE = re.compile(
    r"Disconnecting QuicConnectionAddress\{connId=[0-9a-f]*\} \(/(?P<ip>\[[0-9a-fA-F:.]+\]|[0-9.]+):(?P<port>\d+)"
    r"(?:, streamId=\d+)?\)(?: \(SNI: (?P<sni>[^)]*)\))? with the message: (?P<message>[\w.]+)")


def parse_hytale(line, timestamp):
    match = HYTALE.search(line)
    if not match or match["message"] != "client.general.disconnect.invalidIdentityToken":
        return None
    ip = address(match["ip"])
    if not ip or not public(ip):
        return None
    return event("hytale_rejected", ip, timestamp, service="Hytale", port=5205, protocol="udp",
                 sourcePort=int(match["port"]), rejectionReason="Identity token rejected",
                 **({"sni": text(match["sni"], 253)} if match["sni"] else {}))


PLEX = re.compile(
    r"^(?P<time>[A-Z][a-z]{2} \d{1,2}, \d{4} \d{2}:\d{2}:\d{2}\.\d{3}) \[\d+\] DEBUG - "
    r"Request: \[(?P<ip>\S+?):(?P<port>\d+) \(WAN\)\] (?P<method>[A-Z*]+) (?P<target>\S+) \(\d+ live\) #\w+(?P<flags>.*)$")
PLEX_SESSION = "/video/:/transcode/universal/session/"


def parse_plex(line, zone=timezone.utc):
    """One Plex WAN request. Tokens, query strings and account names are never retained."""
    match = PLEX.match(line)
    if not match:
        return None
    ip = address(match["ip"])
    if not ip or not public(ip):
        return None
    timestamp = datetime.strptime(match["time"], "%b %d, %Y %H:%M:%S.%f").replace(tzinfo=zone).timestamp()
    path = unquote(unquote(match["target"].split("?", 1)[0].split("#", 1)[0]))
    if path.startswith(PLEX_SESSION):
        path = PLEX_SESSION + "[session]"
    path = text(re.sub(r"[A-Za-z0-9_=-]{40,}", "[redacted]", path), 240)
    method = text(match["method"], 16)
    if re.search(r"\bToken \(", match["flags"]):
        kind, bucket, window = "plex_client", ip, 1800
    elif path in ("/identity", "/identity/") or path == "/web" or path.startswith(("/web/", PLEX_SESSION)):
        kind, bucket, window = "plex_public", f"{ip} {path}", 1800
    else:
        kind, bucket, window = "plex_probe", f"{ip} {method} {path}", 300
    fields = {} if kind == "plex_client" else {"method": method, "path": path}
    item = event(kind, ip, timestamp, service="Plex", port=32400, protocol="tcp",
                 sourcePort=int(match["port"]), **fields)
    # Busy clients and scanners are summarised: one event per source and request class per window.
    return {**item, "throttle": f"{kind}:{bucket}:{int(timestamp // window)}"} if item else None


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
        result = {"heartbeat": True, "timestamp": timestamp,
                  "suppressed": max(0, int(data.get("suppressed", 0)))}
        if "ownNetworks" in data:
            result["ownNetworks"] = home_networks(data["ownNetworks"])
        return result
    port, ip = data.get("port"), address(data.get("ip"))
    if port not in PORTS or not ip or not public(ip) or data.get("protocol") not in ("tcp", "udp"):
        return None
    category, service = PORTS[port]
    return event("ssh_probe" if port == 28 else "service_connection", ip, timestamp,
                 type=category, service=service, port=port,
                 protocol=data["protocol"], sourcePort=int(data["sourcePort"]))


PARSERS = {"endlessh": parse_endlessh, "authelia": parse_authelia,
           "ssh": parse_ssh, "fail2ban": parse_fail2ban, "connections": parse_flow,
           "forgejo": parse_forgejo_ssh, "hytale": parse_hytale}


def identity(source, key):
    return hashlib.sha256(f"{source}\0{key}".encode()).hexdigest()[:32]
