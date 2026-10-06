"""The analysis, run from the interface or the command line: one at a time, in the background, with its progress and a way to stop it.

It chains the stages that exist (conversations, vectors, topics). What it reports is only counts and the names of the stages, never a
message. Each stage can be run again: what is done is not redone.
"""
from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime

from dindon import performance
from dindon.analysis.axes import assign_axes
from dindon.analysis.conversations import build_conversations
from dindon.analysis.embeddings import embed_conversations
from dindon.analysis.extraction import extract_claims
from dindon.analysis.ollama import Ollama, OllamaError
from dindon.analysis.stances import verify_stances
from dindon.analysis.themes import NotEnough, discover_themes
from dindon.clock import utc_iso
from dindon.config import Settings
from dindon.db import connect

STAGES = ("conversations", "embeddings", "themes")      # what "analyse" does; the claims are asked for apart (they are long)
ALL_STAGES = STAGES + ("claims", "axes")


class AnalysisBusy(Exception):
    """An analysis is already running."""


class NotReady(Exception):
    """Ollama is not there, or a model is missing: said before anything is started."""


class AnalysisJobs:
    def __init__(self, settings: Settings, client: Ollama | None = None, echo: Callable[[str], None] | None = None):
        self._settings = settings
        self._echo = echo                                   # where the command line shows the progress as it comes
        self.client = client or Ollama(settings.ollama_url)
        self.embed_model, self.name_model = settings.embed_model, settings.naming_model
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._state = self._idle()
        self._lines: deque[str] = deque(maxlen=40)

    @staticmethod
    def _idle() -> dict:
        return {"state": "idle", "guild": None, "stage": None, "started_at": None, "finished_at": None, "done": 0, "of": None, "error": None}

    def readiness(self) -> dict:
        """What the person needs to know before starting: is Ollama running, and are the two models installed."""
        try:
            installed = self.client.models()
        except OllamaError as error:
            return {"ollama": False, "problem": str(error), "models": {self.embed_model: False, self.name_model: False}}
        have = lambda m: m in installed or f"{m}:latest" in installed  # noqa: E731
        return {"ollama": True, "problem": None, "models": {self.embed_model: have(self.embed_model), self.name_model: have(self.name_model)}}

    def status(self) -> dict:
        with self._lock:
            return {**self._state, "lines": list(self._lines)}

    def start(self, guild_id: int, stages: tuple[str, ...] = STAGES, *, topics: int | None = None, rebuild: bool = False, limit: int | None = None) -> None:
        """Checks that the models are there, then starts. Raises NotReady or AnalysisBusy, before anything is started."""
        ready = self.readiness()
        needed = [m for stage, m in (("embeddings", self.embed_model), ("themes", self.name_model), ("claims", self.name_model), ("claims", self.embed_model), ("axes", self.name_model))
                  if stage in stages]
        if not ready["ollama"]:
            raise NotReady(ready["problem"])
        missing = [m for m in needed if not ready["models"].get(m)]
        if missing:
            raise NotReady("modèle(s) à installer : " + ", ".join(f"ollama pull {m}" for m in missing))
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise AnalysisBusy()
            self._cancel = threading.Event()
            self._lines.clear()
            self._state = {**self._idle(), "state": "running", "guild": str(guild_id), "started_at": utc_iso()}
            self._thread = threading.Thread(target=self._run, args=(guild_id, stages, topics, rebuild, self._cancel, limit), daemon=True, name="analysis")
            self._thread.start()

    def cancel(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._cancel.set()
            self._state["state"] = "cancelling"
            return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # --- the thread ---------------------------------------------------------------------------------

    def _line(self, text: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')} {text}"
        with self._lock:
            self._lines.append(line)
        if self._echo:
            self._echo(line)

    def _stage(self, name: str) -> None:
        with self._lock:
            self._state.update(stage=name, done=0, of=None)
        self._line(name)

    def _progress(self, done: int, of: int) -> None:
        with self._lock:
            self._state.update(done=done, of=of)

    @staticmethod
    def _limits(conn) -> Callable[[], dict]:
        """The performance settings in force, read from the database at most every 5 seconds (a change made in the interface applies during a run)."""
        import time

        cache = {"at": 0.0, "value": performance.clean({})}

        def current() -> dict:
            if time.monotonic() - cache["at"] > 5:
                with contextlib.suppress(Exception):                                       # the last known settings stand
                    cache["value"] = performance.load(conn)
                cache["at"] = time.monotonic()
            return cache["value"]

        return current

    def _run(self, guild_id: int, stages: tuple[str, ...], topics: int | None, rebuild: bool, cancel: threading.Event, limit: int | None = None) -> None:
        error = None
        try:
            with connect(self._settings.database_url, wait=5) as conn:
                conn.autocommit = True
                limits = self._limits(conn)
                self.client.limits, self.client.cancelled = limits, cancel.is_set          # the limits of the machine, read again while this runs
                now = limits()
                if now["ai_max_load"] < 100:
                    self._line(f"vitesse limitée : l'IA travaille {now['ai_max_load']} % du temps (réglage Performance de la page Système)")
                if "conversations" in stages:
                    self._stage("conversations")
                    r = build_conversations(conn, guild_id, rebuild=rebuild)
                    self._line(f"{r['made']} conversations faites ({r['messages']} messages) ; {r['kept']} retenues sur {r['total']}")
                if "embeddings" in stages and not cancel.is_set():
                    self._stage("vecteurs")
                    r = embed_conversations(conn, self.client, self.embed_model, guild_id, batch=lambda: limits()["ai_batch"], progress=self._progress, cancelled=cancel.is_set)
                    self._line(f"{r['done']} vecteurs calculés")
                if "themes" in stages and not cancel.is_set():
                    self._stage("thèmes")
                    r = discover_themes(conn, self.client, guild_id, embed_model=self.embed_model, name_model=self.name_model, topics=topics,
                                        progress=self._line, cancelled=cancel.is_set)
                    self._line(f"{r['topics']} thèmes proposés pour {r['assigned']} conversations (k={r['k']}, {r['named_by_model']} nommés par le modèle)")
                if "claims" in stages and not cancel.is_set():
                    self._stage("positions")
                    r = extract_claims(conn, self.client, self.name_model, self.embed_model, guild_id, limit=limit, progress=self._progress, cancelled=cancel.is_set)
                    self._line(f"{r['done']} conversations lues : {r['claims']} positions retenues avec preuve, {r['refused']} refusées"
                               + (f", {r['failed']} à reprendre (le modèle n'a pas répondu)" if r["failed"] else ""))
                if ("claims" in stages or "axes" in stages) and not cancel.is_set():
                    self._stage("positions : relecture du sens")
                    r = verify_stances(conn, self.client, self.name_model, guild_id, progress=self._progress, cancelled=cancel.is_set)
                    self._line(f"{r['checked']} positions relues : {r['changed']} corrigées, {r['questions']} écartées (une question n'est pas une position)"
                               + (f", {r['failed']} à reprendre" if r["failed"] else ""))
                if ("claims" in stages or "axes" in stages) and not cancel.is_set():
                    self._stage("axes")
                    r = assign_axes(conn, self.client, self.name_model, guild_id, progress=self._progress, cancelled=cancel.is_set, embed_model=self.embed_model)
                    self._line(f"{r['done']} propositions reliées aux axes ({r['links']} liens), {r['scores']} scores de personnes calculés"
                               + (f", {r['failed']} à reprendre" if r["failed"] else ""))
        except NotEnough as problem:                              # words that were written for a person
            error = str(problem)
        except OllamaError as problem:
            error = str(problem)
        except InterruptedError:
            pass
        except Exception as problem:                               # anything else: its kind only (its text could say too much)
            error = f"erreur inattendue ({type(problem).__name__})"
        self.client.limits, self.client.cancelled = None, lambda: False
        with self._lock:
            self._state["finished_at"] = utc_iso()
            self._state["error"] = error
            self._state["state"] = "failed" if error else "cancelled" if cancel.is_set() else "done"
