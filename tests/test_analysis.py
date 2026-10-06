"""The first stages of the analysis: conversations, triage, vectors, topics.

Level of proof: SIMULATED. The models are a fake Ollama (tools/fake_ollama.py: words hashed into vectors, names made from keywords), the
messages are invented. What a real model makes of real conversations is measured elsewhere (docs/fonctionnement.md), never here.
"""
from datetime import datetime, timedelta, timezone, UTC

import pytest

from dindon.analysis.conversations import build_conversations
from dindon.analysis.embeddings import embed_conversations
from dindon.analysis.ollama import Ollama, OllamaError
from dindon.analysis.themes import MIN_CONVERSATIONS, NotEnough, discover_themes, silhouette, spherical_kmeans
from dindon.bot.adapter import Directory, build_document, digest
from dindon.ingest.loader import GATEWAY_SOURCE, ingest_document
from fake_ollama import FakeOllama
from gateway_fixtures import ALICE, BOB, BOT, CAROL, GENERAL, GUILD, guild_create, member, message_create
from make_demo_server import World, write_exports
from dindon.ingest.loader import ingest_file

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
GUILD_ID = int(GUILD)


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=30)


def ingest(ingest_db, messages):
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    document = build_document(directory, GUILD, GENERAL, messages)
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)


class Talk:
    """Invented messages, one after another, with ids that grow."""

    def __init__(self, start=NOW - timedelta(days=2)):
        self.at, self.next_id = start, 7_000_000_000_000_000_000

    def say(self, text, author=ALICE, after_minutes=1, **kw):
        self.at += timedelta(minutes=after_minutes)
        self.next_id += 1
        return message_create(self.next_id, text, author, timestamp=self.at.isoformat(), **kw)


SAYS = "il faut taxer les riches pour financer les écoles"


def conversations(conn):
    return conn.execute("SELECT id, message_count, substantive_count, participants, kept, first_message_id FROM conversations ORDER BY started_at").fetchall()


# ---------------------------------------------------------------------------------------------
# Conversations and triage
# ---------------------------------------------------------------------------------------------


def test_a_silence_of_twenty_minutes_cuts_a_conversation(ingest_db):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB, 5), talk.say(SAYS, ALICE, 19),
                       talk.say(SAYS, BOB, 21), talk.say(SAYS, CAROL, 3)])
    result = build_conversations(ingest_db, GUILD_ID, now=NOW)
    assert result["made"] == 2 and result["messages"] == 5
    assert [(c[1], c[3]) for c in conversations(ingest_db)] == [(3, 2), (2, 2)]        # (messages, people)


def test_a_conversation_has_forty_messages_at_most(ingest_db):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS, ALICE if i % 2 else BOB) for i in range(45)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    assert [c[1] for c in conversations(ingest_db)] == [40, 5]


def test_bots_are_left_out_and_do_not_count_as_people(ingest_db):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say("annonce automatique du robot", {**BOT, "bot": True}, member_data=None), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    (only,) = conversations(ingest_db)
    assert only[1] == 2 and only[3] == 2                                                # two messages, two people: the bot is not one of them


def test_a_conversation_that_may_still_go_on_waits(ingest_db):
    talk = Talk(start=NOW - timedelta(minutes=30))
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB, 5), talk.say(SAYS, ALICE, 9)])   # the last one is 15 minutes old: someone may answer
    assert build_conversations(ingest_db, GUILD_ID, now=NOW)["made"] == 0
    assert build_conversations(ingest_db, GUILD_ID, now=NOW + timedelta(minutes=10))["made"] == 1


def test_running_it_again_only_makes_what_is_new_and_never_moves_a_message(ingest_db):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    before = conversations(ingest_db)
    assert build_conversations(ingest_db, GUILD_ID, now=NOW)["made"] == 0
    talk.at += timedelta(hours=3)
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB)])
    result = build_conversations(ingest_db, GUILD_ID, now=NOW)
    after = conversations(ingest_db)
    assert result["made"] == 1 and after[0] == before[0] and len(after) == 2             # the first one is the same row, untouched


def test_rebuilding_starts_again_and_forgets_what_was_computed_from_the_old_ones(ingest_db, client):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    embed_conversations(ingest_db, client, "bge-m3", GUILD_ID)
    assert ingest_db.execute("SELECT count(*) FROM conversation_embeddings").fetchone()[0] == 1
    build_conversations(ingest_db, GUILD_ID, now=NOW, rebuild=True)
    assert ingest_db.execute("SELECT count(*) FROM conversation_embeddings").fetchone()[0] == 0
    assert len(conversations(ingest_db)) == 1


@pytest.mark.parametrize("text, substantive", [
    ("mdr", False), ("oui", False), ("+1 ok", False), ("https://exemple.org/une-page-tres-longue-sans-rien-dire", False),
    ("<:rose:1234567890> <@123456> merci", False), (SAYS, True), ("Je ne suis pas d'accord avec toi", True),
])
def test_a_message_says_something_when_it_has_enough_words(ingest_db, text, substantive):
    assert ingest_db.execute("SELECT analysis_substantive(%s)", (text,)).fetchone()[0] is substantive


def test_a_conversation_is_kept_with_two_things_said_or_one_long(ingest_db):
    talk = Talk()
    long_text = " ".join([SAYS] * 8)
    ingest(ingest_db, [talk.say("mdr"), talk.say("oui", BOB),                                  # nothing said: not kept
                       talk.say(SAYS, after_minutes=60), talk.say("ok", BOB),                  # one thing said: not kept
                       talk.say(SAYS, after_minutes=60), talk.say(SAYS, BOB),                  # two: kept
                       talk.say(long_text, CAROL, after_minutes=60)])                          # one, but long: kept
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    assert [(c[2], c[4]) for c in conversations(ingest_db)] == [(0, False), (1, False), (2, True), (1, True)]


# ---------------------------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------------------------


def test_the_vectors_are_made_once_without_the_names_of_the_people(ingest_db, client, ollama):
    talk = Talk()
    ingest(ingest_db, [talk.say("@Bobby " + SAYS), talk.say("je réponds à Alice : " + SAYS + " https://exemple.org/x", BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    first = embed_conversations(ingest_db, client, "bge-m3", GUILD_ID)
    assert first == {"done": 1, "waiting": 1}
    assert embed_conversations(ingest_db, client, "bge-m3", GUILD_ID) == {"done": 0, "waiting": 0}   # already done: nothing again
    sent = " ".join(t for path, body in ollama.requests if path == "/api/embed" for t in body["input"])
    assert "@Bobby" not in sent and "exemple.org" not in sent and "Bobby" not in sent.split("Alice")[0]   # no mention, no link
    assert ingest_db.execute("SELECT count(*) FROM conversation_embeddings WHERE model = 'bge-m3'").fetchone()[0] == 1


def test_a_long_conversations_vector_includes_its_end(ingest_db, client, ollama):
    talk = Talk()
    ending = "une proposition écologique singulière à la fin"
    ingest(ingest_db, [talk.say("argument " * 170), talk.say("argument " * 170, BOB), talk.say("argument " * 170),
                       talk.say("argument " * 160 + ending, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    assert embed_conversations(ingest_db, client, "bge-m3", GUILD_ID)["done"] == 1
    requests = [body for path, body in ollama.requests if path == "/api/embed"]
    pieces = [piece for body in requests for piece in body["input"]]
    assert len(pieces) > 1 and all(len(piece) <= 6000 for piece in pieces)
    assert ending in pieces[-1] and requests[0]["truncate"] is False


def test_only_the_kept_conversations_get_a_vector(ingest_db, client):
    talk = Talk()
    ingest(ingest_db, [talk.say("mdr"), talk.say("oui", BOB), talk.say(SAYS, after_minutes=60), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    assert embed_conversations(ingest_db, client, "bge-m3", GUILD_ID)["done"] == 1


def test_a_model_that_is_not_installed_is_told_and_nothing_is_stored(ingest_db, client):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    with pytest.raises(OllamaError, match="not found"):
        embed_conversations(ingest_db, client, "no-such-model", GUILD_ID)
    assert ingest_db.execute("SELECT count(*) FROM conversation_embeddings").fetchone()[0] == 0


def test_an_ollama_that_is_not_running_is_told_clearly():
    with pytest.raises(OllamaError, match="ne répond pas"):
        Ollama("http://127.0.0.1:9", timeout=2).models()


# ---------------------------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def server(ingest_db, tmp_path):
    """An invented server of 2 500 messages, in channels that each talk about one subject (and three that talk about everything)."""
    world = World(seed=7, people=30)
    world.generate(2500, days=20, end=NOW - timedelta(days=3))
    for path in write_exports(world, tmp_path / "exports"):
        ingest_file(ingest_db, path)
    return world


def prepared(ingest_db, client, world):
    build_conversations(ingest_db, world.guild_id, now=NOW)
    embed_conversations(ingest_db, client, "bge-m3", world.guild_id)


def test_the_topics_follow_the_subjects_that_people_talk_about(ingest_db, client, server):
    prepared(ingest_db, client, server)
    result = discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b")
    assert result["topics"] >= 5 and result["assigned"] > 0.8 * result["conversations"]
    rows = ingest_db.execute(
        """SELECT a.topic_id, ch.name, count(*) FROM topic_assignments a JOIN conversations c ON c.id = a.conversation_id
           JOIN channels ch ON ch.id = c.channel_id GROUP BY 1, 2""").fetchall()
    themed = {c.name for c in server.channels if c.theme}
    by_topic: dict[int, dict[str, int]] = {}
    for topic, channel, n in rows:
        if channel in themed:
            by_topic.setdefault(topic, {})[channel] = n
    purity = sum(max(v.values()) for v in by_topic.values()) / sum(sum(v.values()) for v in by_topic.values())
    assert purity > 0.9, purity                                  # a topic is, almost always, one channel's subject (invented text: easy)


def test_every_proposal_is_a_proposal_and_says_how_it_was_made(ingest_db, client, server):
    prepared(ingest_db, client, server)
    discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=6)
    rows = ingest_db.execute("SELECT status, origin, label, keywords FROM topics").fetchall()
    assert rows and all(r[0] == "proposed" and r[1] == "discovered" and r[2] and r[3] for r in rows)
    method, model, parameters = ingest_db.execute("SELECT method, model, parameters FROM topic_runs").fetchone()
    assert "bge-m3" in model and parameters["chosen_by"] == "person" and parameters["k"] == 6


def test_a_new_run_replaces_the_proposals_and_never_touches_what_the_person_decided(ingest_db, client, server):
    prepared(ingest_db, client, server)
    discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=6)
    ids = [r[0] for r in ingest_db.execute("SELECT id FROM topics ORDER BY id").fetchall()]
    ingest_db.execute("UPDATE topics SET status = 'validated', label = 'Mon thème', validated_at = now() WHERE id = %s", (ids[0],))
    ingest_db.execute("UPDATE topics SET status = 'rejected' WHERE id = %s", (ids[1],))
    discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=7)
    kept = {r[0]: (r[1], r[2]) for r in ingest_db.execute("SELECT id, status, label FROM topics WHERE id = ANY(%s)", (ids[:2],)).fetchall()}
    assert kept == {ids[0]: ("validated", "Mon thème"), ids[1]: ("rejected", kept[ids[1]][1])}
    assert not ingest_db.execute("SELECT 1 FROM topics WHERE id = ANY(%s)", (ids[2:],)).fetchone()   # the other proposals are gone, with their links
    assert ingest_db.execute("SELECT count(*) FROM topics WHERE status = 'proposed'").fetchone()[0] == 7


def test_a_name_that_the_model_cannot_give_is_replaced_by_the_keywords(ingest_db, client, ollama, server):
    prepared(ingest_db, client, server)
    ollama.garbage_chat = 2                                        # the first topic: two answers that are not JSON
    ollama.fail_chat = 0
    result = discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=6)
    assert result["named_by_model"] == result["topics"] - 1
    labels = [r[0] for r in ingest_db.execute("SELECT label FROM topics ORDER BY id").fetchall()]
    assert sum("faux modèle" not in label for label in labels) == 1 and all(label for label in labels)


def test_the_model_only_sees_keywords_and_excerpts_without_mentions(ingest_db, client, ollama, server):
    prepared(ingest_db, client, server)
    discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=6)
    prompts = " ".join(body["messages"][-1]["content"] for path, body in ollama.requests if path == "/api/chat")
    assert "@" not in prompts and "Extraits de conversations" in prompts


def test_with_too_few_conversations_there_are_no_topics_and_it_is_said(ingest_db, client):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    embed_conversations(ingest_db, client, "bge-m3", GUILD_ID)
    with pytest.raises(NotEnough, match=str(MIN_CONVERSATIONS)):
        discover_themes(ingest_db, client, GUILD_ID, embed_model="bge-m3", name_model="qwen3:14b")
    assert ingest_db.execute("SELECT count(*) FROM topics").fetchone()[0] == 0


def test_the_grouping_finds_the_groups_that_are_there():
    import numpy as np

    rng = np.random.default_rng(0)
    centers = np.eye(1024)[:4]
    x = np.vstack([c + 0.015 * rng.standard_normal((40, 1024)) for c in centers])      # the noise is smaller than the distance between groups
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    labels, _ = spherical_kmeans(x, 4, rng)
    assert all(len(set(labels[i * 40:(i + 1) * 40])) == 1 for i in range(4)) and len(set(labels)) == 4
    assert silhouette(x, labels, rng) > 0.8


def test_a_mention_with_several_words_is_removed_whole(ingest_db, client, ollama):
    """"@Jean Dupont" is one mention: the first stages do not look at people, and a surname must not stay behind."""
    talk = Talk()
    jean = ({"id": "1000000000000000055", "username": "jean", "discriminator": "0", "global_name": "Jean Dupont", "avatar": None}, member("Jean Dupont"))
    ingest(ingest_db, [talk.say("@Jean Dupont " + SAYS, mentions=(jean,)), talk.say("@Jean Dupont je suis d'accord avec ça " + SAYS, BOB, mentions=(jean,))])
    build_conversations(ingest_db, GUILD_ID, now=NOW)
    embed_conversations(ingest_db, client, "bge-m3", GUILD_ID)
    sent = " ".join(t for path, body in ollama.requests if path == "/api/embed" for t in body["input"])
    assert "Dupont" not in sent and "Jean" not in sent and "taxer" in sent


def test_a_proposal_that_the_person_touched_survives_a_new_run_and_so_does_the_target_of_a_merge(ingest_db, client, server):
    prepared(ingest_db, client, server)
    discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=6)
    ids = [r[0] for r in ingest_db.execute("SELECT id FROM topics ORDER BY id").fetchall()]
    ingest_db.execute("UPDATE topics SET label = 'Renommé par moi', touched_at = now() WHERE id = %s", (ids[0],))          # renamed
    ingest_db.execute("UPDATE topics SET status = 'merged', merged_into = %s, touched_at = now() WHERE id = %s", (ids[2], ids[1]))   # 1 into 2
    ingest_db.execute("UPDATE topics SET touched_at = now() WHERE id = %s", (ids[2],))
    discover_themes(ingest_db, client, server.guild_id, embed_model="bge-m3", name_model="qwen3:14b", topics=6)
    rows = {r[0]: r[1:] for r in ingest_db.execute("SELECT id, status, label, merged_into FROM topics WHERE id = ANY(%s)", (ids[:3],)).fetchall()}
    assert rows[ids[0]][1] == "Renommé par moi" and rows[ids[0]][0] == "proposed"                    # kept, with its name
    assert rows[ids[1]] == ("merged", rows[ids[1]][1], ids[2]) and ids[2] in rows                      # the merge still points at a topic that exists
    assert ingest_db.execute("SELECT count(*) FROM topics WHERE status = 'proposed' AND touched_at IS NULL").fetchone()[0] == 6   # and 6 new proposals


def test_a_model_of_the_wrong_size_is_told_with_what_to_do(ingest_db, ollama):
    talk = Talk()
    ingest(ingest_db, [talk.say(SAYS), talk.say(SAYS, BOB)])
    build_conversations(ingest_db, GUILD_ID, now=NOW)

    class Short(Ollama):
        def embed(self, model, texts):
            return [[1.0] * 768 for _ in texts]

    with pytest.raises(OllamaError, match="1024"):
        embed_conversations(ingest_db, Short(ollama.url), "small-model", GUILD_ID)
