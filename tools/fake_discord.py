"""A fake Discord, to test the watcher without Discord, a token or any real data.

It serves the few requests that the watcher makes (`/users/@me`, the channels and active threads of a server) from an
invented server (make_demo_server.World), plus `/_fake/export`, which the fake exporter (tools/fake_exporter.py) uses to
produce exports, and `/_fake/post`, to make someone write a message while the system is running.

    python tools/fake_discord.py --port 8765        # then, in .env:  DINDON_DISCORD_API=http://127.0.0.1:8765/api/v10
                                                    #   DISCORD_TOKEN=fake-token  DINDON_EXPORTER="python tools/fake_exporter.py"
                                                    #   FAKE_DISCORD_URL=http://127.0.0.1:8765  DINDON_GUILD_IDS=<printed id>
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from make_demo_server import World, iso

API = "/api/v10"


class FakeDiscord:
    def __init__(self, world: World, token: str = "fake-token", bot: bool = False, port: int = 0):
        self.world, self.token, self.bot = world, token, bot
        self.requests: list[str] = []          # every path asked, for assertions
        self._lock = threading.Lock()
        self._rate_limit = (0, 0.0)            # (requests to refuse, Retry-After)
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

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(url.query)
                with outer._lock:
                    outer.requests.append(self.path)
                    refused, retry_after = outer._rate_limit
                    if refused and url.path.startswith(API):
                        outer._rate_limit = (refused - 1, retry_after)
                        return self._send(429, {"message": "You are being rate limited.", "retry_after": retry_after}, {"Retry-After": str(retry_after)})
                    if url.path.startswith("/_fake/export"):
                        return self._export(query)
                    if not self._authorized():
                        return self._send(401, {"message": "401: Unauthorized"})
                    guild = str(outer.world.guild_id)
                    if url.path == f"{API}/users/@me":
                        return self._send(200, {"id": "1", "username": "fake"})
                    if url.path == f"{API}/guilds/{guild}/channels":
                        return self._send(200, outer.world.channel_listing())
                    if url.path == f"{API}/guilds/{guild}/threads/active":
                        if not outer.bot:
                            return self._send(403, {"message": "Missing Access"})
                        return self._send(200, {"threads": [{"id": str(c.id), "type": 11, "name": c.name, "parent_id": str(c.parent_id),
                                                             "last_message_id": c.last_message_id} for c in outer.world.channels if c.parent_id]})
                    return self._send(404, {"message": "Unknown"})

            def _export(self, query):
                if self.headers.get("Authorization") != outer.token:
                    return self._send(401, {"message": "bad token"})
                channel = next((c for c in outer.world.channels if str(c.id) == query["channel"][0]), None)
                if channel is None:
                    return self._send(404, {"message": "Unknown Channel"})
                after = int(query["after"][0]) if "after" in query else None
                text = outer.world.export_document(channel, after_id=after, exported_at=datetime.now(timezone.utc))
                self._send(200, text, raw=True)

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

    def start(self) -> "FakeDiscord":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def rate_limit_next(self, requests: int, retry_after: float = 1.0) -> None:
        with self._lock:
            self._rate_limit = (requests, retry_after)

    def post(self, channel, author, content: str, reply_to_id: str | None = None) -> dict:
        """Someone writes a message now (a reply, if `reply_to_id` is given)."""
        with self._lock:
            reply_to = next((m for m in channel.messages if m["id"] == str(reply_to_id)), None) if reply_to_id else None
            when = datetime.now(timezone.utc)
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
    world.generate(args.messages, days=30, end=datetime.now(timezone.utc))
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
