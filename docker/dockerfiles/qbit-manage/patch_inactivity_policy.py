"""Apply one fail-closed validation exception to the pinned upstream release."""

import argparse
import hashlib
from pathlib import Path


REVISION = "1732b2b1acb9a3ea4c44b83c822e675d1bbe7fed"
SOURCE_HASHES = {
    "modules/config.py": "4830037f9798fae46d45c4e0a15026761fae880f40075af2361bcabdaeb8fe0a",
    "modules/util.py": "53d672a26f6a07df3d0a7a0a7dbf8afb9a57e1fd440ab5a30e1e6bd86c15f82b",
    "modules/core/share_limits.py": "dba01ff86b8749de46e4188d01266cb0e5ebaee87bbdc271c058238a9b426f05",
}
ORIGINAL = '                if self.share_limits[group]["min_seeding_time"] > 0 and self.share_limits[group]["max_ratio"] <= 0:\n'
REPLACEMENT = '''                if (
                    self.share_limits[group]["min_seeding_time"] > 0
                    and self.share_limits[group]["max_ratio"] <= 0
                    and not (
                        self.share_limits[group]["max_ratio"] == -1
                        and self.share_limits[group]["max_seeding_time"] == -1
                        and self.share_limits[group]["max_last_active"] > 0
                    )
                ):
'''


def verify_source(name, source):
    actual = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if actual != SOURCE_HASHES[name]:
        raise ValueError(f"{name}: expected pinned {REVISION} source; got sha256 {actual}")


def patched_config(source):
    verify_source("modules/config.py", source)
    if source.count(ORIGINAL) != 1:
        raise ValueError("Expected exactly one upstream minimum-seeding-time validator")
    patched = source.replace(ORIGINAL, REPLACEMENT, 1)
    compile(patched, "modules/config.py", "exec")
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    root = parser.parse_args().source_root
    sources = {name: (root / name).read_bytes().decode("utf-8") for name in SOURCE_HASHES}
    for name, source in sources.items():
        verify_source(name, source)
    (root / "modules/config.py").write_bytes(patched_config(sources["modules/config.py"]).encode("utf-8"))
    print("Applied inactivity-only validation exception; runtime cleanup is unchanged")


if __name__ == "__main__":
    main()
