"""Send a Wake-on-LAN magic packet from the homeserver's LAN."""

import argparse
import ipaddress
import re
import socket
import sys


DEFAULT_MAC = "74:56:3C:B4:F5:4E"
DEFAULT_IP = "192.168.50.255"
DEFAULT_PORT = 9


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


def parse_ip(value):
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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Send one UDP Wake-on-LAN magic packet. Defaults target DANTE-PC's "
            "physical Ethernet MAC on the homeserver LAN."
        ),
        epilog=(
            "--ip changes only the destination, not the target MAC. Use --mac for "
            "another device; an IP alone cannot identify a powered-off device. "
            "Prefer the LAN broadcast: unicast can fail when neighbor/ARP entries "
            "expire. A DHCP IP change does not change the Ethernet MAC. "
            "Sending a packet does not verify that the device woke."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mac", type=parse_mac, default=DEFAULT_MAC,
        help="target Ethernet MAC",
    )
    parser.add_argument(
        "--ip", "--broadcast", dest="ip", type=parse_ip, default=DEFAULT_IP,
        help="numeric IPv4 destination or LAN broadcast (no hostname/ARP lookup)",
    )
    parser.add_argument(
        "--port", type=parse_port, default=DEFAULT_PORT, help="UDP destination port",
    )
    args = parser.parse_args(argv)
    packet = b"\xff" * 6 + args.mac * 16
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sent = sender.sendto(packet, (args.ip, args.port))
            if sent != len(packet):
                raise OSError(f"short UDP send: {sent} of {len(packet)} bytes")
    except OSError as exc:
        print(f"wake-pc: failed to send to {args.ip}:{args.port}: {exc}", file=sys.stderr)
        return 1
    mac = args.mac.hex(":").upper()
    print(
        f"Sent {sent}-byte magic packet for {mac} to {args.ip}:{args.port}. "
        "Wake not verified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
