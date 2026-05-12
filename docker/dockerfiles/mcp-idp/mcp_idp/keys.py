"""RSA keypair persistence + JWT signing + JWKS export.

On first start, generates an RSA-2048 keypair, persists it to ``keys_path``
in JWKS-format JSON. Subsequent starts load the existing key. Multiple keys
can coexist for rotation: the *first* key in the file is the active signing
key; all keys are advertised in JWKS so verifiers can validate JWTs signed
by any of them.

Manual rotation procedure:
    1. Stop the container.
    2. ``python -m mcp_idp.keys rotate <keys_path>`` (generates a new active
       key, demotes the old one to verification-only).
    3. Start the container.
    4. After all access tokens issued under the old key have expired
       (default 1h), remove the old key from the file.

Automatic rotation isn't implemented — for "just me" the manual flow is
fine and avoids the JWKS-grace-window timing complexity.
"""
from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey


@dataclass(frozen=True)
class JwtSigner:
    """Signs JWTs with the active key, exposes the full keyset for JWKS."""

    keyset: KeySet
    active_kid: str
    active_alg: str = "RS256"

    def sign(self, claims: dict) -> str:
        """Sign claims with the active key. Caller fills `iss/sub/aud/exp/iat`."""
        active = self._active_key()
        header = {"alg": self.active_alg, "kid": active.kid, "typ": "JWT"}
        return jwt.encode(header=header, claims=claims, key=active)

    def _active_key(self) -> RSAKey:
        for k in self.keyset.keys:
            if k.kid == self.active_kid:
                return k  # type: ignore[return-value]
        raise RuntimeError(f"active kid {self.active_kid!r} not in keyset")

    def public_jwks_dict(self) -> dict:
        """Return the JWKS as a public-keys-only dict for ``/jwks.json``."""
        return {
            "keys": [
                # joserfc's as_dict(private=False) strips the private parameters.
                k.as_dict(private=False)
                for k in self.keyset.keys
            ]
        }


def load_or_create_signer(keys_path: str) -> JwtSigner:
    """Load JWKS from disk if present, else generate a fresh keypair.

    The file format is the standard JWKS json shape. The first entry is the
    active signing key.
    """
    path = Path(keys_path)
    if path.exists():
        return _load_signer(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return _create_signer(path)


def _load_signer(path: Path) -> JwtSigner:
    data = json.loads(path.read_text())
    keyset = KeySet.import_key_set(data)
    if not keyset.keys:
        raise RuntimeError(f"keys file {path} has no keys")
    active = keyset.keys[0]
    if not active.kid:
        raise RuntimeError(
            f"first key in {path} has no `kid` — re-generate the keypair"
        )
    return JwtSigner(keyset=keyset, active_kid=active.kid)


def _create_signer(path: Path) -> JwtSigner:
    kid = f"k{int(time.time())}"
    key = RSAKey.generate_key(
        2048,
        parameters={"kid": kid, "alg": "RS256", "use": "sig"},
        private=True,
    )
    keyset = KeySet([key])
    # Persist with private parameters so we can sign on next start.
    path.write_text(
        json.dumps({"keys": [key.as_dict(private=True)]}, indent=2)
    )
    # Best-effort tighten file mode on POSIX. Python on Windows ignores 0o600.
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return JwtSigner(keyset=keyset, active_kid=kid)


__all__ = ["JwtSigner", "load_or_create_signer"]
