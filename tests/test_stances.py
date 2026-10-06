"""Stage 5 bis: the position of each claim is read again, narrowly. The model is a fake Ollama that answers by the words that it is shown; what is tested is what the
code does with the answer. Level of proof: SIMULATED (invented messages, fake model, real PostgreSQL)."""
import pytest

from dindon.analysis.ollama import Ollama
from dindon.analysis.stances import PROMPT_VERSION, verify_stances
from fake_ollama import FakeOllama
from test_extraction import ALICE_ID, BOB_ID, GUILD_ID, SAYS_A, SAYS_B, claim, debate, read


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=30)


def two_claims(ingest_db, client, ollama, alice_stance=-1, bob_stance=-1):
    """Alice writes what the proposition says (the first reading gave `alice_stance`), Bob writes the opposite (the first reading gave `bob_stance`)."""
    debate(ingest_db)
    read(ingest_db, client, ollama, [claim(stance=alice_stance), claim("P2", stance=bob_stance, evidence=((2, "ça détruit des emplois dans les petites entreprises"),))])


def answers(ollama, by_word):
    """The model says `relation` when the quote shown contains `word`."""
    def handler(body):
        shown = body["messages"][-1]["content"]
        for word, relation in by_word.items():
            if word in shown:
                return {"relation": relation}
        return {"relation": "nuance"}
    ollama.chat_handler = handler


def stances(db):
    return dict(db.execute("SELECT user_id, stance FROM claims").fetchall())


def test_the_position_follows_what_the_person_wrote_not_what_the_first_reading_said(ingest_db, client, ollama):
    two_claims(ingest_db, client, ollama)                                              # both are « against »: Alice's is wrong (she writes what the proposition says)
    answers(ollama, {"pour tout le monde": "accord", "détruit des emplois": "desaccord"})
    result = verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)
    assert (result["checked"], result["changed"]) == (2, 1)
    assert stances(ingest_db) == {ALICE_ID: 1, BOB_ID: -1}
    assert ingest_db.execute("SELECT stance_before, stance_check FROM claims WHERE user_id = %s", (ALICE_ID,)).fetchone() == (-1, PROMPT_VERSION)   # the first reading is kept


def test_the_model_sees_only_the_words_of_the_person_and_the_proposition(ingest_db, client, ollama):
    two_claims(ingest_db, client, ollama)
    answers(ollama, {})
    verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)
    body = [r for r in ollama.requests if r[0] == "/api/chat"][-1][1]
    shown = body["messages"][-1]["content"]
    assert "Proposition : « L'État doit augmenter le salaire minimum »" in shown and ("détruit des emplois" in shown or SAYS_A.split(",")[0] in shown)
    assert "Alice" not in str(body["messages"]) and "P1" not in shown                  # no name, no conversation: just the quote and the sentence
    assert body["format"]["properties"]["relation"]["enum"] == ["accord", "desaccord", "nuance", "aucune"]


def test_a_question_is_not_a_position_it_stays_with_its_proof_but_counts_for_nothing(ingest_db, client, ollama):
    two_claims(ingest_db, client, ollama, alice_stance=1)
    answers(ollama, {"pour tout le monde": "aucune", "détruit des emplois": "desaccord"})
    result = verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)
    assert result["questions"] == 1
    assert ingest_db.execute("SELECT kind, stance, proposition_id, stance_before FROM claims WHERE user_id = %s", (ALICE_ID,)).fetchone() == ("question", None, None, 1)
    assert ingest_db.execute("SELECT count(*) FROM claim_evidence").fetchone()[0] == 2        # the proof stays


def test_an_answer_that_is_not_in_the_shape_asked_leaves_the_first_reading_and_is_tried_again_later(ingest_db, client, ollama):
    two_claims(ingest_db, client, ollama, alice_stance=1)
    ollama.chat_handler = lambda body: {"claims": []}                                  # the model answers another question
    result = verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)
    assert (result["checked"], result["unclear"]) == (0, 2)
    assert ingest_db.execute("SELECT count(*) FROM claims WHERE stance_check IS NULL").fetchone()[0] == 2
    answers(ollama, {"pour tout le monde": "accord", "détruit des emplois": "desaccord"})
    assert verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)["checked"] == 2


def test_a_claim_is_read_once_and_a_confirmed_one_is_never_touched(ingest_db, client, ollama):
    two_claims(ingest_db, client, ollama)
    ingest_db.execute("UPDATE claims SET review_status = 'confirmed' WHERE user_id = %s", (ALICE_ID,))     # a person decided: the model does not overrule
    answers(ollama, {"pour tout le monde": "accord", "détruit des emplois": "desaccord"})
    assert verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)["checked"] == 1
    assert stances(ingest_db)[ALICE_ID] == -1
    calls = len([r for r in ollama.requests if r[0] == "/api/chat"])
    assert verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)["checked"] == 0 and len([r for r in ollama.requests if r[0] == "/api/chat"]) == calls


def test_the_scores_follow_the_corrected_positions(ingest_db, client, ollama):
    two_claims(ingest_db, client, ollama)
    ingest_db.execute("UPDATE propositions SET text = text")
    pid = ingest_db.execute("SELECT id FROM propositions").fetchone()[0]
    ingest_db.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence, is_validated) "
                      "SELECT %s, id, -1, 1, true FROM axes WHERE code = 'economie'", (pid,))
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    wrong = ingest_db.execute("SELECT score::float8 FROM person_axis_scores WHERE user_id = %s", (ALICE_ID,)).fetchone()[0]
    answers(ollama, {"pour tout le monde": "accord", "détruit des emplois": "desaccord"})
    verify_stances(ingest_db, client, "qwen3:14b", GUILD_ID)
    right = ingest_db.execute("SELECT score::float8 FROM person_axis_scores WHERE user_id = %s", (ALICE_ID,)).fetchone()[0]
    assert wrong > 0 > right                                                           # agreeing with a proposition that weighs toward « Public » is toward Public
