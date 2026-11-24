"""Passive header observation on the physical uplink; no listener or packet files."""

from collections import OrderedDict
import ipaddress
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import time

from events import PORTS, home_networks


def interface_networks(content, interface):
    networks = []
    for line in content.splitlines():
        address, _, prefix, _, flags, name = line.split()
        ip = ipaddress.IPv6Address(int(address, 16))
        if name != interface or not ip.is_global or ip.is_multicast or int(flags, 16) & 0x48:
            continue
        networks.append(str(ipaddress.ip_network(f"{ip}/{int(prefix, 16)}", strict=False)))
    return home_networks(networks)


def packet(data, linktype=1):
    if linktype != 1 or len(data) < 14:
        return None
    protocol = struct.unpack_from("!H", data, 12)[0]
    offset = 14
    while protocol in (0x8100, 0x88A8):
        if len(data) < offset + 4:
            return None
        protocol = struct.unpack_from("!H", data, offset + 2)[0]
        offset += 4
    if protocol == 0x0800:
        if len(data) < offset + 20 or data[offset] >> 4 != 4:
            return None
        length = (data[offset] & 15) * 4
        if length < 20 or struct.unpack_from("!H", data, offset + 6)[0] & 0x1FFF:
            return None
        ip = ipaddress.ip_address(bytes(data[offset + 12:offset + 16]))
        protocol = data[offset + 9]
        offset += length
    elif protocol == 0x86DD:
        if len(data) < offset + 40 or data[offset] >> 4 != 6:
            return None
        ip = ipaddress.ip_address(bytes(data[offset + 8:offset + 24]))
        protocol = data[offset + 6]
        offset += 40
        for _ in range(8):
            if protocol not in (0, 43, 44, 60):
                break
            if len(data) < offset + 8:
                return None
            if protocol == 44:
                if struct.unpack_from("!H", data, offset + 2)[0] & 0xFFF8:
                    return None
                length = 8
            else:
                length = (data[offset + 1] + 1) * 8
            protocol = data[offset]
            offset += length
    else:
        return None
    if (not ip.is_global or ip.is_multicast or protocol not in (6, 17)
            or len(data) < offset + (20 if protocol == 6 else 8)):
        return None
    source, destination = struct.unpack_from("!HH", data, offset)
    if destination not in PORTS:
        return None
    if protocol == 6 and data[offset + 13] & 0x12 != 0x02:
        return None
    return {"schema": "attacks-flow-v1", "ip": str(ip), "sourcePort": source,
            "port": destination, "protocol": "tcp" if protocol == 6 else "udp"}


def run():
    interface = os.environ.get("ATTACKS_INTERFACE", "bond0")
    # IPv6 extension headers are decoded below; port BPF filters miss them.
    ports = " or ".join(f"dst port {port}" for port in PORTS)
    command = ["tcpdump", "-i", interface, "-p", "-Q", "in", "-nn", "-U",
               "-s", "160", "-w", "-", f"(ip and (tcp or udp) and ({ports})) or ip6"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    seen = OrderedDict()
    buffer = bytearray()
    endian = None
    suppressed = 0
    heartbeat = 0
    rate_second, rate = 0, 0
    try:
        while True:
            now = time.time()
            if now - heartbeat >= 30:
                print(json.dumps({"schema": "attacks-flow-v1", "heartbeat": True,
                                  "suppressed": suppressed,
                                  "ownNetworks": interface_networks(
                                      Path("/proc/net/if_inet6").read_text(), interface)}), flush=True)
                heartbeat = now
            ready, _, _ = select.select([process.stdout], [], [], 1)
            if not ready:
                if process.poll() is not None:
                    raise RuntimeError("tcpdump stopped")
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("tcpdump pipe closed")
            buffer.extend(chunk)
            if endian is None:
                if len(buffer) < 24:
                    continue
                endian = {b"\xd4\xc3\xb2\xa1": "<", b"\xa1\xb2\xc3\xd4": ">"}.get(bytes(buffer[:4]))
                if not endian or struct.unpack_from(endian + "I", buffer, 20)[0] != 1:
                    raise RuntimeError("Expected Ethernet pcap input")
                del buffer[:24]
            while len(buffer) >= 16:
                length = struct.unpack_from(endian + "I", buffer, 8)[0]
                if length > 160:
                    raise RuntimeError("Unexpected capture length")
                if len(buffer) < 16 + length:
                    break
                result = packet(buffer[16:16 + length])
                del buffer[:16 + length]
                if not result:
                    continue
                key = (result["ip"], result["port"], result["protocol"],
                       result["sourcePort"] if result["protocol"] == "tcp" else 0)
                while seen and next(iter(seen.values())) < now - 60:
                    seen.popitem(last=False)
                if key in seen:
                    suppressed += 1
                    continue
                if int(now) != rate_second:
                    rate_second, rate = int(now), 0
                if rate >= 100:
                    suppressed += 1
                    continue
                rate += 1
                seen[key] = now
                if len(seen) > 50000:
                    seen.popitem(last=False)
                print(json.dumps(result), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    run()
