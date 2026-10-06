"""The watcher: finds out what is new on Discord, has Dindon's exporter (export/) fetch it, and imports it.

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
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from dindon.clock import utc_iso, utc_now
from dindon.collector.discord_api import DiscordAPI, DiscordError, RateLimited, Watched
from dindon.collector.selection import ImportSelection, resolve_channels
from dindon.collector.snowflake import DISCORD_EPOCH_MS, created_at, snowflake_at  # noqa: F401 (also read from here)
from dindon.config import Settings
from dindon.db import connect
from dindon.export import Exporter, ExporterCancelled, ExporterError
from dindon.ingest.inbox import archive_file
from dindon.ingest.loader import GATEWAY_SOURCE, InvalidExport, ingest_file

log = logging.getLogger("dindon.collector")

CATCHUP_KEY = "collector.last_catchup"  # in runtime_settings: when the last catch-up was made
BOT_SEEN_KEY = "collector.bot_seen"      # in runtime_settings: which start and session of the bot the gaps were last looked at for
GAP_FILL_MIN_SECONDS = 600               # a bot that restarts in a loop does not make a round of the watcher every time
BACKFILL_PARTITION = 50_000  # messages per file in a first import: each file is complete, so progress is kept


@dataclass
class ExportOutcome:
    ok: bool
    new_messages: int = 0
    cancelled: bool = False
    error: str | None = None


class Collector:
    def __init__(self, settings: Settings, api: DiscordAPI | None = None, exporter: Exporter | None = None):
        self.settings = settings
        self.api = api or DiscordAPI(settings.discord_api_url, settings.discord_token)
        self.exporter = exporter or Exporter.from_settings(settings)
        self._exported_up_to: dict[int, int] = {}      # latest message id seen when a channel was last exported
        self._failures: dict[int, tuple[int, float]] = {}  # channel -> (failures in a row, do not retry before)
        self._last_catchup_day = None
        self._bot_seen: dict | None = None                 # the start and the session count of the bot when its gaps were last looked at
        self._last_gap_fill = float("-inf")
        self._catchup_recalled = False                     # the day of the last catch-up is read from the database once (it survives a restart)
        self._state: dict = {"last_poll_at": None, "last_error": None, "exports": 0, "last_export_at": None, "last_catchup_at": None}
        self._needs_backfill: set[int] = set()

    # --- what the interface shows ------------------------------------------------------------------

    def status(self) -> dict:
        return {"enabled": True, "mode": "catchup" if self.settings.collector_catchup_only else "poll", "token_kind": self.api.token_kind,
                "guilds": [str(g) for g in self.settings.followed()],
                "needs_backfill": sorted(str(g) for g in self._needs_backfill), "failing_channels": len(self._failures), **self._state}

    # --- what is known ------------------------------------------------------------------------------

    @staticmethod
    def _known(conn: psycopg.Connection, channels: list[Watched], exported_only: bool = False) -> dict[int, int]:
        """The newest message of each channel that the database has. A forum only has posts: it is its newest post's messages.

        `exported_only` leaves out what only the live bot has written, and what only a partial import (narrowed by people or by a period)
        brought. A first import goes on "after the newest message it has", which is right for what a complete export brought (it
        brings everything up to there), and wrong for a message that the bot announced or that a narrowed import picked: the history
        before it is not here."""
        params = {"live": GATEWAY_SOURCE}
        from_exports = ("AND EXISTS (SELECT 1 FROM ingest_runs r WHERE r.id = m.last_seen_run_id AND r.source_file IS DISTINCT FROM %(live)s "
                        "AND NOT r.is_partial)" if exported_only else "")
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
                prune: bool = False, partition: int | None = None, before: int | None = None, message_filter: str | None = None,
                partial: bool = False, cancel: threading.Event | None = None) -> ExportOutcome:
        root = self.settings.inbox_dir / ".collector"  # hidden: the inbox does not import from there by itself
        root.mkdir(parents=True, exist_ok=True)
        new = 0
        try:
            with tempfile.TemporaryDirectory(dir=root) as tmp:
                for path in self.exporter.export(channel.id, Path(tmp), after=after, threads=threads, partition=partition, before=before,
                                                 message_filter=message_filter, cancel=cancel):
                    if path.stat().st_size == 0:
                        continue  # (a file that is empty: nothing to import)
                    result = ingest_file(conn, path, prune=prune, partial=partial)
                    if result.prune_skipped:
                        log.warning("channel %s: %d messages seem deleted but it is too many to be believed: kept", channel.id, result.prune_skipped)
                    archive_file(path, self.settings.archive_dir, result.sha256)
                    new += result.messages_new
        except ExporterCancelled:
            return ExportOutcome(False, cancelled=True)
        except (ExporterError, InvalidExport, psycopg.Error) as error:
            self._fail(channel.id, error)
            # ExporterError messages are written for the administrator and never
            # include the token or message content. Other exceptions may contain
            # imported data or SQL parameters, so show only their type.
            detail = str(error) if isinstance(error, ExporterError) else type(error).__name__
            return ExportOutcome(False, error=detail[:240])
        if not partial:  # a narrowed import says nothing of what the channel contains up to its newest message
            self._exported_up_to[channel.id] = channel.last_message_id or 0
        self._failures.pop(channel.id, None)
        self._state["exports"] += 1
        self._state["last_export_at"] = utc_iso()
        return ExportOutcome(True, new)

    # --- watching -----------------------------------------------------------------------------------

    def _channels_of(self, guild_id: int) -> list[Watched]:
        return self.api.channels(guild_id) + self.api.active_threads(guild_id)

    def poll(self, conn: psycopg.Connection) -> int:
        """One round: returns how many channels were exported."""
        self.api.resolve_kind()
        self._state["last_poll_at"] = utc_iso()
        exports = 0
        for guild_id in self.settings.followed():
            channels = self._channels_of(guild_id)
            # The first import is an import of a complete history: what the live bot writes, or a narrowed import, does not count
            first_import = conn.execute("SELECT min(imported_at) FROM ingest_runs WHERE guild_id = %s AND source_file IS DISTINCT FROM %s "
                                        "AND NOT is_partial", (guild_id, GATEWAY_SOURCE)).fetchone()[0]
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

    def _recall_catchup(self, conn: psycopg.Connection) -> None:
        """The day of the last catch-up, from the database: without it every restart of the application (a new image, a reboot) made a catch-up of its own."""
        self._catchup_recalled = True
        row = conn.execute("SELECT value FROM runtime_settings WHERE key = %s", (CATCHUP_KEY,)).fetchone()
        if row and (at := row[0].get("at")):
            when = datetime.fromisoformat(at)
            self._last_catchup_day = when.date()
            self._state["last_catchup_at"] = at

    def catchup_due(self, now: datetime) -> bool:
        return now.hour >= self.settings.catchup_hour_utc and self._last_catchup_day != now.date()

    def catchup(self, conn: psycopg.Connection, now: datetime | None = None) -> int:
        """Exports the last days again, to see what was edited or deleted since. Returns how many channels."""
        now = now or utc_now()
        since = now - timedelta(days=self.settings.catchup_days)
        channels = [r[0] for r in conn.execute(
            """SELECT DISTINCT m.channel_id FROM messages m JOIN channels c ON c.id = m.channel_id
               WHERE c.guild_id = ANY(%s) AND m.sent_at > %s""", (list(self.settings.followed()), since))]
        done = 0
        for channel_id in channels:
            if self._backing_off(channel_id):
                continue
            outcome = self._export(conn, Watched(channel_id, "", "text", None, None), after=snowflake_at(since), prune=True)
            done += outcome.ok
        self._last_catchup_day = now.date()
        self._state["last_catchup_at"] = now.isoformat()
        conn.execute("INSERT INTO runtime_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()",
                     (CATCHUP_KEY, Jsonb({"at": now.isoformat()})))
        if not self._failures:  # what failed has worked again: the error is over (it stays on display while a channel still fails)
            self._state["last_error"] = None
        return done

    def _fill_bot_gaps(self, conn: psycopg.Connection) -> bool:
        """The messages that the live bot could not receive: it was restarted, or Discord gave it a new session (its sign of life says so: `started_at`, `gaps`).
        One round of the watcher then brings what is new in the channels that it already has, without waiting for the night. Rare: at most one such round
        every GAP_FILL_MIN_SECONDS, and none the first time (nothing to compare with). Returns whether a round was made."""
        row = conn.execute("SELECT data FROM service_status WHERE name = 'bot'").fetchone()
        if row is None:
            return False
        current = {"started_at": row[0].get("started_at"), "gaps": row[0].get("gaps", 0)}
        if self._bot_seen is None:
            recalled = conn.execute("SELECT value FROM runtime_settings WHERE key = %s", (BOT_SEEN_KEY,)).fetchone()
            self._bot_seen = recalled[0] if recalled else current
        if current == self._bot_seen or time.monotonic() - self._last_gap_fill < GAP_FILL_MIN_SECONDS:
            return False
        log.info("the bot was restarted or reconnected with a new session: looking for what it could not receive")
        self._last_gap_fill = time.monotonic()
        self.poll(conn)
        self._bot_seen = current
        conn.execute("INSERT INTO runtime_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()",
                     (BOT_SEEN_KEY, Jsonb(current)))
        return True

    def _note_backfill(self, conn: psycopg.Connection) -> None:
        """Which followed servers have no first import yet (from the database alone: nothing is asked of Discord)."""
        for guild_id in self.settings.followed():
            first = conn.execute("SELECT min(imported_at) FROM ingest_runs WHERE guild_id = %s AND source_file IS DISTINCT FROM %s "
                                 "AND NOT is_partial", (guild_id, GATEWAY_SOURCE)).fetchone()[0]
            (self._needs_backfill.add if first is None else self._needs_backfill.discard)(guild_id)

    def tick(self, conn: psycopg.Connection) -> None:
        if self.settings.collector_catchup_only:             # the live bot brings the new messages: no polling, only the night's catch-up (and a round after a gap)
            self.api.resolve_kind()                         # bot or account (the interface warns about an account), and a wrong token is told
            self._note_backfill(conn)
            self._fill_bot_gaps(conn)
        else:
            self.poll(conn)
        if not self._catchup_recalled:
            self._recall_catchup(conn)
        if self.catchup_due(utc_now()):
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
                 progress: Callable[[str], None] = print, selection: ImportSelection | None = None,
                 cancel: threading.Event | None = None, report: Callable[[dict], None] | None = None) -> dict:
        """Imports a whole server, a channel after the other (`parallel` at a time). It can be stopped and started again:
        a channel that is already up to date is skipped, and one that is partly done goes on after its newest message.
        Reactions cost one request each: this is the slow part on a big server.

        `selection` narrows it (see collector/selection.py): some channels only, which are still imported completely; and/or only some
        people's messages, or a period, which brings a part of the channels and is recorded as partial (no resuming, and it never counts
        as a complete history). `cancel`, once set, ends the exporter and starts no other channel. `report` receives what happens, as
        dictionaries, for a screen that shows the progress."""
        report = report or (lambda event: None)
        selection = selection or ImportSelection()
        self.api.resolve_kind()
        mode = self.settings.exporter_threads
        available = self._channels_of(guild_id)
        chosen = resolve_channels(selection.channels, available) if selection.channels else available
        explicit = {c.id for c in chosen} if selection.channels else set()
        with new_connection() as conn:
            known = {} if selection.partial else self._known(conn, chosen, exported_only=True)
        todo = []
        for channel in chosen:
            have = known.get(channel.id)
            if channel.last_message_id is None or (have is not None and have >= channel.last_message_id):
                continue
            if channel.kind == "thread" and mode != "none" and channel.id not in explicit:
                continue  # exported with its parent channel
            todo.append((channel, have))
        what = "narrowed import (partial): " if selection.partial else ""
        progress(f"{what}{len(todo)} channels to import out of {len(available)} ({parallel} at a time)")
        report({"event": "planned", "channels": len(todo), "of": len(available)})
        totals = {"channels": 0, "failed": 0, "messages": 0}
        if cancel is not None:
            totals["cancelled"] = 0

        def work(item: tuple[Watched, int | None], number: int) -> None:
            channel, have = item
            if cancel is not None and cancel.is_set():  # asked to stop before this channel started: it is reported like the others
                totals["cancelled"] += 1
                progress(f"[{number}/{len(todo)}] {channel.name or channel.id}: cancelled")
                report({"event": "channel", "name": channel.name or str(channel.id), "ok": False, "cancelled": True, "messages": 0})
                return
            with new_connection() as conn:
                outcome = self._export(conn, channel, after=selection.after_id() if selection.partial else have, before=selection.before_id(),
                                       message_filter=selection.message_filter(), partial=selection.partial, cancel=cancel,
                                       threads=mode if channel.kind != "thread" else "none", partition=BACKFILL_PARTITION)
            if outcome.cancelled:
                totals["cancelled"] += 1
            else:
                totals["channels" if outcome.ok else "failed"] += 1
                totals["messages"] += outcome.new_messages
            progress(f"[{number}/{len(todo)}] {channel.name or channel.id}: " +
                     ("cancelled" if outcome.cancelled else f"{outcome.new_messages} messages" if outcome.ok else
                      f"failed ({outcome.error})" if outcome.error else "failed"))
            report({"event": "channel", "name": channel.name or str(channel.id), "ok": outcome.ok, "cancelled": outcome.cancelled,
                    "messages": outcome.new_messages})

        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            futures = [pool.submit(work, item, number) for number, item in enumerate(todo, 1)]
        for future in futures:
            if future.exception():  # e.g. the database was unreachable: counted, not lost silently
                totals["failed"] += 1
                log.error("backfill: %s", type(future.exception()).__name__)
        return totals
