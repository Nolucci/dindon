"""The loop of the automatic reading (see automation.py): every few seconds it looks whether a cycle is due, and runs it with the same one-at-a-time
analysis job as the page Thèmes and the page Positions. It never starts while an analysis is running, and never reads more than the settings allow."""
from __future__ import annotations

import asyncio
import logging

from dindon import automation
from dindon.analysis.job import AnalysisBusy, AnalysisJobs, NotReady
from dindon.clock import utc_iso
from dindon.config import Settings
from dindon.db import connect

log = logging.getLogger("dindon.auto")

TICK_SECONDS = 20


def _guilds(conn) -> list[int]:
    return [r[0] for r in conn.execute("""SELECT g.id FROM guilds g WHERE EXISTS (SELECT 1 FROM channels c JOIN messages m ON m.channel_id = c.id WHERE c.guild_id = g.id)
                                          OR EXISTS (SELECT 1 FROM debates d JOIN debate_polls q ON q.debate_id = d.id WHERE d.guild_id = g.id)
                                          ORDER BY g.id""").fetchall()]


async def cycle(jobs: AnalysisJobs, settings: Settings) -> dict:
    """One cycle: for each server, what there is to do and is wanted. Returns what happened (counts and the names of the stages, never a message)."""
    conn = await asyncio.to_thread(connect, settings.database_url)
    conn.autocommit = True
    done = []
    try:
        cfg = automation.load(conn)
        for guild in await asyncio.to_thread(_guilds, conn):
            todo = await asyncio.to_thread(automation.pending, conn, guild, jobs.embed_model)
            stages = automation.stages_for(cfg, todo)
            if not stages:
                continue
            entry = {"guild": str(guild), "stages": list(stages)}
            try:
                await asyncio.to_thread(jobs.start, guild, stages, limit=cfg["batch"], keep=True)
            except NotReady as problem:
                done.append({**entry, "state": "failed", "error": str(problem)})
                break                                               # the models are not there: no point in trying the other servers
            except AnalysisBusy:
                done.append({**entry, "state": "skipped", "error": "une analyse était déjà en cours"})
                break
            await asyncio.to_thread(jobs.wait)
            status = jobs.status()
            done.append({**entry, "state": status["state"], "error": status["error"], "lines": status["lines"][-3:]})
            if status["state"] in ("failed", "cancelled"):
                break
    finally:
        conn.close()
    return {"at": utc_iso(), "servers": done, "idle": not done}


async def tick(jobs: AnalysisJobs, settings: Settings) -> bool:
    """Looks whether a cycle is due and runs it. Returns True if one ran."""
    if jobs.status()["state"] in ("running", "cancelling"):
        return False
    conn = await asyncio.to_thread(connect, settings.database_url)
    conn.autocommit = True
    try:
        cfg, st = automation.load(conn), automation.state(conn)
        if not automation.due(cfg, st):
            return False
        automation.update_state(conn, last_cycle_at=utc_iso())    # first: a crash during the cycle must not make it start again at once
    finally:
        conn.close()
    result = await cycle(jobs, settings)
    conn = await asyncio.to_thread(connect, settings.database_url)
    conn.autocommit = True
    try:
        automation.update_state(conn, last_result=result)
    finally:
        conn.close()
    log.info("automatic reading: %s", "nothing to read" if result["idle"] else ", ".join(f"{s['guild']}:{'+'.join(s['stages'])}:{s['state']}" for s in result["servers"]))
    return True


async def auto_loop(jobs: AnalysisJobs, settings: Settings, seconds: float = TICK_SECONDS) -> None:
    while True:
        try:
            await tick(jobs, settings)
        except asyncio.CancelledError:
            raise
        except Exception as error:                                   # never a reason to stop the application
            log.warning("automatic reading: %s", type(error).__name__)
        await asyncio.sleep(seconds)
