"""The limits of the machine: how much the AI and the bot may use, at the cost of their speed. Level of proof: SIMULATED (fake Ollama, real database)."""
import asyncio
import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from dindon import performance
from dindon.analysis.embeddings import embed_conversations
from dindon.analysis.job import AnalysisJobs
from dindon.analysis.ollama import Ollama
from dindon.api.main import create_app
from dindon.bot.runner import BotRunner, Writer
from fake_ollama import FakeOllama
from gateway_fixtures import GUILD
from synthetic import settings_for
from test_analysis import NOW, Talk, ingest
from test_extraction import ALICE_ID, GUILD_ID, PASSWORD, debate, BOB_ID, ALICE, BOB
from dindon.analysis.conversations import build_conversations


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


def test_settings_are_always_complete_and_inside_their_limits():
    assert performance.clean({}) == performance.DEFAULT                     # nothing saved: full speed, as before this existed
    odd = performance.clean({"ai_max_load": 3, "ai_threads": 9999, "ai_batch": "x", "bot_batch_seconds": 99, "ai_keep_alive": "jamais"})
    assert odd == {"preset": "custom", "ai_max_load": 10, "ai_threads": 64, "ai_batch": 16, "bot_batch_seconds": 10.0, "ai_keep_alive": "10m"}
    for name, preset in performance.PRESETS.items():                       # a preset gives its own values, whatever else was sent with it
        got = performance.clean({"preset": name, "ai_max_load": 77})
        assert got["preset"] == name and got["ai_max_load"] == preset["ai_max_load"] and got["bot_batch_seconds"] == preset["bot_batch_seconds"]
    assert performance.PRESETS["saver"]["ai_max_load"] < performance.PRESETS["balanced"]["ai_max_load"] < performance.PRESETS["full"]["ai_max_load"] == 100


def test_the_pause_makes_the_models_work_the_asked_share_of_the_time():
    assert performance.pause_for(2.0, 100) == 0 and performance.pause_for(0, 25) == 0
    assert performance.pause_for(2.0, 50) == pytest.approx(2.0)            # half of the time: as long idle as at work
    assert performance.pause_for(2.0, 25) == pytest.approx(6.0)            # a quarter: three times as long idle
    assert performance.pause_for(1000.0, 10) == performance.MAX_PAUSE      # never so long that the analysis looks dead


def test_every_call_to_the_models_is_followed_by_the_pause_and_carries_the_limits(ollama):
    client = Ollama(ollama.url, timeout=30)
    pauses = []
    client.sleep = pauses.append
    client.limits = lambda: {"ai_max_load": 50, "ai_threads": 3, "ai_keep_alive": "0"}
    ollama.chat_handler = lambda body: {"x": 1}
    client.chat_json("qwen3:14b", "s", "u", {})
    assert len(pauses) == 1 and 0 < pauses[0] < 1                          # at 50 %: as long idle as the call lasted (a few milliseconds here)
    pauses.clear()
    client._pause(time.monotonic() - 4, {"ai_max_load": 50})
    assert sum(pauses) == pytest.approx(4.0, abs=0.1)
    body = [b for p, b in ollama.requests if p == "/api/chat"][0]
    assert body["keep_alive"] == "0" and body["options"]["num_thread"] == 3
    client.embed("bge-m3", ["bonjour"])
    body = [b for p, b in ollama.requests if p == "/api/embed"][0]
    assert body["keep_alive"] == "0" and body["options"] == {"num_thread": 3}


def test_a_long_pause_ends_at_once_when_the_person_stops_the_analysis(ollama):
    client = Ollama(ollama.url, timeout=30)
    slept = []
    client.sleep = slept.append
    client.cancelled = lambda: len(slept) >= 2
    client._pause(time.monotonic() - 100, {"ai_max_load": 10})              # would wait 900 s (capped at 300): stops after two slices
    assert len(slept) == 2


def test_without_limits_nothing_is_asked_and_nothing_is_waited_for(ollama):
    client = Ollama(ollama.url, timeout=30)
    slept = []
    client.sleep = slept.append
    ollama.chat_handler = lambda body: {"x": 1}
    client.chat_json("qwen3:14b", "s", "u", {})
    body = [b for p, b in ollama.requests if p == "/api/chat"][0]
    assert slept == [] and body["keep_alive"] == "10m" and "num_thread" not in body["options"]
    client.limits = lambda: 1 / 0                                           # a broken settings source never makes a call fail
    assert client.chat_json("qwen3:14b", "s", "u", {}) == {"x": 1}


def test_the_size_of_the_batches_can_change_while_the_vectors_are_made(ingest_db, ollama):
    debate(ingest_db)
    talk = Talk(NOW - __import__("datetime").timedelta(hours=30))
    talk.next_id += 1000
    ingest(ingest_db, [talk.say("quel temps magnifique pour une randonnée en montagne", ALICE), talk.say("oui, partons au lever du soleil demain matin", BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    sizes = iter([1, 1])
    client = Ollama(ollama.url, timeout=30)
    embed_conversations(ingest_db, client, "bge-m3", GUILD_ID, batch=lambda: next(sizes))
    assert len([r for r in ollama.requests if r[0] == "/api/embed"]) == 2 and ingest_db.execute("SELECT count(*) FROM conversation_embeddings").fetchone() == (2,)


def test_the_analysis_works_at_the_speed_that_was_set_and_says_so(ingest_url, ingest_db, tmp_path, ollama):
    debate(ingest_db)
    performance.save(ingest_db, {"preset": "saver"})
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    client = Ollama(ollama.url, timeout=30)
    slept = []
    client.sleep = slept.append
    jobs = AnalysisJobs(settings, client=client)
    jobs.start(GUILD_ID, ("conversations", "embeddings"))
    jobs.wait(30)
    status = jobs.status()
    assert status["state"] == "done" and any("25 % du temps" in line for line in status["lines"])
    assert client.limits is None                                            # the limits are only for the time of a run
    body = [b for p, b in ollama.requests if p == "/api/embed"][0]
    assert body["keep_alive"] == "0" and body["options"]["num_thread"] == performance.PRESETS["saver"]["ai_threads"]


def test_the_bot_groups_its_writes_for_as_long_as_it_was_asked(ingest_db, ingest_url):
    runner = BotRunner([GUILD], Writer(ingest_url))
    assert runner._batch_seconds == 0.3
    performance.save(ingest_db, {"preset": "saver"})
    asyncio.run(runner._beat())
    assert runner._batch_seconds == performance.PRESETS["saver"]["bot_batch_seconds"] and runner.heartbeat_data()["batch_seconds"] == 3.0
    ingest_db.execute("DROP TABLE runtime_settings")                        # a database that does not know the table yet
    asyncio.run(runner._beat())
    assert runner._batch_seconds == 0.3                                     # no table: the defaults, as before this existed


@pytest.fixture
def web(ingest_url, ingest_db, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def test_the_page_reads_and_saves_the_limits(web, ingest_db):
    first = web.get("/api/performance").json()
    assert first["settings"]["ai_max_load"] == 100 and set(first["presets"]) == {"saver", "balanced", "full"} and first["cpu_count"]
    saved = web.put("/api/performance", json={"preset": "balanced"}).json()["settings"]
    assert saved["preset"] == "balanced" and saved["ai_max_load"] == 60 and performance.load(ingest_db) == saved           # kept for the bot and the analysis
    custom = web.put("/api/performance", json={"preset": "custom", "ai_max_load": 40, "ai_threads": 2, "ai_keep_alive": "30s", "ai_batch": 5, "bot_batch_seconds": 2.5}).json()["settings"]
    assert custom == {"preset": "custom", "ai_max_load": 40, "ai_threads": 2, "ai_keep_alive": "30s", "ai_batch": 5, "bot_batch_seconds": 2.5}
    for bad in ({"ai_max_load": 5}, {"ai_max_load": 101}, {"ai_keep_alive": "jamais"}, {"bot_batch_seconds": 60}, {"preset": "turbo"}):
        assert web.put("/api/performance", json=bad).status_code == 422


def test_the_limits_need_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert c.get("/api/performance").status_code == 401 and c.put("/api/performance", json={"preset": "saver"}).status_code == 401
