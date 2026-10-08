"""The connection to Discord's Gateway. This is the only module that imports discord.py, and it uses it for one thing:
keeping a connection alive (heartbeat, resume, reconnection, rate limits). It does not read what comes through.

discord.py hands over each frame of the Gateway as it arrived (`on_socket_raw_receive`), and this module puts the dispatched
events, as plain dictionaries, in a queue for the runner. Nothing of discord.py (its models, its caches) goes further, so
that the rest of Dindon does not depend on it and could use another library.

Minimum asked of Discord: the servers (roles, channels, threads) and the messages of the servers' channels, with their
content (a "privileged" intent that the owner of the bot switches on in the Developer Portal). Thread membership and poll votes are also received. Member lists are not downloaded;
presences, reactions and typing indicators are not requested.
"""
from __future__ import annotations

import asyncio
import json
import logging

import aiohttp
import discord
import yarl

from dindon.bot.events import FatalGatewayError, GatewayEvent  # noqa: F401 (re-exported: the engine reads them from here too)

log = logging.getLogger("dindon.bot")

# Gateway intent bits: GUILDS (1 << 0), GUILD_MESSAGES (1 << 9), MESSAGE_CONTENT (1 << 15)
INTENTS = discord.Intents.none()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.guild_polls = True
INTENTS.guild_messages = True
INTENTS.message_content = True

# When Discord cannot be reached at all (once connected, discord.py handles it). At most 5 minutes apart, so that even a failure
# that comes back at every start stays far under Discord's 1000 sessions a day.
CONNECT_RETRY_SECONDS = (5, 10, 30, 60, 120, 300)


class _NoFrames(logging.Filter):
    """discord.py's debug lines of the Gateway contain every frame, that is to say the messages: never let them out."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno > logging.DEBUG


class _NoVoiceWarning(logging.Filter):
    """discord.py warns at every start that voice is not supported. Dindon reads text: the warning only worries."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "voice will NOT be supported" not in record.getMessage()


def protect_logs() -> None:
    gateway_log = logging.getLogger("discord.gateway")
    if not any(isinstance(f, _NoFrames) for f in gateway_log.filters):
        gateway_log.addFilter(_NoFrames())
    client_log = logging.getLogger("discord.client")
    if not any(isinstance(f, _NoVoiceWarning) for f in client_log.filters):
        client_log.addFilter(_NoVoiceWarning())


class _Client(discord.Client):
    def __init__(self, source: GatewaySource):
        super().__init__(
            intents=INTENTS,
            max_messages=None,                                          # no cache of messages
            chunk_guilds_at_startup=False,                              # no download of the members lists
            member_cache_flags=discord.MemberCacheFlags.none(),
            enable_debug_events=True,                                   # needed for on_socket_raw_receive
        )
        self._source = source

    # These handlers do no await before putting the event in the queue: discord.py runs them in the order of the frames,
    # and so the queue keeps the order of the Gateway.
    async def on_socket_raw_receive(self, frame) -> None:
        self._source._frame(frame)

    async def on_connect(self) -> None:
        self._source._put(GatewayEvent("connected"))

    async def on_resumed(self) -> None:
        self._source._put(GatewayEvent("resumed"))

    async def on_disconnect(self) -> None:
        self._source._put(GatewayEvent("disconnected"))


class GatewaySource:
    """`await source.run()` keeps a Gateway connection and fills `source.events`; it returns when `close()` is called, and raises
    FatalGatewayError for what cannot be fixed by waiting. `api_url` and `gateway_url` are Discord's REST and Gateway addresses; they are
    only given in the tests, to talk to a fake Discord (discord.py always starts from its built-in Gateway address)."""

    def __init__(self, token: str, api_url: str | None = None, gateway_url: str | None = None, queue_size: int = 20_000,
                 retry_seconds: tuple[float, ...] = CONNECT_RETRY_SECONDS):
        protect_logs()
        self._token = token[4:] if token.startswith("Bot ") else token
        self._api_url = api_url
        self._gateway_url = gateway_url
        self._retry_seconds = retry_seconds
        self.events: asyncio.Queue[GatewayEvent] = asyncio.Queue(maxsize=queue_size)
        self.dropped = 0
        self._client: _Client | None = None
        self._closing = False

    # --- what the client calls ------------------------------------------------------------------------------------

    def _put(self, event: GatewayEvent) -> None:
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:  # the runner is far behind: a loud loss is better than an unbounded memory
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                log.error("the queue of events is full: %d dropped (the catch-up will bring them back)", self.dropped)

    def _frame(self, frame) -> None:
        try:
            payload = json.loads(frame)
        except (TypeError, ValueError):
            return
        if payload.get("op") == 0 and payload.get("t"):  # a dispatch: the only frames that carry what happens
            self._put(GatewayEvent("dispatch", payload["t"], payload.get("d")))

    # --- running ----------------------------------------------------------------------------------------------------

    def scrub(self, text: object) -> str:
        return str(text).replace(self._token, "***")

    async def run(self) -> None:
        if self._api_url:
            discord.http.Route.BASE = self._api_url.rstrip("/")
        if self._gateway_url:
            discord.gateway.DiscordWebSocket.DEFAULT_GATEWAY = yarl.URL(self._gateway_url)
        attempt = 0
        while not self._closing:
            client = self._client = _Client(self)
            try:
                await client.start(self._token)
                return  # closed on purpose
            except discord.LoginFailure:
                raise FatalGatewayError(
                    "Discord refused the token. DISCORD_TOKEN must be the token of a BOT (Developer Portal > Bot > Reset Token); "
                    "the token of a personal account cannot be used here.") from None
            except discord.PrivilegedIntentsRequired:
                raise FatalGatewayError(
                    "Discord refused the intents: switch on 'Message Content Intent' and 'Server Members Intent' for the bot "
                    "(Developer Portal > Bot > Privileged Gateway Intents), then start the bot again.") from None
            except discord.ConnectionClosed as error:
                if error.code in (4004, 4010, 4011, 4012, 4013, 4014):  # authentication failed, invalid shard/API/intents
                    raise FatalGatewayError(f"Discord closed the connection with code {error.code}: check the token and the intents of the bot.") from None
                reason = f"closed ({error.code})"
            except (TimeoutError, OSError, aiohttp.ClientError, discord.HTTPException, discord.GatewayNotFound) as error:
                reason = f"{type(error).__name__}: {self.scrub(error)}"[:200]
            except Exception as error:  # e.g. discord.py cannot read an event of a shape it does not know: start a new session
                reason = f"unexpected {type(error).__name__}: {self.scrub(error)}"[:200]
                log.error("the Gateway library failed (%s)", reason)
            finally:
                await client.close()
            if self._closing:
                return
            delay = self._retry_seconds[min(attempt, len(self._retry_seconds) - 1)]
            attempt += 1
            log.warning("cannot reach Discord (%s), trying again in %ss", reason, delay)
            await asyncio.sleep(delay)

    async def close(self) -> None:
        self._closing = True
        if self._client is not None:
            await self._client.close()
