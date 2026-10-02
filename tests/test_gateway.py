"""The Gateway connection (discord.py), against a fake Discord (tools/fake_gateway.py) that speaks the protocol.

Level of proof: SIMULATED. discord.py is the real library, the other end is a fake: this shows that the bot asks for the minimum,
keeps the order of the events, resumes after a lost connection without losing or doubling anything, tells a fatal error from a
passing one, and never writes the token anywhere. It does not show how the real Discord behaves.
"""
import asyncio
import logging

import aiohttp
import discord
import pytest

from dindon.bot.gateway import FatalGatewayError, GatewayEvent, GatewaySource
from fake_gateway import FakeGateway
from gateway_fixtures import GENERAL, GUILD, guild_create, message_create

TOKEN = "fake-token-that-must-never-be-logged-0123456789"
GUILDS = 1 << 0
GUILD_MESSAGES = 1 << 9
MESSAGE_CONTENT = 1 << 15


class Harness:
    """A fake Discord, a GatewaySource connected to it, and a way to wait for what comes out of the queue."""

    def __init__(self, **fake):
        self.fake = FakeGateway(TOKEN, guilds=[guild_create()])
        for key, value in fake.items():
            setattr(self.fake, key, value)
        self.seen: list[GatewayEvent] = []

    async def __aenter__(self):
        await self.fake.start()
        self.source = GatewaySource(TOKEN, api_url=self.fake.api_url, gateway_url=self.fake.gateway_url, retry_seconds=(0.05,))
        self.task = asyncio.create_task(self.source.run())
        return self

    async def __aexit__(self, *exc):
        await self.source.close()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        await self.fake.stop()

    async def next(self, wanted, timeout: float = 10):
        """The next event for which `wanted(event)` is true (the ones before it are kept in `seen`)."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0 or self.task.done() and self.source.events.empty():
                error = self.task.exception() if self.task.done() and not self.task.cancelled() else None
                raise AssertionError(f"the event never came (seen: {[(e.kind, e.type) for e in self.seen]}, source stopped with: {error!r})")
            try:
                event = await asyncio.wait_for(self.source.events.get(), min(left, 0.5))
            except asyncio.TimeoutError:
                continue
            self.seen.append(event)
            if wanted(event):
                return event

    def message(self, event: GatewayEvent, mid: str) -> bool:
        return event.type == "MESSAGE_CREATE" and event.data["id"] == mid


def is_(kind: str, type: str = ""):
    return lambda e: e.kind == kind and (not type or e.type == type)


def run(coroutine):
    return asyncio.run(coroutine)


def test_the_bot_asks_for_the_minimum_and_the_token_is_never_logged(caplog):
    caplog.set_level(logging.DEBUG)  # even with every logger as talkative as can be

    async def scenario():
        async with Harness() as h:
            await h.next(is_("dispatch", "GUILD_CREATE"))
            await h.fake.dispatch("MESSAGE_CREATE", message_create(1, "bonjour"))
            await h.next(lambda e: h.message(e, "1"))
            return h.fake.identifies[0]

    identify = run(scenario())
    # servers (roles, channels, threads) and messages with their content: not the members, not the presences, not the reactions
    assert identify["intents"] == GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT
    assert TOKEN not in caplog.text
    assert "bonjour" not in caplog.text  # nor the messages themselves, whatever the level


def test_events_come_out_in_the_order_of_the_gateway_as_plain_dictionaries():
    async def scenario():
        async with Harness() as h:
            created = await h.next(is_("dispatch", "GUILD_CREATE"))
            for number in range(1, 6):
                await h.fake.dispatch("MESSAGE_CREATE", message_create(number, f"message {number}"))
            await h.next(lambda e: h.message(e, "5"))
            return created, [e for e in h.seen if e.type == "MESSAGE_CREATE"], [(e.kind, e.type) for e in h.seen][:3]

    created, messages, first = run(scenario())
    # the frame of READY comes before the library says it is connected, then the description of the server
    assert first == [("dispatch", "READY"), ("connected", ""), ("dispatch", "GUILD_CREATE")]
    assert [m.data["id"] for m in messages] == ["1", "2", "3", "4", "5"]
    assert messages[0].data["content"] == "message 1" and isinstance(messages[0].data, dict)
    assert {r["id"] for r in created.data["roles"]} >= {"300", "301", "302"} and created.data["channels"][1]["id"] == GENERAL


@pytest.mark.parametrize("how", ["drop", "reconnect"])
def test_a_lost_connection_is_resumed_and_what_was_missed_arrives_exactly_once(how):
    async def scenario():
        async with Harness() as h:
            await h.next(is_("dispatch", "GUILD_CREATE"))
            first = await h.fake.dispatch("MESSAGE_CREATE", message_create(1, "avant"))
            await h.next(lambda e: h.message(e, "1"))
            if how == "drop":
                await h.fake.drop()
                await h.next(is_("disconnected"))
                await h.fake.dispatch("MESSAGE_CREATE", message_create(2, "pendant la coupure"))  # nobody is connected
            else:
                await h.fake.reconnect()
                await h.next(is_("disconnected"))
                await h.fake.dispatch("MESSAGE_CREATE", message_create(2, "pendant la coupure"))
            await h.next(lambda e: h.message(e, "2"))
            await h.next(is_("resumed"))
            await h.fake.dispatch("MESSAGE_CREATE", message_create(3, "après"))
            await h.next(lambda e: h.message(e, "3"))
            return h, first

    h, first = run(scenario())
    assert len(h.fake.identifies) == 1 and len(h.fake.resumes) == 1          # one session, resumed: not a new one
    assert h.fake.resumes[0]["session_id"] == "session-1" and h.fake.resumes[0]["seq"] == first
    ids = [e.data["id"] for e in h.seen if e.type == "MESSAGE_CREATE"]
    assert ids == ["1", "2", "3"]                                              # nothing lost, nothing twice
    assert [e.kind for e in h.seen if e.kind != "dispatch"] == ["connected", "disconnected", "resumed"]


def test_an_invalidated_session_starts_a_new_one_and_says_so():
    async def scenario():
        async with Harness() as h:
            await h.next(is_("connected"))
            await h.next(is_("dispatch", "GUILD_CREATE"))
            await h.fake.invalidate_session()
            await h.next(is_("connected"))                                    # a second 'connected': a new session, so a possible gap
            await h.next(is_("dispatch", "GUILD_CREATE"))                     # and the description of the servers again
            return h

    h = run(scenario())
    assert len(h.fake.identifies) == 2 and h.fake.resumes == []              # identified again, did not try to resume


def test_a_refused_token_is_fatal_and_is_not_tried_again():
    async def scenario():
        h = Harness(me_status=401)
        async with h:
            with pytest.raises(FatalGatewayError) as error:
                await h.task
            return h, str(error.value)

    h, message = run(scenario())
    assert "BOT" in message and "personal account" in message
    assert TOKEN not in message
    assert h.fake.rest == ["GET /users/@me"] and h.fake.connections == 0  # refused at the very first request


def test_a_missing_message_content_intent_is_fatal_and_says_what_to_switch_on():
    async def scenario():
        h = Harness(identify_close_code=4014)
        async with h:
            with pytest.raises(FatalGatewayError) as error:
                await h.task
            return h, str(error.value)

    h, message = run(scenario())
    assert "Message Content Intent" in message and TOKEN not in message
    assert h.fake.connections == 1 and len(h.fake.identifies) == 1          # no loop of attempts


def test_when_discord_cannot_be_reached_it_tries_again_and_goes_on(monkeypatch):
    attempts = []
    original = discord.Client.start

    async def flaky(self, token, *, reconnect=True):
        attempts.append(1)
        if len(attempts) <= 2:
            raise aiohttp.ClientConnectionError(f"cannot connect with {token}")
        return await original(self, token, reconnect=reconnect)

    monkeypatch.setattr(discord.Client, "start", flaky)

    async def scenario():
        async with Harness() as h:
            await h.next(is_("dispatch", "GUILD_CREATE"))
            return h

    run(scenario())
    assert len(attempts) == 3


def test_closing_ends_the_run_quietly():
    async def scenario():
        async with Harness() as h:
            await h.next(is_("dispatch", "GUILD_CREATE"))
            await h.source.close()
            await asyncio.wait_for(h.task, 10)
            return h.task.exception()

    assert run(scenario()) is None


def test_a_queue_that_is_full_loses_the_newest_loudly_not_silently(caplog):
    source = GatewaySource(TOKEN, queue_size=2)
    for number in range(5):
        source._put(GatewayEvent("dispatch", "MESSAGE_CREATE", {"id": str(number)}))
    assert source.events.qsize() == 2 and source.dropped == 3
    assert "queue of events is full" in caplog.text and TOKEN not in caplog.text
