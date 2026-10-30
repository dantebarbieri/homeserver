import contextlib
import importlib.util
import io
from pathlib import Path
import socket
import unittest
from unittest.mock import patch


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
        self.assertIn("Wake not verified", output)
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
        ] + [["--unknown"], ["--broadcast"], ["--ip", "192.168.50.180"]]
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
        self.assertIn("Wake not verified", output)
        self.assertEqual(error, "")


if __name__ == "__main__":
    unittest.main()
