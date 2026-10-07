"""The analysis from the interface: start, follow, cancel, and what is done with the topics that it proposes.

Level of proof: SIMULATED (fake Ollama, invented server, real database, real application).
"""
import dataclasses
import time
from datetime import datetime, timedelta, timezone, UTC

import pytest
from fastapi.testclient import TestClient

from dindon.api.main import create_app
from dindon.ingest.loader import ingest_file
from fake_ollama import FakeOllama
from make_demo_server import World, write_exports
from synthetic import settings_for

PASSWORD = "correct horse"


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def world(ingest_db, tmp_path):
    world = World(seed=7, people=30)
    world.generate(2500, days=20, end=datetime.now(UTC) - timedelta(days=3))
    for path in write_exports(world, tmp_path / "exports"):
        ingest_file(ingest_db, path)
    return world


@pytest.fixture
def app(ollama, world, ingest_url, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    with TestClient(create_app(settings, background=False)) as client:
        yield client


@pytest.fixture
def me(app):
    assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return app


def finished(client, timeout=60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get("/api/analysis").json()["job"]
        if job["state"] not in ("running", "cancelling"):
            return job
        time.sleep(0.1)
    raise AssertionError("the analysis did not finish")


def analyze(client, **body) -> dict:
    assert client.post("/api/analysis", json=body).status_code == 200
    return finished(client)


@pytest.mark.parametrize("method, path", [("get", "/api/analysis"), ("post", "/api/analysis"), ("post", "/api/analysis/cancel"), ("get", "/api/topics"), ("get", "/api/digest"),
                                          ("patch", "/api/topics/1"), ("post", "/api/topics/1/merge"), ("post", "/api/topics/validate-batch")])
def test_nothing_of_the_analysis_is_available_without_the_session(app, method, path):
    assert getattr(app, method)(path, **({"json": {}} if method != "get" else {})).status_code == 401


def test_the_state_says_what_is_possible_and_what_is_done(me):
    state = me.get("/api/analysis").json()
    assert state["ready"] == {"ollama": True, "problem": None, "models": {"bge-m3": True, "qwen3:14b": True}}
    assert state["counts"]["messages"] > 2000 and state["counts"]["conversations"] == 0 and state["last_run"] is None
    assert state["job"]["state"] == "idle"


def test_the_analysis_makes_the_conversations_the_vectors_and_proposes_topics(me):
    job = analyze(me)
    assert job["state"] == "done" and job["error"] is None
    state = me.get("/api/analysis").json()
    counts = state["counts"]
    assert counts["conversations"] > 100 and counts["kept"] > 100 and counts["embedded"] == counts["kept"]
    assert counts["topics"]["proposed"] >= 5 and state["last_run"]["chosen_by"] == "silhouette"
    topics = me.get("/api/topics").json()
    assert len(topics) == counts["topics"]["proposed"] and all(t["status"] == "proposed" for t in topics)
    assert topics == sorted(topics, key=lambda t: -t["conversations"])                       # the biggest first
    biggest = topics[0]
    assert biggest["keywords"] and 1 <= len(biggest["examples"]) <= 3 and all(len(e) <= 500 for e in biggest["examples"])
    assert "@" not in " ".join(e for t in topics for e in t["examples"])                      # excerpts without mentions


def test_the_person_can_choose_how_many_topics(me):
    analyze(me, topics=6)
    assert len(me.get("/api/topics").json()) == 6
    assert me.get("/api/analysis").json()["last_run"]["chosen_by"] == "person"


def test_selected_topics_are_validated_together_and_stale_selection_changes_nothing(me):
    analyze(me, topics=6)
    guild = me.get("/api/analysis").json()["guild"]
    topics = me.get("/api/topics").json()
    ids = [topics[0]["id"], topics[1]["id"]]
    response = me.post("/api/topics/validate-batch", json={"guild": guild, "ids": ids + [ids[0]]})
    assert response.status_code == 200 and response.json() == {"validated": 2}
    statuses = {t["id"]: t["status"] for t in me.get("/api/topics").json()}
    assert all(statuses[id] == "validated" for id in ids)
    assert statuses[topics[2]["id"]] == "proposed"
    stale = me.post("/api/topics/validate-batch", json={"guild": guild, "ids": [ids[0], topics[2]["id"]]})
    assert stale.status_code == 409
    assert next(t for t in me.get("/api/topics").json() if t["id"] == topics[2]["id"])["status"] == "proposed"


def test_a_stage_can_be_run_alone_and_again_without_redoing_what_is_done(me, ollama):
    analyze(me, stages=["conversations"])
    assert me.get("/api/analysis").json()["counts"]["embedded"] == 0
    analyze(me, stages=["embeddings"])
    embedded = len([1 for path, _ in ollama.requests if path == "/api/embed"])
    analyze(me, stages=["embeddings"])
    assert len([1 for path, _ in ollama.requests if path == "/api/embed"]) == embedded      # nothing more to embed: no call


def test_an_ollama_without_the_model_is_told_before_anything_starts(me, ollama):
    ollama.models = ["bge-m3:latest"]
    answer = me.post("/api/analysis", json={})
    assert answer.status_code == 409 and "ollama pull qwen3:14b" in answer.json()["detail"]
    assert me.get("/api/analysis").json()["job"]["state"] == "idle"
    assert me.get("/api/analysis").json()["ready"]["models"] == {"bge-m3": True, "qwen3:14b": False}


def test_an_ollama_that_is_not_running_is_told(ingest_url, world, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url="http://127.0.0.1:9")
    with TestClient(create_app(settings, background=False)) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        assert client.get("/api/analysis").json()["ready"]["ollama"] is False
        answer = client.post("/api/analysis", json={})
        assert answer.status_code == 409 and "ne répond pas" in answer.json()["detail"]


def test_one_analysis_at_a_time_and_it_can_be_stopped(me, ollama):
    ollama.chat_delay = 0.4
    assert me.post("/api/analysis", json={}).status_code == 200
    busy = me.post("/api/analysis", json={})
    assert busy.status_code == 409 and "déjà en cours" in busy.json()["detail"]
    assert me.post("/api/analysis/cancel").json()["state"] in ("cancelling", "running")
    assert finished(me)["state"] == "cancelled"


def test_a_failure_is_told_with_words_and_leaves_the_topics_as_they_were(me, ollama):
    analyze(me, topics=6)
    before = me.get("/api/topics").json()
    ollama.models = ["bge-m3:latest", "qwen3:14b"]
    # too few conversations with a vector cannot be forced here; a name that cannot be given falls back on the keywords instead
    ollama.fail_chat = 100
    assert analyze(me, topics=6)["state"] == "done"
    after = me.get("/api/topics").json()
    assert len(after) == len(before) and all(t["keywords"] for t in after)
    assert me.get("/api/analysis").json()["last_run"]["id"] > 1


def test_a_proposal_is_validated_renamed_rejected_and_put_back(me):
    analyze(me, topics=6)
    topic = me.get("/api/topics").json()[0]
    validated = me.patch(f"/api/topics/{topic['id']}", json={"status": "validated"}).json()
    assert validated["status"] == "validated" and validated["validated_at"]
    renamed = me.patch(f"/api/topics/{topic['id']}", json={"label": "Mon nom", "description": "Ma description"}).json()
    assert renamed["label"] == "Mon nom" and renamed["description"] == "Ma description" and renamed["status"] == "validated"
    assert me.patch(f"/api/topics/{topic['id']}", json={"status": "rejected"}).json()["status"] == "rejected"
    assert topic["id"] not in [t["id"] for t in me.get("/api/topics").json()]                  # a rejected topic is hidden...
    assert topic["id"] in [t["id"] for t in me.get("/api/topics?rejected=true").json()]        # ...until it is asked for
    assert me.patch(f"/api/topics/{topic['id']}", json={"status": "proposed"}).json()["validated_at"] is None


def test_a_bad_request_on_a_topic_is_refused(me):
    analyze(me, topics=6)
    topic_id = me.get("/api/topics").json()[0]["id"]
    assert me.patch(f"/api/topics/{topic_id}", json={"status": "deleted"}).status_code == 422
    assert me.patch(f"/api/topics/{topic_id}", json={"label": "x"}).status_code == 422
    assert me.patch("/api/topics/999999", json={"status": "validated"}).status_code == 404


def test_merging_adds_the_conversations_to_the_other_topic_and_can_be_undone(me):
    analyze(me, topics=6)
    topics = me.get("/api/topics").json()
    (a, b) = topics[0], topics[1]
    merged = me.post(f"/api/topics/{a['id']}/merge", json={"into": b["id"]}).json()
    assert merged["id"] == b["id"] and merged["conversations"] == a["conversations"] + b["conversations"]
    assert a["id"] not in [t["id"] for t in me.get("/api/topics").json()]                      # the merged one is no longer listed
    me.patch(f"/api/topics/{a['id']}", json={"status": "proposed"})                            # undone
    again = {t["id"]: t["conversations"] for t in me.get("/api/topics").json()}
    assert again[a["id"]] == a["conversations"] and again[b["id"]] == b["conversations"]


def test_a_topic_cannot_be_merged_with_itself_with_a_rejected_one_or_one_that_is_not_there(me):
    analyze(me, topics=6)
    a, b = me.get("/api/topics").json()[:2]
    assert me.post(f"/api/topics/{a['id']}/merge", json={"into": a["id"]}).status_code == 422
    me.patch(f"/api/topics/{b['id']}", json={"status": "rejected"})
    assert me.post(f"/api/topics/{a['id']}/merge", json={"into": b["id"]}).status_code == 422
    assert me.post(f"/api/topics/{a['id']}/merge", json={"into": 999999}).status_code == 422


def test_what_was_merged_into_a_topic_comes_back_when_that_topic_is_rejected(me):
    analyze(me, topics=6)
    a, b = me.get("/api/topics").json()[:2]
    me.post(f"/api/topics/{a['id']}/merge", json={"into": b["id"]})
    me.patch(f"/api/topics/{b['id']}", json={"status": "rejected"})
    assert a["id"] in [t["id"] for t in me.get("/api/topics").json()]


def test_a_server_id_that_is_not_a_number_is_refused_not_a_crash(me):
    assert me.post("/api/analysis", json={"guild": "abc"}).status_code == 422
    assert me.post("/api/analysis", json={"guild": "1' OR 1=1"}).status_code == 422


def test_what_the_person_does_to_a_proposal_protects_it_from_the_next_run(me):
    analyze(me, topics=6)
    a, b = me.get("/api/topics").json()[:2]
    me.patch(f"/api/topics/{a['id']}", json={"label": "Mon nom"})
    me.post(f"/api/topics/{b['id']}/merge", json={"into": me.get("/api/topics").json()[2]["id"]})
    analyze(me, topics=6)
    labels = [t["label"] for t in me.get("/api/topics").json()]
    assert "Mon nom" in labels                                                       # the renamed one is still there
    with_merged = [t for t in me.get("/api/topics").json() if t["conversations"]]
    assert len(labels) == 6 + 2 and with_merged                                      # six new proposals, and the two that were touched


def test_the_digest_is_a_file_to_download_in_markdown_or_json(me):
    page = me.get("/api/digest")
    assert page.status_code == 200 and "attachment" in page.headers["content-disposition"] and page.headers["content-disposition"].endswith('.md"')
    assert "## Thèmes" in page.text and "## Positions" in page.text and "## Contradictions" in page.text
    data = me.get("/api/digest", params={"format": "json", "limit": 3}).json()
    assert set(data) == {"guild", "themes", "positions", "contradictions"}
