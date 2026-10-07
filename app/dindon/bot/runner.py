"""The engine of the bot: takes the Gateway events, builds JSON v2 documents with the adapter, and feeds the one ingestion.

New messages (MESSAGE_CREATE), **edits** (MESSAGE_UPDATE) and **deletions** (MESSAGE_DELETE, MESSAGE_DELETE_BULK) are applied as they happen; what
was derived from a deleted or edited message goes with it (ingest/loader.py: `forget_messages`, `_drop_derived`). Reactions are not received
(that intent is not asked): the nightly catch-up (or the watcher) brings them in.

* Messages wait a few hundred milliseconds and leave in one document per channel: the ingestion takes a lock and costs about
  80 ms per document, so a burst of messages must not become a burst of documents.
* The database being away is not an error to lose messages over: the batch waits and is tried again, with growing delays. It is
  safe to try again, because the ingestion skips what it already has (see `only_new` in ingest/loader.py).
* A message that the adapter or the ingestion cannot digest is isolated and dropped (and counted), so that one strange message
  cannot hold up its channel forever.
* A message of a server that is not followed is ignored without being looked at. Logs only ever say how many, never what.
* The debates (`/dindon debat`, bot/debate_commands.py) are looked after by a tick in a task of its own while one runs; the messages written in the place of a running
  debate (its thread, or the channel itself) are also handed to it, and then go on to the map like any other.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import sys
import time
from collections.abc import Callable

import psycopg

from dindon.bot.adapter import DIRECTORY_EVENTS, Directory, build_document, digest
from dindon.bot.events import FatalGatewayError, GatewayEvent
from dindon.clock import utc_iso, utc_now
from dindon.config import Settings
from dindon.db import connect
from dindon.ingest.loader import GATEWAY_SOURCE, IngestResult, InvalidExport, forget_messages, ingest_document

log = logging.getLogger("dindon.bot")

DEBATE_TICK_SECONDS = 2        # while a debate runs: how often its silence, its counted messages and its counters are looked at
BATCH_SECONDS = 0.3
MAX_BATCH = 100               # messages in one document
MAX_PENDING = 5000            # messages waiting for a database that is away; beyond, the newest are dropped (the catch-up brings them)
RETRY_SECONDS = (1, 2, 5, 15, 60)
SUMMARY_SECONDS = 600
HEARTBEAT_SECONDS = 30         # the bot says that it is alive (service_status): the interface calls it silent after a few of these missing
FATAL_WAIT_SECONDS = 3600     # after an error that waiting does not fix: stay quiet for an hour before the container restarts

Ingest = Callable[[dict, str], IngestResult]

# What is the fault of a message: a shape that was not expected, or data that the database refuses. Anything else (the database away,
# not ready, locked, out of room...) is not, and the messages wait: dropping them would lose what nothing is wrong with.
UNDIGESTIBLE = (InvalidExport, KeyError, TypeError, ValueError, AttributeError, IndexError, psycopg.DataError, psycopg.IntegrityError)


class Writer:
    """Writes a document with its own connection, opened when needed and opened again after it was lost."""

    def __init__(self, database_url: str):
        self._url = database_url
        self._conn: psycopg.Connection | None = None

    def __call__(self, document: dict, sha256: str) -> IngestResult:
        if self._conn is None or self._conn.closed:
            self._conn = connect(self._url)
            self._conn.autocommit = True
        try:
            # GATEWAY_SOURCE is the name in the ledger of imports; only_new: see the module description
            return ingest_document(self._conn, document, GATEWAY_SOURCE, sha256, only_new=True)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._conn.close()
            self._conn = None
            raise


    def edit(self, document: dict, sha256: str) -> IngestResult:
        """Writes a message again after an edit: unlike a new message, it replaces what the database has (a newer version wins)."""
        return self._run(lambda conn: ingest_document(conn, document, GATEWAY_SOURCE, sha256, only_new=False))

    def forget(self, guild_id: int, message_ids: list[int]) -> int:
        """Removes messages that were deleted on Discord, with what was derived from them."""
        return self._run(lambda conn: forget_messages(conn, guild_id, message_ids))

    def erase_server(self, guild_id: int, directories) -> dict:
        """The bot was removed from a server and the setting asks for everything to go (privacy.erase_server)."""
        from dindon import privacy

        with connect(self._url) as conn:        # its own connection: this runs in a thread, beside the one that writes
            return privacy.erase_server(conn, guild_id, source="removal", file_directories=directories)

    def _run(self, action):
        if self._conn is None or self._conn.closed:
            self._conn = connect(self._url)
            self._conn.autocommit = True
        try:
            return action(self._conn)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._conn.close()
            self._conn = None
            raise

    def performance(self) -> dict:
        """The performance settings in force (performance.py), read with the connection of the heartbeat."""
        from dindon import performance

        if self._conn is None or self._conn.closed:
            self._conn = connect(self._url)
            self._conn.autocommit = True
        try:
            return performance.load(self._conn)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._conn.close()
            self._conn = None
            raise

    def heartbeat(self, data: dict) -> None:
        """Says that the bot is alive, with its counts (service_status). Never a reason to stop: the caller ignores a failure."""
        if self._conn is None or self._conn.closed:
            self._conn = connect(self._url)
            self._conn.autocommit = True
        try:
            self._conn.execute(
                """INSERT INTO service_status (name, updated_at, data) VALUES ('bot', now(), %s::jsonb)
                   ON CONFLICT (name) DO UPDATE SET updated_at = now(), data = excluded.data""", (json.dumps(data),))
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._conn.close()
            self._conn = None
            raise


class BotRunner:
    def __init__(self, guild_ids, ingest: Ingest, *, interactions=None, debates=None, batch_seconds: float = BATCH_SECONDS, max_batch: int = MAX_BATCH,
                 max_pending: int = MAX_PENDING, retry_seconds: tuple[float, ...] = RETRY_SECONDS, clock: Callable[[], float] = time.monotonic,
                 erase_server: Callable[[int], dict] | None = None):
        self.directory = Directory(guild_ids)
        self._ingest = ingest
        self._erase_server = erase_server                # called with the id of a server that the bot was removed from, or None: keep the data
        self.interactions = interactions                # privacy commands (bot/privacy_commands.py), or None
        self._application_id: str | None = None
        self.debates = debates                          # the debates (bot/debate_commands.py), or None
        if debates is not None:
            debates.guild_info = self.directory.guild
            debates.allowed = self.directory.is_allowed   # a debate is only opened on a server that is followed
        self._debate_ticking = False
        self._debate_checking = False
        self._debate_tick_at = -1e9
        self._debate_failing = False
        self._tasks: set[asyncio.Task] = set()
        self._batch_seconds, self._max_batch, self._max_pending, self._retry_seconds = batch_seconds, max_batch, max_pending, retry_seconds
        self._clock = clock
        self.pending: dict[str, dict[str, dict]] = {}   # channel id -> message id -> payload (a message announced twice counts once)
        self._since: dict[str, float] = {}              # channel id -> when its oldest waiting message arrived
        self._pending_count = 0
        self._failures = 0
        self._retry_at = 0.0
        self.connected = False
        self._guild_ids = [] if guild_ids is None else [str(g) for g in guild_ids]   # [] with None: every server that the bot is in
        self._started_at = utc_iso()
        self._last_new_at: str | None = None
        self._beat_failing = False
        self.stats = {"sessions": 0, "gaps": 0, "received": 0, "batches": 0, "new": 0, "duplicate_batches": 0, "ignored_not_followed": 0, "ignored_privacy": 0,
                      "skipped_unknown_channel": 0, "rejected": 0, "dropped": 0, "database_retries": 0,
                      "edited": 0, "deleted": 0, "edits_ignored": 0}
        self.edits: dict[str, dict[str, dict]] = {}     # channel id -> message id -> payload of a message that is already stored and was edited
        self.deleted: dict[str, set[str]] = {}          # guild id -> ids of messages deleted on Discord, waiting to be removed

    # --- what happens on the Gateway --------------------------------------------------------------------------------

    def handle(self, event: GatewayEvent) -> None:
        if event.kind == "connected":
            self.stats["sessions"] += 1
            self.connected = True
            if self.stats["sessions"] > 1:  # a new session after a first one: what happened in between is lost to the Gateway
                self.stats["gaps"] += 1
                if self.debates is not None:
                    self.debates.note_gap()                 # the threads of the running debates are read again
                log.warning("reconnected with a new session: messages written meanwhile were not received here; the nightly catch-up "
                            "(or `dindon catchup`, now) brings them back: the watcher does not see them")
            else:
                log.info("connected to Discord")
        elif event.kind == "resumed":
            self.connected = True
            log.info("connection resumed: nothing was missed")
        elif event.kind == "disconnected":
            self.connected = False
            log.info("disconnected from Discord (it reconnects by itself)")
        elif event.kind == "dispatch":
            self._dispatch(event.type, event.data or {})

    def _dispatch(self, kind: str, data: dict) -> None:
        if kind == "GUILD_DELETE" and not data.get("unavailable") and self._erase_server is not None and self.directory.is_allowed(data.get("id")):
            self._removed(str(data["id"]))      # an outage (unavailable) is not a removal: only leaving, being kicked or banned, or the server deleted
        if self.debates is not None and kind in ("THREAD_DELETE", "CHANNEL_DELETE"):
            (self.debates.on_thread_gone if kind == "THREAD_DELETE" else self.debates.on_channel_gone)(data.get("id"))
        if kind in DIRECTORY_EVENTS:
            if self.directory.apply(kind, data) and kind == "GUILD_CREATE":
                guild = self.directory.guild(data["id"])
                if self.interactions is not None and self._application_id is not None:
                    self._spawn(self.interactions.register_guild(self._application_id, str(data["id"])))
                log.info("server %s is ready: %d channels and threads, %d roles", data["id"], len(guild.channels), len(guild.roles))
        elif kind == "MESSAGE_CREATE":
            if self.debates is not None and self.debates.is_debate_thread(data.get("channel_id")):
                self.debates.on_message(data)           # counted for the debate; it also goes on to the map like any message
            self._message(data)
        elif kind == "READY" and self.interactions is not None and (data.get("application") or {}).get("id"):
            self._application_id = str(data["application"]["id"])
            guild_ids = tuple(dict.fromkeys(str(g["id"]) for g in data.get("guilds", []) if self.directory.is_allowed(g.get("id"))))
            self._spawn(self.interactions.register(self._application_id, guild_ids))
        elif kind == "INTERACTION_CREATE" and self.interactions is not None:
            self._spawn(self.interactions.answer(data))
        elif kind == "MESSAGE_UPDATE":
            self._edit(data)
        elif kind == "MESSAGE_DELETE":
            self._delete(data, [data.get("id")])
            if self.debates is not None:
                self.debates.on_delete(data, [data.get("id")])
        elif kind == "MESSAGE_DELETE_BULK":
            self._delete(data, data.get("ids") or [])
            if self.debates is not None:
                self.debates.on_delete(data, data.get("ids") or [])

    def _removed(self, guild_id: str) -> None:
        """The bot is no longer in this server: what waits for it is dropped and everything held of it is deleted, as the settings ask."""
        info = self.directory.guild(guild_id)
        for channel_id in (info.channels if info else ()):      # what waits to be written would bring the server back
            self._pending_count -= len(self.pending.pop(channel_id, {}))
            self._since.pop(channel_id, None)
            self.edits.pop(channel_id, None)
        self.deleted.pop(guild_id, None)
        self._spawn(self._erase(guild_id))

    async def _erase(self, guild_id: str) -> None:
        try:
            counts = await asyncio.to_thread(self._erase_server, int(guild_id))
            log.info("removed from server %s: everything held of it was deleted (%s)", guild_id, counts)
        except Exception as error:      # the data stays and the next start does not retry: say it plainly, with the way to do it by hand
            log.error("removed from server %s but its data could not be deleted (%s): `dindon forget-server %s` does it", guild_id, type(error).__name__, guild_id)

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._spawned_done)
        return task

    def _debate_tick_due(self) -> None:
        """Looks after the debates: in a task of its own, so that a slow answer from Discord never holds up the Gateway events."""
        if self.debates is None or self._debate_ticking or not self.debates.has_work() or self._clock() - self._debate_tick_at < DEBATE_TICK_SECONDS:
            return
        self._debate_ticking = True
        self._debate_tick_at = self._clock()
        self._spawn(self._debate_tick())

    def _debate_check_due(self) -> None:
        """Reads the next message of a debate for claims, in a task of its own: the model and the Internet are slow, the Gateway must not wait for them. One at a time."""
        if self.debates is None or self._debate_checking or not self.debates.has_checks():
            return
        self._debate_checking = True
        self._spawn(self._debate_check())

    async def _debate_check(self) -> None:
        try:
            await self.debates.check_next()
        finally:
            self._debate_checking = False

    async def _debate_tick(self) -> None:
        try:
            await self.debates.tick()
            if self._debate_failing:
                log.info("the debates are looked after again")
            self._debate_failing = False
        except Exception as error:                      # said once, not every two seconds (the database away, usually): the next tick tries again
            if not self._debate_failing:
                log.warning("the debates could not be looked after (%s)", type(error).__name__)
            self._debate_failing = True
        finally:
            self._debate_ticking = False

    def _spawned_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:   # said once, with the kind of error only (never what was asked)
            log.error("a command could not be handled (%s)", type(task.exception()).__name__)

    def _message(self, data: dict) -> None:
        if not self.directory.is_allowed(data.get("guild_id")):  # another server, or a private message
            self.stats["ignored_not_followed"] += 1
            return
        if self.interactions is not None and str((data.get("author") or {}).get("id")) in self.interactions.service.blocked:
            self.stats["ignored_privacy"] += 1                   # this person asked not to be recorded: the message is not even kept in memory
            return
        channel_id, message_id = str(data["channel_id"]), str(data["id"])
        bucket = self.pending.get(channel_id, {})
        if message_id not in bucket:
            if self._pending_count >= self._max_pending:
                self.stats["dropped"] += 1
                if self.stats["dropped"] == 1 or self.stats["dropped"] % 1000 == 0:
                    log.error("%d messages are waiting for the database: the new ones are dropped (the catch-up brings them back)", self._pending_count)
                return
            self._pending_count += 1
        self.pending.setdefault(channel_id, {})[message_id] = data
        self._since.setdefault(channel_id, self._clock())
        self.stats["received"] += 1

    def _edit(self, data: dict) -> None:
        """A message was edited. Discord also sends this event when a link gets its preview, without the author or the text: that one brings nothing."""
        if not self.directory.is_allowed(data.get("guild_id")):
            return
        if "author" not in data or "content" not in data or not data.get("edited_timestamp"):
            self.stats["edits_ignored"] += 1
            return
        if self.interactions is not None and str(data["author"].get("id")) in self.interactions.service.blocked:
            self.stats["ignored_privacy"] += 1
            return
        channel_id, message_id = str(data["channel_id"]), str(data["id"])
        if message_id in self.pending.get(channel_id, {}):      # not written yet: the new text simply is the message
            self.pending[channel_id][message_id] = data
        else:
            self.edits.setdefault(channel_id, {})[message_id] = data
        self.stats["edited"] += 1

    def _delete(self, data: dict, ids: list) -> None:
        if not self.directory.is_allowed(data.get("guild_id")):
            return
        channel_id, guild_id = str(data.get("channel_id")), str(data["guild_id"])
        for raw in ids:
            message_id = str(raw)
            if self.pending.get(channel_id, {}).pop(message_id, None) is not None:     # deleted before it was written: it never needs to be
                self._pending_count -= 1
                if not self.pending[channel_id]:
                    del self.pending[channel_id]
                    self._since.pop(channel_id, None)
            self.edits.get(channel_id, {}).pop(message_id, None)
            self.deleted.setdefault(guild_id, set()).add(message_id)
        self.stats["deleted"] += len(ids)

    # --- writing ----------------------------------------------------------------------------------------------------

    def _is_due(self, channel_id: str, now: float) -> bool:
        return now - self._since[channel_id] >= self._batch_seconds or len(self.pending[channel_id]) >= self._max_batch

    def next_wait(self, now: float) -> float | None:
        """Seconds until something is due to be written, or None if nothing waits."""
        if self.edits or self.deleted:
            return max(0.0, self._retry_at - now)
        if not self._since:
            return None
        due = min(self._since[c] + (0 if len(self.pending[c]) >= self._max_batch else self._batch_seconds) for c in self._since)
        return max(0.0, max(due, self._retry_at) - now)

    async def flush(self, force: bool = False) -> bool:
        """Writes what is due (all of it if `force`). Returns False if the database is away (what was not written waits)."""
        now = self._clock()
        if not force and now < self._retry_at:
            return False
        for channel_id in [c for c in list(self.pending) if force or self._is_due(c, now)]:
            if not await self._flush_channel(channel_id):
                return False
        return await self._flush_edits() and await self._flush_deleted()

    async def _flush_edits(self) -> bool:
        """Writes the edits (after the new messages: an edit of a message that was just written must find it). The database being away leaves them waiting."""
        write = getattr(self._ingest, "edit", None)
        for channel_id in list(self.edits):
            bucket = self.edits[channel_id]
            if write is None:                                     # an ingestion that cannot (a test double): nothing to do
                self.edits.pop(channel_id)
                continue
            messages = list(bucket.values())
            try:
                document = build_document(self.directory, messages[0]["guild_id"], channel_id, messages, exported_at=utc_now())
            except Exception as error:                            # a payload of a shape that was not expected
                log.error("an edit of channel %s was refused and is dropped (%s)", channel_id, type(error).__name__)
                self.stats["rejected"] += len(messages)
                self.edits.pop(channel_id)
                continue
            if document is None:
                self.edits.pop(channel_id)
                continue
            try:
                await asyncio.to_thread(write, document, digest(document))
            except UNDIGESTIBLE as error:
                log.error("an edit of channel %s was refused and is dropped (%s)", channel_id, type(error).__name__)
                self.stats["rejected"] += len(messages)
                self.edits.pop(channel_id)
                continue
            except Exception as error:
                return self._database_away(error, len(messages))
            for message in messages:                              # what was written goes; an edit that arrived meanwhile (another payload) stays for the next time
                if bucket.get(str(message["id"])) is message:
                    del bucket[str(message["id"])]
            if not bucket:
                del self.edits[channel_id]
        return True

    async def _flush_deleted(self) -> bool:
        forget = getattr(self._ingest, "forget", None)
        for guild_id in list(self.deleted):
            ids = sorted(self.deleted[guild_id])
            if forget is None:
                self.deleted.pop(guild_id)
                continue
            try:
                await asyncio.to_thread(forget, int(guild_id), [int(i) for i in ids])
            except Exception as error:
                return self._database_away(error, len(ids))
            self.deleted[guild_id] -= set(ids)
            if not self.deleted[guild_id]:
                del self.deleted[guild_id]
        return True

    def _database_away(self, error: Exception, waiting: int) -> bool:
        """Notes that the database could not take what was sent: it waits, and is tried again later with growing delays."""
        self._failures += 1
        self.stats["database_retries"] += 1
        delay = self._retry_seconds[min(self._failures - 1, len(self._retry_seconds) - 1)]
        self._retry_at = self._clock() + delay
        log.warning("database unavailable (%s): %d messages, edits or deletions wait, next try in %ss", type(error).__name__, waiting, delay)
        return False

    async def _flush_channel(self, channel_id: str) -> bool:
        bucket = self.pending.pop(channel_id)
        since = self._since.pop(channel_id, self._clock())
        self._pending_count -= len(bucket)
        messages = list(bucket.values())
        for start in range(0, len(messages), self._max_batch):
            left = await self._write(channel_id, messages[start:start + self._max_batch])
            if left:  # the database is away: this and what follows wait, in front of what arrived meanwhile
                waiting = {str(m["id"]): m for m in left + messages[start + self._max_batch:]}
                waiting.update(self.pending.get(channel_id, {}))
                self._pending_count += len(waiting) - len(self.pending.get(channel_id, {}))
                self.pending[channel_id] = waiting
                self._since[channel_id] = min(since, self._since.get(channel_id, since))
                return False
        return True

    async def _write(self, channel_id: str, chunk: list[dict]) -> list[dict]:
        """Builds and ingests one document. Returns the messages that could not be written because the database is away."""
        try:
            document = build_document(self.directory, chunk[0]["guild_id"], channel_id, chunk)
        except Exception as error:  # a payload of a shape that was not expected
            return await self._isolate(channel_id, chunk, error)
        if document is None:
            self.stats["skipped_unknown_channel"] += len(chunk)
            log.warning("channel %s is not known (yet): %d messages skipped, the catch-up brings them back", channel_id, len(chunk))
            return []
        try:
            result = await asyncio.to_thread(self._ingest, document, digest(document))
        except UNDIGESTIBLE as error:  # a document that the ingestion refuses
            return await self._isolate(channel_id, chunk, error)
        except Exception as error:  # not the fault of the messages: the database is away, or not ready
            self._database_away(error, len(chunk) + self._pending_count)
            return chunk
        self._failures = 0
        self._retry_at = 0.0
        self.stats["batches"] += 1
        if result.status == "duplicate":
            self.stats["duplicate_batches"] += 1
        self.stats["new"] += result.messages_new
        if result.messages_new:
            self._last_new_at = utc_iso()
        log.info("channel %s: %d messages received, %d new, %d links changed (%.0f ms)", channel_id, len(chunk), result.messages_new,
                 result.edges_changed, result.seconds * 1000)
        return []

    async def _isolate(self, channel_id: str, chunk: list[dict], error: Exception) -> list[dict]:
        if len(chunk) == 1:
            self.stats["rejected"] += 1
            log.error("message %s of channel %s was refused and is dropped (%s)", chunk[0].get("id"), channel_id, type(error).__name__)
            return []
        log.warning("a batch of %d messages of channel %s was refused (%s): trying them one by one", len(chunk), channel_id, type(error).__name__)
        for index, message in enumerate(chunk):
            left = await self._write(channel_id, [message])
            if left:
                return left + chunk[index + 1:]
        return []

    # --- running ----------------------------------------------------------------------------------------------------

    def status(self) -> dict:
        return {"connected": self.connected, "waiting": self._pending_count, **self.stats}

    def heartbeat_data(self) -> dict:
        """What the bot says about itself in service_status: its counts, the servers it follows and the ones that it is connected to."""
        return {**self.status(), **({"debates": self.debates.status()} if self.debates is not None else {}), "started_at": self._started_at, "last_new_at": self._last_new_at,
                "batch_seconds": self._batch_seconds, "followed": self._guild_ids, "follow_all": self.directory.allowed is None, "ready": sorted(self.directory.guilds)}

    async def _beat(self) -> None:
        if self.interactions is not None:                     # who must not be recorded: read again every beat
            try:
                await asyncio.wait_for(asyncio.to_thread(self.interactions.service.refresh), 10)   # never hold the engine for it
            except Exception as error:
                log.warning("the list of people who must not be recorded could not be read (%s): the last one stands", type(error).__name__)
        read = getattr(self._ingest, "performance", None)
        if read is not None:                                  # the limits set in the interface: how long the messages of a channel are grouped
            with contextlib.suppress(Exception):              # the last known value stands
                self._batch_seconds = float((await asyncio.to_thread(read))["bot_batch_seconds"])
        beat = getattr(self._ingest, "heartbeat", None)
        if beat is None:
            return
        try:
            await asyncio.to_thread(beat, self.heartbeat_data())
        except Exception as error:                            # the database is away: the writing of messages has its own retries
            if not self._beat_failing:                        # said once (not every half minute), and said when it works again
                log.warning("the sign of life could not be written (%s): the page Système will call the bot silent. Is the database "
                            "migrated (`dindon migrate`)?", type(error).__name__)
            self._beat_failing = True
        else:
            if self._beat_failing:
                log.info("the sign of life is written again")
            self._beat_failing = False

    async def run(self, events: asyncio.Queue[GatewayEvent], stop: asyncio.Event) -> None:
        """Handles the events and writes the batches until `stop` is set, then writes what is waiting (once: if the database is
        away at that moment, what waits is lost to the live path and comes back with the catch-up)."""
        get = asyncio.ensure_future(events.get())
        stopped = asyncio.ensure_future(stop.wait())
        last_summary = last_beat = self._clock()
        await self._beat()
        try:
            while not stop.is_set():
                wait = self.next_wait(self._clock())
                sleep = HEARTBEAT_SECONDS if wait is None else min(wait, HEARTBEAT_SECONDS)
                if self.debates is not None and self.debates.has_work():
                    sleep = min(sleep, DEBATE_TICK_SECONDS)       # a running debate may end by its silence
                done, _ = await asyncio.wait({get, stopped}, timeout=sleep, return_when=asyncio.FIRST_COMPLETED)
                if get in done:
                    self.handle(get.result())
                    get = asyncio.ensure_future(events.get())
                    while not events.empty():  # a burst: take it all before looking at the clock
                        self.handle(events.get_nowait())
                if stopped in done:
                    break
                await self.flush()
                self._debate_tick_due()
                self._debate_check_due()
                if self._clock() - last_beat >= HEARTBEAT_SECONDS:
                    last_beat = self._clock()
                    await self._beat()
                if self._clock() - last_summary >= SUMMARY_SECONDS:
                    last_summary = self._clock()
                    log.info("alive: %s", ", ".join(f"{k}={v}" for k, v in self.status().items()))
        finally:
            leftover = get.result() if get.done() and not get.cancelled() else None
            get.cancel()
            stopped.cancel()
        if leftover is not None:
            self.handle(leftover)
        while not events.empty():
            self.handle(events.get_nowait())
        if not await self.flush(force=True):
            log.warning("stopping with %d messages that the database could not take: the catch-up brings them back", self._pending_count)


# --- the `dindon bot` command ------------------------------------------------------------------------------------------


def build_interactions(settings: Settings, service):
    """The commands that members use (`/dindon …`) and the debates behind `/dindon debat`. The checks of the claims are None, and so nothing is read, nothing is sent and nothing is said about
    it to the members, unless the owner switched them on and gave a search service (debate/checker.py); when they are on, `/dindon info` and every debate thread say what leaves the machine."""
    from dindon.bot.debate_commands import Debates
    from dindon.bot.privacy_commands import Interactions
    from dindon.bot.rest import DiscordREST
    from dindon.debate.checker import build_checker

    checker = build_checker(settings)
    interactions = Interactions(settings.discord_token, settings.discord_api_url, service, activity=bool(settings.discord_client_id and settings.discord_client_secret))
    interactions.verification = checker is not None
    from dindon.debate.checker import notice_mode

    interactions.live = notice_mode(checker)                                 # what the members are told that Dindon does (texts.notice)
    from dindon.analysis.ollama import Ollama

    debates = interactions.debates = Debates(settings.database_url, DiscordREST(settings.discord_token, settings.discord_api_url), checker=checker,
                                             poll_client=Ollama(settings.ollama_url, timeout=30), poll_model=settings.naming_model)
    debates.interactions = interactions
    return interactions, debates


async def serve(settings: Settings, fatal_wait: float = FATAL_WAIT_SECONDS) -> int:
    from dindon.bot.gateway import GatewaySource  # the only place where the library comes in

    source = GatewaySource(settings.discord_token, settings.discord_api_url)
    from dindon.bot.privacy_commands import PrivacyService

    service = PrivacyService(settings.database_url, (settings.inbox_dir, settings.archive_dir), retention_days=settings.retention_days)
    writer = Writer(settings.database_url)
    interactions, debates = build_interactions(settings, service)
    runner = BotRunner(None if settings.follow_all else settings.guild_ids, writer,
                       interactions=interactions, debates=debates,
                       erase_server=(lambda gid: writer.erase_server(gid, (settings.inbox_dir, settings.archive_dir))) if settings.erase_on_removal else None)
    stop = asyncio.Event()        # the engine must write what waits and finish
    terminate = asyncio.Event()   # somebody asked for the process to stop (docker stop, Ctrl-C)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # not on every platform (and not in a thread)
            loop.add_signal_handler(sig, lambda: (terminate.set(), stop.set()))
    gateway = asyncio.create_task(source.run())
    engine = asyncio.create_task(runner.run(source.events, stop))
    await asyncio.wait({gateway, engine}, return_when=asyncio.FIRST_COMPLETED)
    code = 0
    if gateway.done() and not gateway.cancelled() and gateway.exception() is not None:
        error = gateway.exception()
        if isinstance(error, FatalGatewayError):
            log.error("%s", error)
            code = 3
        else:
            log.error("the connection to Discord stopped: %s", source.scrub(f"{type(error).__name__}: {error}"))
            code = 1
    stop.set()
    await engine
    if code == 3:  # a restart every few seconds would only be refused again (and counted against the bot): wait
        log.error("not trying again for %d minutes", fatal_wait // 60)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(terminate.wait(), fatal_wait)
    await source.close()
    gateway.cancel()
    await asyncio.gather(gateway, return_exceptions=True)
    return code


def main(settings: Settings) -> int:
    problems = []
    if not settings.discord_token:
        problems.append("DISCORD_TOKEN is empty: put the token of a BOT in .env")
    if not settings.guild_ids and not settings.follow_all:
        problems.append("DINDON_GUILD_IDS lists no valid server id (leave it empty, or put all, to follow every server that the bot is in)")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("discord").setLevel(logging.WARNING)  # its debug lines contain the frames, that is to say the messages
    log.info("following %s; new messages, edits and deletions are applied as they happen (reactions come with the nightly catch-up)",
             "every server that the bot is in" if settings.follow_all else f"{len(settings.guild_ids)} server(s)")
    return asyncio.run(serve(settings))
