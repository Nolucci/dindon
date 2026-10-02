"""The watcher, against a fake Discord and a fake exporter: no token, no network, no real data."""
import dataclasses
import json
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from dindon.collector.discord_api import DiscordAPI, DiscordError, RateLimited
from dindon.collector.exporter import Exporter
from dindon.collector.watch import Collector, snowflake_at
from dindon.ingest.loader import ingest_file
from fake_discord import FakeDiscord
from make_demo_server import Channel, World, write_exports
from synthetic import settings_for

TOOLS = Path(__file__).resolve().parents[1] / "tools"
TOKEN = "fake-account-token-1234"


def exports_asked(fake: FakeDiscord) -> list[str]:
    return [r for r in fake.requests if r.startswith("/_fake/export")]


@pytest.fixture
def world():
    w = World(seed=21, people=25)
    w.generate(1500, days=30, end=datetime.now(timezone.utc) - timedelta(minutes=30))
    return w


@pytest.fixture
def fake(world, monkeypatch):
    server = FakeDiscord(world, token=TOKEN).start()
    monkeypatch.setenv("FAKE_DISCORD_URL", server.base_url)
    yield server
    server.stop()


@pytest.fixture
def collector(fake, world, ingest_url, tmp_path):
    settings = dataclasses.replace(
        settings_for(ingest_url, tmp_path), discord_api_url=fake.api_url, discord_token=TOKEN, guild_ids=(world.guild_id,),
        exporter_path=f"{shlex.quote(sys.executable)} {shlex.quote(str(TOOLS / 'fake_exporter.py'))}", poll_seconds=0.2)
    return Collector(settings)


def connection(url: str) -> psycopg.Connection:
    conn = psycopg.connect(url)
    conn.autocommit = True
    return conn


def message_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM messages").fetchone()[0]


@pytest.fixture
def imported(collector, world, ingest_url):
    """The first import is done, as `dindon backfill` does it."""
    totals = collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=2, progress=lambda _: None)
    assert totals["failed"] == 0
    return totals


# ---------------------------------------------------------------------------------------------
# The first import
# ---------------------------------------------------------------------------------------------


def test_nothing_is_exported_before_the_first_import(collector, fake, ingest_db, world):
    assert collector.poll(ingest_db) == 0
    assert exports_asked(fake) == []  # starting the watcher never launches a huge export by surprise
    assert collector.status()["needs_backfill"] == [str(world.guild_id)]


def test_the_first_import_brings_everything_and_can_be_repeated(collector, fake, ingest_url, world):
    total = sum(len(c.messages) for c in world.channels)
    totals = collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=2, progress=lambda _: None)
    assert totals["messages"] == total and totals["failed"] == 0
    with connection(ingest_url) as conn:
        assert message_count(conn) == total
    asked = len(exports_asked(fake))
    again = collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=2, progress=lambda _: None)
    assert again == {"channels": 0, "failed": 0, "messages": 0} and len(exports_asked(fake)) == asked  # nothing to do


def test_an_interrupted_first_import_goes_on_where_it_stopped(collector, fake, ingest_url, world, tmp_path):
    """Some channels are done, one only to its middle: the rest is fetched, the half-done one after its newest message."""
    folder = tmp_path / "partial"
    folder.mkdir()
    done, half = world.channels[:3], world.channels[3]
    middle = int(half.messages[len(half.messages) // 2]["id"])
    with connection(ingest_url) as conn:
        for number, channel in enumerate(done):
            path = folder / f"{number}.json"
            path.write_text(world.export_document(channel), encoding="utf-8")
            ingest_file(conn, path)
        path = folder / "half.json"
        path.write_text(world.export_document(half, before_id=middle), encoding="utf-8")
        ingest_file(conn, path)
        last_known = conn.execute("SELECT max(id) FROM messages WHERE channel_id = %s", (half.id,)).fetchone()[0]
    collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=2, progress=lambda _: None)
    asked = exports_asked(fake)
    assert not any(f"channel={c.id}" in r for r in asked for c in done)  # what was done is not asked again
    assert any(f"channel={half.id}" in r and f"after={last_known}" in r for r in asked)  # the rest of the half-done one
    with connection(ingest_url) as conn:
        assert message_count(conn) == sum(len(c.messages) for c in world.channels)


# ---------------------------------------------------------------------------------------------
# Watching
# ---------------------------------------------------------------------------------------------


def test_when_nothing_moved_only_the_list_of_channels_is_asked(collector, fake, imported, ingest_db):
    fake.requests.clear()
    assert collector.poll(ingest_db) == 0
    assert exports_asked(fake) == []
    assert [r for r in fake.requests if "/guilds/" in r] == [f"/api/v10/guilds/{collector.settings.guild_ids[0]}/channels"]  # one request


def test_an_exchange_exports_only_its_channel_with_after_and_lights_up_the_link(collector, fake, imported, ingest_db, world):
    channel = max(world.channels, key=lambda c: len(c.messages))
    alice, bob = world.people[0], world.people[1]
    last_known = ingest_db.execute("SELECT max(id) FROM messages WHERE channel_id = %s", (channel.id,)).fetchone()[0]
    first = fake.post(channel, alice, "on en parle ?")
    fake.post(channel, bob, "oui, bonne idée", reply_to_id=first["id"])
    fake.requests.clear()
    assert collector.poll(ingest_db) == 1
    asked = exports_asked(fake)
    assert len(asked) == 1 and f"channel={channel.id}" in asked[0] and f"after={last_known}" in asked[0]  # only what is new
    assert ingest_db.execute("SELECT content FROM messages WHERE id = %s", (int(first["id"]),)).fetchone() == ("on en parle ?",)
    edge = ingest_db.execute("SELECT n FROM edges WHERE from_user_id = %s AND to_user_id = %s AND kind = 'reply'", (bob.id, alice.id)).fetchone()
    assert edge is not None and edge[0] >= 1
    # and it is not asked again until something moves
    fake.requests.clear()
    assert collector.poll(ingest_db) == 0 and exports_asked(fake) == []


def test_a_channel_created_after_the_first_import_is_exported_entirely_an_old_unknown_one_is_not(collector, fake, ingest_url, ingest_db, world, tmp_path):
    folder = tmp_path / "some"
    folder.mkdir()
    for number, channel in enumerate(world.channels[1:]):  # everything but the first channel, which stays unknown
        (folder / f"{number}.json").write_text(world.export_document(channel), encoding="utf-8")
    for path in sorted(folder.glob("*.json")):
        ingest_file(ingest_db, path)
    unknown = world.channels[0]
    newcomer = Channel(world._flake(datetime.now(timezone.utc)), "nouveau", "Détente", unknown.category_id, None)
    world.channels.append(newcomer)
    fake.post(newcomer, world.people[0], "premier message du nouveau salon")
    fake.requests.clear()
    assert collector.poll(ingest_db) == 1
    asked = exports_asked(fake)
    assert len(asked) == 1 and f"channel={newcomer.id}" in asked[0] and "after=" not in asked[0]  # all of it
    assert ingest_db.execute("SELECT count(*) FROM messages WHERE channel_id = %s", (unknown.id,)).fetchone() == (0,)  # left to `backfill`
    collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=1, progress=lambda _: None)
    assert ingest_db.execute("SELECT count(*) FROM messages WHERE channel_id = %s", (unknown.id,)).fetchone()[0] == len(unknown.messages)


# ---------------------------------------------------------------------------------------------
# When things go wrong
# ---------------------------------------------------------------------------------------------


def test_a_rate_limit_stops_everything_for_as_long_as_discord_asks(collector, fake, imported, ingest_db, world):
    fake.post(world.channels[0], world.people[0], "bonjour")
    fake.rate_limit_next(1, retry_after=2.5)
    fake.requests.clear()
    with pytest.raises(RateLimited) as limited:
        collector.poll(ingest_db)
    assert limited.value.retry_after == 2.5
    assert exports_asked(fake) == []  # nothing was asked while Discord said to wait
    assert collector.poll(ingest_db) == 1  # once Discord lets us through again, nothing was lost


def test_a_failing_channel_is_left_alone_for_a_while_then_tried_again(collector, fake, imported, ingest_db, world, monkeypatch):
    channel = world.channels[0]
    fake.post(channel, world.people[0], "bonjour")
    monkeypatch.setenv("FAKE_EXPORTER_FAIL", "1")
    assert collector.poll(ingest_db) == 0
    status = collector.status()
    assert status["failing_channels"] == 1 and "exporter stopped" in status["last_error"] and TOKEN not in status["last_error"]
    monkeypatch.delenv("FAKE_EXPORTER_FAIL")
    fake.requests.clear()
    assert collector.poll(ingest_db) == 0 and exports_asked(fake) == []  # backing off: not asked again right away
    count, _ = collector._failures[channel.id]
    collector._failures[channel.id] = (count, 0.0)  # the waiting time is over
    assert collector.poll(ingest_db) == 1 and collector.status()["failing_channels"] == 0
    assert collector.status()["last_error"] is None  # an error that is over does not stay on display
    assert ingest_db.execute("SELECT count(*) FROM messages WHERE content = 'bonjour' AND channel_id = %s", (channel.id,)).fetchone()[0] >= 1


def test_a_wrong_token_is_reported_without_the_token(fake, world, tmp_path, ingest_url):
    api = DiscordAPI(fake.api_url, "not-the-token")
    with pytest.raises(DiscordError) as error:
        api.resolve_kind()
    assert "not-the-token" not in str(error.value)


def test_the_token_goes_to_the_exporter_by_the_environment_not_the_command_line(fake, tmp_path, monkeypatch, world):
    seen = {}
    import subprocess

    real_popen = subprocess.Popen

    def spy(args, **kwargs):
        seen["args"], seen["env_token"] = args, kwargs["env"].get("DISCORD_TOKEN")
        return real_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    exporter = Exporter(f"{shlex.quote(sys.executable)} {shlex.quote(str(TOOLS / 'fake_exporter.py'))}", TOKEN)
    out = tmp_path / "out"
    files = exporter.export(world.channels[0].id, out)
    assert files and seen["env_token"] == TOKEN and TOKEN not in " ".join(seen["args"])


# ---------------------------------------------------------------------------------------------
# Account or bot
# ---------------------------------------------------------------------------------------------


def test_an_account_token_and_a_bot_token_are_told_apart(world):
    thread = Channel(world._flake(datetime.now(timezone.utc)), "un fil", "Politique", world.channels[0].category_id, None,
                     parent_id=world.channels[0].id, type="GuildPublicThread")
    world.channels.append(thread)
    fake_threads = {}
    for bot in (False, True):
        server = FakeDiscord(world, token="tok", bot=bot).start()
        try:
            api = DiscordAPI(server.api_url, "tok")
            assert api.resolve_kind() == ("bot" if bot else "account")
            fake_threads[bot] = api.active_threads(world.guild_id)
            asked_for_threads = any("/threads/active" in r for r in server.requests)
            assert asked_for_threads == bot                              # an account cannot list them: it is not even tried
            assert thread.id not in [c.id for c in api.channels(world.guild_id)]  # threads are not in the list of channels
        finally:
            server.stop()
    assert fake_threads[False] == [] and [t.id for t in fake_threads[True]] == [thread.id]
    assert fake_threads[True][0].parent_id == world.channels[0].id and fake_threads[True][0].kind == "thread"


# ---------------------------------------------------------------------------------------------
# The nightly catch-up: what was edited or deleted
# ---------------------------------------------------------------------------------------------


def test_the_catch_up_applies_edits_and_deletions_of_the_last_days(collector, fake, imported, ingest_db, world):
    now = datetime.now(timezone.utc)
    since = snowflake_at(now - timedelta(days=7))
    channel = max(world.channels, key=lambda c: sum(1 for m in c.messages if int(m["id"]) > since))
    window = [m for m in channel.messages if int(m["id"]) > since]
    assert len(window) > 30
    deleted, edited = window[len(window) // 3], window[len(window) // 2]
    channel.messages.remove(deleted)
    edited["content"] = "message corrigé après coup"
    edited["timestampEdited"] = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    old_messages = message_count(ingest_db)
    collector.catchup(ingest_db, now)
    assert ingest_db.execute("SELECT count(*) FROM messages WHERE id = %s", (int(deleted["id"]),)).fetchone() == (0,)
    assert ingest_db.execute("SELECT content FROM messages WHERE id = %s", (int(edited["id"]),)).fetchone() == ("message corrigé après coup",)
    assert message_count(ingest_db) == old_messages - 1
    assert not collector.catchup_due(now)  # once a day
    # and the links stay exact
    incremental = ingest_db.execute("SELECT guild_id, from_user_id, to_user_id, kind, n FROM edges ORDER BY 1, 2, 3, 4").fetchall()
    ingest_db.execute("SELECT rebuild_edges()")
    assert incremental == ingest_db.execute("SELECT guild_id, from_user_id, to_user_id, kind, n FROM edges ORDER BY 1, 2, 3, 4").fetchall()


# ---------------------------------------------------------------------------------------------
# The live bot as another source: it must not be taken for a first import
# ---------------------------------------------------------------------------------------------


def _bot_writes_the_newest_message(conn, world, channel):
    """What the bot does on a MESSAGE_CREATE: one new message, recorded under the name 'gateway'."""
    import hashlib

    from dindon.ingest.loader import ingest_document

    newest = int(channel.messages[-1]["id"])
    document = json.loads(world.export_document(channel, after_id=newest - 1))
    assert [m["id"] for m in document["messages"]] == [str(newest)]
    sha = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    ingest_document(conn, document, "gateway", sha, only_new=True)
    return newest


def test_a_server_that_the_bot_saw_first_is_still_imported_in_full_by_backfill(collector, ingest_db, ingest_url, world):
    """If the bot writes the newest message of a channel before any import, 'the newest message is known' must not be read as
    'the history is here': the first import has to bring everything that came before."""
    channel = max(world.channels, key=lambda c: len(c.messages))
    _bot_writes_the_newest_message(ingest_db, world, channel)
    assert message_count(ingest_db) == 1
    collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=2, progress=lambda _: None)
    assert message_count(ingest_db) == sum(len(c.messages) for c in world.channels)


def test_a_message_written_by_the_bot_is_not_a_first_import_for_the_watcher(collector, fake, ingest_db, world):
    channel = max(world.channels, key=lambda c: len(c.messages))
    _bot_writes_the_newest_message(ingest_db, world, channel)
    assert collector.poll(ingest_db) == 0 and exports_asked(fake) == []
    assert collector.status()["needs_backfill"] == [str(world.guild_id)]  # the interface still says that the first import is to do


def test_the_watcher_does_not_see_a_gap_left_by_the_bot_only_the_nightly_catch_up_does(collector, fake, imported, ingest_db, world):
    """After a new Gateway session, messages written meanwhile are missing. The watcher only looks for what is newer than the newest
    message it knows, so it does not see them; the catch-up, which exports the last days again, brings them back. (The documentation
    says so: it must be true.)"""
    channel = max(world.channels, key=lambda c: len(c.messages))
    alice = world.people[0]
    missed = [fake.post(channel, alice, f"manqué {n}") for n in range(2)]
    seen = fake.post(channel, alice, "vu par le bot")
    import hashlib

    from dindon.ingest.loader import ingest_document

    document = json.loads(world.export_document(channel, after_id=int(seen["id"]) - 1))
    ingest_document(ingest_db, document, "gateway", hashlib.sha256(json.dumps(document).encode()).hexdigest(), only_new=True)
    ids = {r[0] for r in ingest_db.execute("SELECT id FROM messages WHERE channel_id = %s", (channel.id,))}
    assert int(seen["id"]) in ids and not {int(m["id"]) for m in missed} & ids
    fake.requests.clear()
    assert collector.poll(ingest_db) == 0 and exports_asked(fake) == []          # the watcher sees nothing to do
    collector.catchup(ingest_db)
    ids = {r[0] for r in ingest_db.execute("SELECT id FROM messages WHERE channel_id = %s", (channel.id,))}
    assert {int(m["id"]) for m in missed} <= ids                                  # the catch-up does
