"""The reread (docs/regles-du-bot.md, « Relecture »): each position read again with the messages that came before it, and corrected when it is not right.

Level of proof: SIMULATED (invented messages, a fake model that says what each test writes, real PostgreSQL). What is tested is what the CODE does with the answer: nothing changes below the
certainty asked, what a person decided is never touched, a change is kept with what it was and can be undone, the scores are recomputed and checked. Whether a real model reads context well is
measured apart.
"""
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from dindon.analysis import reread
from dindon.analysis.job import AnalysisJobs
from dindon.analysis.ollama import Ollama
from dindon.analysis.reread import Item, RereadJobs, apply, audit_scores, decide, render, window
from dindon.api.main import create_app
from fake_ollama import FakeOllama
from gateway_fixtures import ALICE, BOB
from synthetic import settings_for
from test_extraction import ALICE_ID, BOB_ID, GOOD, GUILD_ID, SAYS_A, claim, debate, read

PASSWORD = "correct horse"


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=30)


def say(**fields):
    """What the model answers about one position: by default the position is right and the model sure of it."""
    return {"reasoning": "il défend la thèse", "own_opinion": True, "proposition_fits": True, "better_proposition": "", "stance": 1, "theme": 0, "certainty": 90, **fields}


def claims_of(db):
    return {r[0]: r for r in db.execute("SELECT user_id, stance, kind, proposition_id, review_status, stance_before, reread_version FROM claims").fetchall()}


def two_positions(ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    return {r[0]: r[1] for r in ingest_db.execute("SELECT user_id, id FROM claims")}


@pytest.fixture
def jobs(ingest_url, ollama, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    analysis = AnalysisJobs(settings, client=Ollama(ollama.url, timeout=30))
    return RereadJobs(settings, analysis)


def reread_now(jobs, guild=GUILD_ID, **options):
    jobs.start(guild, **options)
    jobs.wait(60)
    return jobs.status()


# --- the context ------------------------------------------------------------------------------------------------------------------


def test_the_position_is_read_with_the_messages_around_its_proof_anonymous_and_marked(ingest_db, client, ollama):
    ids = two_positions(ingest_db, client, ollama)
    lines = window(ingest_db, ids[BOB_ID])
    text, person = render(lines, BOB_ID)
    assert text.splitlines()[0].startswith("M1 | U1 | il faut augmenter le salaire minimum") and "EVIDENCE" in text and person == "U2"
    assert [line for line in text.splitlines() if "EVIDENCE" in line][0].startswith("M2 | U2 | je suis contre")
    for private in ("Alice", "Bobby", str(ALICE_ID), str(BOB_ID)):
        assert private not in text                                                                          # authors are U1, U2: never a name, never an id


def test_nothing_of_a_person_who_asked_not_to_be_recorded_is_in_the_context(ingest_db, client, ollama):
    ids = two_positions(ingest_db, client, ollama)
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (ALICE_ID,))
    text, _ = render(window(ingest_db, ids[BOB_ID]), BOB_ID)
    assert SAYS_A not in text and "augmenter le salaire minimum" not in text


# --- what is done with the answer -------------------------------------------------------------------------------------------------


def item(**changes):
    values = dict(claim_id=1, user_id=BOB_ID, kind="opinion", stance=-1, proposition_id=7, proposition="L'État doit augmenter le salaire minimum", context="M1 | U1 | ...",
                  person="U2", themes=[(10, "Économie"), (11, "Social")], current_theme=10)
    return Item(**{**values, **changes})


def test_a_model_that_is_not_sure_changes_nothing():
    d = decide(item(), say(stance=1, certainty=69))
    assert (d.verdict, d.changes) == ("uncertain", {})
    assert decide(item(), None).verdict == "uncertain" and decide(item(), {"certainty": "beaucoup"}).verdict == "uncertain"


def test_a_position_that_is_right_is_confirmed():
    assert decide(item(), say(stance=-1)).verdict == "confirmed"


def test_a_wrong_sense_is_corrected_and_says_what_it_was():
    d = decide(item(stance=-1), say(stance=1))
    assert (d.verdict, d.changes) == ("corrected", {"stance": [-1, 1]})


def test_what_is_not_the_opinion_of_the_person_stops_counting():
    for answer in (say(own_opinion=False), say(stance=None)):
        d = decide(item(), answer)
        assert d.changes == {"kind": ["opinion", "question"], "stance": [-1, None], "proposition_id": [7, None]}


def test_a_better_proposition_must_be_a_sentence_and_a_theme_must_be_one_that_was_offered():
    d = decide(item(), say(stance=-1, proposition_fits=False, better_proposition="L'État doit supprimer le salaire minimum pour embaucher"))
    assert d.new_proposition and "proposition_id" in d.changes and "stance" not in d.changes
    assert decide(item(), say(proposition_fits=False, better_proposition="Non")).changes == {"stance": [-1, 1]}                 # too short: not a proposition
    assert decide(item(), say(stance=-1, theme=2)).changes == {"theme": [10, 11]}
    assert decide(item(), say(stance=-1, theme=9)).changes == {} and decide(item(), say(stance=-1, theme=0)).changes == {}
    assert decide(item(), say(stance=-1, theme=1)).changes == {}                                                                # the one it already has


# --- the reread, from start to end --------------------------------------------------------------------------------------------------


def test_a_reread_corrects_what_is_wrong_keeps_what_it_was_and_recomputes_the_scores(ingest_db, client, ollama, jobs):
    ids = two_positions(ingest_db, client, ollama)                                                        # Alice and Bob are both read « for » the same proposition
    ingest_db.execute("UPDATE claims SET stance = -1 WHERE user_id = %s", (BOB_ID,))                      # (the first reading put Bob « against »: right)
    ingest_db.execute("UPDATE claims SET stance = -1 WHERE user_id = %s", (ALICE_ID,))                    # and Alice « against » too: wrong, she writes what the proposition says
    seen = []

    def handler(body):
        prompt = body["messages"][-1]["content"]
        seen.append(prompt)
        alice_is_evaluated = "PERSONNE ÉVALUÉE : U1" in prompt
        return say(stance=1) if alice_is_evaluated else say(stance=-1)

    ollama.chat_handler = handler
    status = reread_now(jobs)
    assert status["state"] == "done" and status["error"] is None
    assert status["counts"]["confirmed"] == 1 and status["counts"]["corrected"] == 1 and status["counts"]["stance_changed"] == 1
    rows = claims_of(ingest_db)
    assert rows[ALICE_ID][1] == 1 and rows[ALICE_ID][5] == -1 and rows[ALICE_ID][6] == reread.VERSION          # corrected, and what it was is kept
    assert rows[BOB_ID][1] == -1 and rows[BOB_ID][6] == reread.VERSION
    assert ingest_db.execute("SELECT verdict, changes FROM claim_rereads WHERE claim_id = %s", (ids[ALICE_ID],)).fetchone() == ("corrected", {"stance": [-1, 1]})
    assert all("Alice" not in p and "Bobby" not in p for p in seen)                                          # the model never gets a name
    context, people = ingest_db.execute("SELECT context, people FROM claim_rereads WHERE claim_id = %s", (ids[ALICE_ID],)).fetchone()
    assert "EVIDENCE" in context and "Alice" not in context and people == {"U1": str(ALICE_ID)}   # what was read is kept, as the model got it, with who is who
    assert status["counts"]["audit"]["different"] == 0                                                       # the scores were recomputed and checked


def test_what_a_person_decided_is_never_read_and_what_was_read_is_not_read_again_unless_asked(ingest_db, client, ollama, jobs):
    ids = two_positions(ingest_db, client, ollama)
    ingest_db.execute("UPDATE claims SET review_status = 'confirmed' WHERE id = %s", (ids[ALICE_ID],))
    ollama.chat_handler = lambda body: say(stance=1)
    first = reread_now(jobs)
    assert first["counts"].get("confirmed", 0) + first["counts"].get("corrected", 0) == 1                      # only Bob's
    again = reread_now(jobs)
    assert again["of"] == 0                                                                                   # the current method already read it
    forced = reread_now(jobs, force=True)
    assert forced["of"] == 1
    assert claims_of(ingest_db)[ALICE_ID][4] == "confirmed"


def test_a_reread_can_be_limited_to_one_person_and_to_a_few_positions(ingest_db, client, ollama, jobs):
    two_positions(ingest_db, client, ollama)
    ollama.chat_handler = lambda body: say(stance=1)
    assert reread_now(jobs, user_id=ALICE_ID)["of"] == 1
    assert reread_now(jobs, limit=1)["of"] == 1                                                              # Bob's: Alice's was read


def test_a_correction_is_undone_and_the_position_is_then_a_person_s(ingest_db, client, ollama, jobs):
    ids = two_positions(ingest_db, client, ollama)
    ollama.chat_handler = lambda body: say(stance=0)
    reread_now(jobs)
    assert claims_of(ingest_db)[ALICE_ID][1] == 0
    assert reread.undo(ingest_db, ids[ALICE_ID]) is True
    assert claims_of(ingest_db)[ALICE_ID][1] == 1 and claims_of(ingest_db)[ALICE_ID][4] == "confirmed"        # as it was, and protected
    assert reread.undo(ingest_db, ids[ALICE_ID]) is False                                                    # nothing left to undo


def test_a_new_proposition_gets_its_own_position_and_the_old_one_is_kept_in_the_record(ingest_db, client, ollama, jobs):
    ids = two_positions(ingest_db, client, ollama)
    ollama.chat_handler = lambda body: say(stance=1, proposition_fits=False, better_proposition="Les entreprises doivent pouvoir embaucher sans plancher de salaire")
    reread_now(jobs, user_id=ALICE_ID)
    before = claims_of(ingest_db)
    after = ingest_db.execute("SELECT proposition_id FROM claims WHERE id = %s", (ids[ALICE_ID],)).fetchone()[0]
    assert after != before[BOB_ID][3]
    assert ingest_db.execute("SELECT status, text FROM propositions WHERE id = %s", (after,)).fetchone() == ("proposed", "Les entreprises doivent pouvoir embaucher sans plancher de salaire")
    change = ingest_db.execute("SELECT changes FROM claim_rereads WHERE claim_id = %s", (ids[ALICE_ID],)).fetchone()[0]
    assert change["proposition_id"][1] == after and change["proposition_id"][0] == before[BOB_ID][3]


def test_a_theme_that_the_reread_gives_is_the_theme_that_the_positions_show(ingest_db, client, ollama):
    ids = two_positions(ingest_db, client, ollama)
    topic = ingest_db.execute("INSERT INTO topics (guild_id, label, origin, status) VALUES (%s, 'Économie', 'discovered', 'validated') RETURNING id", (GUILD_ID,)).fetchone()[0]
    run = ingest_db.execute("INSERT INTO reread_runs (guild_id) VALUES (%s) RETURNING id", (GUILD_ID,)).fetchone()[0]
    d = decide(item(claim_id=ids[ALICE_ID], themes=[(topic, "Économie")], current_theme=None), say(stance=-1, theme=1))
    apply(ingest_db, client, "bge-m3", "m", run, item(claim_id=ids[ALICE_ID], themes=[(topic, "Économie")], current_theme=None), d)
    assert ingest_db.execute("SELECT topic_id FROM claim_themes WHERE claim_id = %s", (ids[ALICE_ID],)).fetchall() == [(topic,)]
    assert reread.current_theme(ingest_db, ids[ALICE_ID]) == topic


# --- the scores, checked ------------------------------------------------------------------------------------------------------------


def test_the_audit_recomputes_each_score_apart_from_the_sql_and_notices_a_difference(ingest_db, client, ollama):
    two_positions(ingest_db, client, ollama)
    axis = ingest_db.execute("SELECT id FROM axes WHERE is_active ORDER BY id LIMIT 1").fetchone()[0]
    ingest_db.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence, is_validated) SELECT id, %s, 0.8, 0.9, true FROM propositions", (axis,))
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    clean = audit_scores(ingest_db, GUILD_ID)
    assert clean["checked"] == 2 and clean["different"] == 0
    ingest_db.execute("UPDATE person_axis_scores SET score = score + 0.2 WHERE user_id = %s", (ALICE_ID,))
    broken = audit_scores(ingest_db, GUILD_ID)
    assert broken["different"] == 1 and broken["examples"][0]["axis"] == axis
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    assert audit_scores(ingest_db, GUILD_ID)["different"] == 0


# --- from the interface ------------------------------------------------------------------------------------------------------------


@pytest.fixture
def me(ingest_url, ollama, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    with TestClient(create_app(settings, background=False)) as app:
        assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield app


def test_nothing_of_the_reread_is_available_without_the_session(ingest_url, ollama, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    with TestClient(create_app(settings, background=False)) as app:
        for method, path in (("get", "/api/reread"), ("post", "/api/reread"), ("post", "/api/reread/cancel"), ("get", "/api/reread/changes"), ("post", "/api/reread/undo/1")):
            assert getattr(app, method)(path).status_code == 401, path


def test_the_page_starts_a_reread_follows_it_lists_the_changes_and_undoes_one(me, ingest_db, client, ollama):
    two_positions(ingest_db, client, ollama)
    state = me.get("/api/reread").json()
    assert state["todo"] == {"positions": 2, "reread": 0, "waiting": 2} and state["job"]["state"] == "idle"
    ollama.chat_handler = lambda body: say(stance=0, reasoning="il hésite")
    assert me.post("/api/reread", json={}).status_code == 200
    me.app.state.reread.wait(60)
    done = me.get("/api/reread").json()
    assert done["job"]["state"] == "done" and done["todo"]["waiting"] == 0 and done["runs"][0]["state"] == "done" and done["runs"][0]["counts"]["corrected"] == 2
    changes = me.get("/api/reread/changes").json()["changes"]
    assert len(changes) == 2 and changes[0]["changes"]["stance"][1] == "nuance" and changes[0]["reason"] == "il hésite" and changes[0]["quotes"]
    assert "EVIDENCE" in changes[0]["context"] and set(changes[0]["people"].values()) == {"Alice", "Bobby"} and changes[0]["person_ref"] in changes[0]["people"]
    claim_id = changes[0]["claim"]
    assert me.post(f"/api/reread/undo/{claim_id}").status_code == 200
    assert me.post(f"/api/reread/undo/{claim_id}").status_code == 409
    assert me.post("/api/reread/undo/999999").status_code == 404
    assert [c["undone"] for c in me.get("/api/reread/changes").json()["changes"]].count(True) == 1


def test_a_reread_does_not_start_during_an_analysis_nor_an_analysis_during_a_reread(me, ingest_db, client, ollama):
    two_positions(ingest_db, client, ollama)
    release = __import__("threading").Event()
    ollama.chat_handler = lambda body: (release.wait(30), say())[1]
    assert me.post("/api/reread", json={}).status_code == 200
    assert me.post("/api/reread", json={}).status_code == 409
    assert me.post("/api/analysis", json={"stages": ["conversations"]}).status_code == 409
    me.post("/api/reread/cancel")
    release.set()
    me.app.state.reread.wait(60)
    assert me.get("/api/reread").json()["job"]["state"] in ("cancelled", "done")


# --- going back: finding the positions to keep as they were ---------------------------------------------------------------------------------


def corrected_run(me, ingest_db, client, ollama):
    two_positions(ingest_db, client, ollama)
    ollama.chat_handler = lambda body: say(stance=0, reasoning="il hésite")
    assert me.post("/api/reread", json={}).status_code == 200
    me.app.state.reread.wait(60)
    return me.get("/api/reread").json()["runs"][0]["id"]


def test_the_corrections_can_be_searched_by_words_person_and_kind_of_change(me, ingest_db, client, ollama):
    corrected_run(me, ingest_db, client, ollama)
    found = lambda **p: me.get("/api/reread/changes", params=p).json()  # noqa: E731
    assert found()["total"] == 2
    assert [c["person"] for c in found(q="bobby")["changes"]] == ["Bobby"]                                    # the name
    assert found(q="salaire minimum")["total"] == 2 and found(q="détruit des emplois")["total"] == 1       # the proposition, the quote
    assert found(q="rien de tout ça")["total"] == 0 and found(q="50%_")["total"] == 0                       # % and _ are not wildcards
    assert found(change="stance")["total"] == 2 and found(change="theme")["total"] == 0 and found(change="kind")["total"] == 0
    assert found(user=str(BOB_ID))["total"] == 1 and found(state="undone")["total"] == 0 and found(state="kept")["total"] == 2
    assert me.get("/api/reread/changes", params={"change": "rien"}).status_code == 422


def test_several_corrections_are_put_back_at_once_and_the_scores_follow(me, ingest_db, client, ollama):
    corrected_run(me, ingest_db, client, ollama)
    changes = me.get("/api/reread/changes").json()["changes"]
    ids = [c["claim"] for c in changes]
    answer = me.post("/api/reread/undo", json={"claims": [*ids, 999999]}).json()
    assert (answer["undone"], answer["skipped"]) == (2, 1)
    rows = claims_of(ingest_db)
    assert rows[ALICE_ID][1] == 1 and rows[BOB_ID][1] == -1 and rows[ALICE_ID][4] == rows[BOB_ID][4] == "confirmed"      # as they were, and now protected
    assert me.get("/api/reread/changes", params={"state": "undone"}).json()["total"] == 2
    assert me.post("/api/reread/undo", json={"claims": ids}).json()["undone"] == 0                            # nothing is undone twice
    assert me.post("/api/reread/undo", json={"claims": []}).status_code == 422


def test_a_whole_reread_is_rolled_back_except_what_a_later_reread_changed_again(me, ingest_db, client, ollama):
    run = corrected_run(me, ingest_db, client, ollama)
    ollama.chat_handler = lambda body: say(stance=-1)
    assert me.post("/api/reread", json={"force": True, "user": str(BOB_ID)}).status_code == 200
    me.app.state.reread.wait(60)
    assert claims_of(ingest_db)[BOB_ID][1] == -1                                                             # Bob's was corrected back by a second reread
    done = me.post(f"/api/reread/undo-run/{run}").json()
    assert (done["undone"], done["skipped"]) == (1, 1)                                                        # Alice's goes back; Bob's first correction is not the last change any more
    assert claims_of(ingest_db)[ALICE_ID][1] == 1
    assert me.post("/api/reread/undo-run/999999").status_code == 404


def test_a_reread_cannot_be_rolled_back_while_one_is_running(me, ingest_db, client, ollama):
    run = corrected_run(me, ingest_db, client, ollama)
    release = __import__("threading").Event()
    ollama.chat_handler = lambda body: (release.wait(30), say())[1]
    assert me.post("/api/reread", json={"force": True}).status_code == 200
    assert me.post(f"/api/reread/undo-run/{run}").status_code == 409
    me.post("/api/reread/cancel")
    release.set()
    me.app.state.reread.wait(60)
