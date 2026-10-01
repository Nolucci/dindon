"""The inbox: any JSON v2 export dropped in `inbox/` is imported, then moved to `archive/`.

Exports made by hand (with the graphical application or the command line) end up here. The exporter
leaves its output file empty while it works and writes it at the end, so:

* an empty file is still being written: it waits;
* a file that does not parse yet (being copied) waits too, and is put aside in `inbox/failed/` with the
  reason if it is still unreadable a minute later;
* a file that was read is moved to `archive/YYYY-MM/<start of its SHA-256>-<name>`.
"""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from dindon.ingest.loader import IngestResult, InvalidExport, ingest_file

log = logging.getLogger("dindon.inbox")

SETTLE_SECONDS = 2        # a file modified more recently than this may still be written
GIVE_UP_SECONDS = 60      # an unreadable file that has not changed for this long is put aside


@dataclass
class InboxOutcome:
    path: Path
    result: IngestResult | None = None
    error: str | None = None


def archive_file(path: Path, archive: Path, sha256: str) -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    target = archive / month / f"{sha256[:8]}-{path.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), target)  # the same content has the same name: moving it again changes nothing
    return target


def scan_once(conn: psycopg.Connection, inbox: Path, archive: Path, now: float | None = None) -> list[InboxOutcome]:
    """Imports every file of the inbox that is ready. Never raises for a bad file: it is reported and put aside."""
    now = time.time() if now is None else now
    outcomes: list[InboxOutcome] = []
    if not inbox.is_dir():
        return outcomes
    for path in sorted((p for p in inbox.glob("*.json") if p.is_file()), key=lambda p: p.stat().st_mtime):
        stat = path.stat()
        if stat.st_size == 0 or now - stat.st_mtime < SETTLE_SECONDS:
            continue  # still being written
        try:
            result = ingest_file(conn, path)
        except InvalidExport as error:
            if now - stat.st_mtime < GIVE_UP_SECONDS:
                continue  # perhaps still being copied: try again
            failed = inbox / "failed"
            failed.mkdir(exist_ok=True)
            shutil.move(str(path), failed / path.name)
            (failed / f"{path.name}.error.txt").write_text(str(error) + "\n", encoding="utf-8")
            log.error("unreadable export put aside in failed/: %s", error)
            outcomes.append(InboxOutcome(path, error=str(error)))
            continue
        except psycopg.Error as error:
            # The file is fine, the database is not (down, restarting): leave it where it is for the next scan
            log.error("database error while importing %s: %s", path.name, type(error).__name__)
            outcomes.append(InboxOutcome(path, error=type(error).__name__))
            break
        archive_file(path, archive, result.sha256)
        log.info("imported %s: %d new, %d updated of %d (%.1fs)", path.name[-40:], result.messages_new,
                 result.messages_updated, result.messages_in_file, result.seconds)
        outcomes.append(InboxOutcome(path, result=result))
    return outcomes
