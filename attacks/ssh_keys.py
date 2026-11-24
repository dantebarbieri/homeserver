"""Recognize public-key fingerprints without access to any private SSH material."""

import base64
import hashlib
import json
from pathlib import Path
import re
import shlex

from events import REASONS, text


class SSHKeys:
    def __init__(self, path):
        self.path = Path(path)
        self.keys = {}
        self.status = {"state": "unavailable", "message": "Public-key registry has not loaded"}

    def reload(self):
        try:
            data = self.path.read_bytes()
            if len(data) > 1024 * 1024:
                raise ValueError("Registry too large")
            users = json.loads(data)
            keys = {}
            for user, entries in users.items():
                if not isinstance(entries, list):
                    raise ValueError("Invalid key list")
                for number, line in enumerate(entries, 1):
                    # Preserve backslashes in comments (e.g. Windows key labels).
                    lexer = shlex.shlex(line, posix=True)
                    lexer.whitespace_split = True
                    lexer.commenters = ""
                    lexer.escape = ""
                    tokens = list(lexer)
                    for index, token in enumerate(tokens[:-1]):
                        if not re.fullmatch(r"(?:ssh-|ecdsa-|sk-)[A-Za-z0-9@._+-]+", token):
                            continue
                        raw = base64.b64decode(tokens[index + 1], validate=True)
                        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
                        label = " ".join(tokens[index + 2:]) or f"configured key {number}"
                        keys[(user, fingerprint)] = text(label, 120)
                        break
                    else:
                        raise ValueError("Malformed public key")
            self.keys = keys
            self.status = {"state": "ready", "message": f"{len(keys)} Nix-managed public keys; no private key access"}
        except (OSError, ValueError, TypeError, AttributeError) as error:
            self.keys = {}
            self.status = {"state": "unavailable", "message": f"Public-key registry unavailable ({type(error).__name__})"}

    def annotate(self, item):
        # Forgejo manages its own SSH keys, so the host registry says nothing about them.
        if item["kind"] != "ssh_accepted" or item.get("service") != "SSH":
            return item
        label = self.keys.get((item.get("user"), item.get("keyFingerprint")))
        if label and item.get("authMethod") == "publickey":
            return {**item, "keyStatus": "recognized", "keyLabel": label}
        return {**item, "kind": "ssh_accepted_unknown", "title": "SSH accepted: unregistered credential",
                "keyStatus": "unregistered", "reason": REASONS["ssh_accepted_unknown"]}
