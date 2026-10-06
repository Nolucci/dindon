"""What is derived from a message goes when the message goes (deleted on Discord) or when its text changes. Level of proof: SIMULATED (invented messages, fake model, real PostgreSQL)."""
from datetime import UTC, datetime

import pytest

from dindon.analysis.conversations import build_conversations
from dindon.analysis.extraction import extract_claims
from dindon.analysis.ollama import Ollama
from dindon.bot.adapter import Directory, build_document, digest
from dindon.ingest.loader import GATEWAY_SOURCE, forget_messages, ingest_document
from fake_ollama import FakeOllama
from gateway_fixtures import ALICE, BOB, GENERAL, GUILD, guild_create
from test_analysis import NOW, Talk, ingest
from test_extraction import ALICE_ID, BOB_ID, GOOD, GUILD_ID, SAYS_A, debate, read


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=30)


def analysed(ingest_db, client, ollama):
    """Alice and Bob talk, their conversation is read: two positions with their quotes, and the scores that they make."""
    debate(ingest_db)
    read(ingest_db, client, ollama, GOOD)
    pid = ingest_db.execute("SELECT id FROM propositions").fetchone()[0]
    ingest_db.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence, is_validated) SELECT %s, id, -1, 1, true FROM axes WHERE code = 'economie'", (pid,))
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    assert ingest_db.execute("SELECT count(*) FROM claims").fetchone()[0] == 2
    assert ingest_db.execute("SELECT count(*) FROM person_axis_scores").fetchone()[0] == 2


def counts(db):
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("messages", "conversations", "claims", "claim_evidence", "conversation_embeddings", "person_axis_scores")}


def test_deleting_a_message_removes_what_was_derived_from_it_and_the_scores_that_it_made(ingest_db, client, ollama):
    analysed(ingest_db, client, ollama)
    before = counts(ingest_db)
    alice_message = ingest_db.execute("SELECT id FROM messages WHERE author_id = %s ORDER BY id LIMIT 1", (ALICE_ID,)).fetchone()[0]
    assert forget_messages(ingest_db, GUILD_ID, [alice_message]) == 1
    after = counts(ingest_db)
    assert after["messages"] == before["messages"] - 1
    assert after["conversations"] == 0 and after["claims"] == 0 and after["claim_evidence"] == 0       # the conversation held the message: what it gave is gone
    assert after["person_axis_scores"] == 0                                                             # and so are the scores that the positions made
    assert ingest_db.execute("SELECT count(*) FROM jobs WHERE kind = 'conversations'").fetchone()[0] >= 1   # the conversation is made again, without it


def test_deleting_a_message_takes_back_its_exchange_on_the_map(ingest_db):
    talk = Talk()
    first = talk.say("salut Bob", ALICE)
    ingest(ingest_db, [first, talk.say("salut Alice", BOB, reply_to=first)])
    assert ingest_db.execute("SELECT n FROM edges WHERE kind = 'reply'").fetchone()[0] == 1
    reply = ingest_db.execute("SELECT id FROM messages WHERE author_id = %s", (BOB_ID,)).fetchone()[0]
    assert forget_messages(ingest_db, GUILD_ID, [reply]) == 1
    assert ingest_db.execute("SELECT count(*) FROM edges WHERE kind = 'reply'").fetchone()[0] == 0   # the link had no other exchange: it is gone


def test_what_is_not_there_or_not_on_this_server_is_ignored(ingest_db):
    talk = Talk()
    ingest(ingest_db, [talk.say("un message", ALICE)])
    only = ingest_db.execute("SELECT id FROM messages").fetchone()[0]
    assert forget_messages(ingest_db, GUILD_ID, []) == 0
    assert forget_messages(ingest_db, GUILD_ID, [987654321]) == 0                                       # unknown
    assert forget_messages(ingest_db, GUILD_ID + 1, [only]) == 0                                        # another server
    assert ingest_db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def edit(ingest_db, payload: dict, **changes) -> None:
    """The same message again, as the exporter would bring it after an edit: a newer export, with the new text (or another change)."""
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    document = build_document(directory, GUILD, GENERAL, [{**payload, **changes}], exported_at=datetime(2026, 10, 3, 18, 0, tzinfo=UTC))
    ingest_document(ingest_db, document, "edit.json", digest(document))


def alices_first_payload():
    """The payload of the first message of the debate of `debate()` (same ids and times: the ones of a new Talk())."""
    return Talk().say(SAYS_A, ALICE)


def test_a_message_that_is_edited_loses_the_positions_made_from_its_old_text(ingest_db, client, ollama):
    analysed(ingest_db, client, ollama)
    edit(ingest_db, alices_first_payload(), content="finalement je ne dis plus rien sur ce sujet", edited_timestamp="2026-10-03T13:00:00+00:00")
    assert ingest_db.execute("SELECT content FROM messages WHERE author_id = %s ORDER BY id LIMIT 1", (ALICE_ID,)).fetchone()[0].startswith("finalement")
    assert counts(ingest_db)["claims"] == 0 and counts(ingest_db)["person_axis_scores"] == 0                  # the old words are no longer what the positions rest on


def test_a_change_that_is_not_the_text_keeps_everything(ingest_db, client, ollama):
    analysed(ingest_db, client, ollama)
    before = counts(ingest_db)
    edit(ingest_db, alices_first_payload(), pinned=True)                                                      # pinned: the text is the same
    assert counts(ingest_db) == before
