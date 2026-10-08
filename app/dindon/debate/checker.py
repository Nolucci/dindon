"""What checks the claims of a message, from the reading of the message to the verdicts (docs/regles-du-bot.md, « Vérification sur Internet »). Synchronous: the engine runs it in a thread.

`Checker.check(text)` takes **the text of a message and nothing else** and returns the results for the claims found in it. Each claim gets a `Lookup` of its own, so that what one claim
found is not available to the next and the budget (2 queries, 3 pages) is per claim.

`build_checker(settings)` returns None, and then nothing is ever read or sent, unless the owner switched the checks on (`DINDON_DEBATE_CHECKS`).

* `observe`: every claim is checked on the Internet and **only written to the database** (to be read by the owner: `dindon debate-report`); nothing is published. Needs a search service.
* `answer`: Dindon **answers first, without the Internet** (`Checker.consider`): certain that a claim is false, it says so under the message, with Valide / Invalide for the participants;
  where they reject its answer it looks on the Internet (`Checker.search`). A claim it cannot answer is checked on the Internet and noted, not published. Works without a search service
  (it then cannot look anything up, and says so).
* `live`: `answer`, and in addition the corrections that trusted sources make by themselves, with no one asking. Needs a measured precision (`resolve_mode`).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from dindon.analysis.ollama import OllamaPool
from dindon.config import Settings
from dindon.debate.claims import AnswerFound, ClaimResult, Considered
from dindon.debate.local import FALSE, TRUE, answer_claim
from dindon.debate.reading import Chat, Reading, read_message
from dindon.debate.scope import Lookup
from dindon.debate.search import FactCheckSearch, SearxSearch
from dindon.debate.trust import Trust
from dindon.debate.verify import verify_claim
from dindon.debate.web import Fetcher

log = logging.getLogger("dindon.bot.debate")


MODES = ("observe", "answer", "live")


def resolve_mode(settings: Settings) -> tuple[str, str | None]:
    """The mode that the bot will really run in, and why it is not the one asked for. `live` (the corrections that sources make by themselves, in public) needs the precision of « contredit »
    that the owner measured (tools/measure_claims.py) to be given and to reach the threshold: without it the bot stays at `answer`, however `.env` asks."""
    if settings.debate_checks != "live":
        return settings.debate_checks, None
    if settings.debate_precision is None:
        return "answer", "DINDON_DEBATE_CHECKS=live demande DINDON_DEBATE_PRECISION (la précision mesurée par tools/measure_claims.py verify)"
    if settings.debate_precision < settings.debate_min_precision:
        return "answer", f"la précision mesurée {settings.debate_precision:.2f} est sous le seuil {settings.debate_min_precision:.2f}"
    return "live", None


HELPERS_REFRESH_SECONDS = 30                                      # how often the list of helper computers is read again and the ones that failed are tried again


class Checker:
    def __init__(self, llm: Chat, model: str, make_lookup: Callable[[], Lookup] | None, trust: Trust | None = None, mode: str = "observe",
                 local_url: str | None = None, load_helpers: Callable[[], tuple[str, ...]] | None = None, helpers: tuple[str, ...] = ()):
        self.llm, self.model, self._make_lookup, self._trust, self.mode = llm, model, make_lookup, trust or Trust(), mode
        self._local_url, self._load_helpers, self._helpers, self._ready_at = local_url, load_helpers, tuple(helpers), time.monotonic()
        self._listed_at = float("-inf")

    def _ready(self) -> None:
        """Before a check, at most every half minute: the helper computers that the owner set in the interface are read again (a new list builds a new pool) and the ones that failed are tried
        again. Without a pool of computers (tests, or a plain client) nothing is done. Never raises: the last list stands."""
        if not isinstance(self.llm, OllamaPool) or time.monotonic() - self._ready_at < HELPERS_REFRESH_SECONDS:
            return
        self._ready_at = time.monotonic()
        if self._load_helpers is not None and self._local_url:
            try:
                urls = tuple(self._load_helpers())
            except Exception:
                urls = self._helpers
            if urls != self._helpers:
                self._helpers, self.llm = urls, OllamaPool(self._local_url, urls, timeout=300)
                log.info("the debates are now checked on %d computer(s)", len(urls) + 1)
        self.llm.retry_failed()

    def computers(self) -> list[dict]:
        """What each computer that checks the debates is doing, for the page Débats (counts and durations, never a text): the server and its helpers, with whether it answered and has the model."""
        if not isinstance(self.llm, OllamaPool):
            return []
        if time.monotonic() - self._listed_at >= HELPERS_REFRESH_SECONDS:     # the lists of models only exist once a computer was asked: without this, every one shows « hors ligne » until the first check
            self._listed_at = time.monotonic()
            self.llm.retry_failed()
        listed = self.llm.known_models()
        rows = self.llm.activity()
        for row in rows:
            names = listed.get(row["url"])
            row["online"] = names is not None and not row["failed"]
            row["has_model"] = bool(names) and (self.model in names or f"{self.model}:latest" in names)
        return rows

    @property
    def can_search(self) -> bool:
        """Whether there is a search service to look anything up with."""
        return self._make_lookup is not None

    def search(self, reading: Reading) -> ClaimResult:
        """The claim checked on the Internet, with a budget of its own (2 searches, 3 pages): the sources and the verdict. Needs a search service."""
        self._ready()
        return verify_claim(self._make_lookup(), self.llm, self.model, self._trust, reading)

    def check(self, text: str) -> list[ClaimResult]:
        """The results for the claims in one message (an empty list when it holds none), every one checked on the Internet. Raises what the local model raises when it cannot answer: the
        message stays unread and is tried later."""
        self._ready()
        return [self.search(reading) for reading in read_message(self.llm, self.model, text)]

    def consider(self, text: str) -> Considered:
        """What Dindon does with a message when it answers first: for each claim, the local model says whether it is **certain** that it is true or false, with no Internet. True: noted, nothing
        is said. False: Dindon's answer, which the participants will judge. Not certain: the claim is checked on the Internet, if there is a search service, and noted. Raises what the model
        raises: the message stays unread and is tried later."""
        self._ready()
        answers: list[AnswerFound] = []
        results: list[ClaimResult] = []
        for reading in read_message(self.llm, self.model, text):
            local = answer_claim(self.llm, self.model, reading)
            if local.verdict in (TRUE, FALSE):
                answers.append(AnswerFound(reading.claim, reading.said, reading.query, local.verdict, local.answer, self.model))
            elif self.can_search:
                results.append(self.search(reading))
        return Considered(tuple(answers), tuple(results))


def notice_mode(checker: object | None) -> str:
    """What the members are told that Dindon does (texts.notice): `observe`, `answer`, `local` (it answers but has no search service: nothing leaves the machine) or `live`."""
    mode = getattr(checker, "mode", "observe")
    return "local" if mode == "answer" and not getattr(checker, "can_search", True) else mode


def build_checker(settings: Settings, load_helpers: Callable[[], tuple[str, ...]] | None = None) -> Checker | None:
    if settings.debate_checks not in MODES:
        return None
    mode, downgraded = resolve_mode(settings)
    searchers = []
    if settings.factcheck_api_key:
        searchers.append(FactCheckSearch(settings.factcheck_api_key))
    if settings.searxng_url:
        searchers.append(SearxSearch(settings.searxng_url))
    if not searchers and mode == "observe":
        log.warning("DINDON_DEBATE_CHECKS=observe is on but no search service is set (DINDON_FACTCHECK_API_KEY or DINDON_SEARXNG_URL): the claims are not checked")
        return None
    if not searchers:
        mode = "answer"                                           # without a search service Dindon can still answer from its local model: it just cannot look anything up
        log.warning("no search service is set (DINDON_FACTCHECK_API_KEY or DINDON_SEARXNG_URL): Dindon answers from its local model only, and cannot look anything up on the Internet")
    fetcher = Fetcher()                                           # public addresses only, ports 80 and 443, robots.txt respected (debate/web.py)
    if downgraded:
        log.warning("the corrections that sources make by themselves are NOT on (%s). Dindon answers and the participants judge, or the claims are noted", downgraded)
    log.info("the claims of the debates are checked in %s mode (%d search service(s))%s", mode, len(searchers), "; nothing is published" if mode == "observe" else "")
    make_lookup = (lambda: Lookup(searchers, fetcher)) if searchers else None
    helpers: tuple[str, ...] = tuple(settings.analysis_workers or ())
    if load_helpers is not None:
        try:
            helpers = tuple(load_helpers())
        except Exception:                                         # the database is away at the start: the list is read again in half a minute
            pass
    # The checks go through a pool of computers even when there is only the server: the page Débats shows what each one is doing. The helpers are the owner's own computers (analysis/helpers.py).
    return Checker(OllamaPool(settings.ollama_url, helpers, timeout=300), settings.debate_model, make_lookup, mode=mode,
                   local_url=settings.ollama_url, load_helpers=load_helpers, helpers=helpers)
