"""Test setup: a throwaway PostgreSQL (compose project "dindontest", port 55432) that is removed at the end.

Set DINDON_TEST_DATABASE_URL to use an existing database instead (it must be disposable).
Tests only ever use synthetic data.
"""
import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from dindon.migrate import migrate

ROOT = Path(__file__).resolve().parents[1]
TEST_URL = "postgresql://dindon:test@127.0.0.1:55432/dindon"


def _compose(*args: str) -> None:
    env = {**os.environ, "POSTGRES_PASSWORD": "test", "POSTGRES_PORT": "55432", "DINDON_PASSWORD": "test"}
    subprocess.run(["docker", "compose", "-p", "dindontest", *args], cwd=ROOT, env=env, check=True)


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("DINDON_TEST_DATABASE_URL")
    if url:
        yield url
        return
    _compose("up", "-d", "--wait", "db")
    try:
        yield TEST_URL
    finally:
        _compose("down", "-v")


@pytest.fixture(scope="session")
def migrated_url(database_url):
    with psycopg.connect(database_url) as conn:
        migrate(conn, ROOT / "db")
    return database_url


@pytest.fixture
def conn(migrated_url):
    """A connection whose work is rolled back at the end of the test."""
    with psycopg.connect(migrated_url) as connection:
        yield connection
        connection.rollback()


# The generators of invented servers live in tools/, next to the scripts that use them
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture
def ingest_url(migrated_url):
    """The URL of a database of its own (copy of the migrated one), for the tests that really commit, as an import does."""
    import uuid

    name = "dindon_t_" + uuid.uuid4().hex[:8]
    base, _, _ = migrated_url.rpartition("/")
    with psycopg.connect(migrated_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE dindon')
    try:
        yield f"{base}/{name}"
    finally:
        with psycopg.connect(migrated_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def ingest_db(ingest_url):
    with psycopg.connect(ingest_url, autocommit=True) as connection:
        yield connection
