"""The debates in the interface: the list, and the detail of one with its statistics and its checked claims (api/debates.py).

Level of proof: SIMULATED: the data comes from the real engine run against a fake Discord (the same as the other debate tests); the API is called with a test client."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from dindon import privacy
from dindon.api.main import create_app
from dindon.debate.claims import ClaimResult
from gateway_fixtures import BOB, CAROL
from synthetic import settings_for
from test_debate_bot import BOB_ID, CAROL_ID, World
from test_debate_checks import EVIDENCE, RESULT, FakeChecker, check, opened
from test_debate_stats import talk

PASSWORD = "correct horse"


def prepared(ingest_url, tmp_path):
    """A debate with two people, positions, a contradicted claim and a claim that nothing settles."""
    world = World(ingest_url, tmp_path, checker=FakeChecker(results=[RESULT, ClaimResult("La dette est sous les 50 % du PIB", "la dette est sous 50 %", "unverifiable", "no_source", None, 2, 0, "m")]))
    from dindon.db import connect

    with connect(ingest_url) as conn:
        conn.autocommit = True
        thread, debate = opened(world, conn)
        talk(world, thread, conn, BOB, "Le chômage est à 12 % en France et la dette est sous les 50 % du PIB, c'est sûr.")
        talk(world, thread, conn, CAROL, "Je ne suis pas d'accord avec toi, et je pense que les chiffres disent autre chose.")
        world.click(BOB_ID, thread, debate.id, "pos", "for")
        world.click(CAROL_ID, thread, debate.id, "pos", "against")
        check(world)
    return world, debate


@pytest.fixture
def api(ingest_url, tmp_path):
    prepared(ingest_url, tmp_path)
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def test_the_debates_need_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as anonymous:
        assert anonymous.get("/api/debates").status_code == 401 and anonymous.get("/api/debates/1").status_code == 401


def test_the_list_gives_each_debate_its_headline_figures_and_the_state_of_the_checks(api):
    answer = api.get("/api/debates").json()
    assert answer["checks"] == {"asked": "off", "mode": "off", "why_not": None, "model": "qwen3:14b", "search_services": [], "min_precision": 0.9, "measured_precision": None}
    [row] = answer["debates"]
    assert (row["participants"], row["messages"], row["claims"], row["status"]) == (2, 2, 2, "open") and row["final"] == {"for": 1, "unsure": 0, "against": 1, "witness": 0, "none": 0}


def test_the_detail_has_the_people_with_names_the_claims_with_their_sources_and_the_parity(api):
    [row] = api.get("/api/debates").json()["debates"]
    detail = api.get(f"/api/debates/{row['id']}").json()
    bob, carol = detail["participants"]
    assert (bob["name"], bob["position"], bob["messages"]) == ("Bobby", "for", 1) and (carol["position"], carol["name"]) == ("against", "carol")   # (her name is her user name: she has no display name)
    assert bob["key_message"]["excerpt"].startswith("Le chômage est à 12 %") and bob["claims"]["contradicted"] == 1
    contradicted, unverifiable = detail["claims"]
    assert contradicted["verdict"] == "contradicted" and contradicted["author_name"] == "Bobby"
    assert contradicted["sources"] == [{"url": EVIDENCE.url, "title": "Taux de chômage", "tier": "official", "stance": "contradicts", "quote": EVIDENCE.quote, "page_period": "T2 2026", "via": "searxng"}]
    assert unverifiable["verdict"] == "unverifiable" and unverifiable["reason"] == "no_source" and unverifiable["sources"] == []
    assert detail["parity"]["for"]["total"] == 2 and detail["messages_waiting_to_be_read"] == 1 and detail["corrections"] == {"posted": 0, "taken_back": 0}
    assert detail["verdicts"] == ["confirmed", "contradicted", "partly", "disputed", "likely_true", "likely_false", "unverifiable"]


def test_the_detail_says_how_the_debate_was_set_up_and_knows_nothing_of_a_timer_or_a_vote(api):
    [row] = api.get("/api/debates").json()["debates"]
    debate = api.get(f"/api/debates/{row['id']}").json()["debate"]
    assert {"status": "open", "close_reason": None, "in_thread": True, "verify": True, "quiet_seconds": 86_400, "context": None}.items() <= debate.items()
    assert not {"round", "max_rounds", "duration_seconds", "ends_at", "voting_ends_at"} & set(debate) and debate["started_at"] and debate["closed_at"] is None
    assert debate["thread_id"] and debate["guild_id"]                                                         # (what the page needs to link to the messages)


def test_a_debate_opened_from_an_axis_says_so_in_the_list_and_the_detail_and_a_free_one_does_not(ingest_url, tmp_path, ingest_db):
    world, _ = prepared(ingest_url, tmp_path)
    world.command(BOB_ID, topic="", axis="structure")
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        rows = client.get("/api/debates").json()["debates"]
        [from_axis] = [r for r in rows if r["axis"]]
        [free] = [r for r in rows if not r["axis"]]
        detail = client.get(f"/api/debates/{from_axis['id']}").json()["debate"]
    name, question, negative, positive = ingest_db.execute("SELECT name, question, negative_pole, positive_pole FROM axes WHERE code = 'structure'").fetchone()
    assert from_axis["axis"] == {"code": "structure", "name": name, "for": negative, "against": positive} and from_axis["topic"] == question   # (the question is the subject)
    assert detail["axis"] == from_axis["axis"] and free["axis"] is None


def test_somebody_who_asked_not_to_be_recorded_is_in_none_of_it_and_an_unknown_debate_is_a_404(api, ingest_db):
    [row] = api.get("/api/debates").json()["debates"]
    privacy.stop_recording(ingest_db, BOB_ID)
    detail = api.get(f"/api/debates/{row['id']}").json()
    assert [p["user_id"] for p in detail["participants"]] == [str(CAROL_ID)] and detail["claims"] == [] and "Bobby" not in str(detail)
    assert api.get("/api/debates/424242").status_code == 404


@pytest.mark.parametrize(("asked", "precision", "mode", "why"), [("observe", None, "observe", None), ("live", None, "answer", "DINDON_DEBATE_PRECISION"), ("live", 0.95, "live", None)])
def test_the_page_says_the_mode_that_the_bot_will_really_run_in_and_why_not_the_one_asked(ingest_url, tmp_path, asked, precision, mode, why):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), debate_checks=asked, debate_precision=precision, searxng_url="http://searxng:8080", factcheck_api_key="SECRET")
    with TestClient(create_app(settings, background=False)) as client:
        client.post("/api/login", json={"password": PASSWORD})
        checks = client.get("/api/debates").json()["checks"]
    assert checks["mode"] == mode and checks["asked"] == asked and (why is None or why in checks["why_not"]) and checks["search_services"] == ["factcheck", "searxng"]
    assert "SECRET" not in str(checks)                                                                      # the key is never sent to the page
