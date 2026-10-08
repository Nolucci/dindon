"""The computers that check the debates (debate/checker.py, bot/debate_commands._publish_computers, api/debates.py « computers »): the pool that the checks go through, the helpers read again
while the bot runs, what is said about each computer, and the page's endpoint.

Level of proof: SIMULATED. The Ollama servers are replaced by a function that lists models; nothing talks to a model or to the network."""
import json

import pytest
from fastapi.testclient import TestClient

from dindon.analysis import ollama as ollama_module
from dindon.analysis.ollama import OllamaError, OllamaPool
from dindon.api.main import create_app
from dindon.db import connect
from dindon.debate import checker as checker_module
from dindon.debate.checker import Checker
from synthetic import settings_for

SERVER, HELPER = "http://ollama:11434", "http://100.64.0.2:11434"


@pytest.fixture
def servers(monkeypatch):
    """The models that each fake Ollama lists; an address that is not in it does not answer."""
    listed = {SERVER: ["qwen3:8b"], HELPER: ["qwen3:8b", "gemma4:12b"]}

    def call(self, path, body=None, timeout=None):
        if self.base_url not in listed:
            raise OllamaError("away")
        assert path == "/api/tags"
        return {"models": [{"name": name, "digest": name} for name in listed[self.base_url]]}

    monkeypatch.setattr(ollama_module.Ollama, "_call", call)
    return listed


def checker(helpers=(), load=None):
    return Checker(OllamaPool(SERVER, helpers), "qwen3:8b", None, local_url=SERVER, load_helpers=load, helpers=helpers)


def test_each_computer_is_listed_with_whether_it_answers_and_has_the_model(servers):
    servers[HELPER] = ["gemma4:12b"]
    c = checker((HELPER,))
    c.llm.models()
    rows = {r["url"]: r for r in c.computers()}
    assert rows[SERVER]["local"] and rows[SERVER]["online"] and rows[SERVER]["has_model"]
    assert not rows[HELPER]["local"] and rows[HELPER]["online"] and not rows[HELPER]["has_model"]      # it answers, but it cannot do this work
    del servers[HELPER]
    c.llm.models()
    assert {r["url"]: r["online"] for r in c.computers()} == {SERVER: True, HELPER: False}


def test_a_client_that_is_not_a_pool_has_no_computers_to_show():
    assert Checker(object(), "qwen3:8b", None).computers() == []


def test_a_computer_that_failed_is_tried_again_and_the_counters_are_kept(servers):
    c = checker((HELPER,))
    c.llm.models()
    c.llm._failed.add(HELPER)
    c.llm._act(HELPER)["calls"] = 3
    c.llm.retry_failed()
    assert c.llm._failed == set() and c.llm._act(HELPER)["calls"] == 3


def test_the_helpers_set_in_the_interface_are_read_again_while_the_bot_runs(servers, monkeypatch):
    monkeypatch.setattr(checker_module, "HELPERS_REFRESH_SECONDS", 0)
    wanted = {"urls": ()}
    c = checker((), load=lambda: wanted["urls"])
    c._ready()
    assert [r["url"] for r in c.computers()] == [SERVER]
    wanted["urls"] = (HELPER,)
    c._ready()
    assert {r["url"] for r in c.computers()} == {SERVER, HELPER}
    wanted["urls"] = ()
    c._ready()
    assert [r["url"] for r in c.computers()] == [SERVER]


def test_a_list_that_cannot_be_read_leaves_the_last_one_standing(servers, monkeypatch):
    monkeypatch.setattr(checker_module, "HELPERS_REFRESH_SECONDS", 0)

    def away():
        raise RuntimeError("database away")

    c = checker((HELPER,), load=away)
    c._ready()
    assert {r["url"] for r in c.computers()} == {SERVER, HELPER}


PASSWORD = "correct horse"


@pytest.fixture
def api(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def say(url, data, age="0 seconds"):
    with connect(url) as conn:
        conn.execute("INSERT INTO service_status (name, updated_at, data) VALUES ('debate_computers', now() - %s::interval, %s::jsonb) "
                     "ON CONFLICT (name) DO UPDATE SET updated_at = excluded.updated_at, data = excluded.data", (age, json.dumps(data)))
        conn.commit()


def test_the_page_gets_what_the_bot_said_and_knows_when_it_is_old(api, ingest_url):
    assert api.get("/api/debates/computers").json() == {"computers": [], "model": None, "age_seconds": None, "fresh": False}
    row = {"url": SERVER, "local": True, "active": 1, "online": True, "has_model": True, "calls": 4}
    say(ingest_url, {"model": "qwen3:8b", "computers": [row]})
    answer = api.get("/api/debates/computers").json()
    assert answer["computers"] == [row] and answer["model"] == "qwen3:8b" and answer["fresh"] and answer["age_seconds"] <= 5
    say(ingest_url, {"model": "qwen3:8b", "computers": [row]}, age="10 minutes")
    assert api.get("/api/debates/computers").json()["fresh"] is False


def test_the_computers_need_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as anonymous:
        assert anonymous.get("/api/debates/computers").status_code == 401


def test_the_bot_writes_what_its_computers_do_often_while_one_works_and_rarely_otherwise(ingest_url, tmp_path):
    from test_debate_bot import World
    from test_debate_checks import FakeChecker

    busy = {"on": True}
    fake = FakeChecker()
    fake.model = "qwen3:8b"
    fake.computers = lambda: [{"url": SERVER, "local": True, "active": int(busy["on"]), "online": True, "has_model": True}]
    world = World(ingest_url, tmp_path, checker=fake)

    def written():
        with connect(ingest_url) as conn:
            row = conn.execute("SELECT data FROM service_status WHERE name = 'debate_computers'").fetchone()
        return None if row is None else row[0]["computers"][0]["active"]

    world.tick(seconds=1)
    assert written() == 1                                         # the first look writes at once
    busy["on"] = False
    world.tick(seconds=1)
    assert written() == 1                                         # a busy computer is looked at again in 3 seconds, not before
    world.tick(seconds=3)
    assert written() == 0                                         # it stopped: the page learns it
