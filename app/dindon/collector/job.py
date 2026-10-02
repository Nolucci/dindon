"""An import started from the interface: one at a time, in the background, with its progress and a way to stop it.

It is `Collector.backfill` (the same as the command line), run in a thread of the application. What it reports is only counts and
the names of the channels, never a message.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

from dindon.collector.discord_api import DiscordError, RateLimited
from dindon.collector.selection import ImportSelection, SelectionError, resolve_channels
from dindon.collector.watch import Collector
from dindon.config import Settings
from dindon.db import connect


class ImportBusy(Exception):
    """An import is already running."""


class NotConfigured(Exception):
    """No token, or no server to follow: there is nothing to import from."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImportJobs:
    def __init__(self, settings: Settings, collector_factory=None):
        self._settings = settings
        self._factory = collector_factory or (lambda: Collector(settings))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._state = self._idle()
        self._lines: deque[str] = deque(maxlen=40)

    @staticmethod
    def _idle() -> dict:
        return {"state": "idle", "guild": None, "selection": None, "started_at": None, "finished_at": None, "planned": None, "of": None,
                "done": 0, "failed": 0, "cancelled": 0, "messages": 0, "error": None}

    def configured(self) -> bool:
        return bool(self._settings.discord_token and self._settings.guild_ids)

    def status(self) -> dict:
        with self._lock:
            return {**self._state, "lines": list(self._lines)}

    def start(self, guild_id: int, selection: ImportSelection) -> None:
        """Checks the selection (the channels are looked up on Discord) and starts. Raises NotConfigured, ImportBusy, SelectionError,
        DiscordError or RateLimited, all before anything is started."""
        if not self.configured():
            raise NotConfigured()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ImportBusy()
        collector = self._factory()
        collector.api.resolve_kind()
        if selection.channels:
            resolve_channels(selection.channels, collector._channels_of(guild_id))  # a wrong name is told now, not after the start
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise ImportBusy()
            self._cancel = threading.Event()
            self._lines.clear()
            self._state = {**self._idle(), "state": "running", "guild": str(guild_id), "selection": selection.describe(), "started_at": _now()}
            self._thread = threading.Thread(target=self._run, args=(collector, guild_id, selection, self._cancel), daemon=True, name="import")
            self._thread.start()

    def cancel(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._cancel.set()
            self._state["state"] = "cancelling"
            return True

    # --- the thread ---------------------------------------------------------------------------------

    def _line(self, text: str) -> None:
        with self._lock:
            self._lines.append(f"{datetime.now().strftime('%H:%M:%S')} {text}")

    def _report(self, event: dict) -> None:
        with self._lock:
            if event["event"] == "planned":
                self._state["planned"], self._state["of"] = event["channels"], event["of"]
            elif event["cancelled"]:
                self._state["cancelled"] += 1
            elif event["ok"]:
                self._state["done"] += 1
                self._state["messages"] += event["messages"]
            else:
                self._state["failed"] += 1

    def _new_connection(self):
        conn = connect(self._settings.database_url, wait=5)
        conn.autocommit = True
        return conn

    def _run(self, collector: Collector, guild_id: int, selection: ImportSelection, cancel: threading.Event) -> None:
        error = None
        try:
            collector.backfill(self._new_connection, guild_id, parallel=2, progress=self._line, selection=selection, cancel=cancel,
                               report=self._report)
        except (SelectionError, DiscordError) as problem:      # words that were written for a person
            error = str(problem)
        except RateLimited as problem:
            error = f"Discord demande d'attendre {problem.retry_after:.0f} s : {problem}"
        except Exception as problem:                            # anything else: its kind only (never its text, which could say too much)
            error = f"erreur inattendue ({type(problem).__name__})"
        with self._lock:
            self._state["finished_at"] = _now()
            self._state["error"] = error
            self._state["state"] = "failed" if error else "cancelled" if cancel.is_set() else "done"
