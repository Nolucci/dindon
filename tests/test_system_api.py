"""The page Système: what the API says of each piece, and the list of what deserves a look.

Level of proof: SIMULATED (a real database, a fake Ollama, rows written by hand where the bot would write them).
"""
import dataclasses
import json
from datetime import datetime, timedelta, timezone, UTC

import pytest
from fastapi.testclient import TestClient

from dindon.api.main import create_app
from dindon.api.system import BOT_SILENT_AFTER, bot_state, checks_for
from fake_ollama import FakeOllama
from synthetic import settings_for

PASSWORD = "correct horse"
TOKEN = "super-secret-token"
FOLLOWED, OTHER = 111222333444555, 999888777666555


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def make_app(ingest_url, ingest_db, tmp_path, ollama):
    def make(**changes):
        wanted = {"ollama_url": ollama.url, "discord_token": TOKEN, "guild_ids": (FOLLOWED,), **changes}
        settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), **wanted)
        client = TestClient(create_app(settings, background=False))
        client.__enter__()
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        return client
    return make


def beat(db, *, age=5, **data):
    payload = {"connected": True, "sessions": 1, "gaps": 0, "received": 4, "new": 3, "ready": [str(FOLLOWED)], "followed": [str(FOLLOWED)],
               "started_at": datetime.now(UTC).isoformat(), **data}
    db.execute("INSERT INTO service_status (name, updated_at, data) VALUES ('bot', %s, %s::jsonb) ON CONFLICT (name) DO UPDATE "
               "SET updated_at = excluded.updated_at, data = excluded.data", (datetime.now(UTC) - timedelta(seconds=age), json.dumps(payload)))


def texts(answer) -> str:
    return " | ".join(c["text"] for c in answer["checks"])


def test_nothing_is_served_without_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path), background=False)) as client:
        assert client.get("/api/system").status_code == 401


def test_a_bot_that_is_alive_and_a_server_that_it_sees_leave_nothing_to_look_at(make_app, ingest_db):
    beat(ingest_db)
    answer = make_app().get("/api/system").json()
    assert answer["bot"]["state"] == "connected" and answer["bot"]["age_seconds"] < 60 and answer["bot"]["data"]["new"] == 3
    assert answer["followed"] == [{"id": str(FOLLOWED), "name": None, "in_database": False, "messages": 0, "seen_by_bot": True}]
    assert answer["ollama"] == {"reachable": True, "models": ["bge-m3:latest", "qwen3:14b"], "models_ready": {"bge-m3": True, "qwen3:14b": True}}
    assert [c["level"] for c in answer["checks"]] == ["info"]                    # only: the followed server has no message yet
    assert "premier message" in texts(answer)


def test_a_bot_that_was_never_seen_that_is_silent_or_that_lost_discord_is_told(make_app, ingest_db):
    client = make_app()
    first = client.get("/api/system").json()
    assert first["bot"]["state"] == "unknown" and "jamais donné signe de vie" in texts(first)
    beat(ingest_db, age=300)
    silent = client.get("/api/system").json()
    assert silent["bot"]["state"] == "silent" and any(c["level"] == "error" for c in silent["checks"]) and "5 min" in texts(silent)
    beat(ingest_db, connected=False)
    lost = client.get("/api/system").json()
    assert lost["bot"]["state"] == "disconnected" and "déconnecté" in texts(lost)


def test_reconnections_with_no_catch_up_are_a_risk_that_is_said_with_the_remedy(make_app, ingest_db):
    beat(ingest_db, gaps=13)
    said = texts(make_app().get("/api/system").json())
    assert "13 fois" in said and "DINDON_COLLECTOR=catchup" in said


def test_a_followed_server_that_the_bot_does_not_see_is_told(make_app, ingest_db):
    beat(ingest_db, ready=[str(OTHER)])
    assert f"ne voit pas le serveur {FOLLOWED}" in texts(make_app().get("/api/system").json())


def test_an_ollama_that_is_away_or_missing_a_model_is_told(make_app, ingest_db, ollama):
    beat(ingest_db)
    client = make_app()
    ollama.models = ["bge-m3:latest"]
    assert "ollama pull qwen3:14b" in texts(client.get("/api/system").json())
    client.app.state.analysis.client.base_url = "http://127.0.0.1:9"
    answer = client.get("/api/system").json()
    assert answer["ollama"]["reachable"] is False and "Ollama" in texts(answer) and "ne répond pas" in texts(answer)


def test_the_counts_of_the_database_and_the_inbox_are_there_and_no_secret_is(make_app, ingest_db, tmp_path):
    beat(ingest_db)
    failed = tmp_path / "inbox" / "failed"
    failed.mkdir(parents=True)
    (failed / "broken.json").write_text("{")
    answer = make_app().get("/api/system")
    body = answer.json()
    assert set(body["database"]) == {"messages", "messages_approximate", "people", "channels", "servers", "migrations", "bytes", "last_import_at"}
    assert body["database"]["migrations"] >= 8 and body["inbox"] == {"pending": 0, "failed": 1} and "illisible" in texts(body)
    assert TOKEN not in answer.text and PASSWORD not in answer.text                # never a secret


def test_without_a_token_the_bot_is_not_expected(make_app, ingest_db):
    answer = make_app(discord_token="", guild_ids=()).get("/api/system").json()
    assert answer["wants_bot"] is False and answer["bot"]["state"] == "unknown" and answer["followed"] == []
    assert "signe de vie" not in texts(answer)


def test_the_states_of_the_bot_follow_its_last_sign_of_life():
    now = datetime.now(UTC)
    row = lambda age, **data: {"updated_at": now - timedelta(seconds=age), "data": data}  # noqa: E731
    assert bot_state(None, now)["state"] == "unknown"
    assert bot_state(row(10, connected=True), now)["state"] == "connected"
    assert bot_state(row(10, connected=False), now)["state"] == "disconnected"
    assert bot_state(row(BOT_SILENT_AFTER + 1, connected=True), now)["state"] == "silent"


def test_a_collector_that_catches_up_makes_the_reconnections_a_lesser_matter():
    followed = [{"id": "1", "in_database": True}]
    bot = {"state": "connected", "age_seconds": 3, "data": {"gaps": 4, "ready": ["1"]}}
    ollama = {"reachable": True, "models_ready": {"a": True}}
    inbox = {"failed": 0}
    off = checks_for(followed=followed, bot=bot, collector={"enabled": False}, ollama=ollama, inbox=inbox, wants_bot=True)
    nightly = checks_for(followed=followed, bot=bot, collector={"enabled": True, "mode": "catchup"}, ollama=ollama, inbox=inbox, wants_bot=True)
    assert [c["level"] for c in off] == ["warning"] and [c["level"] for c in nightly] == ["info"]


def test_the_check_of_the_bot_container_follows_its_sign_of_life(ingest_db):
    from dindon.health import bot_is_alive
    assert not bot_is_alive(ingest_db)                                                  # never seen
    ingest_db.execute("INSERT INTO service_status (name, updated_at, data) VALUES ('bot', now(), '{\"connected\": true}'::jsonb)")
    assert bot_is_alive(ingest_db)
    ingest_db.execute("UPDATE service_status SET data = '{\"connected\": false}'::jsonb")
    assert not bot_is_alive(ingest_db)                                                  # alive but not connected to Discord
    ingest_db.execute("UPDATE service_status SET data = '{\"connected\": true}'::jsonb, updated_at = now() - interval '5 minutes'")
    assert not bot_is_alive(ingest_db)                                                  # silent
