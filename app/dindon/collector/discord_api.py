"""The few read-only requests that the watcher makes itself (the exporter does the rest): is anything new?

`GET /guilds/{id}/channels` gives the id of the latest message of each channel, so that nothing has to be
downloaded to know which channels moved. A bot can also list the active threads of a server in one request;
an account cannot (see the exporter), so with an account the threads are picked up with their parent channel
and by the nightly catch-up.
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

TEXT_TYPES = {0, 2, 5, 13}   # text, voice (it has a chat), announcement, stage
FORUM_TYPES = {15, 16}       # forum, media: they only contain posts, and a post is a thread
THREAD_TYPES = {10, 11, 12}


class DiscordError(Exception):
    """A refusal that waiting will not fix (wrong token, no access)."""


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after


@dataclass(frozen=True)
class Watched:
    id: int
    name: str
    kind: str                # 'text', 'forum' or 'thread'
    parent_id: int | None
    last_message_id: int | None


class DiscordAPI:
    def __init__(self, base_url: str, token: str, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self.token = token[4:] if token.startswith("Bot ") else token
        self.timeout = timeout
        self.token_kind: str | None = "bot" if token.startswith("Bot ") else None  # 'bot' or 'account'

    def _get(self, path: str, authorization: str) -> tuple[int, object]:
        request = urllib.request.Request(f"{self.base_url}{path}", headers={"Authorization": authorization, "User-Agent": "dindon"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise RateLimited(float(error.headers.get("Retry-After") or 5)) from None
            return error.code, None

    def resolve_kind(self) -> str:
        """Account or bot? Same method as the exporter: try as an account, then as a bot."""
        if self.token_kind is None:
            if self._get("/users/@me", self.token)[0] != 401:
                self.token_kind = "account"
            elif self._get("/users/@me", f"Bot {self.token}")[0] != 401:
                self.token_kind = "bot"
            else:
                raise DiscordError("the token is not valid")
        return self.token_kind

    def _json(self, path: str) -> object:
        authorization = f"Bot {self.token}" if self.resolve_kind() == "bot" else self.token
        status, body = self._get(path, authorization)
        if status in (401, 403):
            raise DiscordError(f"access refused ({status}) for {path.split('?')[0]}")
        if status != 200:
            raise DiscordError(f"unexpected answer {status} for {path.split('?')[0]}")
        return body

    @staticmethod
    def _watched(raw: dict) -> Watched | None:
        kind_of = {**{t: "text" for t in TEXT_TYPES}, **{t: "forum" for t in FORUM_TYPES}, **{t: "thread" for t in THREAD_TYPES}}
        kind = kind_of.get(raw.get("type"))
        if kind is None:
            return None
        last = raw.get("last_message_id")
        return Watched(int(raw["id"]), raw.get("name", ""), kind, int(raw["parent_id"]) if raw.get("parent_id") else None,
                       int(last) if last else None)

    def channels(self, guild_id: int) -> list[Watched]:
        return [w for raw in self._json(f"/guilds/{guild_id}/channels") if (w := self._watched(raw))]  # type: ignore[union-attr]

    def active_threads(self, guild_id: int) -> list[Watched]:
        """Bots only. For an account this is empty (see the module's description)."""
        if self.resolve_kind() != "bot":
            return []
        return [w for raw in self._json(f"/guilds/{guild_id}/threads/active")["threads"] if (w := self._watched(raw))]  # type: ignore[index]
