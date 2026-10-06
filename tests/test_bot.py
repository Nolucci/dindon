"""The engine of the bot: Gateway events in, one ingestion out, with a real database.

Level of proof: SIMULATED (invented payloads, a fake Gateway, a real PostgreSQL and a real ingestion). Nothing here has run
against Discord.
"""
import asyncio
import dataclasses
import json
import logging
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
import uvicorn

from dindon.api.main import create_app
from dindon.bot.adapter import build_document, digest, Directory
from dindon.bot.gateway import GatewayEvent, GatewaySource
from dindon.bot.runner import BotRunner, Writer
from dindon.ingest.loader import InvalidExport, ingest_document
from fake_gateway import FakeGateway
from gateway_fixtures import ALICE, BOB, CAROL, EUROPEAN, GENERAL, GUILD, VOICE, guild_create, member, message_create
from synthetic import settings_for
from test_live import Page

ALICE_ID, BOB_ID = int(ALICE["id"]), int(BOB["id"])


def event(type: str, data: dict) -> GatewayEvent:
    return GatewayEvent("dispatch", type, data)


def create(payload: dict) -> GatewayEvent:
    return event("MESSAGE_CREATE", payload)


def runner_for(url: str, **options) -> BotRunner:
    runner = BotRunner([GUILD], Writer(url), batch_seconds=0, **options)
    runner.handle(event("GUILD_CREATE", guild_create()))
    return runner


def flush(runner: BotRunner, force: bool = True) -> bool:
    return asyncio.run(runner.flush(force))


def runs(db) -> int:
    return db.execute("SELECT count(*) FROM ingest_runs").fetchone()[0]


def messages(db) -> dict:
    return dict(db.execute("SELECT id, content FROM messages").fetchall())


def edges(db) -> dict:
    return {(f, t, k): (w, n) for f, t, k, w, n in db.execute("SELECT from_user_id, to_user_id, kind, weight, n FROM edges")}


def exchange(first=100):
    alice_says = message_create(first, "Vous avez vu ?", ALICE, member_data=member("Ali", (EUROPEAN,)),
                                timestamp="2026-10-02T19:00:00.000000+00:00")
    bob_replies = message_create(first + 1, "Oui !", BOB, reply_to=alice_says, timestamp="2026-10-02T19:00:05.000000+00:00")
    return alice_says, bob_replies


# ---------------------------------------------------------------------------------------------
# The first milestone, in miniature: a message, its reply, and the link that lights up
# ---------------------------------------------------------------------------------------------


def test_a_message_and_its_reply_reach_the_database_and_announce_the_link(ingest_db, ingest_url):
    listener = psycopg.connect(ingest_url, autocommit=True)
    listener.execute("LISTEN dindon")
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    runner.handle(create(alice_says))
    runner.handle(create(bob_replies))
    assert flush(runner)
    assert messages(ingest_db) == {100: "Vous avez vu ?", 101: "Oui !"}
    assert set(edges(ingest_db)) == {(BOB_ID, ALICE_ID, "reply")}
    announced = [json.loads(n.payload) for n in listener.notifies(timeout=2, stop_after=2)]
    listener.close()
    edge = next(e for e in announced if e["type"] == "edge")
    assert (edge["from"], edge["to"], edge["kind"], edge["guild"]) == (str(BOB_ID), str(ALICE_ID), "reply", GUILD)
    assert next(e for e in announced if e["type"] == "messages")["count"] == 2
    assert runner.status()["new"] == 2 and runner.status()["batches"] == 1
    ingest_db.execute("SELECT rebuild_edges()")  # the incremental links are what a rebuild gives
    assert set(edges(ingest_db)) == {(BOB_ID, ALICE_ID, "reply")}


# ---------------------------------------------------------------------------------------------
# Duplicates, late events, order
# ---------------------------------------------------------------------------------------------


def test_the_same_event_twice_changes_nothing(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    for payload in (alice_says, bob_replies, bob_replies):          # twice within the same window: it counts once
        runner.handle(create(payload))
    flush(runner)
    state = (messages(ingest_db), edges(ingest_db))
    ledger = runs(ingest_db)
    runner.handle(create(alice_says))                                 # the same two again, later: the very same document
    runner.handle(create(bob_replies))
    flush(runner)
    assert (messages(ingest_db), edges(ingest_db)) == state and runs(ingest_db) == ledger  # even the ledger is untouched
    assert runner.status()["duplicate_batches"] == 1
    runner.handle(create(bob_replies))                                # only one of them: another document, with nothing new in it
    flush(runner)
    assert (messages(ingest_db), edges(ingest_db)) == state and runner.status()["new"] == 2
    runner.handle(create(message_create(102, "autre chose", CAROL, timestamp="2026-10-02T19:01:00.000000+00:00")))
    runner.handle(create(alice_says))                                 # an old message next to a new one: only the new one counts
    flush(runner)
    assert len(messages(ingest_db)) == 3 and edges(ingest_db) == state[1] and runner.status()["new"] == 3


def test_a_late_announcement_does_not_erase_what_a_later_export_brought(ingest_db, ingest_url):
    """The nightly catch-up gave the message its reactions; the same event arrives again afterwards: they must stay."""
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    runner.handle(create(alice_says))
    flush(runner)
    # the catch-up: the same message, edited, with a reaction of Bob, exported later
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    export = build_document(directory, GUILD, GENERAL, [alice_says, bob_replies])  # Bob is in the tables because he reacted
    export["messages"], export["messageCount"] = [m for m in export["messages"] if m["id"] == "100"], 1
    export["exportedAt"] = "2026-10-03T03:00:00.000Z"
    export["messages"][0]["content"] = "Vous avez vu ? (modifié)"
    export["messages"][0]["timestampEdited"] = "2026-10-02T19:30:00.000Z"
    export["messages"][0]["reactions"] = [{"emoji": "🌹", "count": 1, "userIds": [str(BOB_ID)]}]
    export["emojis"] = [{"name": "🌹", "code": "rose", "isAnimated": False, "imageUrl": "https://example.org/rose.svg"}]
    ingest_document(ingest_db, export, "catch-up", "e" * 64)
    after_export = (messages(ingest_db), edges(ingest_db))
    assert after_export[0][100] == "Vous avez vu ? (modifié)" and (BOB_ID, ALICE_ID, "reaction") in after_export[1]
    runner.handle(create(alice_says))                                 # the announcement comes again, with the old text and no reaction
    runner.handle(create(message_create(200, "un autre", BOB, timestamp="2026-10-03T08:00:00.000000+00:00")))
    flush(runner)
    assert messages(ingest_db)[100] == "Vous avez vu ? (modifié)"
    assert (BOB_ID, ALICE_ID, "reaction") in edges(ingest_db) and ingest_db.execute("SELECT count(*) FROM reaction_users").fetchone()[0] == 1
    ingest_db.execute("SELECT rebuild_edges()")
    assert (BOB_ID, ALICE_ID, "reaction") in edges(ingest_db)


@pytest.mark.parametrize("order", ["reply first, parent in the next batch", "reverse order in one batch"])
def test_a_reply_that_arrives_before_its_parent_is_linked_all_the_same(ingest_db, ingest_url, order):
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    runner.handle(create(bob_replies))
    if order.startswith("reply"):
        flush(runner)
        assert set(edges(ingest_db)) == {(BOB_ID, ALICE_ID, "reply")}  # who was replied to travels with the reply
    runner.handle(create(alice_says))
    flush(runner)
    assert set(messages(ingest_db)) == {100, 101} and set(edges(ingest_db)) == {(BOB_ID, ALICE_ID, "reply")}
    assert edges(ingest_db)[(BOB_ID, ALICE_ID, "reply")][1] == 1
    ingest_db.execute("SELECT rebuild_edges()")
    assert edges(ingest_db)[(BOB_ID, ALICE_ID, "reply")][1] == 1


# ---------------------------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------------------------


def test_a_burst_leaves_as_one_document_per_channel(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    before = runs(ingest_db)
    for number in range(50):
        runner.handle(create(message_create(1000 + number, f"message {number}", ALICE if number % 2 else BOB)))
    runner.handle(create(message_create(2000, "ailleurs", ALICE, channel_id=VOICE)))
    flush(runner)
    assert runs(ingest_db) - before == 2 and len(messages(ingest_db)) == 51
    assert runner.status()["batches"] == 2 and runner.status()["waiting"] == 0


def test_a_big_burst_is_cut_in_documents_of_a_given_size_in_order(ingest_db, ingest_url):
    runner = runner_for(ingest_url, max_batch=100)
    before = runs(ingest_db)
    for number in range(250):
        runner.handle(create(message_create(5000 + number, f"m{number}", ALICE)))
    flush(runner)
    assert runs(ingest_db) - before == 3 and len(messages(ingest_db)) == 250
    sizes = [r[0] for r in ingest_db.execute("SELECT message_count FROM ingest_runs ORDER BY id")][-3:]
    assert sizes == [100, 100, 50]


def test_what_is_not_due_yet_waits_for_its_window():
    clock = [0.0]
    runner = BotRunner([GUILD], lambda doc, sha: None, batch_seconds=0.3, clock=lambda: clock[0])
    runner.handle(event("GUILD_CREATE", guild_create()))
    runner.handle(create(message_create(1, "x")))
    assert runner.next_wait(0.0) == pytest.approx(0.3)
    clock[0] = 0.1
    assert asyncio.run(runner.flush()) is True and runner.status()["waiting"] == 1   # not due: nothing written
    assert runner.next_wait(0.2) == pytest.approx(0.1) and runner.next_wait(0.5) == 0
    runner2 = BotRunner([GUILD], lambda doc, sha: None, clock=lambda: 0.0)
    assert runner2.next_wait(0.0) is None


# ---------------------------------------------------------------------------------------------
# What is not followed, not known, or not understood
# ---------------------------------------------------------------------------------------------


def test_other_servers_and_private_messages_are_ignored_without_a_trace(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    runner.handle(event("GUILD_CREATE", guild_create("777")))
    runner.handle(create(message_create(1, "ailleurs", guild_id="777", channel_id="200")))
    private = message_create(2, "en privé", channel_id="55")
    del private["guild_id"]
    runner.handle(create(private))
    flush(runner)
    assert runner.status()["ignored_not_followed"] == 2 and runner.status()["received"] == 0
    assert ingest_db.execute("SELECT count(*) FROM guilds").fetchone()[0] == 0 and runs(ingest_db) == 0


def test_a_channel_that_is_not_known_is_skipped_and_nothing_is_invented(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    runner.handle(create(message_create(1, "dans le vide", channel_id="424242")))
    runner.handle(create(message_create(2, "ici", channel_id=GENERAL)))
    flush(runner)
    assert runner.status()["skipped_unknown_channel"] == 1 and set(messages(ingest_db)) == {2}
    assert ingest_db.execute("SELECT count(*) FROM channels WHERE id = 424242").fetchone()[0] == 0


def edited(payload: dict, text: str) -> dict:
    return {**payload, "content": text, "edited_timestamp": "2026-10-02T19:05:00.000000+00:00"}


def test_an_edit_replaces_the_text_of_a_message_that_is_already_stored(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, _ = exchange()
    runner.handle(create(alice_says))
    flush(runner)
    runner.handle(event("MESSAGE_UPDATE", edited(alice_says, "Vous avez vu ça ?")))
    flush(runner)
    assert messages(ingest_db) == {100: "Vous avez vu ça ?"}
    assert runner.status()["edited"] == 1


def test_an_edit_of_a_message_that_is_not_written_yet_just_changes_what_is_written(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, _ = exchange()
    runner.handle(create(alice_says))
    runner.handle(event("MESSAGE_UPDATE", edited(alice_says, "corrigé avant d'être enregistré")))
    flush(runner)
    assert messages(ingest_db) == {100: "corrigé avant d'être enregistré"}


def test_the_preview_of_a_link_is_not_an_edit(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, _ = exchange()
    runner.handle(create(alice_says))
    flush(runner)
    runner.handle(event("MESSAGE_UPDATE", {"id": "100", "channel_id": GENERAL, "guild_id": GUILD, "embeds": [{"url": "https://exemple.org"}]}))   # no author, no text
    flush(runner)
    assert messages(ingest_db) == {100: "Vous avez vu ?"} and runner.status()["edits_ignored"] == 1 and runner.status()["edited"] == 0


def test_a_deletion_removes_the_message_its_link_and_what_was_derived_from_it(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    runner.handle(create(alice_says))
    runner.handle(create(bob_replies))
    flush(runner)
    assert edges(ingest_db)
    runner.handle(event("MESSAGE_DELETE", {"id": "101", "channel_id": GENERAL, "guild_id": GUILD}))
    flush(runner)
    assert set(messages(ingest_db)) == {100} and not edges(ingest_db)                      # Bob's reply is gone, and the link that it made
    runner.handle(event("MESSAGE_DELETE_BULK", {"ids": ["100", "555"], "channel_id": GENERAL, "guild_id": GUILD}))   # (555 was never stored)
    flush(runner)
    assert messages(ingest_db) == {} and runner.status()["deleted"] == 3


def test_a_message_deleted_before_it_is_written_never_is(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, _ = exchange()
    runner.handle(create(alice_says))
    runner.handle(event("MESSAGE_DELETE", {"id": "100", "channel_id": GENERAL, "guild_id": GUILD}))
    assert runner.status()["waiting"] == 0
    flush(runner)
    assert messages(ingest_db) == {}


def test_edits_and_deletions_wait_for_the_database_and_are_not_lost(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    runner.handle(create(alice_says))
    runner.handle(create(bob_replies))
    flush(runner)
    good_writer = runner._ingest
    runner._ingest = Writer("postgresql://dindon:wrong@127.0.0.1:9/dindon")                  # the database is away
    runner.handle(event("MESSAGE_UPDATE", edited(alice_says, "modifié")))
    runner.handle(event("MESSAGE_DELETE", {"id": "101", "channel_id": GENERAL, "guild_id": GUILD}))
    assert flush(runner) is False and runner.edits and runner.deleted                         # they wait
    runner._ingest, runner._retry_at = good_writer, 0.0                                       # it is back
    assert flush(runner) is True and not runner.edits and not runner.deleted
    assert messages(ingest_db) == {100: "modifié"}


def test_reactions_are_not_received_and_not_applied(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    alice_says, _ = exchange()
    runner.handle(create(alice_says))
    flush(runner)
    state = (messages(ingest_db), edges(ingest_db), runs(ingest_db))
    runner.handle(event("MESSAGE_REACTION_ADD", {"message_id": "100", "channel_id": GENERAL, "guild_id": GUILD, "user_id": str(BOB_ID)}))
    flush(runner)
    assert (messages(ingest_db), edges(ingest_db), runs(ingest_db)) == state


def test_one_strange_message_does_not_hold_up_the_others(ingest_db, ingest_url):
    runner = runner_for(ingest_url)
    strange = message_create(2, "bizarre")
    del strange["author"]                      # the adapter cannot read this one
    runner.handle(create(message_create(1, "bon")))
    runner.handle(create(strange))
    runner.handle(create(message_create(3, "bon aussi")))
    assert flush(runner)
    assert set(messages(ingest_db)) == {1, 3} and runner.status()["rejected"] == 1 and runner.status()["waiting"] == 0


def test_a_message_that_the_ingestion_refuses_is_isolated_too(ingest_db, ingest_url):
    writer = Writer(ingest_url)

    def picky(document, sha):
        if any(m["id"] == "2" for m in document["messages"]):
            raise InvalidExport("refused")
        return writer(document, sha)

    runner = BotRunner([GUILD], picky, batch_seconds=0)
    runner.handle(event("GUILD_CREATE", guild_create()))
    for number in (1, 2, 3):
        runner.handle(create(message_create(number, f"m{number}")))
    assert flush(runner)
    assert set(messages(ingest_db)) == {1, 3} and runner.status()["rejected"] == 1


# ---------------------------------------------------------------------------------------------
# The database goes away
# ---------------------------------------------------------------------------------------------


def test_when_the_database_is_away_the_messages_wait_and_are_written_once_it_is_back(ingest_db, ingest_url):
    writer = Writer(ingest_url)
    failures = [2]

    def flaky(document, sha):
        if failures[0] > 0:
            failures[0] -= 1
            raise psycopg.OperationalError("connection refused")
        return writer(document, sha)

    clock = [0.0]
    runner = BotRunner([GUILD], flaky, batch_seconds=0, retry_seconds=(1, 5), clock=lambda: clock[0])
    runner.handle(event("GUILD_CREATE", guild_create()))
    alice_says, bob_replies = exchange()
    runner.handle(create(alice_says))
    assert flush(runner, force=False) is False                      # first try fails
    assert runner.status()["waiting"] == 1 and runner.status()["database_retries"] == 1 and messages(ingest_db) == {}
    runner.handle(create(bob_replies))                              # arrives while the database is away
    assert flush(runner, force=False) is False                      # not yet the time to try again: nothing is attempted
    assert runner.status()["database_retries"] == 1
    clock[0] = 1.5
    assert flush(runner, force=False) is False                      # second try fails, with a longer wait
    assert runner.status()["waiting"] == 2 and runner.next_wait(1.5) == pytest.approx(5.0)
    clock[0] = 7.0
    assert flush(runner, force=False) is True
    assert messages(ingest_db) == {100: "Vous avez vu ?", 101: "Oui !"} and runner.status()["waiting"] == 0
    assert set(edges(ingest_db)) == {(BOB_ID, ALICE_ID, "reply")} and edges(ingest_db)[(BOB_ID, ALICE_ID, "reply")][1] == 1


def test_a_connection_that_died_is_opened_again(ingest_db, ingest_url):
    writer = Writer(ingest_url)
    runner = BotRunner([GUILD], writer, batch_seconds=0, retry_seconds=(0,))
    runner.handle(event("GUILD_CREATE", guild_create()))
    runner.handle(create(message_create(1, "avant")))
    flush(runner)
    writer._conn.close()                                              # the connection is lost (a restart of the database, say)
    runner.handle(create(message_create(2, "après")))
    flush(runner)                                                     # the first attempt finds a closed connection, the second a new one
    flush(runner)
    assert set(messages(ingest_db)) == {1, 2}


def test_beyond_a_limit_the_newest_are_dropped_loudly_while_the_database_is_away(caplog):
    runner = BotRunner([GUILD], lambda d, s: None, max_pending=3)
    runner.handle(event("GUILD_CREATE", guild_create()))
    for number in range(5):
        runner.handle(create(message_create(number, "x")))
    assert runner.status()["waiting"] == 3 and runner.status()["dropped"] == 2 and "are waiting for the database" in caplog.text


# ---------------------------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------------------------


def test_a_new_session_after_the_first_is_reported_as_a_possible_gap_and_a_resume_is_not(caplog):
    caplog.set_level(logging.INFO)
    runner = BotRunner([GUILD], lambda d, s: None)
    for kind in ("connected", "disconnected", "resumed", "disconnected", "connected"):
        runner.handle(GatewayEvent(kind))
    assert runner.status()["sessions"] == 2 and runner.status()["gaps"] == 1 and runner.connected is True
    assert "connection resumed: nothing was missed" in caplog.text and "new session" in caplog.text


# ---------------------------------------------------------------------------------------------
# Running: the loop, stopping, the logs
# ---------------------------------------------------------------------------------------------


def test_the_loop_writes_within_the_window_and_stopping_writes_what_waits(ingest_db, ingest_url):
    async def scenario():
        events: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()
        runner = BotRunner([GUILD], Writer(ingest_url), batch_seconds=0.05)
        task = asyncio.create_task(runner.run(events, stop))
        events.put_nowait(event("GUILD_CREATE", guild_create()))
        events.put_nowait(create(message_create(1, "d'abord")))
        for _ in range(100):
            if messages(ingest_db):
                break
            await asyncio.sleep(0.05)
        assert messages(ingest_db) == {1: "d'abord"}                  # written by the loop, with nobody asking
        slow = BotRunner([GUILD], Writer(ingest_url), batch_seconds=60)  # a window that would not end before the test does
        stop2 = asyncio.Event()
        events2: asyncio.Queue = asyncio.Queue()
        task2 = asyncio.create_task(slow.run(events2, stop2))
        events2.put_nowait(event("GUILD_CREATE", guild_create()))
        events2.put_nowait(create(message_create(2, "avant l'arrêt")))
        await asyncio.sleep(0.2)
        assert 2 not in messages(ingest_db)
        stop2.set()
        await asyncio.wait_for(task2, 10)                              # stopping writes what waited
        stop.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(scenario())
    assert messages(ingest_db) == {1: "d'abord", 2: "avant l'arrêt"}


def test_the_logs_say_how_many_and_never_what(ingest_url, caplog):
    caplog.set_level(logging.DEBUG)
    runner = runner_for(ingest_url)
    alice_says, bob_replies = exchange()
    alice_says["content"] = "Un texte très personnel"
    strange = message_create(9, "autre texte personnel")
    del strange["author"]
    for payload in (alice_says, bob_replies, strange):
        runner.handle(create(payload))
    flush(runner)
    text = caplog.text
    assert "channel 200" in text and "messages received" in text           # counts and IDs
    assert "personnel" not in text and "alice" not in text.lower() and "Ali" not in text.replace("Alive", "")  # no content, no names


# ---------------------------------------------------------------------------------------------
# The whole chain, with the real library against the fake Gateway, up to the page
# ---------------------------------------------------------------------------------------------

PASSWORD = "correct horse"
TOKEN = "fake-bot-token-for-the-whole-chain"


@pytest.fixture
def page_server(ingest_url, tmp_path):
    """The application (API, live events), serving a page that listens: what the watcher's end-to-end test uses."""
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, background=False), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    page = Page(port)
    yield page
    page.close()
    server.should_exit = True
    thread.join(timeout=10)


def test_a_message_written_on_the_fake_discord_lights_up_the_link_on_the_page(ingest_db, ingest_url, page_server, capsys):
    async def scenario():
        fake = await FakeGateway(TOKEN, guilds=[guild_create()]).start()
        source = GatewaySource(TOKEN, api_url=fake.api_url, gateway_url=fake.gateway_url, retry_seconds=(0.05,))
        runner = BotRunner([GUILD], Writer(ingest_url))
        stop = asyncio.Event()
        tasks = [asyncio.create_task(source.run()), asyncio.create_task(runner.run(source.events, stop))]
        try:
            for _ in range(200):                                       # the server is described to the bot
                if runner.directory.guild(GUILD):
                    break
                await asyncio.sleep(0.05)
            assert runner.directory.guild(GUILD)
            alice_says, bob_replies = exchange(first=int(time.time()) * 1000)
            started = time.monotonic()
            await fake.dispatch("MESSAGE_CREATE", alice_says)
            await fake.dispatch("MESSAGE_CREATE", bob_replies)
            found = await asyncio.to_thread(page_server.wait, lambda e: e["type"] == "edge" and (e["from"], e["to"], e["kind"]) ==
                                            (str(BOB_ID), str(ALICE_ID), "reply"), 15)
            assert found, "the link never lit up"
            return found[0] - started, found[1]
        finally:
            stop.set()
            await source.close()
            await asyncio.gather(*tasks, return_exceptions=True)
            await fake.stop()

    latency, edge = asyncio.run(scenario())
    print(f"\nmessage dispatched by the fake Gateway -> 'edge' event received by the page: {latency:.2f}s")
    assert latency < 3 and edge["weight"] > 0.9 and edge["guild"] == GUILD
    assert len(messages(ingest_db)) == 2


# ---------------------------------------------------------------------------------------------
# Review: what is a passing problem, and what is a message that cannot be digested
# ---------------------------------------------------------------------------------------------


def test_a_database_that_is_not_ready_makes_the_messages_wait_instead_of_dropping_them(migrated_url, tmp_path):
    """The bot can start before the application has applied the migrations: 'relation does not exist' is not the fault of the messages."""
    import uuid

    from dindon.migrate import migrate

    name = "dindon_empty_" + uuid.uuid4().hex[:8]
    base = migrated_url.rpartition("/")[0]
    with psycopg.connect(migrated_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        url = f"{base}/{name}"
        runner = BotRunner([GUILD], Writer(url), batch_seconds=0, retry_seconds=(0,))
        runner.handle(event("GUILD_CREATE", guild_create()))
        for number in (1, 2, 3):
            runner.handle(create(message_create(number, f"m{number}")))
        assert flush(runner) is False                                          # nothing to write them into yet
        assert runner.status()["rejected"] == 0 and runner.status()["waiting"] == 3
        with psycopg.connect(url) as conn:                                      # the application applies the migrations
            migrate(conn, __import__("pathlib").Path(__file__).resolve().parents[1] / "db")
        assert flush(runner) is True
        with psycopg.connect(url) as conn:
            assert {r[0] for r in conn.execute("SELECT id FROM messages")} == {1, 2, 3}
        assert runner.status()["rejected"] == 0
    finally:
        with psycopg.connect(migrated_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def test_an_error_in_the_middle_of_a_transaction_costs_one_message_and_leaves_the_connection_usable(ingest_db, ingest_url):
    """The database itself refuses one message (a person that is in no table): that message is dropped, the others are written, and the
    connection that went through the failed transaction goes on working."""
    writer = Writer(ingest_url)

    def refused_by_the_database(document, sha):
        for m in document["messages"]:
            if m["id"] == "2":
                m["reference"] = {"type": "Default", "messageId": "1", "authorId": "999999999999"}
        return writer(document, sha)

    runner = BotRunner([GUILD], refused_by_the_database, batch_seconds=0)
    runner.handle(event("GUILD_CREATE", guild_create()))
    for number in (1, 2, 3):
        runner.handle(create(message_create(number, f"m{number}")))
    assert flush(runner)
    assert set(messages(ingest_db)) == {1, 3} and runner.status()["rejected"] == 1 and runner.status()["waiting"] == 0
    runner.handle(create(message_create(4, "après")))
    assert flush(runner) and set(messages(ingest_db)) == {1, 3, 4}             # the same connection, still good


def test_the_bot_says_that_it_is_alive_with_counts_only(ingest_db, ingest_url, monkeypatch):
    """Every half minute the bot writes service_status: what the page Système shows. Counts and ids of servers, never a message."""
    monkeypatch.setattr("dindon.bot.runner.HEARTBEAT_SECONDS", 0.1)

    async def scenario():
        events: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()
        runner = BotRunner([GUILD], Writer(ingest_url), batch_seconds=0.05)
        task = asyncio.create_task(runner.run(events, stop))
        events.put_nowait(GatewayEvent("connected"))
        events.put_nowait(event("GUILD_CREATE", guild_create()))
        events.put_nowait(create(message_create(1, "un message secret")))
        for _ in range(100):
            row = ingest_db.execute("SELECT data FROM service_status WHERE name = 'bot'").fetchone()
            if row and row[0]["connected"] and row[0]["new"]:
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(scenario())
    updated, data = ingest_db.execute("SELECT updated_at, data FROM service_status WHERE name = 'bot'").fetchone()
    assert data["connected"] is True and data["sessions"] == 1 and data["new"] == 1 and data["followed"] == [GUILD] and data["ready"] == [GUILD]
    assert data["started_at"] and data["last_new_at"]
    assert "secret" not in json.dumps(data)                                           # no content of any message


def test_a_database_that_is_away_does_not_stop_the_heartbeat_loop(ingest_url, monkeypatch):
    monkeypatch.setattr("dindon.bot.runner.HEARTBEAT_SECONDS", 0.05)

    async def scenario():
        events: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()
        runner = BotRunner([GUILD], Writer("postgresql://nobody:x@127.0.0.1:9/none"), batch_seconds=0.05)
        task = asyncio.create_task(runner.run(events, stop))
        await asyncio.sleep(0.4)                                                      # several beats, all refused
        assert not task.done()
        stop.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(scenario())


def test_a_sign_of_life_that_cannot_be_written_is_said_once_not_every_half_minute(caplog, monkeypatch):
    monkeypatch.setattr("dindon.bot.runner.HEARTBEAT_SECONDS", 0.05)
    caplog.set_level(logging.INFO, logger="dindon.bot")

    async def scenario():
        events: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()
        runner = BotRunner([GUILD], Writer("postgresql://nobody:x@127.0.0.1:9/none"), batch_seconds=0.05)
        task = asyncio.create_task(runner.run(events, stop))
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.wait_for(task, 10)

    asyncio.run(scenario())
    said = [r for r in caplog.records if "sign of life could not be written" in r.getMessage()]
    assert len(said) == 1 and said[0].levelno == logging.WARNING

