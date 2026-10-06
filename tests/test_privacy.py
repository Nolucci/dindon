"""The rights of the people recorded: the register, erasure, the files, the commands on Discord, the interface.

Level of proof: SIMULATED (invented people and payloads, a real PostgreSQL, a fake Discord REST). Nothing here has run on a real server.
"""
import asyncio
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from dindon import privacy
from dindon.api.main import create_app
from dindon.bot.privacy_commands import COMMAND, EPHEMERAL, Interactions, PrivacyService
from dindon.bot.runner import BotRunner, Writer
from gateway_fixtures import ALICE, BOB, CAROL, GUILD, guild_create, message_create
from synthetic import settings_for
from test_bot import create, event, flush, messages

ALICE_ID, BOB_ID, CAROL_ID = int(ALICE["id"]), int(BOB["id"]), int(CAROL["id"])
PASSWORD = "correct horse"


def talk(url, *, service=None):
    """A bot that has recorded a small exchange between three people."""
    runner = BotRunner([GUILD], Writer(url), batch_seconds=0, interactions=None if service is None else Interactions("t", "http://127.0.0.1:9", service))
    runner.handle(event("GUILD_CREATE", guild_create()))
    first = message_create(100, "Bonjour à tous", ALICE, timestamp="2026-10-02T19:00:00.000000+00:00")
    runner.handle(create(first))
    runner.handle(create(message_create(101, f"Salut Alice, tu as vu ça ? <@{CAROL_ID}>", BOB, reply_to=first, mentions=(CAROL,),
                                        timestamp="2026-10-02T19:00:05.000000+00:00")))
    runner.handle(create(message_create(102, "Oui je confirme", CAROL, timestamp="2026-10-02T19:00:10.000000+00:00")))
    assert flush(runner)
    return runner


def held(db, user_id):
    one = lambda q, *args: db.execute(q, args).fetchone()[0]  # noqa: E731
    return {"messages": one("SELECT count(*) FROM messages WHERE author_id = %s", user_id), "user": one("SELECT count(*) FROM users WHERE id = %s", user_id),
            "mentions": one("SELECT count(*) FROM mentions WHERE user_id = %s", user_id),
            "edges": one("SELECT count(*) FROM edges WHERE from_user_id = %s OR to_user_id = %s", user_id, user_id)}


# --- erasing -----------------------------------------------------------------------------------------------------------


def test_erasing_a_person_removes_them_and_what_was_made_from_them(ingest_db, ingest_url):
    talk(ingest_url)
    channel = ingest_db.execute("SELECT channel_id FROM messages LIMIT 1").fetchone()[0]
    conversation = ingest_db.execute("INSERT INTO conversations (channel_id, started_at, ended_at, message_count) VALUES (%s, now(), now(), 3) RETURNING id",
                                     (channel,)).fetchone()[0]
    ingest_db.execute("INSERT INTO conversation_messages SELECT %s, id FROM messages", (conversation,))
    counts = privacy.erase_person(ingest_db, CAROL_ID)
    assert counts["messages"] == 1 and counts["mentions"] == 1 and counts["conversations"] == 1
    assert set(messages(ingest_db)) == {100, 101}                                          # the others' messages stay
    assert held(ingest_db, CAROL_ID) == {"messages": 0, "user": 0, "mentions": 0, "edges": 0}
    assert ingest_db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0     # made from her words: gone, made again without her
    assert ingest_db.execute("SELECT status FROM privacy_subjects WHERE user_id = %s", (CAROL_ID,)).fetchone() == ("erased",)
    log = ingest_db.execute("SELECT action, detail FROM privacy_log").fetchall()
    assert log[0][0] == "erase" and "Oui je confirme" not in json.dumps(log)              # counts only, never a content


def test_what_others_quoted_of_an_erased_person_goes_too(ingest_db, ingest_url):
    talk(ingest_url)
    assert ingest_db.execute("SELECT reference_content FROM messages WHERE id = 101").fetchone()[0]
    privacy.erase_person(ingest_db, ALICE_ID)
    assert ingest_db.execute("SELECT reference_content, reference_author_id FROM messages WHERE id = 101").fetchone() == (None, None)


# --- not recording anymore -------------------------------------------------------------------------------------------


def test_a_person_in_the_register_is_not_recorded_again_by_an_import_a_catch_up_or_the_bot(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    privacy.erase_person(ingest_db, CAROL_ID)
    # 1. the live bot
    service = PrivacyService(ingest_url)
    service.refresh()
    runner = BotRunner([GUILD], Writer(ingest_url), batch_seconds=0, interactions=Interactions("t", "http://127.0.0.1:9", service))
    runner.handle(event("GUILD_CREATE", guild_create()))
    runner.handle(create(message_create(200, "Je reviens", CAROL, timestamp="2026-10-02T20:00:00.000000+00:00")))
    runner.handle(create(message_create(201, f"Carol, tu es là ? <@{CAROL_ID}>", BOB, mentions=(CAROL,), timestamp="2026-10-02T20:00:05.000000+00:00")))
    assert runner.status()["ignored_privacy"] == 1 and flush(runner)
    assert 200 not in messages(ingest_db) and 201 in messages(ingest_db)
    assert ingest_db.execute("SELECT count(*) FROM mentions WHERE user_id = %s", (CAROL_ID,)).fetchone()[0] == 0   # and her mention is not recorded
    assert ingest_db.execute("SELECT count(*) FROM users WHERE id = %s", (CAROL_ID,)).fetchone()[0] == 0
    # 2. the ingestion itself, which every path crosses (an export, a re-export, the catch-up): the same message in a file
    from dindon.ingest.loader import ingest_document
    from dindon.bot.adapter import build_document, digest

    document = build_document(runner.directory, GUILD, "200", [message_create(300, "Encore moi", CAROL, timestamp="2026-10-02T21:00:00.000000+00:00"),
                                                              message_create(301, "Et moi", ALICE, timestamp="2026-10-02T21:00:01.000000+00:00")])
    result = ingest_document(ingest_db, document, "export.json", digest(document))
    assert result.privacy_dropped == 1
    assert 300 not in messages(ingest_db) and 301 in messages(ingest_db)


def test_stopping_keeps_what_is_held_and_only_stops_the_recording(ingest_db, ingest_url):
    talk(ingest_url)
    answer = privacy.stop_recording(ingest_db, BOB_ID, reason="objection")
    assert answer["status"] == "stopped" and BOB_ID in privacy.blocked_ids(ingest_db)
    assert 101 in messages(ingest_db)                                                      # not erased
    privacy.erase_person(ingest_db, BOB_ID)
    assert 101 not in messages(ingest_db) and privacy.stop_recording(ingest_db, BOB_ID)["status"] == "erased"   # an erased person stays erased


def test_releasing_records_again_but_brings_nothing_back(ingest_db, ingest_url):
    runner = talk(ingest_url)
    privacy.erase_person(ingest_db, CAROL_ID)
    assert privacy.release(ingest_db, CAROL_ID) and not privacy.release(ingest_db, CAROL_ID)
    assert 102 not in messages(ingest_db)
    runner.handle(create(message_create(103, "Me revoilà", CAROL, timestamp="2026-10-02T20:00:00.000000+00:00")))
    assert flush(runner) and 103 in messages(ingest_db)


# --- the files ----------------------------------------------------------------------------------------------------------


def test_the_files_that_are_kept_are_rewritten_without_the_person(tmp_path):
    uid = "1000000000000000003"
    document = {"guild": {}, "users": [{"id": uid, "name": "carol"}, {"id": "9", "name": "x"}], "messages": [
        {"id": "1", "authorId": uid, "content": "secret"},
        {"id": "2", "authorId": "9", "content": "hello", "mentionedUserIds": [uid, "9"], "reactions": [{"userIds": [uid, "9"]}],
         "reference": {"authorId": uid, "content": "secret"}}]}
    (tmp_path / "archive" / "2026").mkdir(parents=True)
    path = tmp_path / "archive" / "2026" / "a.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    other = tmp_path / "archive" / "2026" / "b.json"
    other.write_text('{"messages": [], "users": []}', encoding="utf-8")
    result = privacy.scrub_files((tmp_path / "archive", tmp_path / "missing"), int(uid))
    assert result == {"files": 1, "messages": 1}
    text = path.read_text(encoding="utf-8")
    assert uid not in text and "secret" not in text and "hello" in text
    assert other.read_text(encoding="utf-8") == '{"messages": [], "users": []}'           # untouched


# --- seeing what is held, and keeping for a limited time -----------------------------------------------------------------


def test_the_person_can_see_what_is_held(ingest_db, ingest_url):
    talk(ingest_url)
    data = privacy.export_person(ingest_db, CAROL_ID)
    assert [m["content"] for m in data["messages"]] == ["Oui je confirme"]
    assert data["mentioned_in_messages"] == ["101"] and data["account"]["name"] == "carol" and data["register"] is None
    assert "Salut Alice" not in json.dumps(data)                                           # what others wrote is not handed over


def test_old_messages_are_deleted_after_the_retention_and_nothing_if_there_is_none(ingest_db, ingest_url):
    talk(ingest_url)
    ingest_db.execute("UPDATE messages SET sent_at = now() - interval '100 days' WHERE id IN (100, 101)")
    assert privacy.purge_older_than(ingest_db, 0) == {"messages": 0, "debates": 0} and len(messages(ingest_db)) == 3
    assert privacy.purge_older_than(ingest_db, 30) == {"messages": 2, "debates": 0} and set(messages(ingest_db)) == {102}


# --- the commands on Discord ----------------------------------------------------------------------------------------------


class Sent:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body, authorized, attachment=None):
        self.calls.append((method, path, body, authorized, attachment))
        return 200 if method in ("PUT", "PATCH") else 204

    def of(self, method):
        return [c for c in self.calls if c[0] == method]


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def interaction(user, sub, *, id="777", member=True, kind=2):
    who = {"id": str(user)}
    return {"id": id, "token": "tok", "type": kind, "application_id": "42", "data": {"name": "dindon", "options": [{"type": 1, "name": sub}]},
            **({"member": {"user": who}} if member else {"user": who})}


def button(user, custom_id, id="888"):
    return {"id": id, "token": "tok2", "type": 3, "application_id": "42", "data": {"custom_id": custom_id, "component_type": 2},
            "member": {"user": {"id": str(user)}}}


def commands(ingest_url, tmp_path):
    clock = Clock()
    service = PrivacyService(ingest_url, (tmp_path,), clock=clock)
    interactions = Interactions("tok", "http://api", service)
    sent = interactions._request = Sent()
    return interactions, service, sent, clock


def test_the_command_is_registered_and_info_answers_at_once(ingest_url, tmp_path):
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.register("42"))
    assert sent.calls[0][:2] == ("PUT", "/applications/42/commands") and sent.calls[0][2] == [COMMAND] and sent.calls[0][3] is True
    asyncio.run(interactions.answer(interaction(CAROL_ID, "info")))
    method, path, body, authorized, _ = sent.calls[-1]
    assert (method, path, authorized) == ("POST", "/interactions/777/tok/callback", False)   # the token is in the URL: no authorization
    assert body["type"] == 4 and body["data"]["flags"] == EPHEMERAL and "Ce qui est gardé" in body["data"]["content"] and "/dindon card" in body["data"]["content"]
    assert body["data"]["allowed_mentions"] == {"parse": []}
    count = len(sent.calls)
    asyncio.run(interactions.answer({"id": "1", "token": "t", "type": 2, "data": {"name": "autre"}, "member": {"user": {"id": "1"}}}))
    asyncio.run(interactions.answer({"id": "1", "token": "t", "type": 3, "data": {"custom_id": "autre:x:1"}, "member": {"user": {"id": "1"}}}))
    assert len(sent.calls) == count                                                           # not ours: no answer


def test_the_entry_point_of_the_activity_is_kept_when_the_activity_is_set_up(ingest_url, tmp_path):
    """The list of commands is replaced as a whole: without the entry point in it, Discord removes the Activity from the voice channels."""
    from dindon.bot.privacy_commands import ENTRY_POINT

    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    interactions.activity = True
    asyncio.run(interactions.register("42"))
    assert sent.calls[0][2] == [COMMAND, ENTRY_POINT]
    assert ENTRY_POINT["type"] == 4 and ENTRY_POINT["handler"] == 2 and interactions.registered      # Discord opens the Activity itself: no answer to give


def test_what_touches_the_database_is_acknowledged_first_then_answered(ingest_db, ingest_url, tmp_path):
    """Discord gives 3 seconds: the acknowledgement leaves before the work starts."""
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    order = []
    real = service.run
    service.run = lambda *a: (order.append(("work", [c[0] for c in sent.calls])), real(*a))[1]
    asyncio.run(interactions.answer(interaction(CAROL_ID, "mes-donnees")))
    assert order == [("work", ["POST"])]                                                      # the callback had already gone
    assert sent.calls[0][2] == {"type": 5, "data": {"flags": EPHEMERAL}}
    method, path, body, authorized, attachment = sent.calls[1]
    assert (method, path) == ("PATCH", "/webhooks/42/tok/messages/@original") and authorized is False
    assert "1 messages" in body["content"]
    name, raw = attachment
    assert name == f"dindon-{CAROL_ID}.json" and json.loads(raw)["messages"][0]["content"] == "Oui je confirme"


def test_stop_only_stops_and_reprendre_comes_back(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(interaction(CAROL_ID, "stop", member=False)))              # a private message has `user`, not `member`
    assert "ne sont plus enregistrés" in sent.of("PATCH")[-1][2]["content"] and 102 in messages(ingest_db)   # what was held stays
    assert str(CAROL_ID) in service.blocked and privacy.status_of(ingest_db, CAROL_ID) == "stopped"
    clock.now += 60
    asyncio.run(interactions.answer(interaction(CAROL_ID, "reprendre")))
    assert "de nouveau" in sent.of("PATCH")[-1][2]["content"] and str(CAROL_ID) not in service.blocked
    clock.now += 60
    asyncio.run(interactions.answer(interaction(CAROL_ID, "reprendre")))
    assert "rien à reprendre" in sent.of("PATCH")[-1][2]["content"]


def test_erasing_asks_first_and_only_the_person_can_confirm(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(interaction(CAROL_ID, "effacer")))
    ask = sent.calls[-1][2]["data"]
    assert "définitivement" in ask["content"] and 102 in messages(ingest_db)                  # nothing erased yet
    ids = [b["custom_id"] for b in ask["components"][0]["components"]]
    assert ids == [f"dindon:erase:{CAROL_ID}", f"dindon:cancel:{CAROL_ID}"]
    asyncio.run(interactions.answer(button(BOB_ID, ids[0])))                                  # somebody else clicks: ignored
    assert 102 in messages(ingest_db) and len(sent.calls) == 1
    before = len(sent.calls)
    asyncio.run(interactions.answer(button(CAROL_ID, ids[1])))                                # cancel
    assert sent.calls[-1][2]["data"]["content"].startswith("Annulé") and 102 in messages(ingest_db) and len(sent.calls) == before + 1
    asyncio.run(interactions.answer(button(CAROL_ID, ids[0])))                                # confirm
    assert sent.calls[-2][2]["type"] == 7 and sent.calls[-2][2]["data"]["components"] == []   # the buttons are gone at once
    assert "effacé" in sent.calls[-1][2]["content"] and 102 not in messages(ingest_db) and str(CAROL_ID) in service.blocked


def test_a_person_cannot_make_the_bot_work_in_a_loop(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(interaction(CAROL_ID, "stop")))
    asyncio.run(interactions.answer(interaction(CAROL_ID, "reprendre", id="778")))
    assert "Un instant" in sent.calls[-1][2]["data"]["content"] and str(CAROL_ID) in service.blocked
    asyncio.run(interactions.answer(interaction(BOB_ID, "stop", id="779")))                    # somebody else is not held back
    assert sent.calls[-1][2]["content"].startswith("C'est fait")


def test_a_file_too_big_for_discord_is_not_sent(ingest_db, ingest_url, tmp_path, monkeypatch):
    talk(ingest_url)
    monkeypatch.setattr("dindon.bot.privacy_commands.MAX_FILE_BYTES", 10)
    reply = PrivacyService(ingest_url).run(CAROL_ID, "mes-donnees")
    assert reply.file is None and "héberge" in reply.text


def test_the_engine_gives_the_events_to_the_commands_and_reads_the_register(ingest_db, ingest_url):
    service = PrivacyService(ingest_url)
    interactions = Interactions("tok", "http://api", service)
    sent = interactions._request = Sent()
    runner = BotRunner([GUILD], Writer(ingest_url), batch_seconds=0, interactions=interactions)

    async def go():
        runner.handle(event("READY", {"application": {"id": "42"}}))
        runner.handle(event("INTERACTION_CREATE", interaction(CAROL_ID, "info")))
        await asyncio.gather(*list(runner._tasks))
        privacy.stop_recording(ingest_db, ALICE_ID)
        await runner._beat()
    asyncio.run(go())
    assert [c[0] for c in sent.calls] == ["PUT", "POST"] and str(ALICE_ID) in service.blocked


def test_a_failing_command_still_answers_and_says_nothing_was_done(ingest_url, tmp_path, monkeypatch):
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    monkeypatch.setattr(privacy, "stop_recording", lambda *a, **k: 1 / 0)
    asyncio.run(interactions.answer(interaction(CAROL_ID, "stop")))
    assert "rien n'a été modifié" in sent.calls[-1][2]["content"]


def test_the_invite_asks_for_the_scope_of_the_commands():
    from dindon.api.invite import invite_url
    assert "scope=bot+applications.commands" in invite_url("42")


# --- the interface -----------------------------------------------------------------------------------------------------


@pytest.fixture
def client(ingest_url, ingest_db, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), retention_days=30)
    with TestClient(create_app(settings, background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        c.settings = settings
        yield c


def test_everything_needs_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        for method, path in (("get", "/api/privacy"), ("get", "/api/privacy/find?q=al"), ("post", "/api/privacy/erase"), ("get", "/api/privacy/export/1")):
            assert getattr(c, method)(path).status_code == 401


def test_the_person_in_charge_finds_stops_exports_and_erases(client, ingest_db, ingest_url):
    talk(ingest_url)
    found = client.get("/api/privacy/find", params={"q": "carol"}).json()
    assert [(p["user_id"], p["messages"], p["registered"]) for p in found] == [(str(CAROL_ID), 1, False)]
    assert client.get("/api/privacy/find", params={"q": "%%"}).json() == []                  # a wildcard is not a wildcard
    exported = client.get(f"/api/privacy/export/{CAROL_ID}")
    assert exported.headers["content-disposition"].endswith(f'dindon-{CAROL_ID}.json"') and exported.json()["messages"][0]["content"] == "Oui je confirme"
    assert client.post("/api/privacy/stop", json={"user_id": CAROL_ID, "reason": "demande"}).json()["status"] == "stopped"
    assert client.post("/api/privacy/erase", json={"user_id": CAROL_ID}).json()["messages"] == 1
    overview = client.get("/api/privacy").json()
    assert overview["retention_days"] == 30
    assert [(s["user_id"], s["status"]) for s in overview["subjects"]] == [(str(CAROL_ID), "erased")]
    assert [e["action"] for e in overview["log"]] == ["erase", "export", "stop"] or {e["action"] for e in overview["log"]} >= {"stop", "erase", "export"}
    assert client.post("/api/privacy/release", json={"user_id": CAROL_ID}).json() == {"user_id": str(CAROL_ID), "released": True}
    assert client.post("/api/privacy/erase", json={"user_id": 0}).status_code == 422
    assert client.post("/api/privacy/erase", json={"user_id": 10**30}).status_code == 422


def test_the_command_line(ingest_url, ingest_db, monkeypatch, capsys):
    from dindon.__main__ import main

    talk(ingest_url)
    monkeypatch.setenv("DATABASE_URL", ingest_url)
    for argv in (["privacy", "erase", str(CAROL_ID)], ["privacy", "list"], ["privacy", "export", str(ALICE_ID)], ["privacy", "stop"]):
        monkeypatch.setattr("sys.argv", ["dindon", *argv])
        try:
            main()
        except SystemExit as stop:
            assert stop.code == (2 if argv == ["privacy", "stop"] else 0)
    out = capsys.readouterr().out
    assert f"{CAROL_ID}\terased" in out and '"discord_id"' in out


def test_reactions_and_replies_of_a_person_who_asked_to_stop_are_left_out_of_the_totals(ingest_db, ingest_url):
    from dindon.bot.adapter import build_document, digest
    from dindon.ingest.loader import ingest_document

    runner = talk(ingest_url)
    privacy.erase_person(ingest_db, CAROL_ID)
    document = build_document(runner.directory, GUILD, "200", [message_create(400, "Un message", ALICE, timestamp="2026-10-02T22:00:00.000000+00:00")])
    document["messages"][0]["reactions"] = [{"emoji": "👍", "count": 2, "userIds": [str(CAROL_ID), str(BOB_ID)]}]
    document["users"] += [{"id": str(CAROL_ID), "name": "carol", "discriminator": "0000"}, {"id": str(BOB_ID), "name": "bob", "discriminator": "0000"}]
    document["emojis"] = [*document["emojis"], {"id": None, "name": "👍", "code": "thumbsup", "isAnimated": False, "imageUrl": "x"}]
    ingest_document(ingest_db, document, "export.json", digest(document))
    assert ingest_db.execute("SELECT count FROM reactions WHERE message_id = 400").fetchone() == (1,)
    assert ingest_db.execute("SELECT user_id FROM reaction_users WHERE message_id = 400").fetchall() == [(BOB_ID,)]


def test_a_reply_to_an_erased_message_keeps_no_copy_of_it(ingest_db, ingest_url):
    talk(ingest_url)
    ingest_db.execute("UPDATE messages SET reference_author_id = NULL WHERE id = 101")        # a copy whose author was not known
    assert ingest_db.execute("SELECT reference_content FROM messages WHERE id = 101").fetchone()[0]
    privacy.erase_person(ingest_db, ALICE_ID)
    assert ingest_db.execute("SELECT reference_content FROM messages WHERE id = 101").fetchone()[0] is None


def test_somebody_never_seen_can_be_stopped_by_their_id(client, ingest_db):
    found = client.get("/api/privacy/find", params={"q": "123456789012345678"}).json()
    assert found == [{"user_id": "123456789012345678", "name": "Identifiant inconnu de Dindon", "username": "", "messages": 0, "registered": False}]
    assert client.post("/api/privacy/stop", json={"user_id": "123456789012345678"}).json()["status"] == "stopped"
    assert client.get("/api/privacy/find", params={"q": "123456789012345678"}).json()[0]["registered"] is True
    assert client.get("/api/privacy/find", params={"q": "12345"}).json()[0]["user_id"] == "12345"
    assert client.get("/api/privacy/find", params={"q": "99999999999999999999"}).json() == []   # not an id


def test_reading_the_register_never_waits_for_a_long_command(ingest_url):
    """An erasure that rewrites many files holds the service's lock: the engine's heartbeat reads the register on its own connection."""
    service = PrivacyService(ingest_url)
    with service._lock:
        service.refresh()                                                    # would deadlock if it needed the same lock
    assert service.blocked == set()


def test_a_command_that_crashes_is_logged_without_what_was_asked(ingest_url, caplog):
    class Broken:
        service = PrivacyService(ingest_url)

        async def answer(self, data):
            raise RuntimeError("secret detail")

    runner = BotRunner([GUILD], Writer(ingest_url), interactions=Broken())

    async def go():
        runner.handle(event("INTERACTION_CREATE", {"type": 2}))
        await asyncio.gather(*list(runner._tasks), return_exceptions=True)
        await asyncio.sleep(0)
    with caplog.at_level("ERROR", logger="dindon.bot"):
        asyncio.run(go())
    assert "RuntimeError" in caplog.text and "secret detail" not in caplog.text


def card_interaction(asker, target, *, guild=GUILD, id="900"):
    return {"id": id, "token": "tokc", "type": 2, "application_id": "42", "guild_id": guild,
            "data": {"name": "dindon", "options": [{"type": 1, "name": "card", "options": [{"type": 6, "name": "pseudo", "value": str(target)}]}],
                     "resolved": {"users": {str(target): {"id": str(target), "avatar": "abc123"}}}},
            "member": {"user": {"id": str(asker)}}}


def test_info_says_how_the_data_is_managed_and_how_long_it_is_kept(ingest_url, tmp_path):
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(interaction(CAROL_ID, "info")))
    content = sent.calls[-1][2]["data"]["content"]
    for word in ("Ce qui est gardé", "Où et combien de temps", "rien n'est envoyé", "sans limite", "À quoi ça sert", "supprimez un message", "sauvegarde", "/dindon effacer"):
        assert word in content
    assert len(content) < 2000                                                                # Discord's limit for a message
    service.retention_days = 30
    clock.now += 60
    asyncio.run(interactions.answer(interaction(CAROL_ID, "info")))
    assert "30 jours" in sent.calls[-1][2]["data"]["content"] and "sans limite" not in sent.calls[-1][2]["data"]["content"]


def test_the_card_is_posted_in_the_channel_as_an_embed(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(card_interaction(CAROL_ID, BOB_ID)))
    assert sent.calls[0][2] == {"type": 5, "data": {"flags": 0}}                              # acknowledged for everybody (not ephemeral): the card is for the channel
    method, path, body, authorized, _ = sent.calls[1]
    assert (method, path) == ("PATCH", "/webhooks/42/tokc/messages/@original") and body["allowed_mentions"] == {"parse": []}
    embed = body["embeds"][0]
    assert "Profil" in embed["title"] and embed["thumbnail"]["url"].endswith(f"/avatars/{BOB_ID}/abc123.png?size=128") and "Page 1/4" in embed["footer"]["text"]
    text = embed["description"]
    assert "**1 messages**" in text and "02/10/2026" in text and "**Salons**\n#" in text and "\n\n" in text      # blocks with a blank line between them
    assert "fields" not in embed and len(text) < 1200                                                     # one readable block, not a wall
    row = body["components"][0]["components"]                                                  # the buttons that turn the pages: the current one is blue and off
    assert [c["label"] for c in row] == ["Profil", "Interactions", "Positions", "Contradictions"] and row[0]["disabled"] and not row[1]["disabled"]
    assert row[2]["custom_id"] == f"dindon:card:2:{BOB_ID}"


def _page(interactions, sent, asker, target, page, thumbnail="https://cdn.discordapp.com/avatars/1/x.png"):
    click = {"id": "901", "token": "tokp", "type": 3, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(asker)}},
             "data": {"custom_id": f"dindon:card:{page}:{target}"}, "message": {"embeds": [{"thumbnail": {"url": thumbnail}}]}}
    asyncio.run(interactions.answer(click))
    return sent.of("PATCH")[-1][2]


def test_the_pages_of_a_card_show_interactions_positions_and_the_contradictions_with_their_proof(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    one = lambda q, *a: ingest_db.execute(q, a).fetchone()[0]  # noqa: E731
    guild, channel = int(GUILD), one("SELECT channel_id FROM messages WHERE id = 101")
    axis = one("SELECT id FROM axes WHERE code = 'economie'")
    # Bob took the role « Libéral » (which expects the positive side of the axis) but what he says stands on the negative one
    ideology = one("INSERT INTO ideologies (code, name, kind) VALUES ('test-liberal', 'Libéral', 'famille') RETURNING id")
    ingest_db.execute("INSERT INTO ideology_axis_ranges VALUES (%s, %s, 0.4, 1)", (ideology, axis))
    ingest_db.execute("INSERT INTO ideologies (code, name, kind) VALUES ('test-social', 'Social', 'famille')")
    ingest_db.execute("INSERT INTO role_rules (match_type, pattern, kind, ideology_id) VALUES ('exact', 'liberal', 'ideologie', %s)", (ideology,))
    ingest_db.execute("INSERT INTO roles (id, guild_id, name, position) VALUES (8001, %s, 'Libéral', 1)", (guild,))
    ingest_db.execute("INSERT INTO member_roles VALUES (%s, %s, 8001)", (guild, BOB_ID))
    ingest_db.execute("INSERT INTO person_axis_scores (guild_id, user_id, axis_id, score, uncertainty, evidence_weight, n_propositions) VALUES (%s, %s, %s, -0.8, 0.1, 3, 3)",
                      (guild, BOB_ID, axis))
    proposition = one("INSERT INTO propositions (text, status) VALUES ('L''État doit réguler les prix', 'validated') RETURNING id")
    ingest_db.execute("INSERT INTO proposition_axis VALUES (%s, %s, -1, 1, true)", (proposition, axis))
    for at, stance in (("2026-10-02T20:00:00Z", -1), ("2026-10-03T20:00:00Z", 1)):               # he first was against, then for: a change of mind
        claim = one("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version)
                       VALUES (%s, %s, %s, 'opinion', 'veut réguler', %s, 0.9, %s, 'm', 'v') RETURNING id""", guild, BOB_ID, proposition, stance, at)
        ingest_db.execute("INSERT INTO claim_evidence VALUES (%s, 101, 'Salut Alice, tu as vu ça ?')", (claim,))
    ingest_db.execute("SELECT rebuild_edges(%s)", (guild,))

    interactions_page = _page(interactions, sent, CAROL_ID, BOB_ID, 1)["embeds"][0]
    assert "Interactions" in interactions_page["title"] and interactions_page["thumbnail"]["url"].endswith("x.png")      # the picture comes from the message itself
    assert "Alice" in interactions_page["description"]                                                                    # Bob answered Alice
    assert sent.calls[-2][2] == {"type": 6}                                                                                # acknowledged without a new message

    positions = _page(interactions, sent, CAROL_ID, BOB_ID, 2)["embeds"][0]
    text = json.dumps(positions, ensure_ascii=False)
    assert "Positions" in positions["title"] and "réguler les prix" in text and f"https://discord.com/channels/{guild}/{channel}/101" in text and "Salut Alice" in text
    assert "pas un verdict" in text

    contradictions = _page(interactions, sent, CAROL_ID, BOB_ID, 3)["embeds"][0]
    text = json.dumps(contradictions, ensure_ascii=False)
    assert "Contradictions" in contradictions["title"] and contradictions["color"] == 0xE74C3C
    assert "Libéral" in text and "en contradiction" in text and "Le rôle attend" in text                                   # the role against what he says
    assert "A changé d'avis" in text                                                                                      # the change of mind
    assert f"/channels/{guild}/{channel}/101" in text                                                                      # with the proof
    assert len(contradictions["description"]) < 3900 and "> [voir le message]" in contradictions["description"]            # the proof is a block quote

    privacy.stop_recording(ingest_db, BOB_ID, source="test")
    service.blocked.add(str(BOB_ID))
    gone = _page(interactions, sent, CAROL_ID, BOB_ID, 3)                                                                  # somebody who stopped: the next click shows nothing
    assert "rien à montrer" in gone["content"] and not gone.get("embeds")


def test_a_card_with_nothing_read_yet_says_so_instead_of_staying_empty(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    for page, word in ((2, "pas encore lu"), (3, "aucun rôle")):
        embed = _page(interactions, sent, CAROL_ID, BOB_ID, page)["embeds"][0]
        assert word in json.dumps(embed, ensure_ascii=False)
    assert _page(interactions, sent, CAROL_ID, BOB_ID, 3)["embeds"][0]["color"] == 0x2ECC71                               # green: nothing against


def test_a_card_is_refused_for_somebody_who_stopped_or_is_unknown_and_shows_the_axes_when_there_are_some(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    ingest_db.execute("INSERT INTO person_axis_scores (guild_id, user_id, axis_id, score, uncertainty, evidence_weight, n_propositions) "
                      "SELECT %s, %s, id, -0.7, 0.4, 2, 2 FROM axes WHERE code = 'economie'", (int(GUILD), BOB_ID))
    asyncio.run(interactions.answer(card_interaction(CAROL_ID, BOB_ID)))
    page = _page(interactions, sent, CAROL_ID, BOB_ID, 2)["embeds"][0]
    assert "Public" in json.dumps(page, ensure_ascii=False) and "pas un verdict" in json.dumps(page, ensure_ascii=False)
    clock.now += 60
    clock.now += 60
    asyncio.run(interactions.answer(card_interaction(CAROL_ID, 987654321)))                  # never seen
    assert "rien à montrer" in sent.of("PATCH")[-1][2]["content"] and not sent.of("PATCH")[-1][2].get("embeds")
    privacy.stop_recording(ingest_db, BOB_ID, source="test")
    service.blocked.add(str(BOB_ID))
    clock.now += 60
    asyncio.run(interactions.answer(card_interaction(CAROL_ID, BOB_ID)))                     # asked not to be recorded: no card
    assert "rien à montrer" in sent.of("PATCH")[-1][2]["content"]
    clock.now += 60
    asyncio.run(interactions.answer({**card_interaction(CAROL_ID, BOB_ID), "data": {"name": "dindon", "options": [{"type": 1, "name": "card"}]}}))   # no person given
    assert sent.calls[-1][2]["type"] == 4


def test_the_command_has_a_card_subcommand_that_asks_for_a_person():
    card = next(o for o in COMMAND["options"] if o["name"] == "card")
    assert card["options"][0]["type"] == 6 and card["options"][0]["required"]


# --- the bot is removed from a server ----------------------------------------------------------------------------------


def test_erasing_a_server_deletes_what_is_held_of_it_and_nothing_else(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    ingest_db.execute("INSERT INTO guilds (id, name) VALUES (555, 'Autre')")
    ingest_db.execute("INSERT INTO propositions (text) VALUES ('une proposition sans personne')")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "ici.json").write_text(json.dumps({"guild": {"id": GUILD}, "messages": [{"content": "Bonjour"}]}), encoding="utf-8")
    (archive / "ailleurs.json").write_text(json.dumps({"guild": {"id": "555"}, "messages": []}), encoding="utf-8")
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (9, 'stopped', 'x', 'test')")
    counts = privacy.erase_server(ingest_db, int(GUILD), file_directories=(archive,))
    assert counts["messages"] == 3 and counts["channels"] >= 1 and counts["files"] == 1 and counts["propositions"] == 1
    one = lambda q: ingest_db.execute(q).fetchone()[0]  # noqa: E731
    assert one("SELECT count(*) FROM messages") == 0 and one("SELECT count(*) FROM channels") == 0
    assert one("SELECT count(*) FROM users") == 0 and one("SELECT count(*) FROM edges") == 0      # the people seen nowhere else go too
    assert one("SELECT count(*) FROM guilds WHERE id = 555") == 1 and (archive / "ailleurs.json").exists() and not (archive / "ici.json").exists()
    assert one("SELECT count(*) FROM privacy_subjects") == 1                                        # the promises made to people stay
    log = ingest_db.execute("SELECT action, detail FROM privacy_log").fetchall()
    assert log[-1][0] == "erase_server" and "Bonjour" not in json.dumps(log)


def test_removed_from_a_server_the_bot_erases_it_only_when_asked_and_not_in_an_outage(ingest_db, ingest_url, tmp_path):
    async def scenario(erase):
        calls = []
        runner = BotRunner([GUILD], Writer(ingest_url), batch_seconds=0, erase_server=(lambda gid: calls.append(gid) or {}) if erase else None)
        runner.handle(event("GUILD_CREATE", guild_create()))
        runner.handle(event("GUILD_DELETE", {"id": GUILD, "unavailable": True}))      # an outage: not a removal
        runner.handle(event("GUILD_DELETE", {"id": "999"}))                           # a server that was never followed
        await asyncio.sleep(0.05)
        assert calls == []
        runner.handle(event("GUILD_DELETE", {"id": GUILD}))
        await asyncio.sleep(0.05)
        return calls

    assert asyncio.run(scenario(erase=False)) == []                # the setting is off: the data stays
    assert asyncio.run(scenario(erase=True)) == [int(GUILD)]
    assert settings_for(ingest_url, tmp_path).erase_on_removal is False       # off unless somebody asks
    talk(ingest_url)
    assert Writer(ingest_url).erase_server(int(GUILD), ())["messages"] == 3                  # what the bot really calls
    assert ingest_db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
