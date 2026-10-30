"""Send a Wake-on-LAN magic packet from the homeserver's LAN."""

import argparse
import errno
import ipaddress
import math
import re
import socket
import sys
import time


DEFAULT_MAC = "74:56:3C:B4:F5:4E"
DEFAULT_BROADCAST = "192.168.50.255"
DEFAULT_PORT = 9
DEFAULT_WAIT = 120.0
DEFAULT_WAIT_HOST = "192.168.50.180"
DEFAULT_WAIT_PORT = 3389


def parse_mac(value):
    if not re.fullmatch(
        r"(?:[0-9a-fA-F]{12}|[0-9a-fA-F]{2}([:-])(?:[0-9a-fA-F]{2}\1){4}[0-9a-fA-F]{2})",
        value,
    ):
        raise argparse.ArgumentTypeError(
            "MAC must contain six hex octets (AA:BB:CC:DD:EE:FF, "
            "AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF)"
        )
    mac = bytes.fromhex(value.replace(":", "").replace("-", ""))
    if mac == bytes(6) or mac[0] & 1:
        raise argparse.ArgumentTypeError("MAC must be a nonzero unicast device address")
    return mac


def parse_broadcast(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError("destination must be a numeric IPv4 address") from exc
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        if address != ipaddress.IPv4Address("255.255.255.255"):
            raise argparse.ArgumentTypeError("destination must be a unicast or broadcast IPv4 address")
    return str(address)


def parse_port(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return port


def parse_timeout(value):
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be positive finite seconds") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive finite seconds")
    return timeout


def parse_wait_host(value):
    address = parse_broadcast(value)
    if address == "255.255.255.255":
        raise argparse.ArgumentTypeError("RDP target must be a unicast IPv4 address")
    return address


def wait_for_rdp(host, port, timeout):
    deadline = time.monotonic() + timeout
    last_error = "deadline expired"
    retry_errors = {
        errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EHOSTUNREACH,
        errno.ENETUNREACH, errno.ECONNRESET,
    }
    print(f"Waiting up to {timeout:g}s for RDP at {host}:{port}...", flush=True)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"wake-pc: RDP not reachable at {host}:{port} within {timeout:g}s "
                f"({last_error}).",
                file=sys.stderr,
            )
            return 1
        try:
            with socket.create_connection((host, port), timeout=min(1.0, remaining)):
                pass
        except OSError as exc:
            if not isinstance(exc, TimeoutError) and exc.errno not in retry_errors:
                print(f"wake-pc: RDP check failed at {host}:{port}: {exc}", file=sys.stderr)
                return 1
            last_error = str(exc)
        else:
            if time.monotonic() <= deadline:
                print(
                    f"RDP reachable at {host}:{port}. "
                    "PC may already have been online; Windows login not verified."
                )
                return 0
        time.sleep(max(0.0, min(0.5, deadline - time.monotonic())))


def run(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Send one UDP Wake-on-LAN magic packet. Defaults target DANTE-PC's "
            "physical Ethernet MAC on the homeserver LAN."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mac", type=parse_mac, default=DEFAULT_MAC,
        help="target Ethernet MAC",
    )
    parser.add_argument(
        "--broadcast", type=parse_broadcast, default=DEFAULT_BROADCAST,
        help="LAN broadcast destination (numeric IPv4 address)",
    )
    parser.add_argument(
        "--port", type=parse_port, default=DEFAULT_PORT, help="UDP destination port",
    )
    parser.add_argument(
        "--wait", nargs="?", const=DEFAULT_WAIT, type=parse_timeout, metavar="SECONDS",
        default=argparse.SUPPRESS,
        help="wait for RDP reachability after sending (120s if no value)",
    )
    parser.add_argument(
        "--wait-host", type=parse_wait_host, default=argparse.SUPPRESS,
        help=f"numeric IPv4 RDP target, independent of MAC/broadcast (default: {DEFAULT_WAIT_HOST})",
    )
    parser.add_argument(
        "--wait-port", type=parse_port, default=argparse.SUPPRESS,
        help=f"TCP RDP port used with --wait (default: {DEFAULT_WAIT_PORT})",
    )
    args = parser.parse_args(argv)
    timeout = getattr(args, "wait", None)
    if timeout is None and (hasattr(args, "wait_host") or hasattr(args, "wait_port")):
        parser.error("--wait-host and --wait-port require --wait")
    packet = b"\xff" * 6 + args.mac * 16
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sent = sender.sendto(packet, (args.broadcast, args.port))
            if sent != len(packet):
                raise OSError(f"short UDP send: {sent} of {len(packet)} bytes")
    except OSError as exc:
        print(f"wake-pc: failed to send to {args.broadcast}:{args.port}: {exc}", file=sys.stderr)
        return 1
    mac = args.mac.hex(":").upper()
    print(f"Sent magic packet for {mac} to {args.broadcast}:{args.port}.", flush=True)
    if timeout is not None:
        return wait_for_rdp(
            getattr(args, "wait_host", DEFAULT_WAIT_HOST),
            getattr(args, "wait_port", DEFAULT_WAIT_PORT),
            timeout,
        )
    return 0


def main(argv=None):
    try:
        return run(argv)
    except KeyboardInterrupt:
        print("wake-pc: interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
