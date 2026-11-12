"""Authenticated ntfy publishing with a persistent, retrying outbox."""

import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.request
import uuid


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def publisher_headers():
    path = os.environ.get("NTFY_TOKEN_FILE")
    if not path:
        raise ValueError("NTFY_TOKEN_FILE is not configured")
    token = Path(path).read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"tk_[A-Za-z0-9_]+", token):
        raise ValueError("Invalid ntfy publisher token")
    return {"Authorization": f"Bearer {token}"}


class Outbox:
    def __init__(self, state, url, topic):
        self.directory = Path(state) / "ntfy-outbox"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.url = url.rstrip("/") + "/" + topic
        self.lock = threading.Lock()

    def _sync_directory(self):
        if os.name == "posix":
            fd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def submit(self, title, body, priority="default", tags=""):
        entry = {"title": title, "body": body, "priority": priority, "tags": tags}
        fd, tmp = tempfile.mkstemp(prefix=".new-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(entry, file)
                file.flush()
                os.fsync(file.fileno())
            dest = self.directory / f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
            os.replace(tmp, dest)
            self._sync_directory()
        except (OSError, ValueError, TypeError):
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self.flush()

    def flush(self):
        with self.lock:
            for path in sorted(self.directory.glob("*.json")):
                try:
                    with path.open(encoding="utf-8") as file:
                        entry = json.load(file)
                    req = urllib.request.Request(
                        self.url, data=entry["body"].encode(),
                        headers={"Title": entry["title"], "Priority": entry["priority"],
                                 "Tags": entry["tags"], **publisher_headers()})
                    with _opener.open(req, timeout=15):
                        pass
                    path.unlink()
                    self._sync_directory()
                except (OSError, ValueError, KeyError, TypeError) as error:
                    print(f"WARNING: ntfy outbox delivery failed: {type(error).__name__}", flush=True)
                    return False
        return True

    def start(self):
        def retry():
            while True:
                try:
                    self.flush()
                except OSError as error:
                    print(f"WARNING: ntfy outbox unavailable: {type(error).__name__}", flush=True)
                time.sleep(15)

        threading.Thread(target=retry, name="ntfy-outbox", daemon=True).start()


_outbox = None


def start_outbox(state, url, topic):
    global _outbox
    if _outbox is None:
        _outbox = Outbox(state, url, topic)
        _outbox.start()
    return _outbox
