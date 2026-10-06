"""DINDON_GUILD_IDS empty or "all": the bot follows every server that it is in. Level of proof: SIMULATED (fake Discord, real database)."""
import asyncio
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from dindon.api.main import create_app
from dindon.bot.adapter import Directory
from dindon.bot.runner import BotRunner, Writer
from dindon.config import _FOLLOWED, load_settings
from fake_discord import FakeDiscord
from gateway_fixtures import GUILD, guild_create, message_create
from synthetic import settings_for
from test_collector import TOKEN, world  # noqa: F401 (fixture)
from test_bot import create, event, messages


@pytest.fixture(autouse=True)
def fresh_cache():
    _FOLLOWED.clear()


@pytest.mark.parametrize("value, token, follow_all, ids", [
    ("", "t", True, ()), ("all", "t", True, ()), ("ALL", "t", True, ()), ("*", "t", True, ()),
    ("1, 2", "t", False, (1, 2)), ("", "", False, ()),                                    # a list stays a list; no token: nothing to follow
])
def test_the_setting_is_read(monkeypatch, tmp_path, value, token, follow_all, ids):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DINDON_GUILD_IDS", value)
    monkeypatch.setenv("DISCORD_TOKEN", token)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@127.0.0.1:9/x")
    settings = load_settings()
    assert settings.follow_all is follow_all and settings.guild_ids == ids


def test_with_all_the_followed_servers_are_the_ones_the_bot_is_in(world, ingest_url, tmp_path):
    bot = FakeDiscord(world, token=TOKEN, bot=True).start()
    bot.other_servers = [{"id": "999000000000000001", "name": "Un autre"}]
    try:
        settings = dataclasses.replace(settings_for(ingest_url, tmp_path), discord_api_url=bot.api_url, discord_token=TOKEN, follow_all=True)
        assert set(settings.followed()) == {world.guild_id, 999000000000000001}
        assert dataclasses.replace(settings, follow_all=False, guild_ids=(world.guild_id,)).followed() == (world.guild_id,)   # a list is a list
    finally:
        bot.stop()


def test_an_account_never_follows_everything(world, ingest_url, tmp_path):
    account = FakeDiscord(world, token=TOKEN, bot=False).start()
    try:
        settings = dataclasses.replace(settings_for(ingest_url, tmp_path), discord_api_url=account.api_url, discord_token=TOKEN, follow_all=True)
        assert settings.followed() == ()
    finally:
        account.stop()


def test_the_bot_without_a_list_records_every_server_it_is_in(ingest_db, ingest_url):
    runner = BotRunner(None, Writer(ingest_url), batch_seconds=0)
    runner.handle(event("GUILD_CREATE", guild_create()))
    runner.handle(create(message_create(1, "d'un serveur quelconque")))
    asyncio.run(runner.flush(True))
    assert messages(ingest_db) == {1: "d'un serveur quelconque"} and runner.stats["ignored_not_followed"] == 0
    assert runner.heartbeat_data()["follow_all"] is True and runner.heartbeat_data()["ready"] == [GUILD]


def test_the_invitation_says_that_inviting_is_enough(world, ingest_url, tmp_path):
    bot = FakeDiscord(world, token=TOKEN, bot=True).start()
    try:
        settings = dataclasses.replace(settings_for(ingest_url, tmp_path, "pw"), discord_api_url=bot.api_url, discord_token=TOKEN, follow_all=True)
        with TestClient(create_app(settings, background=False)) as client:
            client.post("/api/login", json={"password": "pw"})
            answer = client.get("/api/bot/invite").json()
        assert answer["follow_all"] is True and all(s["following"] for s in answer["servers"])
    finally:
        bot.stop()
