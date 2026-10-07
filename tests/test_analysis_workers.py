"""Private helper configuration and two independent Ollama instances (synthetic data only)."""
import threading
import time
import pytest
from fastapi.testclient import TestClient

from dindon.analysis import helpers
from dindon.analysis import job as job_module
from dindon.analysis.conversations import build_conversations
from dindon.analysis.embeddings import embed_conversations
from dindon.analysis.job import AnalysisJobs
from dindon.analysis.ollama import Ollama, OllamaPool
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


def test_shares_split_the_work_in_percent_and_zero_gets_nothing():
    local = FakeOllama().start()
    helper = FakeOllama().start()
    try:
        pool = OllamaPool(local.url, (helper.url,), timeout=1)
        pool.models()
        pool.set_shares({local.url: 25, helper.url: 75})
        for i in range(8):
            pool.embed("bge-m3", [str(i)])
        def count(fake):
            return sum(path == "/api/embed" for path, _ in fake.requests)
        assert (count(local), count(helper)) == (2, 6)
        seen = {row["url"]: row for row in pool.activity()}
        assert seen[local.url]["calls"] == 2 and seen[helper.url]["calls"] == 6 and seen[helper.url]["items"] == 6
        assert seen[helper.url]["observed"] == 75 and seen[helper.url]["share"] == 75 and seen[helper.url]["active"] == 0
        pool.set_shares({local.url: 100, helper.url: 0})
        before = count(helper)
        pool.embed_batches("bge-m3", [[str(i)] for i in range(4)])
        assert count(helper) == before
    finally:
        local.stop()
        helper.stop()


def test_administrator_sets_shares_and_they_survive_a_restart(ingest_url, ingest_db, tmp_path, monkeypatch):
    monkeypatch.setattr(OllamaPool, "status", lambda self, wanted: [{"url": c.base_url, "online": True, "models": [], "usable": [], "local": c is self.local} for c in self.clients])
    url = "http://100.101.102.103:11434"
    with TestClient(create_app(settings_for(ingest_url, tmp_path, "password"), background=False)) as web:
        assert web.post("/api/login", json={"password": "password"}).status_code == 200
        assert web.put("/api/performance/workers", json={"urls": [url]}).json()["shares"] == {"local": 50, url: 50}
        assert web.put("/api/performance/workers/shares", json={"shares": {"local": 30, url: 70}}).json()["shares"] == {"local": 30, url: 70}
        for bad in ({"local": 50, url: 40}, {"local": 100}, {"local": 120, url: -20}, {"local": 50, "http://100.1.1.1:11434": 50}):
            assert web.put("/api/performance/workers/shares", json={"shares": bad}).status_code == 422
    with TestClient(create_app(settings_for(ingest_url, tmp_path, "password"), background=False)) as restarted:
        assert restarted.post("/api/login", json={"password": "password"}).status_code == 200
        assert restarted.get("/api/performance/workers").json()["shares"] == {"local": 30, url: 70}
        assert restarted.app.state.analysis.client.shares[url] == 70
        assert restarted.put("/api/performance/workers", json={"urls": []}).status_code == 200


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


def test_model_health_check_still_works_after_analysis_is_cancelled():
    server = FakeOllama().start()
    try:
        pool = OllamaPool(server.url, (), timeout=5)
        pool.models()
        stopped = threading.Event()
        pool.cancelled = stopped.is_set
        pool._sync()  # A model call has inherited the analysis cancellation callback.
        stopped.set()

        assert "bge-m3:latest" in pool.models()
        assert pool.status()[0]["online"] is True
    finally:
        server.stop()


def test_cancelling_interrupts_an_inflight_model_request():
    server = FakeOllama().start()
    server.chat_delay = 3
    stopped = threading.Event()
    client = Ollama(server.url, timeout=30)
    client.cancelled = stopped.is_set
    result = []
    thread = threading.Thread(target=lambda: result.append(_cancel_result(client)), daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 2
        while not any(path == "/api/chat" for path, _ in server.requests) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert any(path == "/api/chat" for path, _ in server.requests)
        stopped.set()
        thread.join(1)
        assert not thread.is_alive() and result == ["InterruptedError"]
    finally:
        stopped.set()
        server.stop()


def _cancel_result(client):
    try:
        client.chat_json("qwen3:14b", "system", "message", {})
    except Exception as error:
        return type(error).__name__
    return "completed"


def test_cancelling_interrupts_a_long_database_step(ingest_url, tmp_path, monkeypatch):
    server = FakeOllama().start()
    entered = threading.Event()

    def slow_conversations(conn, guild_id, **_options):
        entered.set()
        conn.execute("SELECT pg_sleep(10)")
        return {"made": 0, "messages": 0, "kept": 0, "total": 0}

    monkeypatch.setattr(job_module, "build_conversations", slow_conversations)
    jobs = AnalysisJobs(settings_for(ingest_url, tmp_path, "password"), client=Ollama(server.url))
    try:
        jobs.start(GUILD_ID, ("conversations",))
        assert entered.wait(3)
        time.sleep(0.2)  # let PostgreSQL enter pg_sleep before sending its cancel request
        assert jobs.cancel()
        jobs.wait(2)
        assert jobs.status()["state"] == "cancelled"
    finally:
        server.stop()


def _measured_pool():
    pool = OllamaPool("http://127.0.0.1:1", ("http://127.0.0.1:2",))
    pool._models = {c.base_url: {"chat", "vectors"} for c in pool.clients}
    pool.set_shares({c.base_url: 50 for c in pool.clients})
    return pool


def test_free_computers_take_work_without_overlapping_requests(monkeypatch):
    pool = _measured_pool()
    pool.set_shares({pool.local.base_url: 90, pool.clients[0].base_url: 10})
    guard = threading.Lock()
    active, maximum, counts = {}, {}, {}

    def work(client, _model, texts):
        with guard:
            url = client.base_url
            active[url] = active.get(url, 0) + 1
            maximum[url] = max(maximum.get(url, 0), active[url])
            counts[url] = counts.get(url, 0) + 1
        time.sleep(0.04 if client is pool.local else 0.005)
        with guard:
            active[url] -= 1
        return texts

    for client in pool.clients:
        monkeypatch.setattr(client, "embed", lambda model, texts, c=client: work(c, model, texts))
    groups = [[str(i)] for i in range(40)]
    assert pool.embed_batches("vectors", groups) == groups
    assert all(value == 1 for value in maximum.values())
    assert counts[pool.clients[0].base_url] > counts[pool.local.base_url] * 3


def test_each_round_reports_its_own_statistics_and_smooths_shares(monkeypatch):
    pool = _measured_pool()
    fast = pool.clients[0]
    delays = {fast.base_url: 0.005, pool.local.base_url: 0.04}
    for client in pool.clients:
        def chat(*_args, c=client):
            time.sleep(delays[c.base_url])
            return {}
        monkeypatch.setattr(client, "chat_json", chat)
    pool.begin_round()
    for _ in range(4):
        pool.chat_json("chat", "s", "u", {})
    first = {r["url"]: r for r in pool.finish_round(1, "chat")}
    assert all(r["calls"] == 2 and r["average"] > 0 for r in first.values())
    assert first[fast.base_url]["share"] > 75
    assert sum(r["share"] for r in first.values()) == 100
    first_share = first[fast.base_url]["share"]
    delays[fast.base_url] = 0.08
    pool.begin_round()
    # Measure both machines, including the slower one, without relying on a quota.
    for client in pool.clients:
        pool._timed(client, "chat_json", "chat", "s", "u", {})
    second = {r["url"]: r for r in pool.finish_round(2, "chat")}
    assert all(r["calls"] == 1 and r["number"] == 2 for r in second.values())
    assert 50 < second[fast.base_url]["share"] < first_share
    assert pool.activity()[0]["round"]["number"] == 2
    assert pool.shares == {c.base_url: 50 for c in pool.clients}  # saved initial settings stay intact
    pool.set_shares({pool.local.base_url: 100, fast.base_url: 0})
    pool.begin_round()
    pool.chat_json("chat", "s", "u", {})
    third = {r["url"]: r for r in pool.finish_round(3, "chat")}
    assert third[fast.base_url]["calls"] == 0 and third[fast.base_url]["share"] == 0
    pool.reset()
    assert all(row["calls"] == 0 and row["round"] is None for row in pool.activity())


def test_waiting_for_a_computer_is_cancellable(monkeypatch):
    pool = _measured_pool()
    stopped = threading.Event()
    pool.cancelled = stopped.is_set
    pool._busy = {c.base_url: 1 for c in pool.clients}
    result = []
    thread = threading.Thread(target=lambda: result.append(_cancel_result(pool)))
    pool._models = {c.base_url: {"qwen3:14b"} for c in pool.clients}
    thread.start()
    stopped.set()
    thread.join(1)
    assert not thread.is_alive() and result == ["InterruptedError"]


def test_analysis_publishes_statistics_after_each_complete_round(ingest_url, tmp_path, monkeypatch):
    pool = _measured_pool()
    settings = settings_for(ingest_url, tmp_path, "password")
    pool._models = {c.base_url: {settings.naming_model, settings.embed_model} for c in pool.clients}
    for client in pool.clients:
        monkeypatch.setattr(client, "chat_json", lambda *_args: {})
    jobs = AnalysisJobs(settings, client=pool)
    seen = []

    def extract(_conn, client, name_model, _embed_model, _guild, **_options):
        # The second round can already inspect the preceding round's statistics.
        seen.append(jobs.status()["last_round"])
        for _ in range(2):
            client.chat_json(name_model, "s", "u", {})
        return {"done": 2, "claims": 0, "refused": 0, "failed": 0, "left": 1, "unread": 0}

    monkeypatch.setattr(job_module, "extract_claims", extract)
    monkeypatch.setattr(job_module, "verify_stances", lambda *_args, **_kwargs: {"checked": 0, "changed": 0, "questions": 0, "failed": 0})
    monkeypatch.setattr(job_module, "assign_axes", lambda *_args, **_kwargs: {"done": 0, "links": 0, "scores": 0, "failed": 0})
    jobs._run(GUILD_ID, ("claims",), None, False, threading.Event(), limit=2, rounds=2)
    final = jobs.status()
    assert final["state"] == "done" and final["last_round"]["number"] == 2
    assert seen[0] is None and seen[1]["number"] == 1
    assert sum(c["calls"] for c in final["last_round"]["computers"]) == 2
    assert sum(c["calls"] for c in final["computers"]) == 4
    assert sum(c["share"] for c in final["last_round"]["computers"]) == 100
