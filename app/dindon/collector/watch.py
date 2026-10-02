"""The watcher: finds out what is new on Discord, has the exporter fetch it, and imports it.

Every `poll_seconds` (30 to 60): one request per server reads the latest message id of each channel. A channel
whose latest message is newer than the newest one in the database is exported with `--after <that id>`, which
downloads only what is new, and the file is imported (and archived). Nothing is downloaded for the others.

* Nothing is exported until a first import of the server has been done (`dindon backfill`), so that starting the
  watcher on a big server never launches a huge export by surprise. A channel created after that first import is
  new, and is exported entirely.
* Once a day, the last days (7 by default) are exported again, to catch what was edited or deleted: it is
  the only way to know about deletions without a bot.
* A channel that fails is left alone for a while (30 s, then twice longer, up to 15 minutes); a rate limit
  from Discord pauses everything for as long as Discord asks.
"""
import asyncio
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import psycopg

from dindon.collector.discord_api import DiscordAPI, DiscordError, RateLimited, Watched
from dindon.collector.exporter import Exporter, ExporterError
from dindon.config import Settings
from dindon.db import connect
from dindon.ingest.inbox import archive_file
from dindon.ingest.loader import GATEWAY_SOURCE, InvalidExport, ingest_file

log = logging.getLogger("dindon.collector")

DISCORD_EPOCH_MS = 1_420_070_400_000
BACKFILL_PARTITION = 50_000  # messages per file in a first import: each file is complete, so progress is kept


def snowflake_at(when: datetime) -> int:
    """The message id that corresponds to a date: everything sent after `when` has a larger id."""
    return (int(when.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22


def created_at(snowflake: int) -> datetime:
    return datetime.fromtimestamp(((snowflake >> 22) + DISCORD_EPOCH_MS) / 1000, tz=timezone.utc)


@dataclass
class ExportOutcome:
    ok: bool
    new_messages: int = 0


class Collector:
    def __init__(self, settings: Settings, api: DiscordAPI | None = None, exporter: Exporter | None = None):
        self.settings = settings
        self.api = api or DiscordAPI(settings.discord_api_url, settings.discord_token)
        self.exporter = exporter or Exporter(settings.exporter_path, settings.discord_token)
        self._exported_up_to: dict[int, int] = {}      # latest message id seen when a channel was last exported
        self._failures: dict[int, tuple[int, float]] = {}  # channel -> (failures in a row, do not retry before)
        self._last_catchup_day = None
        self._state: dict = {"last_poll_at": None, "last_error": None, "exports": 0, "last_export_at": None, "last_catchup_at": None}
        self._needs_backfill: set[int] = set()

    # --- what the interface shows ------------------------------------------------------------------

    def status(self) -> dict:
        return {"enabled": True, "token_kind": self.api.token_kind, "guilds": [str(g) for g in self.settings.guild_ids],
                "needs_backfill": sorted(str(g) for g in self._needs_backfill), "failing_channels": len(self._failures), **self._state}

    # --- what is known ------------------------------------------------------------------------------

    @staticmethod
    def _known(conn: psycopg.Connection, channels: list[Watched], exported_only: bool = False) -> dict[int, int]:
        """The newest message of each channel that the database has. A forum only has posts: it is its newest post's messages.

        `exported_only` leaves out what only the live bot has written. A first import goes on "after the newest message it has", which
        is right for what an export brought (it brings everything up to there), and wrong for a message that the bot announced: the
        history before it is not here."""
        params = {"live": GATEWAY_SOURCE}
        from_exports = ("AND EXISTS (SELECT 1 FROM ingest_runs r WHERE r.id = m.last_seen_run_id AND r.source_file IS DISTINCT FROM %(live)s)"
                        if exported_only else "")
        known: dict[int, int] = {}
        ids = [c.id for c in channels if c.kind != "forum"]
        for channel_id, last in conn.execute(
            f"""SELECT t.id, (SELECT m.id FROM messages m WHERE m.channel_id = t.id {from_exports} ORDER BY m.sent_at DESC LIMIT 1)
                FROM unnest(%(ids)s::bigint[]) AS t(id)""", {**params, "ids": ids}):
            if last:
                known[channel_id] = last
        forums = [c.id for c in channels if c.kind == "forum"]
        if forums:
            known.update(dict(conn.execute(
                f"""SELECT ch.parent_id, max(m.id) FROM channels ch JOIN messages m ON m.channel_id = ch.id
                    WHERE ch.parent_id = ANY(%(forums)s) {from_exports} GROUP BY ch.parent_id""", {**params, "forums": forums}).fetchall()))
        return known

    # --- one export ---------------------------------------------------------------------------------

    def _backing_off(self, channel_id: int) -> bool:
        return channel_id in self._failures and time.monotonic() < self._failures[channel_id][1]

    def _fail(self, channel_id: int, error: Exception) -> None:
        count = self._failures.get(channel_id, (0, 0))[0] + 1
        self._failures[channel_id] = (count, time.monotonic() + min(900, 30 * 2 ** (count - 1)))
        self._state["last_error"] = f"{type(error).__name__}: {error}"[:300]
        log.warning("export of channel %s failed (%d in a row): %s", channel_id, count, self._state["last_error"])

    def _export(self, conn: psycopg.Connection, channel: Watched, after: int | None, threads: str = "none",
                prune: bool = False, partition: int | None = None) -> ExportOutcome:
        root = self.settings.inbox_dir / ".collector"  # hidden: the inbox does not import from there by itself
        root.mkdir(parents=True, exist_ok=True)
        new = 0
        try:
            with tempfile.TemporaryDirectory(dir=root) as tmp:
                for path in self.exporter.export(channel.id, Path(tmp), after=after, threads=threads, partition=partition):
                    if path.stat().st_size == 0:
                        continue  # an empty channel, or nothing new: the exporter leaves an empty file
                    result = ingest_file(conn, path, prune=prune)
                    if result.prune_skipped:
                        log.warning("channel %s: %d messages seem deleted but it is too many to be believed: kept", channel.id, result.prune_skipped)
                    archive_file(path, self.settings.archive_dir, result.sha256)
                    new += result.messages_new
        except (ExporterError, InvalidExport, psycopg.Error) as error:
            self._fail(channel.id, error)
            return ExportOutcome(False)
        self._exported_up_to[channel.id] = channel.last_message_id or 0
        self._failures.pop(channel.id, None)
        self._state["exports"] += 1
        self._state["last_export_at"] = datetime.now(timezone.utc).isoformat()
        return ExportOutcome(True, new)

    # --- watching -----------------------------------------------------------------------------------

    def _channels_of(self, guild_id: int) -> list[Watched]:
        return self.api.channels(guild_id) + self.api.active_threads(guild_id)

    def poll(self, conn: psycopg.Connection) -> int:
        """One round: returns how many channels were exported."""
        self.api.resolve_kind()
        self._state["last_poll_at"] = datetime.now(timezone.utc).isoformat()
        exports = 0
        for guild_id in self.settings.guild_ids:
            channels = self._channels_of(guild_id)
            # The first import is an import of a history: what the live bot writes does not count
            first_import = conn.execute("SELECT min(imported_at) FROM ingest_runs WHERE guild_id = %s AND source_file IS DISTINCT FROM %s",
                                        (guild_id, GATEWAY_SOURCE)).fetchone()[0]
            if first_import is None:
                self._needs_backfill.add(guild_id)
                continue
            self._needs_backfill.discard(guild_id)
            known = self._known(conn, channels)
            for channel in channels:
                if channel.last_message_id is None:
                    continue
                have = known.get(channel.id)
                if channel.last_message_id <= max(have or 0, self._exported_up_to.get(channel.id, 0)):
                    continue
                if have is None and created_at(channel.id) <= first_import:
                    continue  # an old channel that the first import did not have (no access?): `backfill` decides, not the watcher
                if self._backing_off(channel.id):
                    continue
                # With a bot, threads are watched one by one; with an account they come with their parent channel
                threads = self.settings.exporter_threads if channel.kind != "thread" and self.api.token_kind == "account" else "none"
                if self._export(conn, channel, after=have, threads=threads).ok:
                    exports += 1
        if not self._failures:  # the last error is over (a failing channel keeps it on display until it works again)
            self._state["last_error"] = None
        return exports

    def catchup_due(self, now: datetime) -> bool:
        return now.hour >= self.settings.catchup_hour_utc and self._last_catchup_day != now.date()

    def catchup(self, conn: psycopg.Connection, now: datetime | None = None) -> int:
        """Exports the last days again, to see what was edited or deleted since. Returns how many channels."""
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(days=self.settings.catchup_days)
        channels = [r[0] for r in conn.execute(
            """SELECT DISTINCT m.channel_id FROM messages m JOIN channels c ON c.id = m.channel_id
               WHERE c.guild_id = ANY(%s) AND m.sent_at > %s""", (list(self.settings.guild_ids), since))]
        done = 0
        for channel_id in channels:
            if self._backing_off(channel_id):
                continue
            outcome = self._export(conn, Watched(channel_id, "", "text", None, None), after=snowflake_at(since), prune=True)
            done += outcome.ok
        self._last_catchup_day = now.date()
        self._state["last_catchup_at"] = now.isoformat()
        return done

    def tick(self, conn: psycopg.Connection) -> None:
        self.poll(conn)
        if self.catchup_due(datetime.now(timezone.utc)):
            self.catchup(conn)

    async def run(self) -> None:
        conn = None
        while True:
            wait = self.settings.poll_seconds
            try:
                if conn is None or conn.closed:
                    conn = await asyncio.to_thread(connect, self.settings.database_url)
                    conn.autocommit = True
                await asyncio.to_thread(self.tick, conn)
            except asyncio.CancelledError:
                raise
            except RateLimited as error:
                wait = max(wait, error.retry_after)
                self._state["last_error"] = str(error)
            except DiscordError as error:  # a wrong token or no access: asking again every minute would not help
                wait = max(wait, 300)
                self._state["last_error"] = str(error)
                log.error("discord: %s", error)
            except Exception as error:
                self._state["last_error"] = f"{type(error).__name__}"
                log.warning("collector: %s, retrying", type(error).__name__)
                conn = None
            await asyncio.sleep(wait)

    # --- first import -------------------------------------------------------------------------------

    def backfill(self, new_connection: Callable[[], psycopg.Connection], guild_id: int, parallel: int = 2,
                 progress: Callable[[str], None] = print) -> dict:
        """Imports a whole server, a channel after the other (`parallel` at a time). It can be stopped and started again:
        a channel that is already up to date is skipped, and one that is partly done goes on after its newest message.
        Reactions cost one request each: this is the slow part on a big server."""
        self.api.resolve_kind()
        mode = self.settings.exporter_threads
        channels = self._channels_of(guild_id)
        with new_connection() as conn:
            known = self._known(conn, channels, exported_only=True)
        todo = []
        for channel in channels:
            have = known.get(channel.id)
            if channel.last_message_id is None or (have is not None and have >= channel.last_message_id):
                continue
            if channel.kind == "thread" and mode != "none":
                continue  # exported with its parent channel
            todo.append((channel, have))
        progress(f"{len(todo)} channels to import out of {len(channels)} ({parallel} at a time)")
        totals = {"channels": 0, "failed": 0, "messages": 0}

        def work(item: tuple[Watched, int | None], number: int) -> None:
            channel, have = item
            with new_connection() as conn:
                outcome = self._export(conn, channel, after=have, threads=mode if channel.kind != "thread" else "none", partition=BACKFILL_PARTITION)
            totals["channels" if outcome.ok else "failed"] += 1
            totals["messages"] += outcome.new_messages
            progress(f"[{number}/{len(todo)}] {channel.name or channel.id}: " + (f"{outcome.new_messages} messages" if outcome.ok else "failed"))

        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            futures = [pool.submit(work, item, number) for number, item in enumerate(todo, 1)]
        for future in futures:
            if future.exception():  # e.g. the database was unreachable: counted, not lost silently
                totals["failed"] += 1
                log.error("backfill: %s", type(future.exception()).__name__)
        return totals
