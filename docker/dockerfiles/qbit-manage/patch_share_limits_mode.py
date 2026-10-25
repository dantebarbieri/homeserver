"""Backport upstream qbit_manage 5b15de5 (#1437) to the pinned release.

qBittorrent Web API 2.15.3 (qBittorrent 5.3.0) made shareLimitsMode a required
parameter of torrents/setShareLimits. The fix sends share_limits_mode="Default"
only when the connected Web API is 2.15.3 or newer. Remove this file once the
pinned release includes the fix.
"""

import argparse
import hashlib
from pathlib import Path

NAME = "modules/core/share_limits.py"
SOURCE_HASH = "ec1cfc76a8731fc88b2b72260f35ca4a2af6cbd541cd3c3cb8705b488d468612"
# Identical to upstream 5b15de5604f90289630ff8d4c50d9345690f8afb:modules/core/share_limits.py.
PATCHED_HASH = "dba01ff86b8749de46e4188d01266cb0e5ebaee87bbdc271c058238a9b426f05"

MODE_KWARGS = "**self._mode_kwargs(),\n"

HUNKS = [
    ("import os\nfrom datetime import timedelta\n", "import os\nimport re\nfrom datetime import timedelta\n", 1),
    (
        "from modules.webhooks import GROUP_NOTIFICATION_LIMIT\n\n",
        "from modules.webhooks import GROUP_NOTIFICATION_LIMIT\n\n"
        "# torrents/setShareLimits requires shareLimitsMode from Web API 2.15.3 (WebAPI_Changelog.md).\n"
        "SHARE_LIMITS_MODE_MIN_API = (2, 15, 3)\n\n\n"
        "def _parse_api_version(version):\n"
        "    parts = []\n"
        '    for piece in str(version).lstrip("vV").split(".")[:3]:\n'
        '        match = re.match(r"\\d+", piece)\n'
        "        parts.append(int(match.group()) if match else 0)\n"
        "    return tuple(parts + [0] * (3 - len(parts)))\n\n\n",
        1,
    ),
    (
        "                            share_limit_action=\"Default\",\n                        )\n",
        "                            share_limit_action=\"Default\",\n                            " + MODE_KWARGS
        + "                        )\n",
        1,
    ),
    (
        "    def set_limits(\n",
        "    def _mode_kwargs(self):\n"
        '        """shareLimitsMode kwarg for set_share_limits, only when the connected Web API requires it."""\n'
        '        if getattr(self, "_share_limits_mode_kwargs", None) is None:\n'
        "            try:\n"
        "                api_version = self.client.app.web_api_version\n"
        "                needs_mode = _parse_api_version(api_version) >= SHARE_LIMITS_MODE_MIN_API\n"
        "            except Exception:\n"
        "                needs_mode = False\n"
        '            self._share_limits_mode_kwargs = {"share_limits_mode": "Default"} if needs_mode else {}\n'
        "        return self._share_limits_mode_kwargs\n\n"
        "    def set_limits(\n",
        1,
    ),
    (
        "                share_limit_action=share_limit_action,\n            )\n",
        "                share_limit_action=share_limit_action,\n                " + MODE_KWARGS + "            )\n",
        1,
    ),
    (
        "                        share_limit_action=\"Default\",\n                    )\n",
        "                        share_limit_action=\"Default\",\n                        " + MODE_KWARGS
        + "                    )\n",
        1,
    ),
]


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def patched(source):
    if sha256(source) != SOURCE_HASH:
        raise ValueError(f"{NAME}: unexpected source sha256 {sha256(source)}")
    for old, new, count in HUNKS:
        if source.count(old) != count:
            raise ValueError(f"{NAME}: expected {count} match(es) for {old[:60]!r}")
        source = source.replace(old, new)
    if source.count("self._mode_kwargs()") != 3:
        raise ValueError(f"{NAME}: expected 3 set_share_limits call sites")
    compile(source, NAME, "exec")
    if PATCHED_HASH and sha256(source) != PATCHED_HASH:
        raise ValueError(f"{NAME}: unexpected patched sha256 {sha256(source)}")
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    path = parser.parse_args().source_root / NAME
    result = patched(path.read_bytes().decode("utf-8"))
    path.write_bytes(result.encode("utf-8"))
    print(f"Backported shareLimitsMode fix; patched sha256 {sha256(result)}")


if __name__ == "__main__":
    main()
