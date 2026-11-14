"""Prove the worker's share access: media read-only, cache writable, no escapes.

Run as _studio with both shares mounted. The SHA256 is the 2026-11-13 canary
copy; update it for another file.
"""
import errno
import hashlib
import os
from pathlib import Path
import pwd
import uuid

assert pwd.getpwuid(os.getuid()).pw_name == "_studio"
media = Path("/var/lib/studio-worker/mounts/media")
cache = Path("/var/lib/studio-worker/mounts/cache")
source = media / "tdarr-studio-canary" / (
    "Frasier (1993) - S04E24 - Odd Man Out "
    "[WEBDL-1080p][AAC 2.0][x264]-FUZEER.mkv"
)
with source.open("rb") as file:
    digest = hashlib.file_digest(file, "sha256").hexdigest()
assert digest == "5c4e10d341b2865af4cbcca4091b65cacf070c498284653430d4bed5f261a22f"
print("READ: disposable media copy matches its Linux SHA256")

name = ".studio-permission-probe-" + uuid.uuid4().hex
try:
    with (media / "tdarr-studio-canary" / name).open("xb"):
        pass
except OSError as error:
    if error.errno not in {errno.EROFS, errno.EACCES}:
        raise
    print("DENIED: creating a new media file")
else:
    (media / "tdarr-studio-canary" / name).unlink()
    raise RuntimeError("Media mount unexpectedly permits writes")

probe = cache / name
payload = b"private studio cache boundary check\n"
with probe.open("xb") as file:
    file.write(payload)
    file.flush()
    os.fsync(file.fileno())
try:
    assert probe.read_bytes() == payload
    print("WRITE/READ: dedicated cache")
finally:
    probe.unlink()
assert not probe.exists()
print("DELETE: own dedicated-cache probe")

link = cache / ".studio-containment-6ba27f90f4dd4b3393f619a1aef80c04"
try:
    descriptor = os.open(link, os.O_RDONLY)
except OSError as error:
    # Samba's confirmed NT_STATUS_STOPPED_ON_SYMLINK maps to EIO on this Mac.
    if error.errno not in {errno.EACCES, errno.EPERM, errno.ENOENT, errno.ELOOP, errno.EIO}:
        raise
    with source.open("rb") as control:
        assert control.read(1)
    print(f"DENIED: outside-share symlink access (errno {error.errno})")
else:
    os.close(descriptor)
    raise RuntimeError("Shared-cache symlink escaped its share")

print("Actual media/cache access checks passed")
