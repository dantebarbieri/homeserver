import json
from pathlib import Path
import shutil
import threading
import unittest
import uuid

import collector


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".test-state-" + uuid.uuid4().hex)
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class CounterTests(unittest.TestCase):
    def test_block_rates_reset_missing_and_gauge_decrease(self):
        before = [10, 0, 100, 20, 10, 0, 200, 30, 8, 100, 200]
        after = [12, 0, 300, 30, 13, 0, 400, 40, 0, 600, 1200]
        result = collector.block_rates(after, before, 5)
        self.assertAlmostEqual(result["read"], 200 * 512 / 5 / 1e6)
        self.assertEqual(result["active"], 10)
        self.assertEqual(result["latency"], 4)
        self.assertEqual(result["queue"], .2)
        self.assertTrue(all(v is None for v in collector.block_rates(before, after, 5).values()))
        self.assertTrue(all(v is None for v in collector.block_rates(after, None, 5).values()))
        self.assertIsNone(collector.counter_delta([100, 4], [99, 5]))

    def test_memory_is_non_overlapping_and_used_is_independent(self):
        fields = {"MemTotal": 1000, "MemFree": 100, "MemAvailable": 450,
                  "Buffers": 30, "Cached": 200, "SReclaimable": 50, "Shmem": 20,
                  "SUnreclaim": 40, "KernelStack": 10, "PageTables": 10,
                  "SwapTotal": 100, "SwapFree": 80}
        values, capacities = collector.memory_values("\n".join(f"{key}: {value} kB" for key, value in fields.items()))
        self.assertAlmostEqual(sum(values["memory-" + key] for key in ("apps", "cache", "kernel", "free")),
                               capacities["memory-used"])
        self.assertAlmostEqual(values["memory-used"], 550 * 1024 / collector.GIB)
        self.assertNotEqual(values["memory-used"], values["memory-apps"] + values["memory-kernel"])
        with self.assertRaises(ValueError):
            collector.memory_values("MemTotal: 10 kB")

    def test_smart_standby_warnings_and_unsupported_channels(self):
        standby = {"smartctl": {"exit_status": 2, "messages": [{"string": "Device in STANDBY"}]},
                   "temperature": {"current": 42}}
        values, issue = collector.smart_values(standby)
        self.assertIsNone(values["composite"])
        self.assertIn("standby", issue)
        values, issue = collector.smart_values({"smartctl": {"exit_status": 8},
                                               "temperature": {"current": 37}})
        self.assertEqual(values["composite"], 37)
        self.assertIsNone(issue)
        values, _ = collector.smart_values({"nvme_smart_health_information_log":
                                           {"temperature": 44, "temperature_sensors": [0]}})
        self.assertEqual(values["composite"], 44)
        self.assertIsNone(values["secondary"])
        self.assertIsNone(collector.smart_values({})[0]["composite"])

    def test_command_rejects_non_device_arguments(self):
        for name in ("../../etc/passwd", "sda;reboot", "/dev/sda", "md0"):
            with self.assertRaises(ValueError):
                collector.command("smart", name)


class AssignmentTests(WorkspaceTest):
    def disk(self, name, serial, **extra):
        return {"id": name, "serial": serial, "kind": "hdd", **extra}

    def test_persistence_renumbering_and_absent_reservations(self):
        disks = [self.disk("sda", "SYNTH-Z"), self.disk("sdb", "SYNTH-A"),
                 self.disk("nvme0n1", "SYNTH-N", kind="nvme")]
        assignments, issues = collector.assign_slots(disks, {})
        self.assertFalse(issues)
        self.assertEqual(disks[1]["slot"], "cage-1-bay-1")
        self.assertEqual(disks[0]["slot"], "cage-1-bay-2")
        self.assertEqual(disks[2]["slot"], "M2_1")
        path = self.root / "assignments.json"
        collector.atomic_write(path, json.dumps({"assignments": assignments}))
        saved = collector.Collector(self.root).assignments
        new = [self.disk("sdq", "SYNTH-Z"), self.disk("sda", "SYNTH-0")]
        updated, _ = collector.assign_slots(new, saved)
        self.assertEqual(new[0]["slot"], "cage-1-bay-2")
        self.assertEqual(new[1]["slot"], "cage-1-bay-3")
        self.assertEqual(updated["serial:SYNTH-A"], "cage-1-bay-1")
        self.assertEqual(collector.metric_key("serial:SYNTH-Z", "read"),
                         collector.metric_key(new[0]["stableId"], "read"))

    def test_no_identity_no_fallback_and_duplicates(self):
        disks = [self.disk("sda", ""), self.disk("sdb", "SYNTH-DUP"),
                 self.disk("sdc", "SYNTH-DUP")]
        assignments, issues = collector.assign_slots(disks, {})
        self.assertEqual(assignments, {})
        self.assertEqual(len(issues), 3)
        self.assertTrue(all(d["slot"] is None and d["stableId"] is None for d in disks))
        with self.assertRaises(ValueError):
            collector.assign_slots([], {"serial:SYNTH-A": "M2_1", "serial:SYNTH-B": "M2_1"})
        self.assertEqual(collector.stable_id({"wwn": "SYNTH-W", "serial": "SYNTH-S"}), "wwn:SYNTH-W")

    def test_missing_source_invalidates_cached_value(self):
        now = [1000]
        instance = collector.Collector(self.root, clock=lambda: now[0])
        self.assertEqual(instance.refresh("test", 60, lambda: 10), 10)
        now[0] += 59
        self.assertEqual(instance.refresh("test", 60, lambda: 20), 10)
        now[0] += 1

        def failure():
            raise OSError("synthetic missing source")

        self.assertIsNone(instance.refresh("test", 60, failure))
        self.assertEqual(instance.sources["test"]["status"], "unavailable")
        self.assertIsNone(instance.sources["test"]["capturedAt"])

    def test_actual_core_grouping_and_per_thread_usage(self):
        self.write("proc/stat", "cpu 20 0 0 180 0 0 0 0\ncpu0 10 0 0 90 0 0 0 0\ncpu4 10 0 0 90 0 0 0 0\n")
        for index in (0, 4):
            self.write(f"sys/devices/system/cpu/cpu{index}/topology/physical_package_id", "0")
            self.write(f"sys/devices/system/cpu/cpu{index}/topology/core_id", "7")
            self.write(f"sys/devices/system/cpu/cpu{index}/cpufreq/scaling_cur_freq", "3200000")
        instance = collector.Collector(self.root / "state", self.root / "proc", self.root / "sys")
        metrics = {}
        self.assertEqual(instance.cpu(metrics)["cores"], [[0, 4]])
        self.assertIsNone(metrics["cpu"])
        self.write("proc/stat", "cpu 30 0 0 190 0 0 0 0\ncpu0 15 0 0 95 0 0 0 0\ncpu4 15 0 0 95 0 0 0 0\n")
        instance.cpu(metrics)
        self.assertEqual(metrics["core-0"], 50)
        self.assertEqual(metrics["thread-4"], 50)
        self.assertEqual(metrics["cpu-clock"], 3.2)

    def test_inventory_and_export_have_no_serial_labels(self):
        def runner(source, device=None):
            if source == "lsblk":
                return json.dumps({"blockdevices": [
                    {"name": "sda", "kname": "sda", "type": "disk", "size": 1000,
                     "serial": "SYNTH-PRIVATE-SERIAL", "model": "Synthetic disk", "mountpoints": [],
                     "children": [{"name": "sda1", "type": "part", "size": 900, "mountpoints": []}]}
                ]})
            raise OSError("synthetic missing utility")

        instance = collector.Collector(self.root / "state", self.root / "proc", self.root / "sys", runner=runner)
        inventory = instance.inventory()
        disk = inventory["disks"][0]
        self.assertEqual(disk["slot"], "cage-1-bay-1")
        self.assertEqual(inventory["snapshot"]["nodes"][1]["parents"][0]["id"], "sda")
        association = next(a for a in inventory["snapshot"]["associations"] if
                           "drive-cage-1-bay-1" in a["targets"])
        self.assertEqual(association["nodes"], ["sda"])
        self.assertIn("NOT physically confirmed", association["note"])
        key = collector.metric_key(disk["stableId"], "read")
        snapshot = {"channelKeys": {"disk-sda-read": key, "cpu": "cpu"},
                    "metrics": {"disk-sda-read": 1.5, "cpu": None}}
        instance.write(snapshot)
        output = (self.root / "state" / "metrics.prom").read_text()
        self.assertIn(key, output)
        self.assertNotIn("SYNTH-PRIVATE-SERIAL", output)
        self.assertNotIn('metric="cpu"', output)

    def test_nvme_role_follows_mount_dependencies_not_number(self):
        devices = [
            {"name": "nvme1n1", "type": "disk", "serial": "SYNTH-A",
             "children": [{"name": "nvme1n1p1", "type": "part", "children": [
                 {"name": "mapper-root", "kname": "dm-1", "type": "lvm",
                  "fstype": "ext4", "mountpoints": ["/"]}]}]},
            {"name": "nvme0n1", "type": "disk", "serial": "SYNTH-B"},
        ]

        def runner(source):
            return json.dumps({"blockdevices": devices}) if source == "lsblk" else '{"report":[]}'

        instance = collector.Collector(self.root / "state", sys=self.root / "sys", runner=runner)
        inventory = instance.inventory()
        disks = {disk["id"]: disk for disk in inventory["disks"]}
        self.assertEqual(disks["nvme1n1"]["role"], "root")
        self.assertNotIn("role", disks["nvme0n1"])  # /data use alone would not prove cache.
        self.assertEqual(disks["nvme1n1"]["slot"], "M2_1")
        association = next(a for a in inventory["snapshot"]["associations"] if "M2_1" in a["targets"])
        self.assertEqual(association["nodes"], ["nvme1n1"])
        self.assertIn("drive-M2_1", association["targets"])

    def test_background_refresh_does_not_block_sampling_and_expires(self):
        now = [1000]
        instance = collector.Collector(self.root / "state", clock=lambda: now[0], background=True)
        entered, release = threading.Event(), threading.Event()

        def slow():
            entered.set()
            release.wait(timeout=3)
            return 42

        try:
            self.assertIsNone(instance.refresh("slow", 60, slow))
            self.assertTrue(entered.wait(timeout=1))
            self.assertIsNone(instance.refresh("slow", 60, slow))
            self.assertEqual(instance.sources["slow"]["status"], "pending")
            release.set()
            instance.pending["slow"].result(timeout=1)
            self.assertEqual(instance.refresh("slow", 60, slow), 42)
            now[0] += 121
            entered.clear()
            release.clear()
            self.assertIsNone(instance.refresh("slow", 60, slow))
            self.assertEqual(instance.sources["slow"]["status"], "stale")
        finally:
            release.set()
            instance.close()

    def test_readonly_lvm_cache_segments_work_without_kernel_device_numbers(self):
        devices = [{"name": "nvme7n1", "type": "disk", "serial": "SYNTH-CACHE",
                    "children": [{"name": "nvme7n1p1", "type": "part", "children": [
                        {"name": "cache-data", "kname": "dm-2", "type": "lvm"}]}]}]
        rows = [
            {"vg_name": "vg-test", "lv_name": "[cache-pool]", "segtype": "cache-pool",
             "lv_kernel_major": "-1", "lv_kernel_minor": "-1", "devices": "cache-data(0)"},
            {"vg_name": "vg-test", "lv_name": "[cache-data]", "segtype": "linear",
             "lv_kernel_major": "-1", "lv_kernel_minor": "-1", "devices": "/dev/nvme7n1p1(11)"},
        ]
        self.write("sys/class/block/dm-2/dm/name", "vg--test-cache--data")

        def runner(source):
            return json.dumps({"blockdevices": devices} if source == "lsblk" else {"report": [{"lv": rows}]})

        instance = collector.Collector(self.root / "state", sys=self.root / "sys", runner=runner)
        inventory = instance.inventory()
        self.assertEqual(inventory["disks"][0]["role"], "cache")
        node = next(n for n in inventory["snapshot"]["nodes"] if n["id"] == "dm-2")
        self.assertIn("/dev/vg-test/cache-data", node["aliases"])
        self.assertIn("linear", node["summary"])

    def test_smart_rejects_identity_change_and_has_no_wakeup_retry(self):
        calls = []

        def runner(source, device):
            calls.append((source, device))
            return json.dumps({"serial_number": "SYNTH-OTHER",
                               "temperature": {"current": 50}})

        instance = collector.Collector(self.root / "state", runner=runner)
        with self.assertRaises(ValueError):
            instance.smart("sda", "SYNTH-EXPECTED")
        self.assertEqual(calls, [("smart", "sda")])

    def test_complete_snapshot_handles_missing_sources_without_old_numbers(self):
        fields = {"MemTotal": 1000, "MemFree": 100, "MemAvailable": 450,
                  "Buffers": 30, "Cached": 200, "SReclaimable": 50, "Shmem": 20,
                  "SUnreclaim": 40, "KernelStack": 10, "PageTables": 10,
                  "SwapTotal": 100, "SwapFree": 80}
        self.write("proc/meminfo", "\n".join(f"{key}: {value} kB" for key, value in fields.items()))
        self.write("proc/stat", "cpu 10 0 0 90 0 0 0 0\ncpu0 10 0 0 90 0 0 0 0\n")
        self.write("sys/class/hwmon/hwmon0/name", "k10temp")
        self.write("sys/class/hwmon/hwmon0/temp1_label", "Tctl")
        self.write("sys/class/hwmon/hwmon0/temp1_input", "48000")
        now = [1000]
        missing = [False]

        def runner(source, device=None):
            if source == "lsblk":
                return '{"blockdevices":[]}'
            if source == "lvs":
                return '{"report":[]}'
            if source == "gpu" and not missing[0]:
                return "45, 1024, 8192, 55, 80, 35"
            if source == "gpu-engines" and not missing[0]:
                return "N/A, 20"
            if source == "bmc" and not missing[0]:
                return "FAN1 | 900 | RPM | ok\nFAN2 | 850 | RPM | ok\nFAN3 | 800 | RPM | ok\nMB Temp | 40 | degrees C | ok\nOnboard LAN Temp | 60 | degrees C | ok"
            raise OSError("synthetic missing device")

        instance = collector.Collector(self.root / "state", self.root / "proc", self.root / "sys",
                                       runner=runner, clock=lambda: now[0])
        first = instance.collect()
        self.assertEqual(first["metrics"]["temp-cpu"], 48)
        self.assertEqual(first["metrics"]["gpu-dedicated"], 1)
        self.assertEqual(first["capacities"]["gpu-dedicated"], 8)
        self.assertEqual(first["metrics"]["fan-hub"], 800)
        self.assertIsNone(first["metrics"]["gpu-encode"])
        self.assertEqual(first["sources"]["gpu"]["capturedAt"], collector.utc(1000))
        missing[0] = True
        now[0] += 60
        second = instance.collect()
        self.assertIsNone(second["metrics"]["gpu-util"])
        self.assertIsNone(second["metrics"]["fan-hub"])
        self.assertEqual(second["sources"]["gpu"]["status"], "unavailable")
        self.assertIsNone(second["capacities"]["gpu-dedicated"])
        instance.write(second)
        text = (self.root / "state" / "snapshot.json").read_text(encoding="utf-8")
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)


if __name__ == "__main__":
    unittest.main()
