"""Dindon's own exporter: reads a channel (and its threads) from Discord's REST API and writes it as JSON v2 documents, the format of
docs/import-des-donnees.md, which the ingestion reads. It replaces the original exporter (DiscordChatExporter, a .NET program written for someone else's
needs): no second runtime in the image, no process to start, no files that Dindon does not use.

What makes it cheap, for what Dindon does with an export:

* **Only what is asked is downloaded**: `after` and `before` are passed to Discord (the watcher asks for the messages after the newest one it has), and the
  **filter** (people, mentions) is applied before anything else is fetched for a message.
* **Few requests**: 100 messages per request; a person's server profile (nickname, roles) is fetched **once** (kept for an hour, and shared by the
  channels exported at the same time), only for the people who **wrote**, were **mentioned** or were **replied to** (what the text of the messages and the roles
  of the authors need): people who only *reacted* are not looked up, and an ex-member costs one request, once.
* **Reactions**: the count of each reaction is always written; **who** reacted is one request per reaction, so it is fetched only for the recent
  messages by default (`reactions`: `recent` for `reactions_days` days, `all`, `none`). The links of the graph that come from reactions follow.
* **In parallel**: the requests for the members and the reactions of a page are sent while the next page is being read; one connection is kept open per
  thread; the rate limits of Discord are respected before they are hit (export/client.py).
* **Nothing half written**: a file appears in the folder complete (written to a temporary name, then renamed).

The same Exporter object is shared by all the channels that are exported at the same time: they share the rate limiter and the profiles already fetched.
"""
from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dindon.bot.adapter import Directory, build_document
from dindon.clock import utc_now
from dindon.collector.snowflake import created_at
from dindon.export.client import DiscordClient
from dindon.export.errors import ExporterCancelled, ExporterError, Forbidden, NotFound
from dindon.export.filters import compile_filter
from dindon.export.writer import write_document

PAGE = 100
GUILD_TTL = 600.0                 # seconds: roles and channels of a server are read again after that
MEMBER_TTL = 3600.0               # seconds: a person's profile in the server is read again after that
MESSAGE_CHANNELS = {0, 2, 5, 10, 11, 12, 13}     # text, voice, announcement, threads, stage: they have messages
FORUMS = {15, 16}                                # forum, media: they only contain posts, and a post is a thread


def _is_empty(message: dict) -> bool:
    return not (message.get("content") or message.get("attachments") or message.get("embeds") or message.get("sticker_items") or message.get("poll")
                or message.get("message_snapshots"))


@dataclass
class _Guild:
    directory: Directory
    at: float
    threads: dict[str, dict] = field(default_factory=dict)       # active threads by id


def _kept_in_page(page: list[dict], before: int | None, keep: Callable[[dict], bool]) -> tuple[list[dict], bool]:
    """The messages of a page (oldest first) that the filter keeps, and whether the page went past `before` (the export is then finished)."""
    wanted = []
    for message in page:
        if before and int(message["id"]) >= before:
            return wanted, True
        if keep(message):
            wanted.append(message)
    return wanted, False


class Exporter:
    def __init__(self, token: str, api_url: str = "https://discord.com/api/v10", *, workers: int = 6, reactions: str = "recent", reactions_days: int = 30,
                 timeout: float = 3600.0, client: DiscordClient | None = None, clock: Callable[[], float] = time.monotonic):
        if reactions not in ("all", "recent", "none"):
            raise ValueError("reactions: all, recent or none")
        self.client = client or DiscordClient(api_url, token)
        self.workers, self.reactions, self.reactions_days, self.timeout, self._clock = max(1, workers), reactions, reactions_days, timeout, clock
        self._guilds: dict[str, _Guild] = {}
        self._members: dict[tuple[str, str], tuple[float, dict | None]] = {}
        self._inflight: dict[tuple[str, str], Future] = {}
        self._no_members: set[str] = set()                        # servers where the bot may not look people up: not asked again
        self._intent_checked = False
        self._lock = threading.Lock()
        self.stats = {"messages": 0, "files": 0, "member_requests": 0, "reaction_requests": 0}

    @classmethod
    def from_settings(cls, settings) -> Exporter:
        return cls(settings.discord_token, settings.discord_api_url, workers=settings.export_workers, reactions=settings.export_reactions,
                   reactions_days=settings.export_reactions_days)

    # --- the server: roles and channels, kept for a few minutes ------------------------------------------------

    def _guild(self, guild_id: str, cancelled: Callable[[], bool]) -> _Guild:
        with self._lock:
            known = self._guilds.get(guild_id)
        if known and self._clock() - known.at < GUILD_TTL:
            return known
        data = self.client.get(f"/guilds/{guild_id}", cancel=cancelled)
        channels = self.client.get(f"/guilds/{guild_id}/channels", cancel=cancelled)
        threads: list[dict] = []
        with contextlib.suppress(Forbidden, NotFound):            # a bot lists the active threads in one request; an account cannot
            threads = self.client.get(f"/guilds/{guild_id}/threads/active", cancel=cancelled).get("threads", [])
        directory = Directory(None)
        directory.apply("GUILD_CREATE", {"id": guild_id, "name": data.get("name"), "icon": data.get("icon"), "roles": data.get("roles", []),
                                         "channels": channels, "threads": threads})
        guild = _Guild(directory, self._clock(), {str(t["id"]): t for t in threads})
        with self._lock:
            self._guilds[guild_id] = guild
        return guild

    # --- people ------------------------------------------------------------------------------------------------

    def _member(self, guild_id: str, user_id: str, cancelled: Callable[[], bool]) -> dict | None:
        if guild_id in self._no_members:                          # already refused for this server, while this one was waiting its turn
            return None
        try:
            member = self.client.get(f"/guilds/{guild_id}/members/{user_id}", cancel=cancelled)
        except NotFound:                                          # somebody who left: remembered, not asked again
            member = None
        except Forbidden:
            self._no_members.add(guild_id)
            return None
        self.stats["member_requests"] += 1
        with self._lock:
            self._members[(guild_id, user_id)] = (self._clock(), member)
        return member

    def _want_member(self, pool: ThreadPoolExecutor, guild_id: str, user_id: str, cancelled: Callable[[], bool]) -> None:
        key = (guild_id, user_id)
        with self._lock:
            cached = self._members.get(key)
            if guild_id in self._no_members or key in self._inflight or (cached and self._clock() - cached[0] < MEMBER_TTL):
                return
            future = self._inflight[key] = pool.submit(self._member, guild_id, user_id, cancelled)
        future.add_done_callback(lambda _f, k=key: self._inflight.pop(k, None))

    def _people_of(self, messages: list[dict]) -> set[str]:
        """The people whose profile in the server is useful: who wrote (a person, not a webhook), who is mentioned, who was replied to."""
        ids: set[str] = set()
        for m in messages:
            if not m.get("webhook_id"):
                ids.add(str(m["author"]["id"]))
            ids.update(str(u["id"]) for u in m.get("mentions", []))
            parent = m.get("referenced_message")
            if parent:
                if not parent.get("webhook_id"):
                    ids.add(str(parent["author"]["id"]))
                ids.update(str(u["id"]) for u in parent.get("mentions", []))      # (the text of what was replied to names them too)
        return ids

    def _attach_members(self, guild_id: str, messages: list[dict], cancelled: Callable[[], bool]) -> None:
        """Puts the profile of each person on the messages, as the Gateway does (the REST API does not)."""
        for key in [(guild_id, uid) for uid in self._people_of(messages)]:
            with self._lock:
                future = self._inflight.get(key)
            if future is not None:
                while True:
                    try:
                        future.result(timeout=0.25)
                        break
                    except TimeoutError:
                        if cancelled():
                            raise ExporterCancelled() from None
        with self._lock:
            profiles = {uid: m for (g, uid), (_, m) in self._members.items() if g == guild_id}
        for m in messages:
            if str(m["author"]["id"]) in profiles and not m.get("webhook_id"):
                m["member"] = profiles[str(m["author"]["id"])]
            for user in m.get("mentions", []):
                if str(user["id"]) in profiles:
                    user["member"] = profiles[str(user["id"])]
            parent = m.get("referenced_message")
            if parent:
                if str(parent["author"]["id"]) in profiles:
                    parent["member"] = profiles[str(parent["author"]["id"])]
                for user in parent.get("mentions", []):
                    if str(user["id"]) in profiles:
                        user["member"] = profiles[str(user["id"])]

    # --- reactions -----------------------------------------------------------------------------------------------

    def _wants_reactions(self, message: dict) -> bool:
        if self.reactions == "none" or not message.get("reactions"):
            return False
        if self.reactions == "all":
            return True
        age = (utc_now() - datetime.fromisoformat(message["timestamp"])).total_seconds()
        return age <= self.reactions_days * 86400

    def _reaction_users(self, channel_id: str, message_id: str, emoji: dict, cancelled: Callable[[], bool]) -> list[dict]:
        name = f"{emoji['name']}:{emoji['id']}" if emoji.get("id") else emoji["name"]
        users: list[dict] = []
        after = None
        while True:
            params = {"limit": PAGE, **({"after": after} if after else {})}
            try:
                page = self.client.get(f"/channels/{channel_id}/messages/{message_id}/reactions/{quote(name, safe='')}", params, cancel=cancelled)
            except NotFound:                                      # the reaction was removed meanwhile
                break
            self.stats["reaction_requests"] += 1
            users += page
            if len(page) < PAGE:
                break
            after = page[-1]["id"]
        return users

    # --- a bot without the Message Content intent gets messages without their text ----------------------------------

    def _ensure_message_content(self, cancelled: Callable[[], bool]) -> None:
        """Called when a whole page of messages is empty: a bot whose application does not have the « Message Content Intent » (Developer Portal, tab Bot)
        is given messages without their text, and an export of them would silently record empty messages."""
        if self._intent_checked:
            return
        flags = int((self.client.get("/applications/@me", cancel=cancelled) or {}).get("flags", 0))
        if not flags & ((1 << 18) | (1 << 19)):                   # GATEWAY_MESSAGE_CONTENT, GATEWAY_MESSAGE_CONTENT_LIMITED
            raise ExporterError("Les messages arrivent sans leur texte : activez « Message Content Intent » pour le bot "
                                "(portail développeur Discord, onglet Bot, Privileged Gateway Intents), puis recommencez.")
        self._intent_checked = True

    # --- reading a channel ---------------------------------------------------------------------------------------

    def _threads_of(self, parent: dict, mode: str, guild: _Guild, cancelled: Callable[[], bool]) -> list[dict]:
        """The threads of a channel to export along with it: the active ones, and with `all` the archived public ones too."""
        found = {tid: t for tid, t in guild.threads.items() if str(t.get("parent_id")) == str(parent["id"])}
        if mode == "all":
            before = None
            while True:
                data = self.client.get(f"/channels/{parent['id']}/threads/archived/public", {"limit": PAGE, **({"before": before} if before else {})}, cancel=cancelled)
                for t in data.get("threads", []):
                    found.setdefault(str(t["id"]), t)
                if not data.get("has_more") or not data.get("threads"):
                    break
                before = data["threads"][-1]["thread_metadata"]["archive_timestamp"]
        return sorted(found.values(), key=lambda t: int(t["id"]))

    def export(self, channel_id: int, out_dir: Path, after: int | None = None, threads: str = "none", partition: int | None = None,
               before: int | None = None, message_filter: str | None = None, cancel: threading.Event | None = None) -> list[Path]:
        """Exports one channel in JSON v2 into `out_dir` and returns the files. `after` and `before` are message ids (only the messages between them),
        `message_filter` is the filter of a narrowed import, `partition` the number of messages per file, `threads` is `none`, `active` or `all`.
        Setting `cancel` ends the requests. No file is written for a channel that has nothing to export."""
        def cancelled() -> bool:
            return cancel is not None and cancel.is_set()

        deadline = self._clock() + self.timeout
        keep = compile_filter(message_filter)
        out_dir.mkdir(parents=True, exist_ok=True)
        channel = self.client.get(f"/channels/{channel_id}", cancel=cancelled)
        guild_id = str(channel.get("guild_id") or "")
        if not guild_id:
            raise ExporterError("Seuls les salons d'un serveur sont exportés (pas les messages privés).")
        guild = self._guild(guild_id, cancelled)
        guild.directory.guilds[guild_id].channels.setdefault(str(channel["id"]), channel)
        if channel["type"] in FORUMS:
            targets = self._threads_of(channel, "all" if threads == "all" else "active", guild, cancelled) if threads != "none" else []
        else:
            if channel["type"] not in MESSAGE_CHANNELS:
                raise ExporterError(f"Le salon {channel_id} n'a pas de messages (type {channel['type']}).")
            targets = [channel] + (self._threads_of(channel, threads, guild, cancelled) if threads != "none" and channel["type"] not in (10, 11, 12) else [])
        files: list[Path] = []
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="export") as pool:
            try:
                for target in targets:
                    guild.directory.guilds[guild_id].channels.setdefault(str(target["id"]), target)
                    files += self._export_one(pool, guild, guild_id, target, out_dir, after, before, keep, partition, cancelled, deadline)
            except BaseException:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
        return files

    def _ask_for_extras(self, pool: ThreadPoolExecutor, guild_id: str, cid: str, wanted: list[dict], reactions: dict[str, dict[str, Future]],
                        cancelled: Callable[[], bool]) -> None:
        """Starts, for the messages that are kept, the requests for the profile of the people they mention and for the people who reacted."""
        for message in wanted:
            for uid in self._people_of([message]):
                self._want_member(pool, guild_id, uid, cancelled)
            if self._wants_reactions(message):
                by_emoji = reactions.setdefault(str(message["id"]), {})
                for reaction in message["reactions"]:
                    emoji = reaction["emoji"]
                    by_emoji[str(emoji["id"]) if emoji.get("id") else emoji["name"]] = pool.submit(self._reaction_users, cid, str(message["id"]), emoji, cancelled)

    def _export_one(self, pool: ThreadPoolExecutor, guild: _Guild, guild_id: str, channel: dict, out_dir: Path, after: int | None, before: int | None,
                    keep: Callable[[dict], bool], partition: int | None, cancelled: Callable[[], bool], deadline: float) -> list[Path]:
        cid = str(channel["id"])
        files: list[Path] = []
        chunk: list[dict] = []
        reactions: dict[str, dict[str, Future]] = {}              # message id -> emoji key -> the people who reacted (being fetched)

        def flush() -> None:
            if not chunk:
                return
            self._attach_members(guild_id, chunk, cancelled)
            people = {mid: {key: future.result() for key, future in by_emoji.items()} for mid, by_emoji in reactions.items()}
            limits = {"after": created_at(after) if after else None, "before": created_at(before) if before else None}
            document = build_document(guild.directory, guild_id, cid, chunk, exported_at=utc_now(), date_range=limits, reaction_users=people)
            name = f"export [{cid}]" + (f" part{len(files) + 1}" if partition else "") + ".json"
            files.append(write_document(out_dir / name, document))
            self.stats["messages"] += len(chunk)
            self.stats["files"] += 1
            chunk.clear()
            reactions.clear()

        cursor = after or 0
        while True:
            if cancelled():
                raise ExporterCancelled()
            if self._clock() > deadline:
                raise ExporterError(f"L'export a pris plus de {self.timeout:.0f} s : il est arrêté.")
            page = self.client.get(f"/channels/{cid}/messages", {"limit": PAGE, "after": cursor}, cancel=cancelled)
            if not page:
                break
            page.sort(key=lambda m: int(m["id"]))                 # Discord gives a page newest first
            if self.client.kind == "bot" and all(_is_empty(m) for m in page):
                self._ensure_message_content(cancelled)
            cursor = int(page[-1]["id"])
            wanted, finished = _kept_in_page(page, before, keep)
            self._ask_for_extras(pool, guild_id, cid, wanted, reactions, cancelled)       # what the kept messages need, asked now, while the next page is read
            chunk.extend(wanted)
            if partition and len(chunk) >= partition:
                flush()
            if finished or len(page) < PAGE:
                break
        flush()
        return files
