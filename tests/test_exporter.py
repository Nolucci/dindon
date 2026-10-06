"""Dindon's own exporter, against a fake Discord that answers like the REST API (tools/fake_discord.py): the documents must say what the world says, the requests must
be few, and what goes wrong must be said in words and never with the token. Level of proof: SIMULATED (no connection to Discord; the shape of the answers comes from
Discord's documentation and from the original exporter's code, not from a real server)."""
import json
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import jsonschema
import pytest

from dindon.export import Exporter, ExporterCancelled, ExporterError
from dindon.export.client import DiscordClient, RateLimiter, route_of
from dindon.export.errors import Forbidden, NotFound, Unauthorized
from dindon.export.filters import compile_filter
from dindon.export.writer import render
from fake_discord import FakeDiscord
from make_demo_server import Channel, World

TOKEN = "super-secret-token-1234"
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "JSON-format.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def world():
    w = World(seed=21, people=25)
    w.generate(1500, days=30, end=datetime.now(UTC) - timedelta(minutes=30))
    return w


@pytest.fixture
def fake(world):
    server = FakeDiscord(world, token=TOKEN).start()
    yield server
    server.stop()


def biggest(world) -> Channel:
    return max(world.channels, key=lambda c: len(c.messages))


def exporter(fake, **options) -> Exporter:
    return Exporter(TOKEN, fake.api_url, **{"reactions": "all", **options})


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def asked(fake, fragment: str) -> int:
    return len([r for r in fake.requests if fragment in r])


# --- the filter ---------------------------------------------------------------------------------------------------------------


def message(author: str, *mentions: str) -> dict:
    return {"author": {"id": author}, "mentions": [{"id": m} for m in mentions]}


def test_the_filter_understands_what_the_importer_writes_and_nothing_else():
    keep = compile_filter("(from:1 | from:2) (mentions:3)")
    assert keep(message("1", "3")) and keep(message("2", "9", "3")) and not keep(message("1")) and not keep(message("5", "3"))
    assert compile_filter(None)(message("7")) and compile_filter("  ")(message("7"))
    assert compile_filter("from:1 | mentions:2")(message("9", "2")) and not compile_filter("from:1 mentions:2")(message("1"))
    for wrong, why in (("from:abc", "n'est pas compris"), ("content:salut", "n'est pas compris"), ("(from:1", "parenthèse"), ("from:1)", "de trop"), ("from:1 |", "il manque")):
        with pytest.raises(ExporterError, match=why):
            compile_filter(wrong)


# --- the rate limits ----------------------------------------------------------------------------------------------------------


def test_the_bucket_of_a_request_keeps_its_channel_and_forgets_the_rest():
    assert route_of("GET", "/channels/123456/messages?limit=100") == "GET /channels/123456/messages"
    assert route_of("GET", "/channels/123456/messages/777777/reactions/%F0%9F%91%8D") == "GET /channels/123456/messages/:id/reactions/:emoji"
    assert route_of("GET", "/guilds/222222/members/333333") == "GET /guilds/222222/members/:id"


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_an_empty_bucket_makes_the_next_request_wait_instead_of_being_refused():
    clock = Clock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    limiter.wait("a")
    limiter.record("a", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "1.5"}.get)
    limiter.wait("b")                                                          # another bucket: no wait
    assert clock.slept == []
    limiter.wait("a")
    assert sum(clock.slept) == pytest.approx(1.5, abs=0.3)                       # the time that Discord said
    limiter.record("a", {"X-RateLimit-Remaining": "4", "X-RateLimit-Reset-After": "1"}.get)
    before = len(clock.slept)
    limiter.wait("a")
    assert len(clock.slept) == before                                           # requests left: no wait


def test_the_global_rate_is_kept_and_a_penalty_is_waited_for():
    clock = Clock()
    limiter = RateLimiter(per_second=5, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        limiter.wait("r")
    assert clock.slept == []
    limiter.wait("r")                                                           # the sixth in the same second waits for it to end
    assert sum(clock.slept) == pytest.approx(1.0, abs=0.3)
    clock.slept.clear()
    limiter.penalty("r", 3.0, is_global=True)
    limiter.wait("anything")
    assert sum(clock.slept) == pytest.approx(3.0, abs=0.3)


def test_a_wait_ends_at_once_when_the_export_is_stopped():
    clock = Clock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    limiter.penalty("r", 100.0, is_global=False)
    stop = iter([False, False, True])
    with pytest.raises(ExporterCancelled):
        limiter.wait("r", lambda: next(stop))
    assert sum(clock.slept) < 2


# --- the client: what goes wrong ----------------------------------------------------------------------------------------------


def test_an_error_is_said_in_words_and_never_with_the_token(fake, world):
    ex = exporter(fake)
    fake.forbidden_channels.add(str(biggest(world).id))
    for call, error, words in ((lambda: ex.client.get(f"/channels/{biggest(world).id}/messages"), Forbidden, "refuse l'accès"),
                               (lambda: ex.client.get("/channels/999999999"), NotFound, "Introuvable")):
        with pytest.raises(error, match=words) as raised:
            call()
        assert TOKEN not in str(raised.value)
    with pytest.raises(Unauthorized, match="jeton Discord n'est pas valide") as raised:
        DiscordClient(fake.api_url, "not-the-token").get("/users/@me")
    assert "not-the-token" not in str(raised.value)


def test_a_bot_token_and_an_account_token_are_both_understood(world):
    for bot in (False, True):
        server = FakeDiscord(world, token="tok", bot=bot).start()
        try:
            client = DiscordClient(server.api_url, "tok")
            assert client.get("/users/@me")["id"] and client.kind == ("bot" if bot else "account")
            assert DiscordClient(server.api_url, "Bot tok" if bot else "tok").get("/users/@me")["id"]          # the prefix of a bot token is accepted as given
        finally:
            server.stop()


def test_a_server_error_is_tried_again_then_reported(fake, world):
    ex = exporter(fake)
    ex.client._sleep = lambda s: None
    ex.client.limiter._sleep = lambda s: None
    fake.fail_next(2, 503)                                                      # twice, then it works: nothing is lost
    assert len(ex.client.get(f"/channels/{biggest(world).id}/messages", {"limit": 5})) == 5
    fake.fail_next(50, 500)
    with pytest.raises(ExporterError, match="a répondu une erreur \\(500\\)"):
        ex.client.get(f"/channels/{biggest(world).id}/messages", {"limit": 5})


def test_a_rate_limit_is_waited_for_and_an_absurd_one_stops_the_export(fake, world):
    ex = exporter(fake)
    fake.rate_limit_next(2, retry_after=0.05)
    started = time.monotonic()
    assert ex.client.get(f"/channels/{biggest(world).id}/messages", {"limit": 3})
    assert time.monotonic() - started >= 0.05                                   # it waited what Discord asked, and went on
    fake.rate_limit_next(1, retry_after=9999)
    with pytest.raises(ExporterError, match="demande d'attendre 9999 s"):
        ex.client.get(f"/channels/{biggest(world).id}/messages", {"limit": 3})


def test_a_connection_is_kept_open_for_all_the_requests_of_a_thread(fake, world, monkeypatch):
    import http.client

    made = []
    real = http.client.HTTPConnection.__init__
    monkeypatch.setattr(http.client.HTTPConnection, "__init__", lambda self, *a, **k: (made.append(1), real(self, *a, **k))[1])
    client = DiscordClient(fake.api_url, TOKEN)
    for _ in range(12):
        client.get(f"/channels/{biggest(world).id}/messages", {"limit": 2})
    assert len(made) == 1                                                       # twelve requests, one connection (no handshake each time)


# --- what an export says --------------------------------------------------------------------------------------------------------


def test_the_export_says_what_the_server_says(fake, world, tmp_path):
    channel = biggest(world)
    (path,) = exporter(fake).export(channel.id, tmp_path)
    document = read(path)
    jsonschema.validate(document, SCHEMA)                                       # the contract is respected
    expected = json.loads(world.export_document(channel))
    assert document["guild"]["id"] == expected["guild"]["id"] and document["channel"] == expected["channel"] and document["messageCount"] == len(channel.messages)
    assert [m["id"] for m in document["messages"]] == [m["id"] for m in expected["messages"]]                # all of them, in order
    for ours, theirs in zip(document["messages"], expected["messages"], strict=False):
        for key in (set(ours) | set(theirs)) - {"inlineEmojis"}:                  # (the standard emoji of a text are not looked for)
            if key == "reactions":
                assert [(r["emoji"], r["count"], sorted(r["userIds"])) for r in ours[key]] == [(r["emoji"], r["count"], sorted(r["userIds"])) for r in theirs[key]]
            else:
                assert ours.get(key) == theirs.get(key), (ours["id"], key)
    mine, reference = {u["id"]: u for u in document["users"]}, {u["id"]: u for u in expected["users"]}
    assert mine.keys() == reference.keys()
    wrote = {m["authorId"] for m in document["messages"]} | {u for m in document["messages"] for u in m.get("mentionedUserIds", [])}
    for uid in wrote:                                                           # who wrote or was mentioned: the same profile, roles and nickname included
        assert {k: v for k, v in mine[uid].items() if k != "avatarUrl"} == {k: v for k, v in reference[uid].items() if k != "avatarUrl"}, uid
    assert {r["id"] for r in document["roles"]} <= {r["id"] for r in expected["roles"]}
    assert not list(tmp_path.glob("*.part"))                                    # nothing half written is left


def test_what_is_written_is_laid_out_as_the_contract_wants_it(fake, world, tmp_path):
    (path,) = exporter(fake).export(biggest(world).id, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith('{\n"users":[\n') and text.count("\n") >= len(read(path)["messages"]) + 10          # one line per element
    assert text == render(read(path))                                           # and the writer is the one place that decides it


def test_nothing_to_export_writes_no_file(fake, world, tmp_path):
    channel = biggest(world)
    assert exporter(fake).export(channel.id, tmp_path, after=int(channel.messages[-1]["id"])) == [] and list(tmp_path.iterdir()) == []


def test_only_the_asked_window_is_downloaded_and_it_is_said_in_the_document(fake, world, tmp_path):
    channel = biggest(world)
    ids = [int(m["id"]) for m in channel.messages]
    low, high = ids[len(ids) // 3], ids[2 * len(ids) // 3]
    fake.requests.clear()
    (path,) = exporter(fake).export(channel.id, tmp_path, after=low, before=high)
    document = read(path)
    assert [int(m["id"]) for m in document["messages"]] == [i for i in ids if low < i < high]
    assert set(document["dateRange"]) == {"after", "before"} and document["dateRange"]["after"] < document["dateRange"]["before"]
    pages = [r for r in fake.requests if f"/channels/{channel.id}/messages?" in r]
    assert all("after=" in r for r in pages) and len(pages) <= math.ceil((len([i for i in ids if i > low]) + 1) / 100) + 1       # not the whole history


def test_a_filter_keeps_the_messages_and_asks_nothing_more_for_the_others(fake, world, tmp_path):
    channel = biggest(world)
    author = max({m["authorId"] for m in channel.messages}, key=lambda a: sum(1 for m in channel.messages if m["authorId"] == a))
    ex = exporter(fake)
    (path,) = ex.export(channel.id, tmp_path, message_filter=f"(from:{author})")
    document = read(path)
    assert document["messages"] and {m["authorId"] for m in document["messages"]} == {author}
    people = {author} | {u for m in document["messages"] for u in m.get("mentionedUserIds", [])} | {m["reference"]["authorId"] for m in document["messages"] if "reference" in m}
    parents = {m["id"]: m for m in channel.messages}                            # the text of a reply quotes the message it answers: the people that one mentions matter too
    for m in document["messages"]:
        parent = parents.get(m.get("reference", {}).get("messageId"))
        if parent:
            people |= set(parent.get("mentionedUserIds", []))
    assert ex.stats["member_requests"] <= len(people)                          # only the people who matter for the messages that were kept
    mentioned = next((m for m in channel.messages if m.get("mentionedUserIds")), None)
    if mentioned:
        (second,) = exporter(fake).export(channel.id, tmp_path / "b", message_filter=f"(mentions:{mentioned['mentionedUserIds'][0]})")
        assert all(mentioned["mentionedUserIds"][0] in m["mentionedUserIds"] for m in read(second)["messages"])


def test_a_big_channel_is_cut_in_files_that_are_each_a_complete_document(fake, world, tmp_path):
    channel = biggest(world)
    files = exporter(fake).export(channel.id, tmp_path, partition=100)
    assert len(files) == math.ceil(len(channel.messages) / 100) and files == sorted(files)
    total = 0
    for f in files:
        document = read(f)
        jsonschema.validate(document, SCHEMA)
        assert document["messageCount"] == len(document["messages"]) <= 100 and {m["authorId"] for m in document["messages"]} <= {u["id"] for u in document["users"]}
        total += len(document["messages"])
    assert total == len(channel.messages) and "part1" in files[0].name


def test_the_threads_of_a_channel_are_exported_along_with_it_when_asked(world, tmp_path):
    parent = biggest(world)
    thread = Channel(world._flake(datetime.now(UTC) - timedelta(days=2)), "un fil", parent.category, parent.category_id, None, parent_id=parent.id, type="GuildPublicThread")
    author = world.people[0]
    world.post(thread, author, "dans le fil", datetime.now(UTC) - timedelta(days=1))
    world.channels.append(thread)
    server = FakeDiscord(world, token=TOKEN, bot=True).start()
    try:
        ex = Exporter(TOKEN, server.api_url)
        assert len(ex.export(parent.id, tmp_path / "none", threads="none")) == 1
        files = ex.export(parent.id, tmp_path / "active", threads="active")
        assert len(files) == 2 and read(files[1])["channel"]["name"] == "un fil" and read(files[1])["channel"]["type"] == "GuildPublicThread"
        assert read(files[1])["channel"]["category"] == parent.name                       # a thread is under the channel that it belongs to
        assert [m["content"] for m in read(files[1])["messages"]] == ["dans le fil"]
        assert [m["id"] for m in read(ex.export(thread.id, tmp_path / "alone")[0])["messages"]] == [m["id"] for m in thread.messages]
    finally:
        server.stop()


# --- how much is asked ------------------------------------------------------------------------------------------------------------


def test_the_requests_are_few_and_the_profiles_are_asked_once(fake, world, tmp_path):
    channel = biggest(world)
    ex = exporter(fake, reactions="none")
    ex.export(channel.id, tmp_path / "a")
    pages = asked(fake, f"/channels/{channel.id}/messages?")
    assert pages == math.ceil(len(channel.messages) / 100) + (1 if len(channel.messages) % 100 == 0 else 0)          # 100 messages per request
    document = read(next((tmp_path / "a").glob("*.json")))
    people = {m["authorId"] for m in document["messages"]} | {u for m in document["messages"] for u in m.get("mentionedUserIds", [])}
    assert ex.stats["member_requests"] <= len(people | {m["reference"]["authorId"] for m in document["messages"] if "reference" in m})
    assert asked(fake, "/reactions/") == 0                                       # `none`: not a request for who reacted
    before = asked(fake, "/members/")
    ex.export(channel.id, tmp_path / "b")                                        # again: the profiles are known
    assert asked(fake, "/members/") == before                                    # (the server and its channels were read once: roles and channels are kept)
    assert len([r for r in fake.requests if re.fullmatch(r"/api/v10/guilds/\d+(/channels|/threads/active)?", r)]) <= 3


def test_who_reacted_is_fetched_for_the_recent_messages_only_by_default(fake, world, tmp_path):
    channel = biggest(world)
    with_reactions = [m for m in channel.messages if m.get("reactions")]
    assert len(with_reactions) > 10
    for mode, expected_all in (("none", 0), ("all", len([r for m in with_reactions for r in m["reactions"]]))):
        fake.requests.clear()
        exporter(fake, reactions=mode).export(channel.id, tmp_path / mode)
        assert asked(fake, "/reactions/") == expected_all
    fake.requests.clear()
    now = datetime.now(UTC)
    ages = sorted((now - datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))).total_seconds() / 86400 for m in with_reactions)
    days = ages[len(ages) // 2]                                                  # the middle one: some messages are recent, some are not
    (path,) = exporter(fake, reactions="recent", reactions_days=days).export(channel.id, tmp_path / "recent")
    age = lambda m: (datetime.now(UTC) - datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))).total_seconds() / 86400  # noqa: E731
    recent = [m for m in read(path)["messages"] if "reactions" in m and age(m) <= days - 0.01]
    old = [m for m in read(path)["messages"] if "reactions" in m and age(m) > days + 0.01]
    assert recent and old
    assert all("userIds" in r for m in recent for r in m["reactions"]) and not any("userIds" in r for m in old for r in m["reactions"])        # counted, nobody named
    assert all(r["count"] > 0 for m in old for r in m["reactions"])


def test_a_person_who_left_has_no_profile_and_is_asked_once(fake, world, tmp_path):
    channel = biggest(world)
    author = channel.messages[0]["authorId"]
    fake.ex_members.add(author)
    ex = exporter(fake, reactions="none")
    document = read(ex.export(channel.id, tmp_path)[0])
    user = next(u for u in document["users"] if u["id"] == author)
    assert "roleIds" not in user and "nickname" not in user                      # nothing invented
    assert asked(fake, f"/members/{author}") == 1


def test_when_the_bot_may_not_look_people_up_the_export_goes_on_without_profiles(fake, world, tmp_path):
    fake.forbidden_members = True
    ex = exporter(fake, reactions="none")
    document = read(ex.export(biggest(world).id, tmp_path)[0])
    assert document["messages"] and not any("roleIds" in u for u in document["users"])
    assert 1 <= asked(fake, "/members/") <= ex.workers                           # asked at once by the workers, then never again for this server


# --- stopping, and failing --------------------------------------------------------------------------------------------------------


def test_stopping_ends_the_requests_quickly(fake, world, tmp_path):
    fake.latency = 0.2
    stop = threading.Event()
    threading.Timer(0.6, stop.set).start()
    started = time.monotonic()
    with pytest.raises(ExporterCancelled):
        exporter(fake).export(biggest(world).id, tmp_path, cancel=stop)
    assert time.monotonic() - started < 4 and not list(tmp_path.glob("*.json"))      # nothing is imported from a stopped export


def test_an_export_that_takes_too_long_is_stopped_in_words(fake, world, tmp_path):
    fake.latency = 0.05
    with pytest.raises(ExporterError, match="a pris plus de 0 s"):
        Exporter(TOKEN, fake.api_url, timeout=0.01).export(biggest(world).id, tmp_path)


def test_a_channel_that_cannot_be_read_is_said(fake, world, tmp_path):
    channel = biggest(world)
    fake.forbidden_channels.add(str(channel.id))
    with pytest.raises(Forbidden, match="refuse l'accès"):
        exporter(fake).export(channel.id, tmp_path)
    with pytest.raises(NotFound, match="Introuvable"):
        exporter(fake).export(42424242, tmp_path)
    next(c for c in world.channels)
    assert not list(tmp_path.glob("*.json"))


def test_the_settings_build_the_exporter(fake):
    import dataclasses

    from synthetic import settings_for

    class Settings:
        discord_token, discord_api_url, export_workers, export_reactions, export_reactions_days = TOKEN, fake.api_url, 3, "none", 7

    ex = Exporter.from_settings(Settings)
    assert (ex.workers, ex.reactions, ex.reactions_days) == (3, "none", 7)
    with pytest.raises(ValueError):
        Exporter(TOKEN, fake.api_url, reactions="sometimes")


def test_the_command_line_exports_a_channel(fake, world, tmp_path, monkeypatch, capsys):
    from dindon.__main__ import main

    channel = biggest(world)
    monkeypatch.setenv("DISCORD_TOKEN", TOKEN)
    monkeypatch.setenv("DINDON_DISCORD_API", fake.api_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@127.0.0.1:9/x")
    monkeypatch.setattr("sys.argv", ["dindon", "export", str(channel.id), "--out", str(tmp_path / "out"), "--reactions", "none"])
    with pytest.raises(SystemExit) as stop:
        main()
    assert stop.value.code == 0
    files = list((tmp_path / "out").glob("*.json"))
    assert len(files) == 1 and read(files[0])["messageCount"] == len(channel.messages)
    out = capsys.readouterr().out
    assert f"{len(channel.messages)} messages in 1 file(s)" in out and TOKEN not in out
    monkeypatch.setattr("sys.argv", ["dindon", "export", "424242", "--out", str(tmp_path / "x")])
    with pytest.raises(SystemExit) as stop:
        main()
    assert stop.value.code == 1 and "Export impossible" in capsys.readouterr().err
    monkeypatch.setattr("sys.argv", ["dindon", "export", str(channel.id), "--filter", "content:x", "--out", str(tmp_path / "y")])
    with pytest.raises(SystemExit) as stop:
        main()
    assert stop.value.code == 1 and "n'est pas compris" in capsys.readouterr().err


def test_a_bot_without_the_message_content_intent_is_told_instead_of_recording_empty_messages(world, tmp_path):
    server = FakeDiscord(world, token=TOKEN, bot=True).start()
    try:
        server.message_content = False
        with pytest.raises(ExporterError, match="Message Content Intent"):
            Exporter(TOKEN, server.api_url).export(biggest(world).id, tmp_path)
        assert not list(tmp_path.glob("*.json"))
        server.message_content = True
        assert Exporter(TOKEN, server.api_url).export(biggest(world).id, tmp_path / "ok")
    finally:
        server.stop()
