"""Exercise a patched copy of the installed Bazarr Whisper provider."""

import ast
from datetime import timedelta
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace


class HTTPError(Exception):
    pass


def load_methods(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    provider = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WhisperAIProvider"
    )
    methods = [
        node for node in provider.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"detect_language", "download_subtitle"}
    ]
    if len(methods) != 2:
        raise RuntimeError("Expected Bazarr Whisper provider methods not found")
    for method in methods:
        method.decorator_list = []
        method.returns = None
        for arg in method.args.posonlyargs + method.args.args + method.args.kwonlyargs:
            arg.annotation = None
    namespace = {
        "HTTPError": HTTPError,
        "JSONDecodeError": ValueError,
        "logger": logging.getLogger("bazarr-test"),
        "time": time,
        "timedelta": timedelta,
        "wlm": SimpleNamespace(
            alpha3_to_alpha2=lambda value: "te",
            get_name=lambda value: value,
            _get_language=lambda code, name: (code, name),
        ),
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def check(path):
    methods = load_methods(path)
    for status in (200, 302, 400, 503):
        requests = []
        response = SimpleNamespace(
            status_code=status,
            content=b"1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            json=lambda: {"language_code": "te", "detected_language": "telugu"},
        )

        def post(url, **kwargs):
            requests.append((url, kwargs))
            return response

        provider = SimpleNamespace(
            encode_audio_stream=lambda *args: b"\0\0",
            ffmpeg_path="ffmpeg",
            pass_video_name=False,
            endpoint="http://127.0.0.1:9000",
            session=SimpleNamespace(post=post),
            response=10,
            timeout=10,
        )
        subtitle = SimpleNamespace(
            task="translate", audio_language="tel", force_audio_stream=None,
            video=SimpleNamespace(original_path="test"), content=None,
        )
        for name, argument in (("download_subtitle", subtitle), ("detect_language", "test")):
            try:
                result = methods[name](provider, argument)
            except HTTPError:
                if status == 200:
                    raise
            else:
                if status != 200:
                    raise AssertionError(f"{name} accepted HTTP {status}")
                if name == "detect_language" and result != ("te", "telugu"):
                    raise AssertionError("Unexpected successful detection")
            if requests[-1][1].get("allow_redirects") is not False:
                raise AssertionError(f"{name} allows redirects")
        if subtitle.content != (response.content if status == 200 else None):
            raise AssertionError(f"Incorrect subtitle content for HTTP {status}")
    print("Patched provider: 200 succeeds; 302, 400 and 503 rejected for both endpoints")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check-bazarr-whisper-patch.py <patched-whisperai.py>")
    check(sys.argv[1])
