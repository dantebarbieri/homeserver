import contextlib
import errno
import importlib.util
import io
from pathlib import Path
import socket
import unittest
from unittest.mock import MagicMock, patch


spec = importlib.util.spec_from_file_location(
    "wake_pc", Path(__file__).parents[1] / "wake-pc.py",
)
wake_pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake_pc)

EXPECTED_MAC = bytes.fromhex("74563cb4f54e")
EXPECTED_PACKET = b"\xff" * 6 + EXPECTED_MAC * 16


class WakePcTests(unittest.TestCase):
    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = wake_pc.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_default_packet_and_broadcast_socket(self):
        with patch.object(wake_pc.socket, "socket") as factory:
            sender = factory.return_value.__enter__.return_value
            sender.sendto.return_value = 102
            result, output, error = self.run_cli([])
        factory.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sender.sendto.assert_called_once_with(EXPECTED_PACKET, ("192.168.50.255", 9))
        self.assertEqual(result, 0)
        self.assertIn("Sent magic packet", output)
        self.assertEqual(error, "")

    def test_mac_formats(self):
        for value in ("74:56:3C:B4:F5:4E", "74-56-3c-b4-f5-4e", "74563cb4f54e"):
            with self.subTest(value=value):
                self.assertEqual(wake_pc.parse_mac(value), EXPECTED_MAC)

    def test_invalid_cli_never_opens_socket(self):
        cases = [
            ["--mac", value] for value in (
                "", "74:56:3c:b4:f5", "74:56-3c:b4:f5:4e",
                "GG:56:3c:b4:f5:4e", "00:00:00:00:00:00",
                "ff:ff:ff:ff:ff:ff", "01:56:3c:b4:f5:4e",
            )
        ] + [
            ["--broadcast", value] for value in (
                "DANTE-PC", "192.168.50.999", "::1", "192.168.50.0/24",
                "0.0.0.0", "224.0.0.1", "240.0.0.1",
            )
        ] + [
            ["--port", value] for value in ("0", "-1", "65536", "abc", "9.5")
        ] + [
            ["--wait", value] for value in ("0", "-1", "nan", "inf", "1e999", "abc")
        ] + [
            ["--wait", "--wait-host", value] for value in (
                "DANTE-PC", "::1", "255.255.255.255", "0.0.0.0",
            )
        ] + [
            ["--wait-host", "127.0.0.1"], ["--wait-port", "1234"],
            ["--wait-host", "192.168.50.180"], ["--wait-port", "3389"],
            ["--wait", "--wait-port", "65536"],
            ["--unknown"], ["--broadcast"], ["--ip", "192.168.50.180"],
        ]
        for argv in cases:
            with self.subTest(argv=argv), patch.object(wake_pc.socket, "socket") as factory:
                with self.assertRaises(SystemExit) as exc:
                    self.run_cli(argv)
                self.assertEqual(exc.exception.code, 2)
                factory.assert_not_called()

    def test_destination_override_preserves_mac(self):
        with patch.object(wake_pc.socket, "socket") as factory:
            sender = factory.return_value.__enter__.return_value
            sender.sendto.return_value = 102
            result, _, _ = self.run_cli(["--broadcast", "192.168.60.255", "--port", "65535"])
        self.assertEqual(result, 0)
        sender.sendto.assert_called_once_with(EXPECTED_PACKET, ("192.168.60.255", 65535))

    def test_broadcast_and_mac_override(self):
        with patch.object(wake_pc.socket, "socket") as factory:
            sender = factory.return_value.__enter__.return_value
            sender.sendto.return_value = 102
            result, _, _ = self.run_cli([
                "--broadcast", "255.255.255.255", "--mac", "02:11:22:33:44:55",
            ])
        self.assertEqual(result, 0)
        sender.sendto.assert_called_once_with(
            b"\xff" * 6 + bytes.fromhex("021122334455") * 16,
            ("255.255.255.255", 9),
        )

    def test_send_errors_are_nonzero_and_not_success_shaped(self):
        for stage in ("create", "option", "send", "short"):
            with self.subTest(stage=stage), patch.object(wake_pc.socket, "socket") as factory:
                sender = factory.return_value.__enter__.return_value
                sender.sendto.return_value = 102
                if stage == "create":
                    factory.side_effect = OSError("socket unavailable")
                elif stage == "option":
                    sender.setsockopt.side_effect = OSError("permission denied")
                elif stage == "send":
                    sender.sendto.side_effect = OSError("network unreachable")
                else:
                    sender.sendto.return_value = 0
                result, output, error = self.run_cli([])
                self.assertEqual(result, 1)
                self.assertEqual(output, "")
                self.assertIn("wake-pc: failed to send", error)

    def test_help_sends_nothing(self):
        with patch.object(wake_pc.socket, "socket") as factory:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli(["--help"])
            self.assertEqual(exc.exception.code, 0)
            factory.assert_not_called()

    def test_help_has_no_epilog(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            wake_pc.main(["--help"])
        self.assertNotIn("A DHCP IP change", output.getvalue())
        self.assertIn("--wait [SECONDS]", output.getvalue())

    def test_wait_cli_defaults_and_overrides(self):
        for argv, endpoint in (
            (["--wait"], ("192.168.50.180", 3389, 120.0)),
            (["--wait", "2.5"], ("192.168.50.180", 3389, 2.5)),
            (["--wait", "--wait-host", "127.0.0.1", "--wait-port", "1234"],
             ("127.0.0.1", 1234, 120.0)),
        ):
            with self.subTest(argv=argv), patch.object(wake_pc.socket, "socket") as factory:
                factory.return_value.__enter__.return_value.sendto.return_value = 102
                with patch.object(wake_pc, "wait_for_rdp", return_value=0) as wait:
                    self.assertEqual(self.run_cli(argv)[0], 0)
                    wait.assert_called_once_with(*endpoint)
                factory.return_value.__enter__.return_value.sendto.assert_called_once_with(
                    EXPECTED_PACKET, ("192.168.50.255", 9),
                )

    def test_send_only_never_checks_readiness(self):
        with patch.object(wake_pc.socket, "socket") as factory:
            factory.return_value.__enter__.return_value.sendto.return_value = 102
            with patch.object(wake_pc, "wait_for_rdp") as wait:
                self.assertEqual(self.run_cli([])[0], 0)
                wait.assert_not_called()

    def test_send_failure_never_waits(self):
        with patch.object(wake_pc.socket, "socket", side_effect=OSError("send failed")):
            with patch.object(wake_pc, "wait_for_rdp") as wait:
                self.assertEqual(self.run_cli(["--wait"])[0], 1)
                wait.assert_not_called()

    def run_wait(self, effects, timeout=1.0):
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        output, error = io.StringIO(), io.StringIO()
        with patch.object(wake_pc.time, "monotonic", side_effect=lambda: now[0]):
            with patch.object(wake_pc.time, "sleep", side_effect=sleep):
                with patch.object(wake_pc.socket, "create_connection", side_effect=effects) as connect:
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        result = wake_pc.wait_for_rdp("192.168.50.180", 3389, timeout)
        return result, output.getvalue(), error.getvalue(), connect, now[0]

    def test_already_reachable_does_not_claim_wake(self):
        result, output, error, _, _ = self.run_wait([MagicMock()])
        self.assertEqual(result, 0)
        self.assertIn("may already have been online", output)
        self.assertIn("Windows login not verified", output)
        self.assertEqual(error, "")

    def test_retries_then_reachable(self):
        result, output, _, connect, elapsed = self.run_wait([
            ConnectionRefusedError(errno.ECONNREFUSED, "refused"), MagicMock(),
        ])
        self.assertEqual(result, 0)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(elapsed, 0.5)
        self.assertIn("RDP reachable", output)

    def test_timeout_is_bounded_and_reports_rdp_not_power(self):
        result, output, error, connect, elapsed = self.run_wait(
            TimeoutError("connect timed out"), timeout=0.25,
        )
        self.assertEqual(result, 1)
        self.assertEqual(elapsed, 0.25)
        connect.assert_called_once_with(("192.168.50.180", 3389), timeout=0.25)
        self.assertIn("RDP not reachable", error)
        self.assertNotIn("RDP reachable", output)

    def test_late_connection_does_not_report_success(self):
        with patch.object(wake_pc.time, "monotonic", side_effect=[0, 0, 2, 2, 2]):
            with patch.object(wake_pc.time, "sleep"):
                with patch.object(wake_pc.socket, "create_connection", return_value=MagicMock()):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(wake_pc.wait_for_rdp("127.0.0.1", 3389, 1), 1)

    def test_unexpected_probe_error_is_explicit(self):
        result, _, error, connect, _ = self.run_wait(
            PermissionError(errno.EACCES, "permission denied"),
        )
        self.assertEqual(result, 1)
        self.assertEqual(connect.call_count, 1)
        self.assertIn("RDP check failed", error)
        self.assertIn("permission denied", error)

    def test_ctrl_c_is_clean(self):
        with patch.object(wake_pc, "run", side_effect=KeyboardInterrupt):
            result, output, error = self.run_cli(["--wait"])
        self.assertEqual(result, 130)
        self.assertEqual(output, "")
        self.assertEqual(error, "wake-pc: interrupted.\n")

    def test_real_loopback_packet(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            port = receiver.getsockname()[1]
            result, output, error = self.run_cli(["--broadcast", "127.0.0.1", "--port", str(port)])
            packet, _ = receiver.recvfrom(1024)
        self.assertEqual(result, 0)
        self.assertEqual(packet, EXPECTED_PACKET)
        self.assertEqual(len(packet), 102)
        self.assertIn("Sent magic packet", output)
        self.assertEqual(error, "")

    def test_real_loopback_wait(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                result, output, error = self.run_cli([
                    "--broadcast", "127.0.0.1", "--port", str(receiver.getsockname()[1]),
                    "--wait", "1", "--wait-host", "127.0.0.1",
                    "--wait-port", str(listener.getsockname()[1]),
                ])
                connection, _ = listener.accept()
                connection.close()
            packet, _ = receiver.recvfrom(1024)
        self.assertEqual(result, 0)
        self.assertEqual(packet, EXPECTED_PACKET)
        self.assertIn("RDP reachable", output)
        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
