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
