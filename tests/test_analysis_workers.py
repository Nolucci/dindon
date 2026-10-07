"""Private helper configuration and two independent Ollama instances (synthetic data only)."""
import pytest
from fastapi.testclient import TestClient

from dindon.analysis import helpers
from dindon.analysis.conversations import build_conversations
from dindon.analysis.embeddings import embed_conversations
from dindon.analysis.ollama import OllamaPool
from dindon.api.main import create_app
from fake_ollama import FakeOllama
from synthetic import settings_for
from test_analysis import NOW, SAYS, Talk, ingest
from test_extraction import ALICE, BOB, GUILD_ID, debate


def test_only_tailscale_addresses_can_be_added(ingest_db):
    good = "http://100.101.102.103:11434"
    assert helpers.save(ingest_db, [good, good + "/"]) == (good,)
    assert helpers.load(ingest_db) == (good,)
    for bad in ("http://127.0.0.1:11434", "http://8.8.8.8:11434", "http://100.101.102.103:11434/api", "http://100.101.102.103:11434@evil.test", "https://100.101.102.103:11434"):
        with pytest.raises(ValueError):
            helpers.validate(bad)


def test_embedding_batches_use_both_computers_and_retry_locally():
    local = FakeOllama().start()
    helper = FakeOllama().start()
    try:
        pool = OllamaPool(local.url, (helper.url,), timeout=1)
        assert "bge-m3:latest" in pool.models()
        vectors = pool.embed_batches("bge-m3", [["premier"], ["second"], ["troisième"], ["quatrième"]])
        assert len(vectors) == 4 and all(len(group[0]) == 1024 for group in vectors)
        assert any(path == "/api/embed" for path, _ in local.requests)
        assert any(path == "/api/embed" for path, _ in helper.requests)
        helper.stop()
        assert len(pool.embed("bge-m3", ["reprendre"])[0]) == 1024
    finally:
        local.stop()


def test_administrator_can_add_and_remove_helper_without_restarting(ingest_url, ingest_db, tmp_path, monkeypatch):
    monkeypatch.setattr(OllamaPool, "status", lambda self, wanted: [{"url": c.base_url, "online": True, "models": [], "usable": [], "local": c is self.local} for c in self.clients])
    app = create_app(settings_for(ingest_url, tmp_path, "password"), background=False)
    with TestClient(app) as web:
        assert web.get("/api/performance/workers").status_code == 401
        assert web.post("/api/login", json={"password": "password"}).status_code == 200
        url = "http://100.101.102.103:11434"
        added = web.put("/api/performance/workers", json={"urls": [url]})
        assert added.status_code == 200 and added.json()["configured"] == [url]
        assert helpers.load(ingest_db) == (url,)
        assert web.get("/api/performance/workers").json()["workers"][0]["url"] == url
        assert web.put("/api/performance/workers", json={"urls": ["http://example.com:11434"]}).status_code == 422
    with TestClient(create_app(settings_for(ingest_url, tmp_path, "password"), background=False)) as restarted:
        assert restarted.post("/api/login", json={"password": "password"}).status_code == 200
        assert restarted.get("/api/performance/workers").json()["configured"] == [url]
        assert restarted.put("/api/performance/workers", json={"urls": []}).status_code == 200
        assert helpers.load(ingest_db) == ()


def test_parallel_embedding_saves_all_conversations(ingest_db):
    local = FakeOllama().start()
    helper = FakeOllama().start()
    try:
        debate(ingest_db)
        talk = Talk()
        talk.next_id += 1000
        ingest(ingest_db, [talk.say(SAYS, ALICE), talk.say(SAYS, BOB), talk.say(SAYS, ALICE, after_minutes=60), talk.say(SAYS, BOB)])
        build_conversations(ingest_db, GUILD_ID, now=NOW)
        pool = OllamaPool(local.url, (helper.url,), timeout=5)
        pool.models()
        result = embed_conversations(ingest_db, pool, "bge-m3", GUILD_ID, batch=1)
        assert result["done"] >= 2
        assert ingest_db.execute("SELECT count(*) FROM conversation_embeddings").fetchone()[0] == result["done"]
        assert any(path == "/api/embed" for path, _ in local.requests)
        assert any(path == "/api/embed" for path, _ in helper.requests)
    finally:
        helper.stop()
        local.stop()


def test_a_different_embedding_build_is_not_mixed_with_the_server():
    local = FakeOllama().start()
    helper = FakeOllama().start()
    try:
        helper.digests["bge-m3:latest"] = "another-build"
        pool = OllamaPool(local.url, (helper.url,), timeout=5)
        pool.models()
        assert pool.parallelism_for("bge-m3") == 1
        pool.embed_batches("bge-m3", [["a"], ["b"]])
        assert not any(path == "/api/embed" for path, _ in helper.requests)
    finally:
        helper.stop()
        local.stop()
