"""Test setup: a throwaway PostgreSQL (compose project "dindontest", port 55432) that is removed at the end.

Set DINDON_TEST_DATABASE_URL to use an existing database instead (it must be disposable).
Tests only ever use synthetic data.
"""
import ipaddress
import os
import socket
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
    for attempt in range(40):                      # a copy needs that nobody else is connected to the original: a connection of the test before may still be closing
        try:
            with psycopg.connect(migrated_url, autocommit=True) as admin:
                admin.execute(f'CREATE DATABASE "{name}" TEMPLATE dindon')
            break
        except psycopg.errors.ObjectInUse:
            if attempt == 39:
                raise
            import time

            time.sleep(0.25)
    try:
        yield f"{base}/{name}"
    finally:
        with psycopg.connect(migrated_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def ingest_db(ingest_url):
    with psycopg.connect(ingest_url, autocommit=True) as connection:
        yield connection


@pytest.fixture(autouse=True)
def discord_is_never_reached(monkeypatch):
    """discord.py starts from its built-in Discord addresses. Whatever a test does, they point to a closed local port, so that
    no test can ever reach the real Discord (a test that talks to the fake one sets its own addresses)."""
    import discord
    import yarl

    monkeypatch.setattr(discord.http.Route, "BASE", "http://127.0.0.1:9/api/v10")
    monkeypatch.setattr(discord.gateway.DiscordWebSocket, "DEFAULT_GATEWAY", yarl.URL("ws://127.0.0.1:9/"))


# --- the tests never leave this machine ---------------------------------------------------------------------------------
# Not even to say hello to Discord: any connection to, or name resolution of, anything but this machine is refused and recorded, and
# a test during which something was refused fails (even if the code under test swallowed the error, as a retry loop would).
BLOCKED: list[str] = []


def _is_this_machine(host) -> bool:
    if host in (None, "", "localhost", "0.0.0.0", "::"):
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return str(host).endswith(".localhost")


@pytest.fixture(scope="session", autouse=True)
def tests_never_leave_this_machine():
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def refuse(host) -> None:
        BLOCKED.append(str(host))
        raise OSError(f"blocked: the tests may only talk to this machine, not to {host}")

    def connect(self, address):
        if isinstance(address, tuple) and not _is_this_machine(address[0]):
            refuse(address[0])
        return real_connect(self, address)

    def connect_ex(self, address):
        if isinstance(address, tuple) and not _is_this_machine(address[0]):
            refuse(address[0])
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_this_machine(host):
            refuse(host)
        return real_getaddrinfo(host, *args, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", connect)
    patch.setattr(socket.socket, "connect_ex", connect_ex)
    patch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    patch.undo()


@pytest.fixture
def blocked_attempts() -> list[str]:
    return BLOCKED


@pytest.fixture(autouse=True)
def no_test_tried_to_leave_this_machine():
    BLOCKED.clear()
    yield
    assert not BLOCKED, f"this test tried to reach: {sorted(set(BLOCKED))}"


@pytest.fixture(autouse=True)
def fake_cdn(monkeypatch):
    """Discord's CDN is a fake that answers a real (tiny) picture: the server fetches the photos of the people on the map (the Activity, the picture of `/dindon map`, the interface).
    No test reaches the real one. The list is what was asked."""
    import io

    from PIL import Image

    from dindon.api import activity

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 90)).save(buffer, "PNG")
    fetched = []
    monkeypatch.setattr(activity, "_fetch_image", lambda url: (fetched.append(url), (buffer.getvalue(), "image/png"))[1])
    activity._avatars.clear()
    return fetched
