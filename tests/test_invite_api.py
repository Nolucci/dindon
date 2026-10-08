"""Inviting the bot from the interface: the link, the servers where the bot is, and what is never said.

Level of proof: SIMULATED (fake Discord, real application). The real Discord has not been asked.
"""
import dataclasses
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from dindon.api.main import create_app
from fake_discord import FakeDiscord
from synthetic import settings_for
from test_collector import TOKEN, world  # noqa: F401 (fixture)

PASSWORD = "correct horse"


def client(settings):
    return TestClient(create_app(settings, background=False))


@pytest.fixture
def bot_discord(world):
    server = FakeDiscord(world, token=TOKEN, bot=True).start()
    server.other_servers = [{"id": "999000000000000001", "name": "Zèbre"}, {"id": "999000000000000002", "name": "abeille"}]
    yield server
    server.stop()


@pytest.fixture
def me(bot_discord, world, ingest_url, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=bot_discord.api_url, discord_token=TOKEN,
                                   guild_ids=(world.guild_id,))
    with client(settings) as app:
        assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield app


def test_the_invitation_needs_the_session(bot_discord, world, ingest_url, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=bot_discord.api_url, discord_token=TOKEN)
    with client(settings) as app:
        assert app.get("/api/bot/invite").status_code == 401


def test_the_link_asks_for_the_bot_scope_and_only_what_the_bot_needs(me):
    answer = me.get("/api/bot/invite").json()
    assert answer["kind"] == "bot" and answer["application"] == {"id": "424242424242424242", "name": "Dindon (faux)", "public": True}
    url = urlparse(answer["url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.scheme, url.netloc, url.path) == ("https", "discord.com", "/oauth2/authorize")
    assert query == {"client_id": "424242424242424242", "scope": "bot applications.commands", "permissions": str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 16) | (1 << 35) | (1 << 38) | (1 << 49))}
    assert answer["permissions"] == ["VIEW_CHANNEL", "SEND_MESSAGES", "EMBED_LINKS", "READ_MESSAGE_HISTORY", "CREATE_PUBLIC_THREADS", "SEND_MESSAGES_IN_THREADS", "SEND_POLLS"]
    assert not int(query["permissions"]) & ((1 << 3) | (1 << 13) | (1 << 29))                    # never administrator, never manage messages / webhooks


def test_the_servers_say_which_ones_are_followed(me, world):
    servers = me.get("/api/bot/invite").json()["servers"]
    assert [s["name"] for s in servers] == ["abeille", world.name, "Zèbre"]                 # alphabetical, ignoring case
    assert {s["id"]: s["following"] for s in servers} == {str(world.guild_id): True, "999000000000000001": False, "999000000000000002": False}


def test_the_token_is_never_in_the_answer(me):
    assert TOKEN not in me.get("/api/bot/invite").text


def test_without_a_token_nothing_is_asked_of_discord(bot_discord, world, ingest_url, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=bot_discord.api_url, discord_token="")
    with client(settings) as app:
        assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
        assert app.get("/api/bot/invite").json() == {"configured": False}
    assert bot_discord.requests == []


def test_an_account_cannot_be_invited_anywhere(world, ingest_url, tmp_path):
    account = FakeDiscord(world, token=TOKEN, bot=False).start()
    try:
        settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=account.api_url, discord_token=TOKEN)
        with client(settings) as app:
            assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
            answer = app.get("/api/bot/invite").json()
        assert answer["kind"] == "account" and answer["url"] is None and answer["application"] is None
    finally:
        account.stop()


def test_a_private_application_is_said_to_be_private(bot_discord, me):
    bot_discord.bot_public = False
    assert me.get("/api/bot/invite").json()["application"]["public"] is False


def test_a_refusal_of_discord_is_told_without_the_token(world, ingest_url, tmp_path):
    server = FakeDiscord(world, token="another-token", bot=True).start()
    try:
        settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), discord_api_url=server.api_url, discord_token=TOKEN)
        with client(settings) as app:
            assert app.post("/api/login", json={"password": PASSWORD}).status_code == 200
            answer = app.get("/api/bot/invite")
        assert answer.status_code == 502 and TOKEN not in answer.text
    finally:
        server.stop()


def test_a_rate_limit_is_told(bot_discord, me):
    bot_discord.rate_limit_next(1, retry_after=7)
    answer = me.get("/api/bot/invite")
    assert answer.status_code == 429 and "7 s" in answer.json()["detail"]
