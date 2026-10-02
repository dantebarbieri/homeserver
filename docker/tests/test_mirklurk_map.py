import importlib.util
import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("map_smoke", ROOT / "scripts/mirklurk-map-smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class MapDeploymentTests(unittest.TestCase):
    def test_synthetic_packet_contains_only_one_generated_character(self):
        packet = smoke.packet("Synthetic deployment check")
        length = struct.unpack(">I", packet[:4])[0]
        manifest = json.loads(packet[4:4 + length])
        body = packet[4 + length:]
        self.assertEqual(manifest["entries"], [
            {"path": "Player.save", "size": len(body), "modified": 0},
        ])
        self.assertEqual(json.loads(body), [{"worldGrid": [[1] * 5 for _ in range(5)]}])
        self.assertLess(len(packet), 1024)

    def test_redirects_do_not_forward_capabilities(self):
        self.assertIsNone(smoke.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere/"))

    def test_map_proxy_uses_socket_peer_and_disables_api_logs(self):
        config = (ROOT / "nginx/mirklurk-map-npm.conf").read_text()
        self.assertIn("location ^~ /api/", config)
        self.assertIn("access_log off;", config)
        self.assertIn("error_log /dev/null;", config)
        self.assertIn("proxy_set_header X-Forwarded-For $realip_remote_addr;", config)
        self.assertNotIn("$proxy_add_x_forwarded_for", config)
        self.assertIn("client_max_body_size 64m;", config)
        self.assertIn("if ($scheme = http) { return 403; }", config)

    def test_web_trusts_only_exact_proxy_and_overwrites_upload_identity(self):
        config = (ROOT / "nginx/mirklurk-map.conf").read_text()
        trusted = [line.strip() for line in config.splitlines() if line.strip().startswith("set_real_ip_from")]
        self.assertEqual(trusted, [
            "set_real_ip_from 192.168.128.46;",
            "set_real_ip_from fd2b:92df:1a5b:1::2e;",
        ])
        self.assertIn("proxy_set_header X-Upload-IP $remote_addr;", config)
        self.assertIn("error_log /dev/null;", config)
        self.assertIn("connect-src 'self'", config)


if __name__ == "__main__":
    unittest.main()
