"""Make Bazarr's Whisper provider reject non-2xx responses and redirects.

Upstream saves any response body, including 503 or 422 errors, as a subtitle.
Every edit must match exactly once; any upstream change fails the image build.
"""

import re
import sys
from pathlib import Path

IMPORT = "from requests.exceptions import JSONDecodeError\n"
CALL = re.compile(
    r'^(?P<indent>[ \t]*)r = self\.session\.post\(f"\{self\.endpoint\}/'
    r'(?P<endpoint>detect-language|asr)",(?P<arguments>[^()]*)'
    r"timeout=\(self\.response, self\.timeout\)\)$",
    re.MULTILINE,
)


def guarded(match):
    indent = match["indent"]
    return (
        f'{indent}r = self.session.post(f"{{self.endpoint}}/{match["endpoint"]}",'
        f"{match['arguments']}timeout=(self.response, self.timeout), allow_redirects=False)\n"
        f"{indent}if not 200 <= r.status_code < 300:\n"
        f'{indent}    raise HTTPError(f"WhisperAI request failed with HTTP {{r.status_code}}")'
    )


def patch(source):
    if source.count(IMPORT) != 1 or "allow_redirects" in source:
        raise SystemExit("Unexpected Bazarr Whisper provider: imports or redirects changed")
    endpoints = sorted(match["endpoint"] for match in CALL.finditer(source))
    if endpoints != ["asr", "detect-language"]:
        raise SystemExit(f"Unexpected Bazarr Whisper provider requests: {endpoints}")
    source = source.replace(IMPORT, "from requests.exceptions import HTTPError, JSONDecodeError\n")
    source = CALL.sub(guarded, source)
    compile(source, "whisperai.py", "exec")
    return source


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_whisperai.py <whisperai.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Patched Bazarr Whisper provider to reject non-2xx responses")
