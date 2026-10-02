"""The engine of the bot: takes the Gateway events, builds JSON v2 documents with the adapter, and feeds the one ingestion.

Only new messages are handled for now (MESSAGE_CREATE). Edits, deletions and reactions arrive on the same connection and are
counted but not applied: the nightly catch-up (or the watcher) brings them in, as before.

* Messages wait a few hundred milliseconds and leave in one document per channel: the ingestion takes a lock and costs about
  80 ms per document, so a burst of messages must not become a burst of documents.
* The database being away is not an error to lose messages over: the batch waits and is tried again, with growing delays. It is
  safe to try again, because the ingestion skips what it already has (see `only_new` in ingest/loader.py).
* A message that the adapter or the ingestion cannot digest is isolated and dropped (and counted), so that one strange message
  cannot hold up its channel forever.
* A message of a server that is not followed is ignored without being looked at. Logs only ever say how many, never what.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Callable

import psycopg

from dindon.bot.adapter import DIRECTORY_EVENTS, Directory, build_document, digest
from dindon.bot.events import FatalGatewayError, GatewayEvent
from dindon.config import Settings
from dindon.db import connect
from dindon.ingest.loader import GATEWAY_SOURCE, IngestResult, InvalidExport, ingest_document

log = logging.getLogger("dindon.bot")

BATCH_SECONDS = 0.3
MAX_BATCH = 100               # messages in one document
MAX_PENDING = 5000            # messages waiting for a database that is away; beyond, the newest are dropped (the catch-up brings them)
RETRY_SECONDS = (1, 2, 5, 15, 60)
SUMMARY_SECONDS = 600
FATAL_WAIT_SECONDS = 3600     # after an error that waiting does not fix: stay quiet for an hour before the container restarts
NOT_APPLIED = ("MESSAGE_UPDATE", "MESSAGE_DELETE", "MESSAGE_DELETE_BULK")  # arrive, are counted, are not applied yet

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


class BotRunner:
    def __init__(self, guild_ids, ingest: Ingest, *, batch_seconds: float = BATCH_SECONDS, max_batch: int = MAX_BATCH,
                 max_pending: int = MAX_PENDING, retry_seconds: tuple[float, ...] = RETRY_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.directory = Directory(guild_ids)
        self._ingest = ingest
        self._batch_seconds, self._max_batch, self._max_pending, self._retry_seconds = batch_seconds, max_batch, max_pending, retry_seconds
        self._clock = clock
        self.pending: dict[str, dict[str, dict]] = {}   # channel id -> message id -> payload (a message announced twice counts once)
        self._since: dict[str, float] = {}              # channel id -> when its oldest waiting message arrived
        self._pending_count = 0
        self._failures = 0
        self._retry_at = 0.0
        self.connected = False
        self.stats = {"sessions": 0, "gaps": 0, "received": 0, "batches": 0, "new": 0, "duplicate_batches": 0, "ignored_not_followed": 0,
                      "skipped_unknown_channel": 0, "rejected": 0, "dropped": 0, "database_retries": 0,
                      **{f"not_applied_{name.lower()}": 0 for name in NOT_APPLIED}}

    # --- what happens on the Gateway --------------------------------------------------------------------------------

    def handle(self, event: GatewayEvent) -> None:
        if event.kind == "connected":
            self.stats["sessions"] += 1
            self.connected = True
            if self.stats["sessions"] > 1:  # a new session after a first one: what happened in between is lost to the Gateway
                self.stats["gaps"] += 1
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
        if kind in DIRECTORY_EVENTS:
            if self.directory.apply(kind, data) and kind == "GUILD_CREATE":
                guild = self.directory.guild(data["id"])
                log.info("server %s is ready: %d channels and threads, %d roles", data["id"], len(guild.channels), len(guild.roles))
        elif kind == "MESSAGE_CREATE":
            self._message(data)
        elif kind in NOT_APPLIED and self.directory.is_allowed(data.get("guild_id")):
            self.stats[f"not_applied_{kind.lower()}"] += 1

    def _message(self, data: dict) -> None:
        if not self.directory.is_allowed(data.get("guild_id")):  # another server, or a private message
            self.stats["ignored_not_followed"] += 1
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

    # --- writing ----------------------------------------------------------------------------------------------------

    def _is_due(self, channel_id: str, now: float) -> bool:
        return now - self._since[channel_id] >= self._batch_seconds or len(self.pending[channel_id]) >= self._max_batch

    def next_wait(self, now: float) -> float | None:
        """Seconds until something is due to be written, or None if nothing waits."""
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
        return True

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
            self._failures += 1
            self.stats["database_retries"] += 1
            delay = self._retry_seconds[min(self._failures - 1, len(self._retry_seconds) - 1)]
            self._retry_at = self._clock() + delay
            log.warning("database unavailable (%s): %d messages wait, next try in %ss", type(error).__name__, len(chunk) + self._pending_count, delay)
            return chunk
        self._failures = 0
        self._retry_at = 0.0
        self.stats["batches"] += 1
        if result.status == "duplicate":
            self.stats["duplicate_batches"] += 1
        self.stats["new"] += result.messages_new
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

    async def run(self, events: "asyncio.Queue[GatewayEvent]", stop: asyncio.Event) -> None:
        """Handles the events and writes the batches until `stop` is set, then writes what is waiting (once: if the database is
        away at that moment, what waits is lost to the live path and comes back with the catch-up)."""
        get = asyncio.ensure_future(events.get())
        stopped = asyncio.ensure_future(stop.wait())
        last_summary = self._clock()
        try:
            while not stop.is_set():
                wait = self.next_wait(self._clock())
                done, _ = await asyncio.wait({get, stopped}, timeout=SUMMARY_SECONDS if wait is None else min(wait, SUMMARY_SECONDS),
                                             return_when=asyncio.FIRST_COMPLETED)
                if get in done:
                    self.handle(get.result())
                    get = asyncio.ensure_future(events.get())
                    while not events.empty():  # a burst: take it all before looking at the clock
                        self.handle(events.get_nowait())
                if stopped in done:
                    break
                await self.flush()
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


async def serve(settings: Settings, fatal_wait: float = FATAL_WAIT_SECONDS) -> int:
    from dindon.bot.gateway import GatewaySource  # the only place where the library comes in

    source = GatewaySource(settings.discord_token, settings.discord_api_url)
    runner = BotRunner(settings.guild_ids, Writer(settings.database_url))
    stop = asyncio.Event()        # the engine must write what waits and finish
    terminate = asyncio.Event()   # somebody asked for the process to stop (docker stop, Ctrl-C)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: (terminate.set(), stop.set()))
        except NotImplementedError:  # not on every platform (and not in a thread)
            pass
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
        try:
            await asyncio.wait_for(terminate.wait(), fatal_wait)
        except asyncio.TimeoutError:
            pass
    await source.close()
    gateway.cancel()
    await asyncio.gather(gateway, return_exceptions=True)
    return code


def main(settings: Settings) -> int:
    problems = []
    if not settings.discord_token:
        problems.append("DISCORD_TOKEN is empty: put the token of a BOT in .env")
    if not settings.guild_ids:
        problems.append("DINDON_GUILD_IDS is empty: list the server(s) to follow in .env (the bot never follows 'all' servers)")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("discord").setLevel(logging.WARNING)  # its debug lines contain the frames, that is to say the messages
    log.info("following %d server(s); only new messages are received for now (no edits, deletions or reactions)", len(settings.guild_ids))
    return asyncio.run(serve(settings))
