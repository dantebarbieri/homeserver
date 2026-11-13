"""Prove the _studio worker cannot get a shell, unapproved forwards, the admin
SSH key or a Docker socket.

Run as _studio.
"""
import errno
import os
import pwd
import socket
import subprocess

assert pwd.getpwuid(os.getuid()).pw_name == "_studio"
base = ["/usr/bin/ssh", "-v", "-F", "/var/lib/studio-worker/.ssh/config",
        "-o", "ConnectTimeout=5"]
tests = [
    ("shell", ["studio-transfer", "true"], "open failed: connect failed: open failed"),
    ("pty", ["-tt", "studio-transfer", "true"], "open failed: connect failed: open failed"),
    ("sftp", ["-s", "studio-transfer", "sftp"], "open failed: connect failed: open failed"),
    ("unapproved forwarding", ["-W", "127.0.0.1:22", "studio-transfer"],
     "administratively prohibited"),
    ("reverse forwarding", ["-N", "-R", "127.0.0.1:0:127.0.0.1:1445",
                            "studio-transfer"], "remote port forwarding failed"),
]
for name, arguments, expected in tests:
    result = subprocess.run(base + arguments, input="", capture_output=True,
                            text=True, timeout=12, check=False)
    if (result.returncode != 255 or expected not in result.stderr.lower()
            or "Authenticated to " not in result.stderr):
        raise RuntimeError(f"{name} restriction not proved: code={result.returncode}, "
                           f"error={result.stderr.strip()}")
    print(f"DENIED: {name}")

try:
    descriptor = os.open("/Users/dante/.ssh/id_ed25519", os.O_RDONLY)
except PermissionError:
    print("DENIED: administrator private key access")
else:
    os.close(descriptor)
    raise RuntimeError("Worker can open administrator private key")

for path in ["/var/run/docker.sock", "/Users/dante/.colima/default/docker.sock"]:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        try:
            client.connect(path)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.ENOENT}:
                raise
            print(f"UNAVAILABLE: Docker socket ({error.errno})")
        else:
            raise RuntimeError(f"Worker can connect to Docker socket: {path}")

print("Worker account and SSH forwarding boundary checks passed")
