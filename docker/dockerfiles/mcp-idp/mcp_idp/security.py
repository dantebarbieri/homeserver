"""Cryptographic helpers — HMAC token hashing, secret generation, constant-time compare.

We use HMAC-SHA256 with a server-side pepper (``IDP_PEPPER``) for all
hashed secrets — client_secret, auth-code, refresh-token. This kills the
DCR bcrypt-DoS vector flagged by the design rubber-duck (open registration
+ heavy hash = trivial DoS) while remaining secure because the secrets we
hash are all 256+ bits of entropy from :func:`secrets.token_urlsafe`.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


def hash_secret(value: str, pepper: str) -> str:
    """HMAC-SHA256 hex digest of ``value`` keyed by ``pepper``.

    Storing the digest (not the cleartext) means a database snapshot can't
    be replayed against the IdP. The pepper is operator-set and stored
    only in env / docker-secret, never in the database, so even a full
    database leak doesn't give an attacker the cleartext.
    """
    return hmac.new(
        pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_hashed_secret(value: str, expected_hash: str, pepper: str) -> bool:
    """Constant-time compare of HMAC(value) vs ``expected_hash``."""
    actual = hash_secret(value, pepper)
    return hmac.compare_digest(actual, expected_hash)


def random_token(nbytes: int = 32) -> str:
    """URL-safe random token (base64url, no padding). 32 bytes → ~43 chars,
    256 bits of entropy."""
    return secrets.token_urlsafe(nbytes)


def random_id(prefix: str = "", nbytes: int = 16) -> str:
    """Short URL-safe random ID with optional prefix. 16 bytes → ~22 chars."""
    return f"{prefix}{secrets.token_urlsafe(nbytes)}"


def constant_time_eq(a: str, b: str) -> bool:
    """Cross-length-safe constant-time string compare."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


__all__ = [
    "constant_time_eq",
    "hash_secret",
    "random_id",
    "random_token",
    "verify_hashed_secret",
]
