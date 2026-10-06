"""What the application does besides answering requests: it imports what is dropped in inbox/, deletes what is older than the retention, reads the new
messages when the automatic reading is on, and runs the collector. Each one is a task of the event loop, started with the application and cancelled with it."""
import asyncio
import logging

from fastapi import FastAPI

from dindon.analysis.auto import auto_loop
from dindon.config import Settings
from dindon.db import connect
from dindon.ingest.inbox import scan_once

log = logging.getLogger("dindon")

RETENTION_PERIOD = 86400        # the retention is applied once a day
RETENTION_RETRY = 3600          # and tried again in an hour when it failed


async def retention_loop(settings: Settings) -> None:
    """Deletes what is older than DINDON_RETENTION_DAYS, once a day (nothing is kept longer than what was announced)."""
    from dindon import privacy

    while True:
        try:
            conn = await asyncio.to_thread(connect, settings.database_url)
            conn.autocommit = True
            try:
                done = await asyncio.to_thread(privacy.purge_older_than, conn, settings.retention_days)
            finally:
                conn.close()
            if done["messages"]:
                log.info("retention: %d messages older than %d days were deleted", done["messages"], settings.retention_days)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("retention: %s, retrying in an hour", type(error).__name__)
            await asyncio.sleep(RETENTION_RETRY)
            continue
        await asyncio.sleep(RETENTION_PERIOD)


async def inbox_loop(settings: Settings) -> None:
    """Imports what is dropped in inbox/, every couple of seconds."""
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                conn = await asyncio.to_thread(connect, settings.database_url)
                conn.autocommit = True
            await asyncio.to_thread(scan_once, conn, settings.inbox_dir, settings.archive_dir)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("inbox: %s, retrying", type(error).__name__)
            conn = None
        await asyncio.sleep(2)


def start_background_tasks(app: FastAPI, settings: Settings) -> list[asyncio.Task]:
    """The tasks of a running application (not started by the tests, which drive the inbox and the collector themselves)."""
    tasks = [asyncio.create_task(inbox_loop(settings))]
    if settings.retention_days > 0:
        tasks.append(asyncio.create_task(retention_loop(settings)))
    tasks.append(asyncio.create_task(auto_loop(app.state.analysis, settings)))      # the automatic reading: does nothing unless it was switched on
    if settings.discord_token and (settings.guild_ids or settings.follow_all) and settings.collector_enabled:
        from dindon.collector.watch import Collector

        app.state.collector = Collector(settings)
        tasks.append(asyncio.create_task(app.state.collector.run()))
    return tasks
