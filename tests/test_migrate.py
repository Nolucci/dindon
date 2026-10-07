"""The database: what the baseline creates, and the small migration tool."""
import shutil
import uuid
from pathlib import Path

import psycopg
import pytest

from dindon.migrate import BASELINE, MigrationError, migrate

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"


def _row_counts(conn) -> dict[str, int]:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
    ]
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)}


def test_a_new_database_is_healthy(conn):
    def count(sql):
        return conn.execute(sql).fetchone()[0]
    assert count(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' "
        "AND table_type = 'BASE TABLE' AND table_name <> 'schema_migrations'"
    ) == 57
    assert count(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'VIEW'"
    ) == 9
    assert count("SELECT count(*) FROM axes") == 21
    assert count("SELECT count(*) FROM axes WHERE is_active") == 21
    assert count("SELECT count(*) FROM axes WHERE origin = '12axes'") == 12
    assert count("SELECT count(*) FROM ideologies") == 28
    assert count("SELECT count(*) FROM ideology_axis_ranges") == 72
    assert count("SELECT count(*) FROM role_rules") == 37
    assert count("SELECT count(*) FROM ideologies WHERE is_validated") == 0  # waiting for the user's review


def test_all_the_axes_are_active_from_the_start(conn):
    # The 12 axes of the model and the 9 extensions: all of them are scored (decision of 2026-10-04)
    assert {r[0] for r in conn.execute("SELECT code FROM axes WHERE NOT is_active")} == set()


def test_running_everything_again_changes_nothing(conn):
    before = _row_counts(conn)
    assert migrate(conn, DB_DIR) == []
    for name in BASELINE:  # the SQL files themselves can be played again, too
        conn.execute((DB_DIR / name).read_text(encoding="utf-8"))
    assert _row_counts(conn) == before


@pytest.fixture
def scratch_db(migrated_url):
    """An empty database of its own, for the tests that apply migrations from nothing."""
    name = "dindon_scratch_" + uuid.uuid4().hex[:8]
    with psycopg.connect(migrated_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            base, _, _ = migrated_url.rpartition("/")
            yield f"{base}/{name}"
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def sql_dir(tmp_path):
    for name in BASELINE:
        shutil.copy(DB_DIR / name, tmp_path / name)
    (tmp_path / "migrations").mkdir()
    return tmp_path


def test_a_migration_is_applied_once_and_in_order(scratch_db, sql_dir):
    (sql_dir / "migrations" / "0002_second.sql").write_text("INSERT INTO t VALUES (2);")
    (sql_dir / "migrations" / "0001_first.sql").write_text("CREATE TABLE t (x int);")
    with psycopg.connect(scratch_db) as conn:
        assert migrate(conn, sql_dir) == [*BASELINE, "0001_first.sql", "0002_second.sql"]
        assert migrate(conn, sql_dir) == []
        assert conn.execute("SELECT x FROM t").fetchall() == [(2,)]


def test_a_migration_that_was_changed_after_it_ran_is_refused(scratch_db, sql_dir):
    path = sql_dir / "migrations" / "0001_first.sql"
    path.write_text("CREATE TABLE t (x int);")
    with psycopg.connect(scratch_db) as conn:
        migrate(conn, sql_dir)
        path.write_text("CREATE TABLE t (x int, y int);")
        with pytest.raises(MigrationError, match="0001_first.sql"):
            migrate(conn, sql_dir)


def test_a_failing_migration_leaves_nothing_behind(scratch_db, sql_dir):
    (sql_dir / "migrations" / "0001_broken.sql").write_text("CREATE TABLE t (x int); SELECT 1/0;")
    with psycopg.connect(scratch_db) as conn:
        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate(conn, sql_dir)
        assert conn.execute("SELECT to_regclass('t')").fetchone() == (None,)
        assert conn.execute("SELECT count(*) FROM schema_migrations WHERE kind = 'migration'").fetchone() == (0,)


def test_a_baseline_file_that_changed_is_played_again(scratch_db, sql_dir):
    with psycopg.connect(scratch_db) as conn:
        migrate(conn, sql_dir)
        with (sql_dir / "seed-axes.sql").open("a") as f:
            f.write("\n-- a comment\n")
        assert migrate(conn, sql_dir) == ["seed-axes.sql"]
