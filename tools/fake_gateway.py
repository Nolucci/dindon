"""A fake Discord Gateway, to test the bot without Discord, a token or any real data.

It speaks the protocol that discord.py speaks (https://discord.com/developers/docs/events/gateway): HELLO, IDENTIFY then READY
and GUILD_CREATE, heartbeats, RESUME with a replay of what was missed, RECONNECT, INVALID_SESSION, and closing codes. It serves the
only REST request that a client makes to start (`/users/@me`). It records what the client sent (the intents, the token, the
resume requests), so that tests can look at it, and it can be made to misbehave in the ways that matter: drop the connection,
ask for a reconnection, invalidate the session, close with a code, refuse the token, fail a request.

    server = await FakeGateway("a-fake-token", guilds=[guild_payload]).start()
    GatewaySource("a-fake-token", api_url=server.api_url, gateway_url=server.gateway_url)

Everything runs in the event loop of the caller. Never any network beyond 127.0.0.1.
"""
from __future__ import annotations

import json

from aiohttp import WSMsgType, web

# What discord.py wants to find in a GUILD_CREATE, besides what a test cares about
GUILD_DEFAULTS = {
    "icon": None, "splash": None, "discovery_splash": None, "owner_id": "900", "afk_channel_id": None, "afk_timeout": 300,
    "verification_level": 0, "default_message_notifications": 0, "explicit_content_filter": 0, "emojis": [], "stickers": [],
    "features": [], "mfa_level": 0, "system_channel_id": None, "system_channel_flags": 0, "rules_channel_id": None,
    "vanity_url_code": None, "description": None, "banner": None, "premium_tier": 0, "premium_subscription_count": 0,
    "preferred_locale": "en-US", "public_updates_channel_id": None, "nsfw_level": 0, "premium_progress_bar_enabled": False,
    "large": False, "member_count": 1, "joined_at": "2024-01-01T00:00:00.000000+00:00", "voice_states": [], "members": [],
    "presences": [], "stage_instances": [], "guild_scheduled_events": [], "max_members": 100, "approximate_member_count": 1,
    "safety_alerts_channel_id": None, "application_id": None, "widget_enabled": False, "widget_channel_id": None,
}


class FakeGateway:
    def __init__(self, token: str = "fake-bot-token", guilds: list[dict] | None = None, bot_id: str = "900"):
        self.token = token
        self.guilds = [{**GUILD_DEFAULTS, **g} for g in (guilds or [])]
        self.bot = {"id": bot_id, "username": "dindon-test", "discriminator": "0", "global_name": None, "avatar": None, "bot": True,
                    "verified": True, "mfa_enabled": False, "flags": 0}
        # What a test can ask the server to do
        self.me_status = 200          # answer of /users/@me (401: the token is refused)
        self.me_failures = 0          # how many /users/@me are first answered with a 500
        self.identify_close_code: int | None = None   # close the connection with this code when the client identifies (4014: intent refused)
        # What a test can look at
        self.identifies: list[dict] = []
        self.resumes: list[dict] = []
        self.connections = 0
        self.rest: list[str] = []
        self.history: list[tuple[int, str, dict]] = []   # (sequence number, event, data) of everything dispatched
        self.api_url = self.gateway_url = ""
        self._seq = 0
        self._session = ""
        self._ws: web.WebSocketResponse | None = None
        self._runner: web.AppRunner | None = None

    # --- life -------------------------------------------------------------------------------------------------------

    async def start(self) -> FakeGateway:
        app = web.Application()
        app.router.add_get("/api/v10/users/@me", self._me)
        app.router.add_get("/api/v10/oauth2/applications/@me", self._application)   # discord.py asks for it right after logging in
        app.router.add_get("/ws", self._socket)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.api_url, self.gateway_url = f"http://127.0.0.1:{port}/api/v10", f"ws://127.0.0.1:{port}/ws"
        return self

    async def stop(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._runner is not None:
            await self._runner.cleanup()

    # --- REST -------------------------------------------------------------------------------------------------------

    @staticmethod
    def _json(body: dict, status: int = 200) -> web.Response:
        # discord.py only reads the answer as JSON if the type is exactly 'application/json' (no charset), as Discord sends it
        return web.Response(body=json.dumps(body).encode(), status=status, content_type="application/json")

    async def _me(self, request: web.Request) -> web.Response:
        self.rest.append("GET /users/@me")
        if self.me_failures > 0:
            self.me_failures -= 1
            return self._json({"message": "Internal error"}, 500)
        if self.me_status != 200 or request.headers.get("Authorization") != f"Bot {self.token}":
            return self._json({"message": "401: Unauthorized", "code": 0}, 401)
        return self._json(self.bot)

    async def _application(self, request: web.Request) -> web.Response:
        self.rest.append("GET /oauth2/applications/@me")
        return self._json({"id": self.bot["id"], "name": "dindon-test", "icon": None, "description": "", "bot_public": False,
                           "bot_require_code_grant": False, "owner": self.bot, "verify_key": "0" * 64, "flags": 0, "team": None})

    # --- the Gateway ------------------------------------------------------------------------------------------------

    async def _send(self, payload: dict) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.send_str(json.dumps(payload))

    async def dispatch(self, event: str, data: dict) -> int:
        """Sends an event (or keeps it, if nobody is connected, for a client that resumes). Returns its sequence number."""
        self._seq += 1
        self.history.append((self._seq, event, data))
        await self._send({"op": 0, "t": event, "s": self._seq, "d": data})
        return self._seq

    async def _socket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        self._ws = ws
        await ws.send_str(json.dumps({"op": 10, "d": {"heartbeat_interval": 30_000}}))
        async for message in ws:
            if message.type != WSMsgType.TEXT:
                continue
            frame = json.loads(message.data)
            op, data = frame["op"], frame.get("d")
            if op == 1:      # heartbeat
                await self._send({"op": 11})
            elif op == 2:    # IDENTIFY
                self.identifies.append(data)
                if self.identify_close_code:
                    await ws.close(code=self.identify_close_code, message=b"fake")
                    break
                self._session = f"session-{len(self.identifies)}"
                await self.dispatch("READY", {
                    "v": 10, "user": self.bot, "session_id": self._session, "resume_gateway_url": self.gateway_url,
                    "application": {"id": self.bot["id"], "flags": 0}, "guilds": [{"id": g["id"], "unavailable": True} for g in self.guilds]})
                for guild in self.guilds:
                    await self.dispatch("GUILD_CREATE", guild)
            elif op == 6:    # RESUME
                self.resumes.append(data)
                if data.get("session_id") == self._session and data.get("seq") is not None and data["seq"] <= self._seq:
                    for seq, event, payload in [h for h in self.history if h[0] > data["seq"]]:
                        await self._send({"op": 0, "t": event, "s": seq, "d": payload})
                    await self.dispatch("RESUMED", {})
                else:
                    await self._send({"op": 9, "d": False})
        if self._ws is ws:
            self._ws = None
        return ws

    # --- misbehaving ------------------------------------------------------------------------------------------------

    async def drop(self) -> None:
        """The connection is lost (the client resumes)."""
        if self._ws is not None:
            await self._ws.close(code=1001)

    async def reconnect(self) -> None:
        """Discord asks the client to reconnect (opcode 7)."""
        await self._send({"op": 7, "d": None})

    async def invalidate_session(self) -> None:
        """The session cannot be resumed (opcode 9): the client starts a new one, and what happened meanwhile is lost to it."""
        await self._send({"op": 9, "d": False})

    async def close_with(self, code: int) -> None:
        """Discord closes the connection with one of its codes (4004: wrong token, 4014: intent not allowed...)."""
        if self._ws is not None:
            await self._ws.close(code=code, message=b"fake")
