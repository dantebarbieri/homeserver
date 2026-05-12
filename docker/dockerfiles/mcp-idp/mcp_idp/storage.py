"""Async SQLite storage for clients, codes, refresh tokens, auth requests, etc.

All secrets / codes / tokens stored as HMAC-SHA256 hashes (see
:mod:`mcp_idp.security`). The cleartext values are returned to clients
exactly once at issuance and never persisted.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import aiosqlite

# Schema is created idempotently on startup (see :func:`init_db`).
SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    client_secret_hash TEXT NOT NULL,
    client_name TEXT,
    redirect_uris_json TEXT NOT NULL,
    grant_types_json TEXT NOT NULL,
    response_types_json TEXT NOT NULL,
    token_endpoint_auth_method TEXT NOT NULL,
    scope TEXT,
    registered_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_map (
    -- Maps the authenticated proxy username (e.g. Authelia Remote-User) to a
    -- stable opaque subject identifier. Survives username renames.
    proxy_user TEXT PRIMARY KEY,
    sub TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_requests (
    -- Server-side authorization-request transaction. Created by GET /authorize,
    -- consumed by POST /authorize (consent submit). Decouples request params
    -- from the consent form so the POST submits ONLY (auth_request_id,
    -- csrf_token, decision) and we never trust hidden form fields for
    -- security-critical values.
    auth_request_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    response_type TEXT NOT NULL,
    scope TEXT,
    state TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    nonce TEXT,
    resource TEXT NOT NULL,
    sub TEXT NOT NULL,
    csrf_token_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    scope TEXT,
    code_challenge TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    nonce TEXT,
    sub TEXT NOT NULL,
    resource TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    sub TEXT NOT NULL,
    scope TEXT,
    resource TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked_at INTEGER,
    replaced_by_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_codes_expires_at ON auth_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_requests_expires_at ON auth_requests(expires_at);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
"""


@dataclass(frozen=True)
class Client:
    client_id: str
    client_secret_hash: str
    client_name: str | None
    redirect_uris: tuple[str, ...]
    grant_types: tuple[str, ...]
    response_types: tuple[str, ...]
    token_endpoint_auth_method: str
    scope: str | None
    registered_at: int


@dataclass(frozen=True)
class AuthRequest:
    auth_request_id: str
    client_id: str
    redirect_uri: str
    response_type: str
    scope: str | None
    state: str
    code_challenge: str
    code_challenge_method: str
    nonce: str | None
    resource: str
    sub: str
    csrf_token_hash: str
    expires_at: int


@dataclass(frozen=True)
class AuthCode:
    code_hash: str
    client_id: str
    redirect_uri: str
    scope: str | None
    code_challenge: str
    code_challenge_method: str
    nonce: str | None
    sub: str
    resource: str
    expires_at: int


@dataclass(frozen=True)
class RefreshToken:
    token_hash: str
    client_id: str
    sub: str
    scope: str | None
    resource: str
    issued_at: int
    expires_at: int
    revoked_at: int | None
    replaced_by_hash: str | None


class Storage:
    """Thin async wrapper around aiosqlite. One connection, asyncio loop."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _c(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Storage.init() not called"
        return self._conn

    # --- clients ----------------------------------------------------------

    async def insert_client(self, c: Client) -> None:
        await self._c.execute(
            """
            INSERT INTO clients (
                client_id, client_secret_hash, client_name,
                redirect_uris_json, grant_types_json, response_types_json,
                token_endpoint_auth_method, scope, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.client_id,
                c.client_secret_hash,
                c.client_name,
                json.dumps(list(c.redirect_uris)),
                json.dumps(list(c.grant_types)),
                json.dumps(list(c.response_types)),
                c.token_endpoint_auth_method,
                c.scope,
                c.registered_at,
            ),
        )
        await self._c.commit()

    async def get_client(self, client_id: str) -> Client | None:
        async with self._c.execute(
            "SELECT * FROM clients WHERE client_id = ?", (client_id,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
        return _row_to_client(dict(zip(cols, row, strict=True)))

    # --- subject map ------------------------------------------------------

    async def get_or_create_subject(self, proxy_user: str, *, now: int) -> str:
        async with self._c.execute(
            "SELECT sub FROM subject_map WHERE proxy_user = ?", (proxy_user,)
        ) as cur:
            row = await cur.fetchone()
            if row is not None:
                return row[0]
        # Generate a stable opaque subject. Using urn-style for clarity.
        from .security import random_id  # local import to avoid cycle

        sub = f"sub:{random_id(nbytes=16)}"
        await self._c.execute(
            "INSERT INTO subject_map (proxy_user, sub, created_at) VALUES (?, ?, ?)",
            (proxy_user, sub, now),
        )
        await self._c.commit()
        return sub

    # --- auth requests ----------------------------------------------------

    async def insert_auth_request(self, ar: AuthRequest) -> None:
        await self._c.execute(
            """
            INSERT INTO auth_requests (
                auth_request_id, client_id, redirect_uri, response_type,
                scope, state, code_challenge, code_challenge_method, nonce,
                resource, sub, csrf_token_hash, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ar.auth_request_id, ar.client_id, ar.redirect_uri,
                ar.response_type, ar.scope, ar.state, ar.code_challenge,
                ar.code_challenge_method, ar.nonce, ar.resource, ar.sub,
                ar.csrf_token_hash, ar.expires_at,
            ),
        )
        await self._c.commit()

    async def pop_auth_request(self, auth_request_id: str) -> AuthRequest | None:
        async with self._c.execute(
            "SELECT * FROM auth_requests WHERE auth_request_id = ?",
            (auth_request_id,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
        await self._c.execute(
            "DELETE FROM auth_requests WHERE auth_request_id = ?",
            (auth_request_id,),
        )
        await self._c.commit()
        return _row_to_auth_request(dict(zip(cols, row, strict=True)))

    async def gc_auth_requests(self, *, now: int) -> int:
        cur = await self._c.execute(
            "DELETE FROM auth_requests WHERE expires_at <= ?", (now,)
        )
        await self._c.commit()
        return cur.rowcount or 0

    # --- auth codes -------------------------------------------------------

    async def insert_auth_code(self, c: AuthCode) -> None:
        await self._c.execute(
            """
            INSERT INTO auth_codes (
                code_hash, client_id, redirect_uri, scope, code_challenge,
                code_challenge_method, nonce, sub, resource, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.code_hash, c.client_id, c.redirect_uri, c.scope,
                c.code_challenge, c.code_challenge_method, c.nonce,
                c.sub, c.resource, c.expires_at,
            ),
        )
        await self._c.commit()

    async def pop_auth_code(self, code_hash: str) -> AuthCode | None:
        """Atomically look up + delete (single-use)."""
        async with self._c.execute(
            "SELECT * FROM auth_codes WHERE code_hash = ?", (code_hash,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
        await self._c.execute(
            "DELETE FROM auth_codes WHERE code_hash = ?", (code_hash,)
        )
        await self._c.commit()
        return _row_to_auth_code(dict(zip(cols, row, strict=True)))

    async def gc_auth_codes(self, *, now: int) -> int:
        cur = await self._c.execute(
            "DELETE FROM auth_codes WHERE expires_at <= ?", (now,)
        )
        await self._c.commit()
        return cur.rowcount or 0

    # --- refresh tokens ---------------------------------------------------

    async def insert_refresh_token(self, rt: RefreshToken) -> None:
        await self._c.execute(
            """
            INSERT INTO refresh_tokens (
                token_hash, client_id, sub, scope, resource, issued_at,
                expires_at, revoked_at, replaced_by_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rt.token_hash, rt.client_id, rt.sub, rt.scope, rt.resource,
                rt.issued_at, rt.expires_at, rt.revoked_at, rt.replaced_by_hash,
            ),
        )
        await self._c.commit()

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        async with self._c.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
        return _row_to_refresh_token(dict(zip(cols, row, strict=True)))

    async def revoke_refresh_token(
        self, token_hash: str, *, now: int, replaced_by_hash: str | None = None
    ) -> None:
        await self._c.execute(
            """
            UPDATE refresh_tokens
            SET revoked_at = ?, replaced_by_hash = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (now, replaced_by_hash, token_hash),
        )
        await self._c.commit()

    async def revoke_refresh_token_family(
        self, client_id: str, sub: str, *, now: int
    ) -> int:
        """Revoke ALL refresh tokens for (client_id, sub). Used on replay
        detection — RFC 9700 calls for revoking the entire family."""
        cur = await self._c.execute(
            """
            UPDATE refresh_tokens
            SET revoked_at = ?
            WHERE client_id = ? AND sub = ? AND revoked_at IS NULL
            """,
            (now, client_id, sub),
        )
        await self._c.commit()
        return cur.rowcount or 0

    async def gc_refresh_tokens(self, *, now: int) -> int:
        cur = await self._c.execute(
            "DELETE FROM refresh_tokens WHERE expires_at <= ?", (now,)
        )
        await self._c.commit()
        return cur.rowcount or 0


# --- row → dataclass converters -------------------------------------------


def _row_to_client(d: dict[str, Any]) -> Client:
    return Client(
        client_id=d["client_id"],
        client_secret_hash=d["client_secret_hash"],
        client_name=d["client_name"],
        redirect_uris=tuple(json.loads(d["redirect_uris_json"])),
        grant_types=tuple(json.loads(d["grant_types_json"])),
        response_types=tuple(json.loads(d["response_types_json"])),
        token_endpoint_auth_method=d["token_endpoint_auth_method"],
        scope=d["scope"],
        registered_at=d["registered_at"],
    )


def _row_to_auth_request(d: dict[str, Any]) -> AuthRequest:
    return AuthRequest(
        auth_request_id=d["auth_request_id"],
        client_id=d["client_id"],
        redirect_uri=d["redirect_uri"],
        response_type=d["response_type"],
        scope=d["scope"],
        state=d["state"],
        code_challenge=d["code_challenge"],
        code_challenge_method=d["code_challenge_method"],
        nonce=d["nonce"],
        resource=d["resource"],
        sub=d["sub"],
        csrf_token_hash=d["csrf_token_hash"],
        expires_at=d["expires_at"],
    )


def _row_to_auth_code(d: dict[str, Any]) -> AuthCode:
    return AuthCode(
        code_hash=d["code_hash"],
        client_id=d["client_id"],
        redirect_uri=d["redirect_uri"],
        scope=d["scope"],
        code_challenge=d["code_challenge"],
        code_challenge_method=d["code_challenge_method"],
        nonce=d["nonce"],
        sub=d["sub"],
        resource=d["resource"],
        expires_at=d["expires_at"],
    )


def _row_to_refresh_token(d: dict[str, Any]) -> RefreshToken:
    return RefreshToken(
        token_hash=d["token_hash"],
        client_id=d["client_id"],
        sub=d["sub"],
        scope=d["scope"],
        resource=d["resource"],
        issued_at=d["issued_at"],
        expires_at=d["expires_at"],
        revoked_at=d["revoked_at"],
        replaced_by_hash=d["replaced_by_hash"],
    )


# Time helper used across the package (and easy to monkey-patch in tests).
def now() -> int:
    return int(time.time())


__all__ = [
    "AuthCode",
    "AuthRequest",
    "Client",
    "RefreshToken",
    "Storage",
    "now",
]
