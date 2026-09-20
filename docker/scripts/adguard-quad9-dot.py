#!/usr/bin/env python3
"""Switch only the existing unfiltered Quad9 upstream to certificate-checked DoT."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


OLD = "https://dns10.quad9.net/dns-query"
NEW = "tls://dns10.quad9.net"


def migrate(text):
    dns = list(re.finditer(r"(?m)^dns:[ \t]*\n", text))
    if len(dns) != 1:
        raise ValueError("Expected one top-level dns mapping")
    following = re.search(r"(?m)^[^\s#]", text[dns[0].end():])
    end = dns[0].end() + following.start() if following else len(text)
    blocks = list(re.compile(
        r"(?m)^  upstream_dns:\s*\n(?:[ ]+-[^\n]*(?:\n|$))+",
    ).finditer(text, dns[0].end(), end))
    if len(blocks) != 1 or text.count(OLD) != 1 or NEW in text:
        raise ValueError("Expected one unchanged Quad9 DoH entry in dns.upstream_dns")
    block = blocks[0]
    if not re.search(rf"(?m)^ +-[ ]+['\"]?{re.escape(OLD)}['\"]?[ ]*$", block[0]):
        raise ValueError("Quad9 URL is not a standalone upstream_dns entry")
    return text[:block.start()] + block[0].replace(OLD, NEW) + text[block.end():]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path,
        default=Path("/srv/docker/data/adguardhome/confdir/AdGuardHome.yaml"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.config.is_symlink():
        raise ValueError("Refusing a symlinked configuration")
    original = args.config.read_bytes()
    replacement = migrate(original.decode()).encode()
    if not args.apply:
        print(f"Ready: replace only {OLD} with {NEW}; no file changed")
        return

    running = subprocess.check_output(
        ["docker", "inspect", "--format", "{{.State.Running}}", "adguardhome"],
        text=True,
    ).strip()
    if running != "false":
        raise RuntimeError("Stop adguardhome before editing its persisted configuration")
    metadata = args.config.stat()
    backup = args.config.with_name(
        args.config.name + ".pre-quad9-dot." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    with backup.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=args.config.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
        if args.config.read_bytes() != original:
            raise RuntimeError("Configuration changed concurrently; refusing replacement")
        os.replace(temporary, args.config)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(f"Changed only Quad9 transport; private rollback copy: {backup}")


if __name__ == "__main__":
    main()
