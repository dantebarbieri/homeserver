"""Read-only, allowlisted Docker accounting. Never publish inspect/env/argv."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from urllib.parse import quote, urlsplit


INTERVAL = 5
LIMIT = 8 * 1024 * 1024
IDENTITY = re.compile(r"[0-9a-f]{64}\Z")
ICON = re.compile(r"[a-z0-9][a-z0-9_.-]{0,100}\Z", re.I)
FIELDS = ("cpu", "memory", "memoryPercent", "diskRead", "diskWrite", "rx", "tx",
          "gpu", "gpuEncode", "gpuDecode", "vram")


def icon_url(icon):
    if not isinstance(icon, str):
        return None
    if icon.startswith("https://"):
        parsed = urlsplit(icon)
        if (not parsed.username and not parsed.password and not parsed.port and
                not parsed.query and not parsed.fragment and
                (parsed.hostname == "cdn.jsdelivr.net" or
                 (parsed.hostname or "").endswith(".danteb.com"))):
            return icon
        return None
    if not ICON.fullmatch(icon):
        return None
    if icon.startswith(("mdi-", "si-")):
        prefix, name = icon.split("-", 1)
        base = "npm/@mdi/svg@latest/svg" if prefix == "mdi" else "npm/simple-icons@latest/icons"
        return f"https://cdn.jsdelivr.net/{base}/{name.removesuffix('.svg')}.svg"
    extension = icon.rsplit(".", 1)[-1] if "." in icon else "png"
    if extension not in ("svg", "png", "webp"):
        return None
    name = icon.rsplit(".", 1)[0] if "." in icon else icon
    base = "selfhst/icons@main" if name.startswith("sh-") else "homarr-labs/dashboard-icons"
    return f"https://cdn.jsdelivr.net/gh/{base}/{extension}/{name.removeprefix('sh-')}.{extension}"


def homepage_metadata(text):
    import yaml
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ValueError("Invalid Homepage YAML") from None
    if not isinstance(data, list):
        raise ValueError("Homepage services must be a list")
    result = {}
    for group in data:
        if not isinstance(group, dict):
            continue
        for category, entries in group.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for name, config in entry.items():
                    if not isinstance(config, dict) or config.get("server") != "my-docker":
                        continue
                    container = config.get("container")
                    if not isinstance(container, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
                        continue
                    if container in result:
                        raise ValueError("Ambiguous Homepage container mapping")
                    result[container] = {"name": str(name)[:160], "group": str(category)[:160],
                                         "icon": icon_url(config.get("icon"))}
    return result


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def docker_get(path):
    if not (path == "/containers/json?all=1" or
            re.fullmatch(r"/containers/[0-9a-f]{64}/(?:stats\?stream=false&one-shot=true|top\?ps_args=-eo%20pid%2Ccomm)", path)):
        raise ValueError("Docker endpoint is not allowlisted")
    connection = UnixHTTP("localhost", timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read(LIMIT + 1)
        if response.status != 200 or len(raw) > LIMIT:
            raise OSError("Docker read failed")
        return json.loads(raw)
    finally:
        connection.close()


def rate(current, previous, elapsed, scale=1):
    if (previous is None or elapsed <= 0 or elapsed > 20 or current < previous or
            not all(math.isfinite(value) for value in (current, previous, elapsed))):
        return None
    return (current - previous) / elapsed * scale


def leaf_device(sys, major, minor):
    device = sys / "dev" / "block" / f"{major}:{minor}"
    if not device.exists():
        raise OSError("Block accounting device disappeared")
    return not ((device / "partition").exists() or
                ((device / "slaves").exists() and any((device / "slaves").iterdir())))


def process_stat(raw):
    # comm can contain spaces and parentheses; field 22 distinguishes PID reuse.
    _, separator, tail = raw.rpartition(")")
    fields = tail.split()
    if not separator or len(fields) < 22:
        raise ValueError("Invalid process stat")
    return {"ticks": int(fields[11]) + int(fields[12]),
            "started": int(fields[19]), "rss": int(fields[21])}


def gpu_processes(raw):
    names, result = None, {}
    for line in raw.splitlines():
        if line.startswith("#"):
            header = line[1:].split()
            if header[:3] == ["gpu", "pid", "type"]:
                names = header
            continue
        fields = line.split()
        if not fields or names is None:
            continue
        record = dict(zip(names, fields))
        if not record.get("pid", "").isdigit():
            continue
        pid = int(record["pid"])
        values = {}
        for name, column in (("gpu", "sm"), ("gpuEncode", "enc"), ("gpuDecode", "dec"), ("vram", "fb")):
            value = record.get(column, "-")
            values[name] = float(value) * (1024 ** 2 if name == "vram" else 1) if value.isdigit() else None
        if pid in result:
            for name in values:
                left, right = result[pid][name], values[name]
                values[name] = left + right if left is not None and right is not None else None
        result[pid] = values
    if names is None:
        raise ValueError("Unsupported NVIDIA per-process output")
    return result


def gpu_sample():
    process = subprocess.run(("nvidia-smi", "pmon", "-s", "um", "-c", "1"),
                             capture_output=True, timeout=4, check=True, text=True)
    if len(process.stdout) > LIMIT:
        raise ValueError("NVIDIA output exceeds limit")
    return gpu_processes(process.stdout)


def network_owners(containers):
    aliases = {}
    for item in containers:
        aliases[item["Id"]] = item["Id"]
        for name in item.get("Names", []):
            aliases[name.lstrip("/")] = item["Id"]
    owners = {}
    for item in containers:
        owner, visited = item, set()
        while owner["Id"] not in visited:
            visited.add(owner["Id"])
            mode = owner.get("HostConfig", {}).get("NetworkMode", "")
            if not mode.startswith("container:"):
                owners[item["Id"]] = None if mode in ("host", "none") else owner["Id"]
                break
            identity = aliases.get(mode[10:])
            owner = next((other for other in containers if other["Id"] == identity), None)
            if owner is None:
                break
        owners.setdefault(item["Id"], None)
    return owners


class ServiceCollector:
    def __init__(self, proc="/proc", sys="/sys", metadata="/srv/homeserver/homepage/services.yaml",
                 request=docker_get, gpu=gpu_sample, clock=time.monotonic):
        self.proc, self.sys, self.metadata = Path(proc), Path(sys), Path(metadata)
        self.request, self.gpu, self.clock = request, gpu, clock
        self.previous, self.old_processes = {}, {}
        self.cpus = os.cpu_count() or 1
        self.hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

    def block_totals(self, stats):
        entries = stats.get("blkio_stats", {}).get("io_service_bytes_recursive")
        if entries is None:
            return None, None
        totals = {"read": 0, "write": 0}
        for entry in entries:
            operation = str(entry.get("op", "")).lower()
            if operation not in totals:
                continue
            # Device-mapper/RAID layers repeat physical I/O. Count leaf devices only.
            if not leaf_device(self.sys, int(entry["major"]), int(entry["minor"])):
                continue
            totals[operation] += int(entry["value"])
        return totals["read"], totals["write"]

    def process(self, pid, name, identity, now, gpu, host_memory):
        base = self.proc / str(pid)
        before = process_stat((base / "stat").read_text())
        if not any(identity in line for line in (base / "cgroup").read_text().splitlines()):
            raise ProcessLookupError("Process moved out of this container")
        values = dict.fromkeys(FIELDS)
        io = None
        try:
            io = {key: int(value.strip()) for key, value in
                  (line.split(":", 1) for line in (base / "io").read_text().splitlines())}
        except PermissionError:
            pass
        after = process_stat((base / "stat").read_text())
        if before["started"] != after["started"]:
            raise ProcessLookupError("PID reused during collection")
        key = (identity, pid, after["started"])
        previous = self.old_processes.get(key)
        elapsed = now - previous["time"] if previous else 0
        values["cpu"] = rate(after["ticks"], previous["ticks"] if previous else None, elapsed, 100 / self.hz / self.cpus)
        values["memory"] = max(0, after["rss"]) * self.page
        values["memoryPercent"] = values["memory"] / host_memory * 100
        if io:
            for field, counter in (("diskRead", "read_bytes"), ("diskWrite", "write_bytes")):
                values[field] = rate(io[counter], previous["io"].get(counter) if previous and previous["io"] else None, elapsed)
        if gpu is not None:
            values.update(gpu.get(pid, dict.fromkeys(("gpu", "gpuEncode", "gpuDecode", "vram"), 0)))
        return ({"id": f"{pid}:{after['started']}", "pid": pid, "name": name[:100], "values": values},
                key, {"time": now, "ticks": after["ticks"], "io": io})

    def container(self, item, metadata, owners, gpu, host_memory):
        identity = item["Id"]
        name = item["Names"][0].lstrip("/")
        row = {"id": identity, "container": name, "name": name, "group": "Other containers",
               "icon": None, "state": item.get("State", "unknown"), "values": dict.fromkeys(FIELDS),
               "processes": [], "issues": [], "processStatus": "unavailable",
               "networkOwner": owners[identity]}
        row.update(metadata.get(name, {}))
        if row["state"] != "running":
            return row, None, {}
        try:
            stats = self.request(f"/containers/{identity}/stats?stream=false&one-shot=true")
            now = self.clock()
            previous = self.previous.get(identity)
            elapsed = now - previous["time"] if previous else 0
            total = int(stats["cpu_stats"]["cpu_usage"]["total_usage"])
            counters = {"cpu": total, "diskRead": None, "diskWrite": None, "rx": None, "tx": None}
            try:
                counters["diskRead"], counters["diskWrite"] = self.block_totals(stats)
            except (OSError, ValueError, KeyError, TypeError):
                row["issues"].append("Block-device accounting unavailable; CPU and memory are still reported.")
            if owners[identity] == identity and "networks" in stats:
                # Tunnel counters repeat the traffic on the namespace's Docker links.
                links = [value for key, value in stats["networks"].items()
                         if not re.match(r"^(lo$|tun|tap|wg)", key)]
                if links:
                    counters.update({field: sum(int(link[counter]) for link in links)
                                     for field, counter in (("rx", "rx_bytes"), ("tx", "tx_bytes"))})
            values = row["values"]
            for field, counter in counters.items():
                values[field] = rate(counter, previous.get(field) if previous else None, elapsed,
                                     100 / 1e9 / self.cpus if field == "cpu" else 1) if counter is not None else None
            usage = stats.get("memory_stats", {})
            if "usage" in usage:
                inactive = usage.get("stats", {}).get("inactive_file", usage.get("stats", {}).get("total_inactive_file", 0))
                values["memory"] = max(0, int(usage["usage"]) - int(inactive))
                values["memoryPercent"] = values["memory"] / host_memory * 100
            row["memoryLimit"] = usage.get("limit")
            new_previous = {"time": now, **counters}
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            row["issues"].append("Container counters unavailable; no previous readings substituted.")
            return row, None, {}
        new_processes = {}
        try:
            top = self.request(f"/containers/{identity}/top?ps_args=-eo%20pid%2Ccomm")
            pid_column, name_column = top["Titles"].index("PID"), top["Titles"].index("COMMAND")
            rows = top["Processes"]
            if len(rows) > 20000:
                raise ValueError("Process count exceeds limit")
            missed = 0
            for process in rows:
                try:
                    observed, key, counters = self.process(int(process[pid_column]), process[name_column],
                                                          identity, now, gpu, host_memory)
                    row["processes"].append(observed)
                    new_processes[key] = counters
                except (OSError, ValueError, KeyError, IndexError):
                    missed += 1
            row["processStatus"] = "partial" if missed else "ok"
            if missed:
                row["issues"].append(f"{missed} process(es) exited, moved or could not be read.")
            if gpu is not None and not missed:
                for field in ("gpu", "gpuEncode", "gpuDecode", "vram"):
                    samples = [process["values"][field] for process in row["processes"]]
                    row["values"][field] = sum(samples) if samples and all(value is not None for value in samples) else None
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            row["issues"].append("Process enumeration unavailable.")
        return row, new_previous, new_processes

    def collect(self):
        started = self.clock()
        issues, metadata = [], {}
        try:
            metadata = homepage_metadata(self.metadata.read_text())
        except (OSError, ValueError) as error:
            issues.append(f"Homepage names/icons unavailable ({type(error).__name__}); Docker names shown.")
        try:
            gpu = self.gpu()
        except (OSError, ValueError, subprocess.SubprocessError):
            gpu = None
            issues.append("NVIDIA per-process counters unavailable; GPU columns are not host-wide substitutes.")
        host_memory = next(int(line.split()[1]) * 1024 for line in
                           (self.proc / "meminfo").read_text().splitlines() if line.startswith("MemTotal:"))
        if host_memory <= 0:
            raise ValueError("Invalid host memory")
        containers = self.request("/containers/json?all=1")
        if not isinstance(containers, list) or len(containers) > 1000:
            raise ValueError("Invalid Docker inventory")
        if any(not IDENTITY.fullmatch(item.get("Id", "")) or not item.get("Names") for item in containers):
            raise ValueError("Invalid Docker identities")
        owners = network_owners(containers)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda item: self.container(item, metadata, owners, gpu, host_memory), containers))
        rows, previous, processes = [], {}, {}
        for row, counters, children in results:
            rows.append(row)
            if counters is not None:
                previous[row["id"]] = counters
            processes.update(children)
        self.previous, self.old_processes = previous, processes
        return {"version": 1, "mode": "live", "status": "ok", "capturedAt": datetime.now(timezone.utc).isoformat(),
                "intervalSeconds": INTERVAL, "hostCpus": self.cpus, "hostMemory": host_memory,
                "collectionSeconds": self.clock() - started, "services": rows, "issues": issues}

    def snapshot(self):
        try:
            return self.collect()
        except (OSError, ValueError, KeyError, TypeError, StopIteration, http.client.HTTPException) as error:
            self.previous, self.old_processes = {}, {}
            return {"version": 1, "mode": "live", "status": "unavailable",
                    "capturedAt": datetime.now(timezone.utc).isoformat(), "services": [],
                    "issues": [f"Service accounting unavailable ({type(error).__name__})."]}

    def run(self, stop, write):
        while not stop.is_set():
            started = self.clock()
            write(json.dumps(self.snapshot(), allow_nan=False, separators=(",", ":")))
            stop.wait(max(0, INTERVAL - (self.clock() - started)))
