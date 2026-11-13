#!/usr/bin/env python3
"""Read-only Linux telemetry collector. No network listener or history database."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from datetime import datetime, timezone


INTERVAL = 5
GIB = 2 ** 30
TIB = 2 ** 40
SLOTS = {
    "hdd": sorted(f"cage-{cage}-bay-{bay}" for cage in range(1, 4) for bay in range(1, 5)),
    "nvme": ["M2_1", "M2_2"],
}
COMMANDS = {
    "lsblk": ("lsblk", "--json", "--bytes", "--output",
              "NAME,KNAME,PKNAME,TYPE,SIZE,MODEL,SERIAL,WWN,ROTA,FSTYPE,MOUNTPOINTS"),
    "lvs": ("lvs", "--readonly", "--reportformat", "json", "--units", "b", "--nosuffix",
            "-a", "-o", "lv_kernel_major,lv_kernel_minor,lv_name,vg_name,segtype,devices"),
    "bmc": ("ipmitool", "sensor"),
    "gpu": ("nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,"
            "temperature.gpu,power.draw,fan.speed", "--format=csv,noheader,nounits"),
    "gpu-engines": ("nvidia-smi", "--query-gpu=utilization.encoder,utilization.decoder",
                    "--format=csv,noheader,nounits"),
}
DEVICE = re.compile(r"(?:sd[a-z]+|nvme[0-9]+n[0-9]+)\Z")


def utc(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp,
                                  timezone.utc).isoformat().replace("+00:00", "Z")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def command(source, device=None, timeout=8):
    """Only locally defined, read-only commands; cap output and execution time."""
    if source == "smart":
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise ValueError("Invalid physical block device")
        args = ("smartctl", "-n", "standby", "-a", "-j", f"/dev/{device}")
    else:
        args = COMMANDS[source]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, shell=False)
    output = []

    def read():
        output.append(process.stdout.read(4 * 1024 * 1024 + 1))
        if len(output[0]) > 4 * 1024 * 1024:
            process.kill()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
        reader.join(timeout=1)
        if reader.is_alive() or not output or len(output[0]) > 4 * 1024 * 1024:
            raise RuntimeError(f"{source}: output limit exceeded")
        text = output[0].decode("utf-8", errors="replace")
        # smartctl uses a bit mask: health warnings may still contain useful data.
        if process.returncode and source != "smart":
            raise RuntimeError(f"{source}: command exited {process.returncode}")
        return text
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        reader.join(timeout=1)
        process.stdout.close()


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o750)
    if hasattr(os, "chown") and os.geteuid() == 0:
        os.chown(path.parent, -1, 65534)
    staging = path.with_name(path.name + ".new")
    # O_NOFOLLOW also protects the root collector against pre-existing symlinks.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(staging, flags, 0o640)
    try:
        os.fchmod(descriptor, 0o640) if hasattr(os, "fchmod") else None
        if hasattr(os, "fchown") and os.geteuid() == 0:
            os.fchown(descriptor, -1, 65534)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def stable_id(disk):
    for field in ("wwn", "serial"):
        value = str(disk.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return None


def assign_slots(disks, assignments):
    """Reserve absent devices forever; never use an sdX name as an identity."""
    assignments = dict(assignments)
    valid_slots = set(sum(SLOTS.values(), []))
    if any(not isinstance(key, str) or not key.startswith(("wwn:", "serial:"))
           or slot not in valid_slots for key, slot in assignments.items()):
        raise ValueError("Invalid persisted disk assignment")
    if len(set(assignments.values())) != len(assignments):
        raise ValueError("Duplicate persisted slot")
    identities = [stable_id(disk) for disk in disks if stable_id(disk)]
    duplicates = {identity for identity in identities if identities.count(identity) > 1}
    issues = []
    for disk in sorted(disks, key=lambda d: (str(d.get("serial") or ""), d["id"])):
        identity = stable_id(disk)
        disk.update(stableId=identity, slot=None, mapping="provisional")
        if not identity or identity in duplicates:
            issues.append(f"{disk['id']}: stable identity unavailable or duplicated; no slot assigned")
            disk["stableId"] = None
            continue
        if identity in assignments and assignments[identity] not in SLOTS[disk["kind"]]:
            issues.append(f"{disk['id']}: reserved slot has incompatible device kind")
            continue
        if identity not in assignments:
            unused = [slot for slot in SLOTS[disk["kind"]] if slot not in assignments.values()]
            if unused:
                assignments[identity] = unused[0]
            else:
                issues.append(f"{disk['id']}: no unused provisional slot")
        disk["slot"] = assignments.get(identity)
    return assignments, issues


def metric_key(identity, field):
    return "disk_" + hashlib.sha256(identity.encode()).hexdigest()[:32] + "_" + field


def counter_delta(current, previous):
    if previous is None or len(current) != len(previous):
        return None
    delta = [a - b for a, b in zip(current, previous)]
    return None if any(value < 0 for value in delta) else delta


def block_rates(current, previous, elapsed):
    empty = dict.fromkeys(("read", "write", "active", "latency", "queue"))
    if elapsed <= 0 or len(current) < 11:
        return empty
    # In-flight requests (index 8) are a gauge, not a monotonic counter.
    indexes = (0, 2, 3, 4, 6, 7, 9, 10)
    delta = counter_delta([current[i] for i in indexes],
                          [previous[i] for i in indexes] if previous and len(previous) >= 11 else None)
    if delta is None:
        return empty
    reads, sectors_read, read_ms, writes, sectors_written, write_ms, busy_ms, weighted_ms = delta
    return {"read": sectors_read * 512 / elapsed / 1e6,
            "write": sectors_written * 512 / elapsed / 1e6,
            "active": min(100, busy_ms / elapsed / 10),
            "latency": (read_ms + write_ms) / (reads + writes) if reads + writes else 0,
            "queue": weighted_ms / elapsed / 1000}


def memory_values(text):
    fields = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if rest.strip():
            fields[name] = int(rest.split()[0]) * 1024
    required = ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SReclaimable",
                "Shmem", "SUnreclaim", "KernelStack", "PageTables", "SwapTotal", "SwapFree")
    if any(name not in fields for name in required):
        raise ValueError("meminfo: required counters missing")
    total = fields["MemTotal"]
    free = fields["MemFree"]
    cache = max(0, fields["Buffers"] + fields["Cached"] + fields["SReclaimable"] - fields["Shmem"])
    kernel = fields["SUnreclaim"] + fields["KernelStack"] + fields["PageTables"]
    if free + cache + kernel > total:
        raise ValueError("meminfo: inconsistent partition counters")
    values = {"memory-free": free / GIB, "memory-cache": cache / GIB,
              "memory-kernel": kernel / GIB, "memory-apps": (total - free - cache - kernel) / GIB,
              "memory-used": (total - fields["MemAvailable"]) / GIB,
              "swap": (fields["SwapTotal"] - fields["SwapFree"]) / GIB}
    capacities = {key: total / GIB for key in values if key.startswith("memory-")}
    capacities["swap"] = fields["SwapTotal"] / GIB
    return values, capacities


def smart_values(payload):
    status = payload.get("smartctl", {}).get("exit_status", 0)
    messages = " ".join(str(entry.get("string", "")) for entry in
                        payload.get("smartctl", {}).get("messages", []))
    # Bits 0..2 are command failures; bit 1 also includes standby refusal.
    # Health-warning bits do not invalidate a freshly read temperature.
    if status & 7 or re.search(r"standby|sleep", messages + " " + str(payload.get("power_mode", "")), re.I):
        return {"composite": None, "secondary": None}, "SMART unavailable (standby/asleep or command error)"
    nvme = payload.get("nvme_smart_health_information_log", {})
    composite = number(nvme.get("temperature"))
    if composite is None:
        composite = number(payload.get("temperature", {}).get("current"))
    secondary = None
    sensors = nvme.get("temperature_sensors", [])
    if sensors:
        # This is sensor 1, not a claim about a controller/NAND location.
        secondary = number(sensors[0])
        if secondary is not None and secondary <= 0:
            secondary = None
    if composite is None:
        for attribute in payload.get("ata_smart_attributes", {}).get("table", []):
            if attribute.get("id") in (190, 194):
                composite = number(attribute.get("raw", {}).get("value"))
                if composite is not None and 0 < composite < 150:
                    break
                composite = None
    return {"composite": composite, "secondary": secondary}, (
        None if composite is not None else "SMART temperature unavailable")


class Collector:
    def __init__(self, state_dir, proc="/proc", sys="/sys", runner=command, clock=time.time, background=False):
        self.state_dir = Path(state_dir)
        self.proc, self.sys = Path(proc), Path(sys)
        self.runner, self.clock = runner, clock
        self.cache, self.sources, self.previous = {}, {}, {}
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="atlas-read") if background else None
        self.smart_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="atlas-smart") if background else None
        self.pending = {}
        self.assignments = {}
        assignment_file = self.state_dir / "assignments.json"
        if assignment_file.exists():
            self.assignments = json.loads(assignment_file.read_text(encoding="utf-8"))["assignments"]
            assign_slots([], self.assignments)  # Fail closed rather than reshuffling corrupt state.

    def text(self, path):
        return Path(path).read_text(encoding="utf-8").strip()

    def refresh(self, name, interval, function):
        now = self.clock()
        state = self.cache.get(name)
        if self.executor:
            pending = self.pending.get(name)
            if pending and pending.done():
                self.pending.pop(name)
                state = self.finish_refresh(name, interval, pending.result())
            if name not in self.pending and (not state or now - state["attempt"] >= interval):
                executor = self.smart_executor if name.startswith("smart:") else self.executor
                self.pending[name] = executor.submit(self.attempt_refresh, function)
            if not state:
                self.sources[name] = {"capturedAt": None, "lastAttempt": utc(now),
                                      "expiresAt": None, "status": "pending"}
                return None
            if now - state["attempt"] > interval * 2:
                self.sources[name]["status"] = "stale"
                self.cache[name]["issue"] = f"{name}: cached read expired while refresh pending"
                return None
            return state["value"]
        if state and now - state["attempt"] < interval:
            return state["value"]
        return self.finish_refresh(name, interval, self.attempt_refresh(function))["value"]

    def attempt_refresh(self, function):
        try:
            value = function()
            issue = None
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, StopIteration, subprocess.SubprocessError) as error:
            value, issue = None, f"{type(error).__name__}: {error}"
        return self.clock(), value, issue

    def finish_refresh(self, name, interval, result):
        now, value, issue = result
        previous = self.cache.get(name, {})
        success = now if value is not None else previous.get("success")
        self.cache[name] = {"attempt": now, "success": success, "value": value,
                            "issue": f"{name}: {issue}" if issue else None}
        self.sources[name] = {"capturedAt": utc(success) if value is not None else None,
                              "lastAttempt": utc(now), "lastSuccess": utc(success) if success is not None else None,
                              "expiresAt": utc(now + interval * 2), "status": "ok" if value is not None else "unavailable"}
        return self.cache[name]

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.smart_executor.shutdown(wait=True, cancel_futures=True)

    def inventory(self):
        payload = json.loads(self.runner("lsblk"))
        nodes, disks, mounts = {}, {}, {}

        def walk(entries, parent=None):
            for entry in entries:
                name = entry.get("kname") or entry["name"]
                if not re.fullmatch(r"[A-Za-z0-9_.!+-]+", name):
                    continue
                device_type = entry.get("type")
                kind = ("Physical NVMe" if name.startswith("nvme") else "Physical HDD") if device_type == "disk" else (
                    "Partition" if device_type == "part" else
                    "LVM / device-mapper" if name.startswith("dm-") else "Block device")
                node = nodes.setdefault(name, {"id": name, "label": f"/dev/{name}", "kind": kind,
                                               "sizeBytes": int(entry.get("size") or 0), "parents": [],
                                               "model": str(entry.get("model") or "").strip()})
                node["summary"] = " · ".join(filter(None, [entry.get("fstype"),
                    ", ".join(str(m) for m in entry.get("mountpoints", []) if m)]))
                for mount in entry.get("mountpoints", []):
                    if mount in ("/", "/data"):
                        mounts[mount] = name
                # md member edges are supplied by the actual sysfs membership below.
                if parent and not (self.sys / "class" / "block" / name / "md").exists():
                    relation = {"id": parent, "relation": "Partition of" if device_type == "part" else "Kernel backing device"}
                    if relation not in node["parents"]:
                        node["parents"].append(relation)
                if device_type == "disk" and DEVICE.fullmatch(name):
                    disks[name] = {"id": name, "kind": "nvme" if name.startswith("nvme") else "hdd",
                                   "serial": str(entry.get("serial") or "").strip() or None,
                                   "wwn": str(entry.get("wwn") or "").strip() or None,
                                   "model": node["model"], "sizeBytes": node["sizeBytes"]}
                walk(entry.get("children", []), name)

        walk(payload["blockdevices"])
        self.assignments, issues = assign_slots(list(disks.values()), self.assignments)
        atomic_write(self.state_dir / "assignments.json", json.dumps({
            "version": 1, "mapping": "provisional", "method": "serial-sorted",
            "assignments": self.assignments}, allow_nan=False))
        raids, bonds, associations = [], [], []
        for name, node in list(nodes.items()):
            base = self.sys / "class" / "block" / name
            md = base / "md"
            if md.exists():
                raid = {"id": name, "level": self.text(md / "level").upper(),
                        "raidDisks": int(self.text(md / "raid_disks")),
                        "state": self.text(md / "array_state"),
                        "degraded": int(self.text(md / "degraded")),
                        "syncAction": self.text(md / "sync_action") if (md / "sync_action").exists() else "unavailable",
                        "members": []}
                node["parents"] = []
                node["kind"] = "mdadm " + raid["level"]
                for member in sorted(md.glob("dev-*")):
                    identity = (member / "block").resolve().name
                    if identity in nodes:
                        slot = self.text(member / "slot")
                        raid["members"].append({"id": identity, "state": self.text(member / "state"),
                                                "slot": int(slot) if slot.isdigit() else None})
                raids.append(raid)
            elif (base / "slaves").exists():
                for slave in sorted((base / "slaves").iterdir()):
                    relation = {"id": slave.name, "relation": "Kernel backing device"}
                    if slave.name in nodes and relation not in node["parents"]:
                        node["parents"].append(relation)
            if name in disks:
                # Derive only the PCI attachment, never a physical motherboard header.
                device_path = (base / "device").resolve()
                for ancestor in (device_path, *device_path.parents):
                    if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", ancestor.name):
                        controller_id = "pci-" + ancestor.name
                        driver = (ancestor / "driver").resolve().name if (ancestor / "driver").exists() else "unavailable"
                        nodes.setdefault(controller_id, {"id": controller_id, "label": "PCI " + ancestor.name,
                            "kind": "Storage controller", "summary": "Kernel driver: " + driver, "parents": []})
                        node["parents"].append({"id": controller_id, "relation": "Kernel PCI attachment"})
                        break
        lvm = None
        try:
            lvm = json.loads(self.runner("lvs"))["report"]
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            issues.append(f"lvs: metadata unavailable ({type(error).__name__}); kernel dependencies only")
        mapper_nodes = {}
        for name, node in nodes.items():
            path = self.sys / "class" / "block" / name / "dm" / "name"
            if path.exists():
                mapper = self.text(path)
                mapper_nodes[mapper] = name
                node["aliases"] = ["/dev/mapper/" + mapper]
        logical_volumes = {}
        for report in lvm or []:
            for volume in report.get("lv", []):
                group = str(volume.get("vg_name", "")).strip()
                name = str(volume.get("lv_name", "")).strip().strip("[]")
                logical_volumes.setdefault((group, name), []).append(volume)
                mapper = group.replace("-", "--") + "-" + name.replace("-", "--")
                node = nodes.get(mapper_nodes.get(mapper))
                if node is not None:
                    alias = f"/dev/{group}/{name}"
                    if alias not in node["aliases"]:
                        node["aliases"].append(alias)
                    segment = f"{group}/{name} · {str(volume.get('segtype', '')).strip()} · {str(volume.get('devices', '')).strip()}"
                    node["summary"] = " · ".join(filter(None, [node["summary"], segment]))
        for mount, name in mounts.items():
            filesystem_id = "root-filesystem" if mount == "/" else "data-filesystem"
            nodes[filesystem_id] = {"id": filesystem_id, "label": mount, "kind": "Mounted filesystem",
                                    "parents": [{"id": name, "relation": "Mounted from"}],
                                    "summary": "Live lsblk mount observation; block size is not filesystem capacity"}

        def ancestors(name):
            found, pending = set(), [name]
            while pending:
                current = pending.pop()
                if current in found:
                    continue
                found.add(current)
                pending.extend(parent["id"] for parent in nodes.get(current, {}).get("parents", []))
                for raid in raids:
                    if raid["id"] == current:
                        pending.extend(member["id"] for member in raid["members"])
            return found

        root_backing = ancestors(mounts["/"]) if "/" in mounts else set()
        def volume_backing(group, name, visited=None):
            visited = set() if visited is None else visited
            key = (group, name)
            if key in visited:
                return set()
            visited.add(key)
            backing = set()
            for volume in logical_volumes.get(key, []):
                for device in str(volume.get("devices", "")).split(","):
                    device = re.sub(r"\(\d+\)$", "", device.strip())
                    if device.startswith("/dev/"):
                        target = device.rsplit("/", 1)[-1]
                        target = mapper_nodes.get(target, target)
                        if target in nodes:
                            backing.update(ancestors(target))
                    elif device:
                        backing.update(volume_backing(group, device.strip("[]"), visited))
            return backing

        cache_backing = set()
        for report in lvm or []:
            for logical_volume in report.get("lv", []):
                if str(logical_volume.get("segtype", "")).strip() != "cache-pool":
                    continue
                # --readonly intentionally reports kernel numbers as -1 on some
                # LVM versions; follow on-disk segment references in that case.
                cache_backing.update(volume_backing(
                    str(logical_volume.get("vg_name", "")).strip(),
                    str(logical_volume.get("lv_name", "")).strip().strip("[]")))
                major = str(logical_volume.get("lv_kernel_major", "")).strip()
                minor = str(logical_volume.get("lv_kernel_minor", "")).strip()
                if major.isdigit() and minor.isdigit():
                    device = self.sys / "dev" / "block" / (major + ":" + minor)
                    if device.exists():
                        cache_backing.update(ancestors(device.resolve().name))
        for disk in disks.values():
            if disk["id"] in root_backing:
                disk["role"] = "root"
            elif disk["id"] in cache_backing:
                disk["role"] = "cache"
        for interface in sorted((self.sys / "class" / "net").glob("*")):
            if not ((interface / "device").exists() or (interface / "bonding").exists()):
                continue
            name = interface.name
            nodes[name] = {"id": name, "label": name, "kind": "Linux network bond" if
                           (interface / "bonding").exists() else "Physical network interface", "parents": []}
            if (interface / "bonding").exists():
                bonds.append({"id": name, "mode": self.text(interface / "bonding" / "mode").split()[0],
                              "activeSlave": self.text(interface / "bonding" / "active_slave"),
                              "members": self.text(interface / "bonding" / "slaves").split()})
        # Some bonding members have no device link (e.g. virtual lower interfaces).
        for bond in bonds:
            for member in bond["members"]:
                nodes.setdefault(member, {"id": member, "label": member, "kind": "Network interface", "parents": []})
        network_nodes = [name for name, node in nodes.items() if node["kind"] in (
            "Linux network bond", "Physical network interface", "Network interface")]
        associations.append({"targets": ["network-ports", "rear-io"], "nodes": network_nodes,
                             "note": "Current Linux NIC/bond inventory, not individual physical-port bindings. "
                                     "A host-visible USB NIC is not the dedicated BMC LAN socket."})
        for bond in bonds:
            if bond["id"] == "bond0":
                associations.append({"targets": ["LAN1", "LAN2"], "nodes": [bond["id"], *bond["members"]],
                                     "note": "Known onboard-LAN bond shown as a group only. LAN1/LAN2-to-interface "
                                             "pairing remains unverified; PCI function order is not physical port evidence."})
        for disk in disks.values():
            nodes[disk["id"]]["summary"] += " · Provisional serial-sorted mapping; not physically confirmed"
            if disk["slot"]:
                targets = ["drive-" + disk["slot"]]
                if disk["kind"] == "nvme":
                    targets.append(disk["slot"])
                associations.append({"targets": targets, "nodes": [disk["id"]],
                                     "note": "Provisional serial-sorted placement, NOT physically confirmed."})
        for kind, targets in (("hdd", ["disk-bays", "disks"]),
                              ("nvme", ["nvme-group"])):
            associations.append({"targets": targets,
                                 "nodes": [d["id"] for d in disks.values() if d["kind"] == kind],
                                 "note": "Live inventory; individual provisional assignments are not physical evidence."})
        topology = {"schemaVersion": 1, "capturedAt": utc(self.clock()),
                    "source": "Live read-only lsblk, sysfs md and network state; optional lvs --readonly.",
                    "note": "Names are current aliases; serial-sorted placements remain provisional.",
                    "limitations": "Not an atomic hardware snapshot. No physical cable, bay, header or port confirmation. "
                                    "Kernel dependencies do not prove exact LVM extent allocation or cache occupancy.",
                    "nodes": list(nodes.values()), "raids": raids, "bonds": bonds,
                    "associations": associations}
        return {"disks": list(disks.values()), "snapshot": topology, "issues": issues, "lvm": lvm}

    def cpu(self, metrics):
        current = {}
        for line in self.text(self.proc / "stat").splitlines():
            fields = line.split()
            if re.fullmatch(r"cpu[0-9]*", fields[0]):
                current[fields[0]] = [int(value) for value in fields[1:9]]
        old = self.previous.get("cpu", {})
        self.previous["cpu"] = current
        values = {}
        for name, counters in current.items():
            delta = counter_delta(counters, old.get(name))
            values[name] = (100 * (sum(delta) - delta[3] - delta[4]) / sum(delta)
                            if delta and sum(delta) else None)
            metrics["cpu" if name == "cpu" else "thread-" + name[3:]] = values[name]
        groups, frequencies = {}, []
        for name in sorted(current):
            if name == "cpu":
                continue
            index = int(name[3:])
            base = self.sys / "devices" / "system" / "cpu" / name
            try:
                key = (int(self.text(base / "topology" / "physical_package_id")),
                       int(self.text(base / "topology" / "core_id")))
                groups.setdefault(key, []).append(index)
            except (OSError, ValueError):
                continue
            try:
                frequencies.append(int(self.text(base / "cpufreq" / "scaling_cur_freq")) / 1e6)
            except (OSError, ValueError):
                pass
        cores = [sorted(groups[key]) for key in sorted(groups)]
        for index, threads in enumerate(cores):
            samples = [values.get("cpu" + str(thread)) for thread in threads]
            metrics[f"core-{index}"] = sum(samples) / len(samples) if all(v is not None for v in samples) else None
        metrics["cpu-clock"] = sum(frequencies) / len(frequencies) if frequencies else None
        return {"cores": cores}

    def temperatures(self, metrics):
        found = False
        for hwmon in sorted((self.sys / "class" / "hwmon").glob("hwmon*")):
            try:
                if self.text(hwmon / "name") != "k10temp":
                    continue
                for label in hwmon.glob("temp*_label"):
                    if self.text(label) == "Tctl":
                        metrics["temp-cpu"] = int(self.text(label.with_name(label.name.replace("_label", "_input")))) / 1000
                        found = True
            except (OSError, ValueError):
                continue
        return found

    def smart(self, name, serial):
        payload = json.loads(self.runner("smart", name))
        observed_serial = str(payload.get("serial_number") or "").strip()
        if serial and observed_serial and observed_serial != serial:
            raise ValueError("SMART device identity changed since inventory; discarding sample")
        return smart_values(payload)

    def collect(self):
        now = self.clock()
        metrics = dict.fromkeys(("cpu", "cpu-clock", "cpu-power", "cache-used", "gpu-util",
            "gpu-3d", "gpu-copy", "gpu-encode", "gpu-decode", "gpu-dedicated", "gpu-shared",
            "gpu-power", "temp-cpu", "temp-gpu", "temp-board", "temp-lan", "fan-cpu1",
            "fan-cpu2", "fan-hub", "fan-gpu", "memory-used", "memory-apps", "memory-cache",
            "memory-kernel", "memory-free", "swap", "data-used", "root-used"))
        issues = ["Disk placement is provisional/serial-sorted, never physically confirmed.",
                  "memory-apps is residual other/anonymous memory, not per-process RSS.",
                  "Rear fan 2000 RPM values are ASSUMPTIONS, not measured; FAN3 is one shared six-fan hub reading.",
                  "Optional NVMe secondary is SMART temperature sensor 1; vendor-specific physical meaning is unverified.",
                  "CPU power, cache occupancy, GPU 3D/copy/shared memory are unavailable (no supported source)."]
        metrics.update({"fan-rear1": 2000, "fan-rear2": 2000})
        capacities = dict.fromkeys(("memory-used", "memory-apps", "memory-cache", "memory-kernel",
                                   "memory-free", "swap", "data-used", "root-used", "gpu-dedicated"))
        available, channel_keys = dict.fromkeys(("data-used", "root-used")), {}
        inventory = self.refresh("inventory", 60, self.inventory)
        if inventory is None:
            issues.append("inventory: unavailable or pending; no previous topology or bundled fixture substituted")
            inventory = {"disks": [], "snapshot": {"schemaVersion": 1, "capturedAt": utc(now),
                         "source": "Live inventory unavailable", "limitations": "No cached fixture substituted.",
                         "nodes": [], "raids": [], "bonds": [], "associations": []}, "issues": []}
        issues.extend(inventory["issues"])
        cpu = {"cores": []}
        try:
            cpu = self.cpu(metrics)
        except (OSError, ValueError, IndexError) as error:
            self.previous.pop("cpu", None)
            issues.append(f"cpu: unavailable ({type(error).__name__})")
        if metrics["cpu"] is None:
            issues.append("cpu: utilization unavailable (first sample, reset or missing counters)")
        if metrics["cpu-clock"] is None:
            issues.append("cpu-clock: current cpufreq readings unavailable")
        if not cpu["cores"]:
            issues.append("cpu: actual package/core topology unavailable")
        try:
            values, totals = memory_values(self.text(self.proc / "meminfo"))
            metrics.update(values)
            capacities.update(totals)
        except (OSError, ValueError) as error:
            issues.append(f"memory: unavailable ({type(error).__name__})")
        for mount, key in (("/", "root-used"), ("/data", "data-used")):
            try:
                # Avoid reporting the root filesystem as /data when /data is unmounted.
                if mount == "/data" and not os.path.ismount(mount):
                    raise OSError("/data is not a mount point")
                stat = os.statvfs(mount)
                metrics[key] = (stat.f_blocks - stat.f_bfree) * stat.f_frsize / TIB
                capacities[key] = stat.f_blocks * stat.f_frsize / TIB
                available[key] = stat.f_bavail * stat.f_frsize / TIB
            except (OSError, AttributeError) as error:
                issues.append(f"{key}: filesystem unavailable ({type(error).__name__})")
        if not self.temperatures(metrics):
            issues.append("temp-cpu: k10temp Tctl unavailable; no BMC/Tdie substitution")
        disk_by_name = {d["id"]: d for d in inventory["disks"]}
        block_ids = list(disk_by_name) + ["md0"]
        for name in block_ids:
            disk = disk_by_name.get(name)
            identity = disk["stableId"] if disk else "array:md0"
            prefix = "disk-array" if name == "md0" else "disk-" + name
            try:
                counters = [int(v) for v in self.text(self.sys / "class" / "block" / name / "stat").split()]
                previous = self.previous.get("block:" + name)
                rates = block_rates(counters, previous[1] if previous and previous[2] == identity else None,
                                    now - previous[0] if previous else 0)
                self.previous["block:" + name] = (now, counters, identity)
            except (OSError, ValueError):
                rates = dict.fromkeys(("read", "write", "active", "latency", "queue"))
                self.previous.pop("block:" + name, None)
            if any(value is None for value in rates.values()):
                issues.append(f"{name}: block rates unavailable (missing, reset or first sample)")
            for field, value in rates.items():
                key = prefix + "-" + field
                metrics[key] = value
                if identity:
                    channel_keys[key] = metric_key(identity, field)
            if not disk:
                continue
            temp_id = "temp-" + name
            if disk["kind"] == "nvme":
                temp_id = "temp-" + re.sub(r"n\d+$", "", name)
            metrics[temp_id] = None
            if disk["kind"] == "nvme":
                metrics[temp_id + "-secondary"] = None
            if identity:
                channel_keys[temp_id] = metric_key(identity, "temperature")
                if disk["kind"] == "nvme":
                    channel_keys[temp_id + "-secondary"] = metric_key(identity, "temperature_sensor1")
                result = self.refresh("smart:" + identity, 300,
                                      lambda n=name, s=disk["serial"]: self.smart(n, s))
                if result:
                    temperatures, issue = result
                    metrics[temp_id] = temperatures["composite"]
                    if disk["kind"] == "nvme":
                        metrics[temp_id + "-secondary"] = temperatures["secondary"]
                    if issue:
                        issues.append(f"{name}: {issue}")
                        self.sources["smart:" + identity]["status"] = "unavailable"
                else:
                    issues.append(f"{name}: SMART read unavailable or pending")
        active_blocks = {"block:" + name for name in block_ids}
        for key in list(self.previous):
            if key.startswith("block:") and key not in active_blocks:
                del self.previous[key]
        nics = [node["id"] for node in inventory["snapshot"]["nodes"]
                if node["kind"] in ("Linux network bond", "Physical network interface", "Network interface")]
        if not nics:
            issues.append("network: no physical NIC/bond inventory available")
        for name in nics:
            try:
                base = self.sys / "class" / "net" / name / "statistics"
                counters = [int(self.text(base / field)) for field in ("rx_bytes", "tx_bytes")]
                previous = self.previous.get("net:" + name)
                delta = counter_delta(counters, previous[1] if previous else None)
                elapsed = now - previous[0] if previous else 0
                self.previous["net:" + name] = (now, counters)
                values = [value * 8 / elapsed / 1e6 for value in delta] if delta is not None and elapsed > 0 else [None, None]
            except (OSError, ValueError):
                self.previous.pop("net:" + name, None)
                values = [None, None]
            for direction, value in zip(("rx", "tx"), values):
                metrics[f"net-{name}-{direction}"] = value
            if None in values:
                issues.append(f"{name}: NIC rates unavailable (missing, reset or first sample)")
        gpu = self.refresh("gpu", INTERVAL, lambda: next(csv.reader(io.StringIO(self.runner("gpu")))))
        if gpu and len(gpu) == 6:
            for key, index, divisor in (("gpu-util", 0, 1), ("gpu-dedicated", 1, 1024),
                                       ("temp-gpu", 3, 1), ("gpu-power", 4, 1), ("fan-gpu", 5, 1)):
                value = number(gpu[index].strip())
                metrics[key] = value / divisor if value is not None else None
            total = number(gpu[2].strip())
            capacities["gpu-dedicated"] = total / 1024 if total is not None else None
        engines = self.refresh("gpu-engines", INTERVAL,
                               lambda: next(csv.reader(io.StringIO(self.runner("gpu-engines")))))
        if engines and len(engines) == 2:
            metrics.update({"gpu-encode": number(engines[0].strip()), "gpu-decode": number(engines[1].strip())})
        bmc = self.refresh("bmc", 60, lambda: self.runner("bmc"))
        if bmc:
            expected = {"FAN1": "fan-cpu1", "FAN2": "fan-cpu2", "FAN3": "fan-hub",
                        "MB Temp": "temp-board", "Onboard LAN Temp": "temp-lan"}
            for line in bmc.splitlines():
                fields = [part.strip() for part in line.split("|")]
                if len(fields) >= 4 and fields[0] in expected:
                    metrics[expected[fields[0]]] = number(fields[1]) if fields[3] not in ("ns", "na", "nr") else None
        for key in ("fan-cpu1", "fan-cpu2", "fan-hub", "temp-board", "temp-lan"):
            if metrics[key] is None:
                issues.append(f"{key}: exact BMC sensor unavailable")
        for key in ("gpu-util", "gpu-dedicated", "gpu-power", "fan-gpu", "temp-gpu", "gpu-encode", "gpu-decode"):
            if metrics[key] is None:
                issues.append(f"{key}: NVIDIA counter unavailable/unsupported")
        for state in self.cache.values():
            if state["issue"]:
                issues.append(state["issue"])
        # Unidentified disks have current readings, but intentionally no persistent series.
        for key in metrics:
            if key not in channel_keys and not key.startswith(("disk-", "temp-sd", "temp-nvme")):
                channel_keys[key] = key if re.fullmatch(r"[A-Za-z0-9_.:-]+", key) else (
                    "channel_" + hashlib.sha256(key.encode()).hexdigest()[:32])
        for source in ("cpu", "memory", "filesystems", "k10temp", "block", "network"):
            failed = {"cpu": metrics["cpu"] is None,
                      "memory": metrics["memory-used"] is None,
                      "filesystems": any(metrics[key] is None for key in ("root-used", "data-used")),
                      "k10temp": metrics["temp-cpu"] is None,
                      "block": any(metrics.get(("disk-array" if name == "md0" else "disk-" + name) + "-read") is None
                                   for name in block_ids),
                      "network": not nics or any(metrics.get(f"net-{name}-rx") is None for name in nics)}[source]
            self.sources[source] = {"capturedAt": utc(now), "lastAttempt": utc(now),
                                    "expiresAt": utc(now + INTERVAL * 2),
                                    "status": "unavailable" if failed else "ok"}
        self.sources["rear-fans"] = {"capturedAt": None, "status": "assumed",
                                     "note": "2000 RPM constant assumption; no telemetry source"}
        return {"version": 1, "mode": "live", "capturedAt": utc(self.clock()), "intervalSeconds": INTERVAL,
                "retentionDays": 90, "metrics": metrics, "capacities": capacities, "available": available,
                "inventory": {"disks": inventory["disks"], "cpu": cpu, "snapshot": inventory["snapshot"],
                              "lvm": inventory.get("lvm"), "mapping": "provisional", "mappingMethod": "serial-sorted"},
                "issues": issues, "channelKeys": channel_keys, "sources": dict(self.sources)}

    def write(self, snapshot):
        lines = ["# HELP server_atlas_value Current Server Atlas measurement; absent when unavailable.",
                 "# TYPE server_atlas_value gauge"]
        for frontend, key in sorted(snapshot["channelKeys"].items()):
            value = snapshot["metrics"].get(frontend)
            if number(value) is not None:
                lines.append(f'server_atlas_value{{metric="{key}"}} {value}')
        atomic_write(self.state_dir / "metrics.prom", "\n".join(lines) + "\n")
        atomic_write(self.state_dir / "snapshot.json", json.dumps(snapshot, allow_nan=False, separators=(",", ":")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="/var/lib/server-atlas")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    collector = Collector(args.state_dir, background=not args.once)
    try:
        while True:
            started = time.monotonic()
            collector.write(collector.collect())
            if args.once:
                break
            time.sleep(max(0, INTERVAL - (time.monotonic() - started)))
    finally:
        collector.close()


if __name__ == "__main__":
    main()
