"""A fake Discord, to test the watcher and the exporter without Discord, a token or any real data.

It serves, from an invented server (make_demo_server.World), the requests that Dindon makes: `/users/@me`, the server, its channels and active threads, a
channel, **the messages of a channel** (`after`, `before`, `limit`, newest first in a page, as Discord does), the profile of a member, and the people who
reacted. Plus `/_fake/post`, to make someone write a message while the system is running.

Behaviours to provoke what goes wrong: `latency` (seconds per request), `rate_limit_next` (the next requests get a 429), `fail_next(n, status)` (the next requests
of messages get this error), `forbidden_channels`, `forbidden_members`, `ex_members` (people who left: their profile is a 404).

    python tools/fake_discord.py --port 8765        # then, in .env:  DINDON_DISCORD_API=http://127.0.0.1:8765/api/v10
                                                    #   DISCORD_TOKEN=fake-token  DINDON_GUILD_IDS=<printed id>
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import threading
import time
import urllib.parse
from datetime import datetime, UTC
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from make_demo_server import World
from rest_payloads import category_objects, channel_object, member_object, message_object, role_object, user_object

API = "/api/v10"


class FakeDiscord:
    def __init__(self, world: World, token: str = "fake-token", bot: bool = False, port: int = 0):
        self.world, self.token, self.bot = world, token, bot
        self.requests: list[str] = []          # every path asked, for assertions
        self.bot_public = True                 # the "Public Bot" setting of the application
        self.other_servers: list[dict] = []    # servers where the bot is, next to the invented one: [{"id": "...", "name": "..."}]
        self._lock = threading.Lock()
        self._rate_limit = (0, 0.0)            # (requests to refuse, Retry-After)
        self.latency = 0.0                     # seconds that each request takes
        self.message_content = True            # the « Message Content Intent » of the bot: without it, messages come without their text
        self.forbidden_channels: set[str] = set()
        self.forbidden_members = False         # the bot may not look people up
        self.ex_members: set[str] = set()      # ids of people who left the server: their profile is a 404
        self.permissions = 66560               # what the bot may do in each server (view channels + read the history), as Discord's bit field
        self.commands: list[str] = ["dindon"]  # the global slash commands of the application
        self._fail = (0, 500)                  # (requests of messages to fail, the status)
        self._ids: dict[int, tuple[int, list[int]]] = {}   # channel -> (number of messages, their ids) for paging quickly
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, status: int, body, headers: dict | None = None, raw: bool = False):
                data = body.encode() if raw else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self) -> bool:
                expected = f"Bot {outer.token}" if outer.bot else outer.token
                return self.headers.get("Authorization") == expected

            def _headers(self) -> dict:
                return {"X-RateLimit-Remaining": "5", "X-RateLimit-Reset-After": "1.0"}

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                if outer.latency:
                    time.sleep(outer.latency)
                with outer._lock:
                    outer.requests.append(self.path)
                    refused, retry_after = outer._rate_limit
                    if refused and url.path.startswith(API):
                        outer._rate_limit = (refused - 1, retry_after)
                        return self._send(429, {"message": "You are being rate limited.", "retry_after": retry_after, "global": False}, {"Retry-After": str(retry_after)})
                    if not self._authorized():
                        return self._send(401, {"message": "401: Unauthorized"})
                    return self._route(url.path, query)

            def _route(self, path: str, query: dict):
                world = outer.world
                guild = str(world.guild_id)
                if path == f"{API}/users/@me":
                    return self._send(200, {"id": "1", "username": "fake"})
                if path == f"{API}/oauth2/applications/@me":
                    if not outer.bot:
                        return self._send(401, {"message": "401: Unauthorized"})
                    return self._send(200, {"id": "424242424242424242", "name": "Dindon (faux)", "bot_public": outer.bot_public,
                                            "flags": (1 << 18) if outer.message_content else 0})
                if path == f"{API}/users/@me/guilds":
                    return self._send(200, [{"id": guild, "name": world.name, "permissions": str(outer.permissions)}, *outer.other_servers])
                if path == f"{API}/gateway":
                    return self._send(200, {"url": "wss://gateway.invalid"})
                if (m := re.fullmatch(rf"{API}/applications/(\d+)/commands", path)):
                    return self._send(200, [{"name": name} for name in outer.commands])
                if path == f"{API}/guilds/{guild}":
                    return self._send(200, {"id": guild, "name": world.name, "icon": None, "roles": [role_object(r) for r in world.roles.values()],
                                            "approximate_member_count": len(world.people), "approximate_presence_count": 3})
                if path == f"{API}/guilds/{guild}/channels":
                    return self._send(200, [*category_objects(world), *[channel_object(world, c) for c in world.channels if not c.parent_id]])
                if path == f"{API}/guilds/{guild}/threads/active":
                    if not outer.bot:
                        return self._send(403, {"message": "Missing Access"})
                    return self._send(200, {"threads": [channel_object(world, c) for c in world.channels if c.parent_id]})
                if (m := re.fullmatch(rf"{API}/guilds/{guild}/members/(\d+)", path)):
                    if outer.forbidden_members:
                        return self._send(403, {"message": "Missing Access"})
                    person = next((p for p in world.people if str(p.id) == m[1]), None)
                    if person is None or m[1] in outer.ex_members:
                        return self._send(404, {"message": "Unknown Member", "code": 10007})
                    return self._send(200, {**member_object(person), "user": user_object(person)})
                if (m := re.fullmatch(rf"{API}/channels/(\d+)", path)):
                    channel = outer._channel(m[1])
                    return self._send(404, {"message": "Unknown Channel"}) if channel is None else self._send(200, channel_object(world, channel), self._headers())
                if (m := re.fullmatch(rf"{API}/channels/(\d+)/threads/archived/public", path)):
                    return self._send(200, {"threads": [], "has_more": False})
                if (m := re.fullmatch(rf"{API}/channels/(\d+)/messages", path)):
                    return self._messages(m[1], query)
                if (m := re.fullmatch(rf"{API}/channels/(\d+)/messages/(\d+)/reactions/(.+)", path)):
                    return self._reactors(m[1], m[2], urllib.parse.unquote(m[3]), query)
                return self._send(404, {"message": "Unknown"})

            def _messages(self, channel_id: str, query: dict):
                channel = outer._channel(channel_id)
                if channel is None:
                    return self._send(404, {"message": "Unknown Channel"})
                if channel_id in outer.forbidden_channels:
                    return self._send(403, {"message": "Missing Access"})
                failing, status = outer._fail
                if failing:
                    outer._fail = (failing - 1, status)
                    return self._send(status, {"message": "Internal error"})
                ids = outer._ids_of(channel)
                limit = min(int(query.get("limit", 50)), 100)
                if "after" in query:                       # the `limit` messages that come right after: Discord gives them newest first
                    start = bisect.bisect_right(ids, int(query["after"]))
                    chosen = channel.messages[start:start + limit][::-1]
                elif "before" in query:
                    end = bisect.bisect_left(ids, int(query["before"]))
                    chosen = channel.messages[max(0, end - limit):end][::-1]
                else:
                    chosen = channel.messages[-limit:][::-1]
                payloads = [message_object(outer.world, channel, e) for e in chosen]
                if not outer.message_content:                  # a bot without the intent: no text, no attachments, nothing
                    payloads = [{**p, "content": "", "attachments": [], "embeds": [], "mentions": []} for p in payloads]
                self._send(200, payloads, self._headers())

            def _reactors(self, channel_id: str, message_id: str, emoji: str, query: dict):
                found = outer.world.msg_index.get(message_id)
                if found is None or str(found[0].id) != channel_id:
                    return self._send(404, {"message": "Unknown Message"})
                key = emoji.partition(":")[2] if ":" in emoji else emoji
                reaction = next((r for r in found[1].get("reactions", []) if r["emoji"] == key), None)
                if reaction is None:
                    return self._send(404, {"message": "Unknown Emoji"})
                users = sorted(reaction["userIds"], key=int)
                if "after" in query:
                    users = [u for u in users if int(u) > int(query["after"])]
                self._send(200, [user_object(outer.world.person_by_id(u)) for u in users[:int(query.get("limit", 25))]], self._headers())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path != "/_fake/post":
                    return self._send(404, {})
                channel = next(c for c in outer.world.channels if str(c.id) == str(body["channel"]))
                message = outer.post(channel, outer.world.person_by_id(body["author"]), body.get("content", "message"), body.get("reply_to"))
                self._send(200, {"id": message["id"]})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    # --- control, for the tests and for the demo ---------------------------------------------------

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{API}"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> FakeDiscord:
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _channel(self, channel_id: str):
        return next((c for c in self.world.channels if str(c.id) == str(channel_id)), None)

    def _ids_of(self, channel) -> list[int]:
        count, ids = self._ids.get(channel.id, (-1, []))
        if count != len(channel.messages):
            ids = [int(m["id"]) for m in channel.messages]
            self._ids[channel.id] = (len(channel.messages), ids)
        return ids

    def fail_next(self, requests: int, status: int = 500) -> None:
        """The next `requests` requests for messages are answered with this error."""
        with self._lock:
            self._fail = (requests, status)

    def rate_limit_next(self, requests: int, retry_after: float = 1.0) -> None:
        with self._lock:
            self._rate_limit = (requests, retry_after)

    def post(self, channel, author, content: str, reply_to_id: str | None = None) -> dict:
        """Someone writes a message now (a reply, if `reply_to_id` is given)."""
        with self._lock:
            reply_to = next((m for m in channel.messages if m["id"] == str(reply_to_id)), None) if reply_to_id else None
            when = datetime.now(UTC)
            if channel.messages:
                from make_demo_server import parse_iso
                from datetime import timedelta
                when = max(when, parse_iso(channel.messages[-1]["timestamp"]) + timedelta(milliseconds=1))
            return self.world.post(channel, author, content, when, reply_to=reply_to)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--people", type=int, default=40)
    parser.add_argument("--messages", type=int, default=3000)
    parser.add_argument("--bot", action="store_true", help="the token is a bot token (default: an account token)")
    parser.add_argument("--talk", action="store_true", help="make people write a message every few seconds, to see the map move")
    args = parser.parse_args()
    world = World(seed=3, people=args.people)
    world.generate(args.messages, days=30, end=datetime.now(UTC))
    server = FakeDiscord(world, bot=args.bot, port=args.port).start()
    print(f"fake Discord on {server.api_url}  (token: fake-token, server id: {world.guild_id})")
    import random
    rng = random.Random()
    try:
        while True:
            time.sleep(4)
            if args.talk:
                channel = rng.choice([c for c in world.channels if c.messages])
                recent = channel.messages[-1]
                author = rng.choice(world.people[:15])
                reply = recent["id"] if rng.random() < 0.7 and recent["authorId"] != str(author.id) else None
                server.post(channel, author, world._statement(author, channel.theme), reply)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
