"""The automatic reading: off by default, configurable, one cycle at a time, never without the acknowledgement for the positions, never the messages of somebody
who asked to stop. Level of proof: SIMULATED (fake Ollama, real database)."""
import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone, UTC

import pytest
from fastapi.testclient import TestClient

from dindon import automation, privacy
from dindon.analysis import auto
from dindon.analysis.auto import cycle, tick
from dindon.analysis.job import AnalysisJobs
from dindon.analysis.ollama import Ollama
from dindon.api.main import create_app
from fake_ollama import FakeOllama
from synthetic import settings_for
from test_extraction import ALICE_ID, BOB_ID, GOOD, GUILD_ID, PASSWORD, SAYS_B, debate

PARIS = lambda h: datetime(2026, 10, 3, h, 30, tzinfo=UTC) - timedelta(hours=2)   # noqa: E731  (October: Paris is UTC+2, so PARIS(h) is h:30 in Paris)
GUILD = str(GUILD_ID)


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    server.chat_handler = lambda body: {"claims": GOOD}
    yield server
    server.stop()


@pytest.fixture
def setup(ingest_url, ingest_db, tmp_path, ollama):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    jobs = AnalysisJobs(settings, client=Ollama(ollama.url, timeout=30))
    return settings, jobs


def test_it_is_off_by_default_and_the_settings_are_always_valid():
    assert automation.clean({}) == automation.DEFAULT and automation.DEFAULT["enabled"] is False and automation.DEFAULT["positions"] is False
    odd = automation.clean({"interval_minutes": 40, "batch": 9999, "window_from": 40, "window_to": 0, "positions": True})
    assert odd["interval_minutes"] == 30 and odd["batch"] == 500 and (odd["window_from"], odd["window_to"]) == (23, 1)
    assert odd["positions"] is False                                                   # without the acknowledgement the positions are off, whatever was asked
    assert automation.clean({"positions": True, "positions_acknowledged": True})["positions"] is True


def test_the_hours_follow_the_time_zone_and_can_go_over_midnight():
    always = automation.clean({})
    assert automation.in_window(always, PARIS(3))
    night = automation.clean({"window_from": 22, "window_to": 6})
    assert [automation.in_window(night, PARIS(h)) for h in (21, 22, 23, 0, 5, 6, 12)] == [False, True, True, True, True, False, False]
    day = automation.clean({"window_from": 9, "window_to": 18})
    assert [automation.in_window(day, PARIS(h)) for h in (8, 9, 17, 18)] == [False, True, True, False]
    assert automation.in_window(day, datetime(2026, 10, 3, 8, 30, tzinfo=UTC))      # 8:30 UTC is 10:30 in Paris


def test_when_a_cycle_is_due():
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    on = automation.clean({"enabled": True, "interval_minutes": 60})
    never = {"last_cycle_at": None, "run_requested_at": None}
    assert not automation.due(automation.clean({}), never, now)                          # off: never
    assert automation.due(on, never, now)                                                # on, never ran
    ago = lambda m: (now - timedelta(minutes=m)).isoformat()  # noqa: E731
    assert not automation.due(on, {**never, "last_cycle_at": ago(30)}, now) and automation.due(on, {**never, "last_cycle_at": ago(61)}, now)
    assert not automation.due({**on, "window_from": 1, "window_to": 2}, {**never, "last_cycle_at": ago(600)}, now)       # an hour that is not allowed
    asked = {"last_cycle_at": ago(5), "run_requested_at": ago(1)}
    assert automation.due(automation.clean({}), asked, now) and automation.due(on, asked, now)                           # « now »: whatever the interval, and even when off
    assert not automation.due(automation.clean({}), {"last_cycle_at": ago(1), "run_requested_at": ago(5)}, now)           # a request already answered
    assert automation.next_at(automation.clean({}), never, now) is None


def test_only_what_is_wanted_and_waiting_is_run():
    todo = {"new_messages": 5, "without_vector": 0, "unread": 0, "unlinked": 0, "unplaced": 0, "topic_run": False}
    on = lambda **k: automation.clean({"enabled": True, **k})  # noqa: E731
    assert automation.stages_for(on(), todo) == ("conversations", "embeddings")
    assert automation.stages_for(on(vectors=False), todo) == ()                        # not wanted
    assert automation.stages_for(on(), {**todo, "new_messages": 0}) == ()               # nothing waiting
    assert automation.stages_for(on(positions=True), todo) == ("conversations", "embeddings")                  # no acknowledgement: no positions
    assert automation.stages_for(on(positions=True, positions_acknowledged=True), {**todo, "new_messages": 0, "unlinked": 3}) == ("claims",)
    assert "themes" not in automation.stages_for(on(themes=True), {**todo, "unplaced": 24}) and "themes" in automation.stages_for(on(themes=True), {**todo, "unplaced": 25})


def test_a_cycle_makes_the_conversations_and_vectors_but_reads_no_position_unless_asked(ingest_db, setup, ollama):
    settings, jobs = setup
    debate(ingest_db)
    ingest_db.execute("UPDATE messages SET sent_at = now() - interval '2 hours'")
    automation.save(ingest_db, {"enabled": True, "vectors": True})
    assert asyncio.run(tick(jobs, settings)) is True
    assert ingest_db.execute("SELECT count(*) FROM conversations").fetchone() == (1,) and ingest_db.execute("SELECT count(*) FROM conversation_embeddings").fetchone() == (1,)
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (0,) and not [r for r in ollama.requests if r[0] == "/api/chat"]       # no model asked what people think
    st = automation.state(ingest_db)
    assert st["last_cycle_at"] and st["last_result"]["servers"][0]["stages"] == ["conversations", "embeddings"] and st["last_result"]["servers"][0]["state"] == "done"
    assert asyncio.run(tick(jobs, settings)) is False                                  # the interval is not over


def test_with_the_acknowledgement_the_positions_are_read_in_small_batches(ingest_db, setup, ollama):
    settings, jobs = setup
    debate(ingest_db)
    ingest_db.execute("UPDATE messages SET sent_at = now() - interval '2 hours'")
    automation.save(ingest_db, {"enabled": True, "positions": True, "positions_acknowledged": True, "batch": 1})
    asyncio.run(tick(jobs, settings))
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (2,) and ingest_db.execute("SELECT count(*) FROM proposition_axis").fetchone()[0] >= 0
    assert automation.state(ingest_db)["last_result"]["servers"][0]["stages"] == ["conversations", "embeddings", "claims"]
    ingest_db.execute("UPDATE runtime_settings SET value = jsonb_set(value, '{last_cycle_at}', to_jsonb((now() - interval '2 hours')::text)) WHERE key = 'auto_analysis_state'")
    assert asyncio.run(tick(jobs, settings)) is True
    assert automation.state(ingest_db)["last_result"]["idle"] is True                  # nothing left: a cycle that does nothing, and says so


def test_somebody_who_asked_to_stop_is_never_read(ingest_db, setup, ollama):
    settings, jobs = setup
    debate(ingest_db)
    ingest_db.execute("UPDATE messages SET sent_at = now() - interval '2 hours'")
    privacy.stop_recording(ingest_db, BOB_ID)                                           # Bobby: stopped, what is held of him stays but is not read
    automation.save(ingest_db, {"enabled": True, "positions": True, "positions_acknowledged": True})
    asyncio.run(tick(jobs, settings))
    sent = " ".join(str(b["messages"]) for p, b in ollama.requests if p == "/api/chat")
    assert SAYS_B not in sent and "salaire minimum" in sent                              # Alice is read, Bobby is not


def test_a_person_can_ask_for_a_cycle_now_even_when_it_is_off(ingest_db, setup):
    settings, jobs = setup
    debate(ingest_db)
    ingest_db.execute("UPDATE messages SET sent_at = now() - interval '2 hours'")
    assert asyncio.run(tick(jobs, settings)) is False                                   # off: nothing
    automation.request_run(ingest_db)
    assert asyncio.run(tick(jobs, settings)) is True and ingest_db.execute("SELECT count(*) FROM conversations").fetchone() == (1,)
    assert asyncio.run(tick(jobs, settings)) is False                                   # the request was answered


def test_a_busy_analysis_is_never_disturbed_and_a_missing_model_is_said(ingest_db, setup, ollama):
    settings, jobs = setup
    debate(ingest_db)
    ingest_db.execute("UPDATE messages SET sent_at = now() - interval '2 hours'")
    automation.save(ingest_db, {"enabled": True})
    jobs._state["state"] = "running"
    assert asyncio.run(tick(jobs, settings)) is False and automation.state(ingest_db)["last_cycle_at"] is None
    jobs._state["state"] = "idle"
    ollama.models = []                                                                  # Ollama is there, the models are not
    assert asyncio.run(tick(jobs, settings)) is True
    result = automation.state(ingest_db)["last_result"]["servers"][0]
    assert result["state"] == "failed" and "ollama pull" in result["error"]            # said, and it waits for the next interval


def test_cancelling_an_automatic_cycle_does_not_start_the_next_server(setup, monkeypatch):
    settings, _ = setup
    monkeypatch.setattr(auto, "_guilds", lambda _conn: [111, 222])
    monkeypatch.setattr(automation, "pending", lambda *_args: {"new_messages": 1})
    monkeypatch.setattr(automation, "stages_for", lambda *_args: ("conversations",))
    started = []

    class CancelledJobs:
        embed_model = "bge-m3"

        def start(self, guild, stages, limit=None):
            started.append(guild)

        def wait(self):
            pass

        def status(self):
            return {"state": "cancelled", "error": None, "lines": []}

    result = asyncio.run(cycle(CancelledJobs(), settings))
    assert started == [111] and [server["state"] for server in result["servers"]] == ["cancelled"]


# --- the interface ------------------------------------------------------------------------------------------------------------


@pytest.fixture
def web(ingest_url, ingest_db, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def test_the_page_reads_and_saves_the_automatic_reading(web, ingest_db):
    debate(ingest_db)
    first = web.get("/api/automation").json()
    assert first["settings"]["enabled"] is False and first["next_at"] is None and first["pending"]["without_vector"] == 1 and first["pending"]["unread"] == 1 and first["timezone"]
    assert web.put("/api/automation", json={"enabled": True, "positions": True}).status_code == 422                 # without the acknowledgement
    saved = web.put("/api/automation", json={"enabled": True, "positions": True, "positions_acknowledged": True, "interval_minutes": 60, "batch": 5,
                                             "window_from": 22, "window_to": 6}).json()
    assert saved["settings"]["positions"] is True and saved["settings"]["interval_minutes"] == 60 and automation.load(ingest_db) == saved["settings"]
    assert saved["next_at"]
    asked = web.post("/api/automation/run").json()
    assert asked["state"]["run_requested_at"]
    for bad in ({"batch": 0}, {"window_from": 24}, {"window_to": 0}, {"interval_minutes": 0}):
        assert web.put("/api/automation", json=bad).status_code == 422


def test_it_needs_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert [c.get("/api/automation").status_code, c.put("/api/automation", json={}).status_code, c.post("/api/automation/run").status_code] == [401, 401, 401]
