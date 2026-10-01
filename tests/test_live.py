"""End to end, with a real server on a real port: someone writes on the (fake) Discord, and the link lights up in the page.

A fake Discord and a fake exporter stand in for Discord; everything else is the real thing: the watcher, the exporter
process, the ingestion, PostgreSQL's NOTIFY, and the Server-Sent Events that the page listens to.
"""
import dataclasses
import http.client
import json
import queue
import shlex
import socket
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import uvicorn

from dindon.api.main import create_app
from dindon.ingest.loader import ingest_file
from fake_discord import FakeDiscord
from make_demo_server import World, write_exports
from synthetic import settings_for

TOOLS = Path(__file__).resolve().parents[1] / "tools"
TOKEN = "fake-account-token-1234"
PASSWORD = "correct horse"
POLL_SECONDS = 1.0


class Page:
    """What the page does: logs in, then listens to /events."""

    def __init__(self, port: int):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/login", data=json.dumps({"password": PASSWORD}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.cookie = response.headers["Set-Cookie"].split(";")[0]
        self.events: "queue.Queue[tuple[float, dict]]" = queue.Queue()
        self._connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        self._connection.request("GET", "/events", headers={"Cookie": self.cookie})
        self._response = self._connection.getresponse()
        assert self._response.status == 200 and self._response.getheader("Content-Type").startswith("text/event-stream")
        threading.Thread(target=self._read, daemon=True).start()
        assert self.wait(lambda e: e["type"] == "hello", 5)

    def _read(self):
        try:
            for line in self._response:
                if line.startswith(b"data:"):
                    self.events.put((time.monotonic(), json.loads(line[5:])))
        except Exception:
            pass

    def wait(self, wanted, timeout: float) -> tuple[float, dict] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                arrived, event = self.events.get(timeout=0.1)
            except queue.Empty:
                continue
            if wanted(event):
                return arrived, event
        return None

    def close(self):
        try:
            self._connection.sock.shutdown(socket.SHUT_RDWR)  # as a closing tab does: the server sees it at once
        except OSError:
            pass
        self._connection.close()


@pytest.fixture
def system(ingest_db, ingest_url, tmp_path, monkeypatch):
    """The whole thing, running: a fake Discord, and Dindon (watcher, inbox, API) in front of a database that holds the first import."""
    world = World(seed=31, people=25)
    world.generate(1200, days=20, end=datetime.now(timezone.utc) - timedelta(minutes=30))
    for path in write_exports(world, tmp_path / "first-import"):
        ingest_file(ingest_db, path)
    fake = FakeDiscord(world, token=TOKEN).start()
    monkeypatch.setenv("FAKE_DISCORD_URL", fake.base_url)
    settings = dataclasses.replace(
        settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=fake.api_url, discord_token=TOKEN, guild_ids=(world.guild_id,),
        exporter_path=f"{shlex.quote(sys.executable)} {shlex.quote(str(TOOLS / 'fake_exporter.py'))}", poll_seconds=POLL_SECONDS)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, background=True), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    page = Page(port)
    try:
        yield world, fake, page, port, tmp_path
    finally:
        page.close()
        server.should_exit = True
        thread.join(timeout=10)
        fake.stop()


def test_a_new_exchange_lights_up_the_link_within_seconds(system, capsys):
    world, fake, page, port, _ = system
    channel = max(world.channels, key=lambda c: len(c.messages))
    alice, bob = world.people[0], world.people[1]
    started = time.monotonic()
    first = fake.post(channel, alice, "Vous avez vu la nouvelle ?")
    fake.post(channel, bob, "oui, ça change tout", reply_to_id=first["id"])
    found = page.wait(lambda e: e["type"] == "edge" and (e["from"], e["to"], e["kind"]) == (str(bob.id), str(alice.id), "reply"), 15)
    assert found, "the link never lit up"
    latency = found[0] - started
    print(f"\nexchange on the fake Discord -> 'edge' event received by the page: {latency:.2f}s (the watcher polls every {POLL_SECONDS:.0f}s)")
    assert latency < POLL_SECONDS + 3
    event = found[1]
    assert event["weight"] > 0.9 and event["guild"] == str(world.guild_id)
    assert page.wait(lambda e: e["type"] == "messages" and e["channel"] == str(channel.id), 2)  # and the new messages are announced
    # the map, asked right after, already shows the link
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/graph", headers={"Cookie": page.cookie})
    with urllib.request.urlopen(request) as response:
        graph = json.load(response)
    assert any({e["source"], e["target"]} == {str(alice.id), str(bob.id)} for e in graph["edges"])


def test_a_file_dropped_in_the_inbox_is_imported_archived_and_announced(system):
    world, fake, page, port, tmp_path = system
    other = World(seed=99, people=10)
    other.generate(80, days=5, end=datetime.now(timezone.utc) - timedelta(hours=2))
    channel = max(other.channels, key=lambda c: len(c.messages))
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    name = "manual export.json"
    (inbox / name).write_text(other.export_document(channel), encoding="utf-8")
    found = page.wait(lambda e: e["type"] == "messages" and e["channel"] == str(channel.id), 15)
    assert found and found[1]["count"] == len(channel.messages)
    assert not (inbox / name).exists() and list((tmp_path / "archive").glob(f"*/*-{name}"))


def test_the_status_shows_the_watcher_and_the_warning_for_an_account(system):
    world, fake, page, port, _ = system
    time.sleep(POLL_SECONDS * 2)
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers={"Cookie": page.cookie})
    with urllib.request.urlopen(request) as response:
        status = json.load(response)
    assert status["collector"]["enabled"] and status["collector"]["last_poll_at"] and status["collector"]["token_kind"] == "account"
    assert status["warnings"] == ["account_token"] and status["live"] is True
