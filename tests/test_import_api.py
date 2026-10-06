"""Importing a part of a server from the interface: the routes, the progress, stopping, one at a time.

Level of proof: SIMULATED (fake Discord, fake exporter, real database, real application).
"""
import dataclasses
import shlex
import sys
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dindon.api.main import create_app
from dindon.collector.watch import Collector
from synthetic import settings_for
from test_collector import TOKEN, fake, message_count, world  # noqa: F401 (fixtures)
from test_import_selection import connection, ids_in, largest

PASSWORD = "correct horse"


@pytest.fixture
def settings(fake, world, ingest_url, tmp_path):
    return dataclasses.replace(
        settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=fake.api_url, discord_token=TOKEN, guild_ids=(world.guild_id,),
        poll_seconds=0.2)


@pytest.fixture
def app(settings):
    with TestClient(create_app(settings, background=False)) as client:
        yield client


@pytest.fixture
def me(app):
    assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return app


def wait_until_finished(client, timeout=30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/import").json()
        if status["state"] not in ("running", "cancelling"):
            return status
        time.sleep(0.1)
    raise AssertionError(f"the import did not finish: {status}")


def body(world, **kwargs) -> dict:
    return {"guild": str(world.guild_id), **kwargs}


# ---------------------------------------------------------------------------------------------
# Who may, and what is said
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method, path", [("get", "/api/import/options"), ("get", "/api/import"), ("post", "/api/import"), ("post", "/api/import/cancel")])
def test_nothing_of_the_import_is_available_without_the_session(app, world, method, path):
    response = getattr(app, method)(path, **({"json": body(world)} if method == "post" and path == "/api/import" else {}))
    assert response.status_code == 401


def test_the_options_list_the_channels_that_discord_shows_now(me, world):
    options = me.get("/api/import/options").json()
    assert options["configured"] is True and len(options["guilds"]) == 1
    guild = options["guilds"][0]
    assert guild["id"] == str(world.guild_id) and guild["name"] == str(world.guild_id)        # not known to the database yet: its id
    assert {c["id"] for c in guild["channels"]} == {str(c.id) for c in world.channels if not c.parent_id}
    assert [c["name"].casefold() for c in guild["channels"]] == sorted(c["name"].casefold() for c in guild["channels"])
    assert all(set(c) == {"id", "name", "kind", "empty"} for c in guild["channels"])


def test_without_a_token_nothing_can_be_started(settings, world, ingest_url):
    bare = dataclasses.replace(settings, discord_token="", guild_ids=())
    with TestClient(create_app(bare, background=False)) as client:
        client.post("/api/login", json={"password": PASSWORD})
        assert client.get("/api/import/options").json() == {"configured": False, "guilds": []}
        assert client.post("/api/import", json=body(world)).status_code == 403          # no server is followed, so none can be imported


def test_a_server_that_is_not_followed_cannot_be_imported(me, world):
    refused = me.post("/api/import", json={"guild": "12345"})
    assert refused.status_code == 403 and "DINDON_GUILD_IDS" in refused.json()["detail"]
    assert me.post("/api/import", json={"guild": "abc"}).status_code == 422


@pytest.mark.parametrize("wrong, words", [
    ({"authors": ["pseudo"]}, "identifiant Discord"),
    ({"mentions": ["12ab"]}, "identifiant Discord"),
    ({"after": "hier"}, "n'est pas une date"),
    ({"after": "2025-05-01", "before": "2025-04-01"}, "à l'envers"),
    ({"channels": ["nulle-part"]}, "Salons visibles"),
])
def test_a_selection_that_cannot_be_understood_is_refused_with_words_and_nothing_starts(me, fake, world, wrong, words):
    response = me.post("/api/import", json=body(world, **wrong))
    assert response.status_code == 422 and words in response.json()["detail"]
    assert me.get("/api/import").json()["state"] == "idle"


# ---------------------------------------------------------------------------------------------
# An import, from start to end
# ---------------------------------------------------------------------------------------------


def test_an_import_runs_in_the_background_and_says_what_it_did(me, fake, world, ingest_url):
    assert me.get("/api/import").json()["state"] == "idle"
    channel = largest(world)
    author = Counter(m["authorId"] for m in channel.messages).most_common(1)[0][0]
    expected = {int(m["id"]) for m in channel.messages if m["authorId"] == author}
    started = me.post("/api/import", json=body(world, channels=[channel.name], authors=[author]))
    assert started.status_code == 200 and started.json()["state"] in ("running", "done")
    status = wait_until_finished(me)
    assert status["state"] == "done" and status["error"] is None and status["finished_at"]
    assert (status["planned"], status["done"], status["failed"], status["cancelled"]) == (1, 1, 0, 0)
    assert status["messages"] == len(expected) and status["selection"]["partial"] is True and status["selection"]["authors"] == [author]
    assert status["guild"] == str(world.guild_id) and any(channel.name in line and str(len(expected)) in line for line in status["lines"])
    with connection(ingest_url) as conn:
        assert ids_in(conn) == expected


def test_the_channels_only_are_imported_completely_and_the_next_import_can_start(me, fake, world, ingest_url):
    first = world.channels[0]
    assert me.post("/api/import", json=body(world, channels=[first.name])).status_code == 200
    status = wait_until_finished(me)
    assert status["selection"]["partial"] is False and status["messages"] == len(first.messages)
    again = me.post("/api/import", json=body(world, channels=[first.name]))
    assert again.status_code == 200 and wait_until_finished(me)["done"] == 0         # up to date: nothing to do, and it did not refuse to start


def test_only_one_import_at_a_time_and_a_running_one_can_be_stopped(me, fake, world, ingest_url, monkeypatch):
    fake.latency = 0.6                                                                # each channel takes a while
    names = [c.name for c in world.channels[:3]]
    assert me.post("/api/import", json=body(world, channels=names)).status_code == 200
    time.sleep(0.8)
    running = me.get("/api/import").json()
    assert running["state"] == "running" and running["planned"] == 3
    busy = me.post("/api/import", json=body(world, channels=names[:1]))
    assert busy.status_code == 409 and "déjà en cours" in busy.json()["detail"]
    started = time.monotonic()
    assert me.post("/api/import/cancel").json()["state"] == "cancelling"
    status = wait_until_finished(me)
    assert time.monotonic() - started < 12                                            # the requests were ended, not waited for
    assert status["state"] == "cancelled" and status["cancelled"] == 3 and status["done"] == 0 and status["error"] is None
    with connection(ingest_url) as conn:
        assert message_count(conn) == 0                                               # what was not finished was not imported
    fake.latency = 0
    assert me.post("/api/import", json=body(world, channels=names[:1])).status_code == 200   # and a new one can start
    assert wait_until_finished(me)["state"] == "done"


def test_stopping_when_nothing_runs_changes_nothing(me):
    assert me.post("/api/import/cancel").json()["state"] == "idle"


def test_a_failure_inside_the_import_is_shown_by_its_kind_never_by_its_text(me, fake, world, monkeypatch):
    def broken(self, *args, **kwargs):
        raise RuntimeError(f"boom, and here is the token: {TOKEN}")

    monkeypatch.setattr(Collector, "backfill", broken)
    assert me.post("/api/import", json=body(world, channels=[world.channels[0].name])).status_code == 200
    status = wait_until_finished(me)
    assert status["state"] == "failed" and status["error"] == "erreur inattendue (RuntimeError)"
    assert TOKEN not in str(status)


def test_the_token_is_in_no_answer(me, fake, world):
    answers = [me.get("/api/import/options").text, me.get("/api/import").text,
               me.post("/api/import", json=body(world, channels=[world.channels[0].name])).text]
    answers += [str(wait_until_finished(me)), me.post("/api/import", json=body(world, authors=["x"])).text]
    assert not any(TOKEN in a for a in answers)
