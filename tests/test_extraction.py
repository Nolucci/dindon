"""Stage 4-5: what each person claims, with proof. The model is a fake Ollama that says what each test writes; what is tested is what the code does
with its answer: it must not trust it. Level of proof: SIMULATED (invented messages, fake model, real PostgreSQL)."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from dindon import privacy
from dindon.analysis.conversations import build_conversations
from dindon.analysis.extraction import MAX_CHARS, PROMPT_VERSION, extract_claims, prepare, prepare_windows, validate
from dindon.analysis.ollama import Ollama, OllamaError
from dindon.api.main import create_app
from fake_ollama import FakeOllama
from gateway_fixtures import ALICE, BOB, CAROL, GUILD
from synthetic import settings_for
from test_analysis import NOW, Talk, ingest

GUILD_ID = int(GUILD)
ALICE_ID, BOB_ID = int(ALICE["id"]), int(BOB["id"])
PASSWORD = "correct horse"
SAYS_A = "il faut augmenter le salaire minimum pour tout le monde"
SAYS_B = "je suis contre, ça détruit des emplois dans les petites entreprises"
SAYS_C = "mdr bien sûr, comme si les patrons étaient des saints"


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=30)


def claim(participant="P1", proposition="L'État doit augmenter le salaire minimum", stance=1, kind="opinion", evidence=((1, SAYS_A),), confidence=0.9):
    return {"participant": participant, "proposition": proposition, "stance": stance, "kind": kind, "claim": "Défend une hausse du salaire minimum",
            "confidence": confidence, "evidence": [{"ref": r, "quote": q} for r, q in evidence]}


def debate(ingest_db):
    """Alice and Bob talk, then the conversation is made (it is over: its last message is old)."""
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS_A, ALICE), talk.say(SAYS_B, BOB), talk.say(SAYS_C, ALICE)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)


GOOD = [claim(), claim("P2", stance=-1, evidence=((2, "ça détruit des emplois dans les petites entreprises"),))]


def read(ingest_db, client, ollama, claims, **options):
    ollama.chat_handler = lambda body: {"claims": claims}
    return extract_claims(ingest_db, client, "qwen3:14b", "bge-m3", GUILD_ID, **options)


def test_the_model_is_given_the_people_as_numbers_and_the_messages_as_numbers(ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    path, body = [r for r in ollama.requests if r[0] == "/api/chat"][0]
    sent = body["messages"][-1]["content"]
    assert f"#1 P1: {SAYS_A}" in sent and f"#2 P2: {SAYS_B}" in sent
    assert "Alice" not in sent and "Bobby" not in sent and str(ALICE_ID) not in sent                    # no name, no id: only what is written


def test_a_claim_with_a_true_quote_of_its_author_is_kept_with_its_proof(ingest_db, client, ollama):
    debate(ingest_db)
    result = read(ingest_db, client, ollama, GOOD)
    assert (result["done"], result["claims"], result["refused"]) == (1, 2, 0)
    rows = ingest_db.execute("SELECT user_id, stance, kind, confidence, model, prompt_version, proposition_id FROM claims ORDER BY user_id").fetchall()
    assert [(r[0], r[1], r[2], r[4], r[5]) for r in rows] == [(ALICE_ID, 1, "opinion", "qwen3:14b", PROMPT_VERSION), (BOB_ID, -1, "opinion", "qwen3:14b", PROMPT_VERSION)]
    assert rows[0][6] == rows[1][6] and rows[0][6] is not None                                           # the same proposition, for and against
    proofs = ingest_db.execute("SELECT c.user_id, m.author_id, e.quote FROM claim_evidence e JOIN claims c ON c.id = e.claim_id JOIN messages m ON m.id = e.message_id").fetchall()
    assert {(u, a) for u, a, _ in proofs} == {(ALICE_ID, ALICE_ID), (BOB_ID, BOB_ID)}                    # every proof is a message of the person
    assert ingest_db.execute("SELECT count(*) FROM propositions").fetchone() == (1,)
    assert ingest_db.execute("SELECT status, created_by FROM propositions").fetchone() == ("proposed", "qwen3:14b")   # nothing is validated by the code


@pytest.mark.parametrize("bad, why", [
    (claim(evidence=((1, "une phrase que personne n'a écrite ici"),)), "a quote that is not in the message"),
    (claim(evidence=((2, SAYS_B),)), "a proof that is a message of somebody else"),
    (claim(evidence=((9, SAYS_A),)), "a message that does not exist"),
    (claim(evidence=()), "no proof at all"),
    (claim(participant="P9"), "a participant that does not exist"),
    (claim(stance=None), "an opinion without a position"),
    (claim(stance=2), "a position out of the scale"),
    (claim(kind="n'importe quoi"), "a kind that does not exist"),
    (claim(evidence=((1, "il"),)), "a quote too short to prove anything"),
], ids=lambda x: x if isinstance(x, str) else "")
def test_a_claim_that_does_not_hold_up_is_refused_and_counted(ingest_db, client, ollama, bad, why):
    debate(ingest_db)
    result = read(ingest_db, client, ollama, [*GOOD, bad])
    assert (result["claims"], result["refused"]) == (2, 1), why
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (2,)


def test_a_quote_is_found_whatever_the_case_the_spaces_and_the_punctuation_at_the_edges(ingest_db, client, ollama):
    debate(ingest_db)
    answer = [claim(evidence=((1, "  « IL FAUT   augmenter le salaire minimum… »"),))]
    assert read(ingest_db, client, ollama, answer)["claims"] == 1


def test_a_short_assent_does_not_become_a_political_position():
    r = prepare([(1, 10, "il a raison", None)])
    claim_about_vote = claim(proposition="Les électeurs doivent soutenir Marine Le Pen", evidence=((1, "il a raison"),))
    kept, refused = validate({"claims": [claim_about_vote]}, r)
    assert kept == [] and refused == 1


def test_promoting_a_discord_server_is_not_a_political_position():
    quote = "@Gaius Julius Squeesar boost le serv stp"
    read = prepare([(1, 10, quote, None)])
    proposed = claim(proposition="Il faut soutenir Squeezie", evidence=((1, quote),), confidence=0.5)
    kept, refused = validate({"claims": [proposed]}, read)
    assert kept == [] and refused == 1


def test_irony_and_questions_are_no_position(ingest_db, client, ollama):
    debate(ingest_db)
    answer = [claim(stance=1, kind="humour", evidence=((3, "comme si les patrons étaient des saints"),))]
    assert read(ingest_db, client, ollama, answer)["claims"] == 1
    assert ingest_db.execute("SELECT kind, stance, proposition_id FROM claims").fetchone() == ("humour", None, None)   # kept as a fact about the message, never as a position


def test_a_conversation_that_was_read_is_not_read_again(ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    calls = len([r for r in ollama.requests if r[0] == "/api/chat"])
    again = read(ingest_db, client, ollama, GOOD)
    assert again["done"] == 0 and len([r for r in ollama.requests if r[0] == "/api/chat"]) == calls
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (2,)


def test_reanalysis_preserves_a_reviewed_claim_without_duplicating_it(ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    ingest_db.execute("UPDATE claims SET review_status = 'confirmed' WHERE user_id = %s", (ALICE_ID,))
    ingest_db.execute("DELETE FROM claims WHERE review_status = 'auto'")
    ingest_db.execute("DELETE FROM conversation_extractions")
    result = read(ingest_db, client, ollama, GOOD)
    assert result["claims"] == 1
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (2,)


def test_a_conversation_with_nothing_in_it_is_recorded_so_that_it_is_not_read_again(ingest_db, client, ollama):
    debate(ingest_db)
    result = read(ingest_db, client, ollama, [])
    assert result["done"] == 1 and result["claims"] == 0
    assert ingest_db.execute("SELECT claims, refused FROM conversation_extractions").fetchone() == (0, 0)
    assert read(ingest_db, client, ollama, GOOD)["done"] == 0


def test_the_model_being_away_leaves_the_conversation_for_next_time_and_stops_after_three_in_a_row(ingest_db, client, ollama):
    debate(ingest_db)
    ollama.fail_chat = 1
    first = extract_claims(ingest_db, client, "qwen3:14b", "bge-m3", GUILD_ID)
    assert first["failed"] == 1 and first["done"] == 0
    assert ingest_db.execute("SELECT count(*) FROM conversation_extractions").fetchone() == (0,)        # not recorded: it will be read
    assert read(ingest_db, client, ollama, GOOD)["done"] == 1


def test_a_second_conversation_about_the_same_thing_joins_the_same_proposition_and_a_different_one_does_not(ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    talk = Talk(NOW - timedelta_hours(30))
    talk.next_id += 1000                                                                              # other messages, other ids
    ingest(ingest_db, [talk.say("quel temps magnifique pour une randonnée en montagne", CAROL), talk.say("oui, partons au lever du soleil demain matin", ALICE)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    ollama.chat_handler = lambda body: {"claims": [
        {"participant": "P1", "proposition": "L'État doit augmenter le salaire minimum", "stance": 1, "kind": "opinion", "claim": "x", "confidence": 0.5,
         "evidence": [{"ref": 1, "quote": "quel temps magnifique pour une randonnée"}]},
        {"participant": "P2", "proposition": "Il faut partir en randonnée au lever du soleil", "stance": 1, "kind": "opinion", "claim": "y", "confidence": 0.5,
         "evidence": [{"ref": 2, "quote": "partons au lever du soleil demain matin"}]}]}
    extract_claims(ingest_db, client, "qwen3:14b", "bge-m3", GUILD_ID)
    assert ingest_db.execute("SELECT count(*) FROM propositions").fetchone() == (2,)                    # the same words: the same proposition; other words: a new one


def timedelta_hours(n):
    from datetime import timedelta
    return timedelta(hours=n)


def test_erasing_a_person_erases_what_was_read_in_their_conversations(ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    privacy.erase_person(ingest_db, ALICE_ID)
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (0,)                          # hers, and those read in the conversations that she was in
    assert ingest_db.execute("SELECT count(*) FROM claim_evidence").fetchone() == (0,)
    assert ingest_db.execute("SELECT count(*) FROM conversation_extractions").fetchone() == (0,)        # the conversation will be read again, without her


def test_validate_works_on_the_text_that_the_model_was_given():
    rows = [(1, 10, "Je suis pour https://x.example/page la hausse", None), (2, 20, "moi contre la hausse", None), (3, 20, "  ", None)]
    r = prepare(rows)
    assert r.text == "#1 P1: Je suis pour la hausse\n#2 P2: moi contre la hausse" and r.people == {"P1": 10, "P2": 20}
    kept, refused = validate({"claims": [claim(evidence=((1, "Je suis pour la hausse"),)), "pas un objet", {"participant": "P1"}]}, r)
    assert len(kept) == 1 and refused == 2


def test_long_messages_are_sent_in_bounded_windows_with_their_source_refs():
    end = "il faut augmenter le salaire minimum pour tous"
    rows = [(1, 10, "début " + "mot " * 1800 + end, None), (2, 20, SAYS_B, None)]
    windows = prepare_windows(rows)
    assert len(windows) > 1 and all(len(window.text) <= MAX_CHARS for window in windows)
    assert "début" in windows[0].text and end in windows[-1].text
    assert windows[-1].message_ids[1] == 1 and windows[-1].message_ids[2] == 2


def test_the_last_window_can_produce_a_claim(ingest_db, client, ollama):
    talk = Talk()
    ending = "il faut augmenter le salaire minimum pour tout le monde"
    messages = [talk.say("mot " * 400) for _ in range(4)]
    source = talk.say("mot " * 350 + ending)
    ingest(ingest_db, [*messages, source, talk.say(SAYS_B, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)

    def respond(body):
        content = body["messages"][-1]["content"]
        return {"claims": [claim(evidence=((5, ending),))]} if ending in content else {"claims": []}

    ollama.chat_handler = respond
    result = extract_claims(ingest_db, client, "qwen3:14b", "bge-m3", GUILD_ID)
    assert result["done"] == 1 and result["claims"] == 1
    assert len([r for r in ollama.requests if r[0] == "/api/chat"]) > 1
    assert ingest_db.execute("SELECT message_id FROM claim_evidence").fetchone() == (int(source["id"]),)


def test_a_failed_later_window_leaves_the_whole_conversation_to_retry(ingest_db, client, monkeypatch):
    talk = Talk()
    ingest(ingest_db, [talk.say("mot " * 400) for _ in range(5)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    calls = 0

    def fail_later(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OllamaError("second window failed")
        return {"claims": []}

    monkeypatch.setattr(client, "chat_json", fail_later)
    result = extract_claims(ingest_db, client, "qwen3:14b", "bge-m3", GUILD_ID)
    assert result["failed"] == 1 and result["done"] == 0
    assert ingest_db.execute("SELECT count(*) FROM conversation_extractions").fetchone() == (0,)
    monkeypatch.setattr(client, "chat_json", lambda *args: {"claims": []})
    assert extract_claims(ingest_db, client, "qwen3:14b", "bge-m3", GUILD_ID)["done"] == 1


def test_a_conversation_alone_is_not_read(ingest_db, client, ollama):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS_A, ALICE)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    assert read(ingest_db, client, ollama, GOOD)["claims"] == 0


# --- the interface -------------------------------------------------------------------------------------------------------------


@pytest.fixture
def web(ingest_url, ingest_db, tmp_path, ollama):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    with TestClient(create_app(settings, background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def test_the_pages_show_the_positions_with_their_proof(web, ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    o = web.get("/api/positions", params={"guild": GUILD}).json()
    assert o["conversations"] == {"kept": 1, "read": 1} and o["claims"] == {"total": 2, "positions": 2, "people": 2, "refused": 0}
    assert [(p["people"], p["for"], p["against"], p["nuanced"]) for p in o["propositions"]] == [(2, 1, 1, 0)]
    pid = o["propositions"][0]["id"]
    detail = web.get(f"/api/positions/proposition/{pid}", params={"guild": GUILD}).json()
    assert [(p["id"], p["stance"]) for p in detail["people"]] == [(str(ALICE_ID), 1), (str(BOB_ID), -1)]            # ids as text (they do not fit a JavaScript number)
    assert detail["people"][0]["evidence"][0]["quote"] == SAYS_A and detail["people"][0]["evidence"][0]["channel"]
    mine = web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()
    assert [(p["proposition"], p["stance"]) for p in mine["positions"]] == [("L'État doit augmenter le salaire minimum", 1)]
    assert web.get("/api/positions/proposition/999999", params={"guild": GUILD}).status_code == 404


def test_a_bad_proposition_can_be_excluded_from_results_and_restored(web, ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    pid = web.get("/api/positions", params={"guild": GUILD}).json()["propositions"][0]["id"]
    route = f"/api/positions/proposition/{pid}"
    assert web.patch(route, params={"guild": GUILD}, json={"rejected": True}).json()["status"] == "rejected"
    assert web.get("/api/positions", params={"guild": GUILD}).json()["propositions"] == []
    assert web.get("/api/positions", params={"guild": GUILD, "rejected": True}).json()["propositions"][0]["status"] == "rejected"
    assert web.patch(route, params={"guild": GUILD}, json={"rejected": False}).json()["status"] == "proposed"
    assert len(web.get("/api/positions", params={"guild": GUILD}).json()["propositions"]) == 1


def test_the_latest_position_counts_and_the_change_is_shown(web, ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    cid = ingest_db.execute("SELECT id FROM claims WHERE user_id = %s", (ALICE_ID,)).fetchone()[0]
    ingest_db.execute("UPDATE claims SET stated_at = stated_at - interval '10 days' WHERE id = %s", (cid,))
    ingest_db.execute("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version)
                         SELECT guild_id, user_id, proposition_id, kind, 'a changé', -1, 0.8, now(), model, prompt_version FROM claims WHERE id = %s""", (cid,))
    mine = web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()["positions"][0]
    assert mine["stance"] == -1 and [h["stance"] for h in mine["history"]] == [1, -1]


def test_the_analysis_can_be_asked_to_read_the_positions_with_a_limit(web, ingest_db, ollama):
    debate(ingest_db)
    ollama.chat_handler = lambda body: {"claims": GOOD}
    assert web.post("/api/analysis", json={"guild": GUILD, "stages": ["claims"], "limit": 5}).status_code == 200
    web.app.state.analysis.wait(30)
    job = web.get("/api/analysis", params={"guild": GUILD}).json()["job"]
    assert job["state"] == "done" and any("positions retenues" in line for line in job["lines"])
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (2,)
    assert web.post("/api/analysis", json={"guild": GUILD, "stages": ["claims"], "limit": 0}).status_code == 422


def test_a_proposition_is_listed_under_the_theme_of_its_conversations(web, ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    cid = ingest_db.execute("SELECT id FROM conversations").fetchone()[0]
    first = ingest_db.execute("INSERT INTO topics (guild_id, label, origin) VALUES (%s, 'Salaires', 'discovered') RETURNING id", (GUILD_ID,)).fetchone()[0]
    second = ingest_db.execute("INSERT INTO topics (guild_id, label, origin, status, merged_into) VALUES (%s, 'Paye', 'discovered', 'merged', %s) RETURNING id", (GUILD_ID, first)).fetchone()[0]
    run = ingest_db.execute("INSERT INTO topic_runs (guild_id, method, model, parameters) VALUES (%s, 'test', 'x', '{}'::jsonb) RETURNING id", (GUILD_ID,)).fetchone()[0]
    ingest_db.execute("INSERT INTO topic_assignments (run_id, conversation_id, topic_id, similarity) VALUES (%s, %s, %s, 0.9)", (run, cid, second))
    p = web.get("/api/positions", params={"guild": GUILD}).json()["propositions"][0]
    assert (p["theme"], p["theme_id"]) == ("Salaires", first)                                             # a merged theme counts for the one it joined


def test_the_propositions_can_be_searched_filtered_and_sorted(web, ingest_db, client, ollama):
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    cid = ingest_db.execute("SELECT id FROM conversations").fetchone()[0]
    only = ingest_db.execute("INSERT INTO propositions (text, created_by) VALUES ('Planter des arbres en ville', 'test') RETURNING id").fetchone()[0]
    ingest_db.execute("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version, conversation_id)
                         VALUES (%s, %s, %s, 'opinion', 'x', 1, 0.9, now(), 'test', 'test', %s)""", (GUILD_ID, BOB_ID, only, cid))
    ask = lambda **params: web.get("/api/positions", params={"guild": GUILD, **params}).json()  # noqa: E731
    assert ask()["matching"] == 2 and {t["label"] for t in ask()["themes"]} == {"Sans thème"}
    assert [p["text"] for p in ask(q="ARBRES")["propositions"]] == ["Planter des arbres en ville"]                  # case does not matter
    assert [p["text"] for p in ask(q="forêts")["propositions"]] == []                                            # a word that is not there
    assert ask(q="alic")["matching"] == 1 and "salaire" in ask(q="alic")["propositions"][0]["text"]                # a name: the propositions where Alice takes a position
    assert ask(q="alice salaire")["matching"] == 1 and ask(q="alice arbres")["matching"] == 0                       # every word has to match
    assert ask(stance="against")["matching"] == 1 and ask(stance="nuanced")["matching"] == 0
    assert ask(sort="divided")["propositions"][0]["against"] == 1                                                   # for and against: the most divided first
    assert ask(q="%")["matching"] == 2 and ask(q="_")["matching"] == 2                                              # a wildcard is not one
    assert web.get("/api/positions", params={"guild": GUILD, "sort": "nope"}).status_code == 422
    assert web.get("/api/positions", params={"guild": GUILD, "stance": "nope"}).status_code == 422
