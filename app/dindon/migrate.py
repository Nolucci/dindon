"""Applies the SQL files to the database. Small on purpose: no framework.

Two kinds of files, both recorded in `schema_migrations` with their SHA-256:

* the baseline: the four files of db/ (schema, analysis, seed data, vectors). They can be run again
  without effect, so a baseline file is applied again whenever its content has changed;
* numbered migrations: db/migrations/0001_name.sql, 0002_... Each one is applied once, in order.
  Changing a migration that has already been applied is an error: write a new one instead.
"""
import hashlib
from pathlib import Path

import psycopg

BASELINE = ("schema.sql", "schema-analysis.sql", "seed-axes.sql", "schema-vector.sql")
LOCK_KEY = 7_262_024  # advisory lock, so that two processes never migrate at the same time

BOOKKEEPING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name       text PRIMARY KEY,
    kind       text NOT NULL CHECK (kind IN ('baseline', 'migration')),
    sha256     text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    pass


def _files(db_dir: Path) -> list[tuple[str, str, Path]]:
    files = []
    for name in BASELINE:
        path = db_dir / name
        if not path.is_file():
            raise MigrationError(f"missing baseline file: {path}")
        files.append((name, "baseline", path))
    migrations = sorted((db_dir / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    files.extend((p.name, "migration", p) for p in migrations)
    return files


def migrate(conn: psycopg.Connection, db_dir: Path) -> list[str]:
    """Brings the database up to date. Returns the names of the files that were applied."""
    applied = []
    # Autocommit, so that each file below gets its own real transaction
    conn.commit()
    previous_autocommit = conn.autocommit
    conn.autocommit = True
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    try:
        conn.execute(BOOKKEEPING)
        known = dict(conn.execute("SELECT name, sha256 FROM schema_migrations").fetchall())
        for name, kind, path in _files(db_dir):
            sql = path.read_bytes()
            sha = hashlib.sha256(sql).hexdigest()
            if known.get(name) == sha:
                continue
            if name in known and kind == "migration":
                raise MigrationError(
                    f"{name} was changed after it was applied: write a new migration instead"
                )
            with conn.transaction():
                conn.execute(sql.decode("utf-8"))
                conn.execute(
                    """INSERT INTO schema_migrations (name, kind, sha256) VALUES (%s, %s, %s)
                       ON CONFLICT (name) DO UPDATE SET sha256 = excluded.sha256, applied_at = now()""",
                    (name, kind, sha),
                )
            applied.append(name)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        conn.autocommit = previous_autocommit
    return applied
