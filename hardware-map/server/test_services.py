import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services import ServiceCollector, docker_get, gpu_processes, homepage_metadata, icon_url, network_owners


CID = "a" * 64


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "meminfo").write_text("MemTotal: 1048576 kB\n")
        self.metadata = self.root / "services.yaml"
        self.metadata.write_text("- Media:\n    - Friendly Plex:\n        container: plex\n        server: my-docker\n"
                                 "        icon: plex.svg\n        widget:\n          key: must-not-leak\n")
        leaf = patch("services.leaf_device", side_effect=lambda sys, major, minor: major == 8)
        leaf.start()
        self.addCleanup(leaf.stop)
        self.pid = self.root / "11"
        self.pid.mkdir()
        (self.pid / "cgroup").write_text(f"0::/system.slice/docker-{CID}.scope\n")
        self.stat(100)
        self.io(100)
        self.now, self.cpu, self.read, self.rx = 100, 1000000000, 100, 100
        self.containers = [{"Id": CID, "Names": ["/plex"], "State": "running", "HostConfig": {"NetworkMode": "proxy"},
                            "Labels": {"secret": "must-not-leak"}, "Command": "secret-password"}]
        self.collector = ServiceCollector(self.root, self.root, self.metadata, self.request,
                                          gpu=lambda: {}, clock=lambda: self.now)
        self.collector.cpus, self.collector.hz, self.collector.page = 32, 100, 4096

    def stat(self, ticks, started=10):
        fields = ["0"] * 22
        fields[0], fields[11], fields[19], fields[21] = "S", str(ticks), str(started), "100"
        (self.pid / "stat").write_text("11 (name with ) spaces) " + " ".join(fields))

    def io(self, read):
        (self.pid / "io").write_text(f"read_bytes: {read}\nwrite_bytes: 0\n")

    def request(self, path):
        if path == "/containers/json?all=1":
            return self.containers
        if "/stats?" in path:
            return {"cpu_stats": {"cpu_usage": {"total_usage": self.cpu}}, "memory_stats": {
                "usage": 1000000, "stats": {"inactive_file": 100000}, "limit": 2000000},
                "blkio_stats": {"io_service_bytes_recursive": [
                    {"major": 8, "minor": 0, "op": "Read", "value": self.read}]},
                "networks": {"eth0": {"rx_bytes": self.rx, "tx_bytes": 20},
                             "tun0": {"rx_bytes": self.rx, "tx_bytes": 20}}}
        return {"Titles": ["PID", "COMMAND"], "Processes": [["11", "Plex Transcoder"]]}

    def test_whole_host_cpu_working_set_and_directional_rates_without_secret_fields(self):
        first = self.collector.collect()["services"][0]
        self.assertIsNone(first["values"]["cpu"])
        self.assertIsNone(first["values"]["rx"])
        self.assertEqual(first["values"]["memory"], 900000)
        self.assertEqual(first["name"], "Friendly Plex")
        self.now += 5
        self.cpu += 5000000000
        self.read += 1000
        self.rx += 2000
        self.stat(600)
        self.io(1100)
        snapshot = self.collector.collect()
        row = snapshot["services"][0]
        self.assertEqual(row["values"]["cpu"], 3.125)
        self.assertEqual(row["values"]["diskRead"], 200)
        self.assertEqual(row["values"]["rx"], 400)
        self.assertEqual(row["processes"][0]["values"]["cpu"], 3.125)
        self.assertIsNone(row["processes"][0]["values"]["rx"])
        self.assertEqual(row["processes"][0]["values"]["memory"], 409600)
        self.assertNotIn("must-not-leak", json.dumps(snapshot))
        self.assertNotIn("secret-password", json.dumps(snapshot))

    def test_resets_gaps_and_pid_reuse_do_not_create_spikes(self):
        self.collector.collect()
        self.now += 5
        self.cpu = 10
        self.rx = 0
        self.stat(999999, started=20)
        row = self.collector.collect()["services"][0]
        self.assertIsNone(row["values"]["cpu"])
        self.assertIsNone(row["values"]["rx"])
        self.assertIsNone(row["processes"][0]["values"]["cpu"])
        self.now += 30
        self.cpu += 1
        self.assertIsNone(self.collector.collect()["services"][0]["values"]["cpu"])

    def test_shared_namespace_counted_once_and_host_network_not_attributed(self):
        borrower = {**self.containers[0], "Id": "b" * 64, "Names": ["/consumer"],
                    "HostConfig": {"NetworkMode": "container:" + CID}}
        host = {**borrower, "Id": "c" * 64, "HostConfig": {"NetworkMode": "host"}}
        self.assertEqual(network_owners([self.containers[0], borrower, host]),
                         {CID: CID, "b" * 64: CID, "c" * 64: None})
        self.containers.append(borrower)
        self.collector.collect()
        self.now += 5
        self.rx += 2000
        rows = self.collector.collect()["services"]
        self.assertEqual(rows[0]["values"]["rx"], 400)
        self.assertIsNone(rows[1]["values"]["rx"])

    def test_block_layers_not_double_counted_and_stopped_rows_not_zeroed(self):
        stats = {"blkio_stats": {"io_service_bytes_recursive": [
            {"major": 253, "minor": 0, "op": "Read", "value": 500},
            {"major": 8, "minor": 0, "op": "Read", "value": 500}]}}
        self.assertEqual(self.collector.block_totals(stats), (500, 0))
        self.containers[0]["State"] = "exited"
        row = self.collector.collect()["services"][0]
        self.assertTrue(all(value is None for value in row["values"].values()))

    def test_racing_process_and_gpu_failure_are_explicit_not_fake_zeros(self):
        self.collector.gpu = lambda: (_ for _ in ()).throw(OSError())
        (self.pid / "cgroup").write_text("0::/another-container\n")
        snapshot = self.collector.collect()
        row = snapshot["services"][0]
        self.assertIsNone(row["values"]["gpu"])
        self.assertEqual(row["processStatus"], "partial")
        self.assertTrue(row["issues"])
        self.assertTrue(snapshot["issues"])

    def test_homepage_mapping_is_explicit_local_and_icons_cannot_carry_credentials(self):
        self.assertEqual(homepage_metadata(self.metadata.read_text())["plex"]["icon"],
                         "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/plex.svg")
        self.assertIsNone(icon_url("https://user:password@icons.danteb.com/a.svg"))
        self.assertIsNone(icon_url("https://icons.danteb.com/a.svg?key=secret"))
        self.assertIsNone(icon_url("https://danteb.com.evil/a.svg"))
        with self.assertRaises(ValueError):
            homepage_metadata("- Media: [")
        with self.assertRaises(ValueError):
            docker_get("/containers/id/restart")

    def test_nvidia_columns_use_per_pid_samples_not_device_totals(self):
        rows = gpu_processes("# gpu pid type sm mem enc dec fb command\n0 11 C 40 2 80 - 250 python\n")
        self.assertEqual(rows[11], {"gpu": 40, "gpuEncode": 80, "gpuDecode": None, "vram": 250 * 1024 ** 2})
        with self.assertRaises(ValueError):
            gpu_processes("Not supported")


if __name__ == "__main__":
    unittest.main()
