#!/usr/bin/env python3
"""apply-migrations.py — run pending SQL migrations against the OpenClaw
state database.

Usage:
    apply-migrations.py /var/lib/openclaw/state.db pi/sqlite-migrations/

Refuses to apply migrations out of order. Connection is opened in
autocommit mode (isolation_level=None) so sqlite3.executescript() can run
the migration file as-is — executescript issues its own COMMIT and is
incompatible with explicit BEGIN/COMMIT. The applied filename is
recorded in _migrations only after executescript returns successfully.

Caveat: if executescript fails midway, SQLite has already partially
applied any DDL that ran before the failing statement (DDL is not
rolled back), and the migration is *not* recorded in _migrations. That
file will be retried on the next run, which usually fails on the
already-applied prefix. Manual reconciliation is required in that rare
case — keep migrations short and idempotent where possible.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path


MIGRATION_RE = re.compile(r"^(\d{4})_[a-zA-Z0-9_-]+\.sql$")


def discover(directory: Path) -> list[tuple[int, Path]]:
    out = []
    for p in sorted(directory.iterdir()):
        m = MIGRATION_RE.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return out


def applied(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_migrations'"
    )
    if not cur.fetchone():
        return set()
    return {r[0] for r in conn.execute("SELECT filename FROM _migrations")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("db", type=Path, help="path to state.db (created if missing)")
    ap.add_argument("migrations_dir", type=Path, help="directory of NNNN_*.sql files")
    args = ap.parse_args()

    if not args.migrations_dir.is_dir():
        print(f"not a directory: {args.migrations_dir}", file=sys.stderr)
        return 2

    migrations = discover(args.migrations_dir)
    if not migrations:
        print("no migration files found", file=sys.stderr)
        return 0

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")

    done = applied(conn)
    last_applied = max(
        (int(MIGRATION_RE.match(name).group(1)) for name in done),
        default=0,
    )

    pending = [(n, p) for n, p in migrations if p.name not in done]
    if not pending:
        print(f"up to date ({len(done)} applied)")
        return 0

    for n, path in pending:
        if n <= last_applied:
            print(
                f"refusing to apply {path.name}: number {n} is "
                f"<= last applied ({last_applied})",
                file=sys.stderr,
            )
            return 3
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO _migrations (filename) VALUES (?)", (path.name,)
            )
        except Exception as e:
            print(f"failed: {path.name}: {e}", file=sys.stderr)
            return 4
        print(f"applied: {path.name}")
        last_applied = n

    print(f"{len(pending)} migrations applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
