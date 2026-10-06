"""Discord's REST API, read-only, made for exporting a lot of messages cheaply.

* **One connection per thread, kept open** (HTTP keep-alive): a request does not pay a new TCP and TLS handshake. On a long export that is most of
  the time of a request.
* **Rate limits are respected before they bite**: Discord says in every answer how many requests are left in a bucket (`X-RateLimit-Remaining`)
  and when it resets (`X-RateLimit-Reset-After`). A request that would be refused waits instead, so that the exporter is never refused (and never
  slowed by the penalty of ignoring a 429). A global limit of requests per second is kept too. When a 429 arrives anyway, it waits what Discord asked
  and goes on.
* **Retries** only for what trying again can fix: a dropped connection, a 5xx, a 429. A 401, 403 or 404 is answered at once, in words.
* **The token** goes in one header and nowhere else: it is not in a URL, a log, or an error.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
import urllib.parse
from collections import deque
from collections.abc import Callable
from typing import Any

from dindon.export.errors import DiscordHTTPError, ExporterCancelled, ExporterError, Forbidden, NotFound, Unauthorized

GLOBAL_PER_SECOND = 40          # Discord's limit is 50 for a bot: a margin
MAX_RETRY_AFTER = 120.0         # never wait longer than this for one request: a longer penalty is reported
_DIGITS = re.compile(r"/[0-9]{5,}")


def route_of(method: str, path: str) -> str:
    """The rate-limit bucket of a request, as Discord defines them: the route with its first id (the 'major' resource: a channel, a server) kept and
    the other ids and the emoji of a reaction taken out."""
    first = True

    def replace(match: re.Match) -> str:
        nonlocal first
        if first:
            first = False
            return match[0]
        return "/:id"

    route = _DIGITS.sub(replace, path.split("?")[0])
    return f"{method} " + re.sub(r"/reactions/[^/]+", "/reactions/:emoji", route)


class RateLimiter:
    """Waits when a bucket is empty, and keeps the global rate. Thread-safe; the sleeping is done outside the lock."""

    def __init__(self, per_second: int = GLOBAL_PER_SECOND, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.per_second, self._clock, self._sleep = per_second, clock, sleep
        self._lock = threading.Lock()
        self._until: dict[str, float] = {}       # route -> not before this time
        self._global_until = 0.0
        self._recent: deque[float] = deque()      # when the last requests were sent
        self.waited = 0.0                         # seconds spent waiting, for the figures of an export

    def wait(self, route: str, cancelled: Callable[[], bool] = lambda: False) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._recent and now - self._recent[0] >= 1.0:
                    self._recent.popleft()
                until = max(self._until.get(route, 0.0), self._global_until)
                if until <= now and len(self._recent) >= self.per_second:
                    until = self._recent[0] + 1.0
                if until <= now:
                    self._recent.append(now)
                    return
                delay = until - now
            self._sleep_for(delay, cancelled)

    def _sleep_for(self, delay: float, cancelled: Callable[[], bool]) -> None:
        self.waited += delay
        while delay > 0:
            if cancelled():
                raise ExporterCancelled()
            step = min(delay, 0.25)
            self._sleep(step)
            delay -= step

    def record(self, route: str, header: Callable[[str], str | None]) -> None:
        """Takes into account what an answer says of the bucket (`header` reads a header of the answer)."""
        try:
            remaining = int(header("X-RateLimit-Remaining") or 1)
            reset_after = float(header("X-RateLimit-Reset-After") or 0)
        except (TypeError, ValueError):
            return
        if remaining <= 0 and reset_after > 0:
            with self._lock:
                self._until[route] = max(self._until.get(route, 0.0), self._clock() + reset_after)

    def penalty(self, route: str, seconds: float, is_global: bool) -> None:
        with self._lock:
            target = self._clock() + seconds
            if is_global:
                self._global_until = max(self._global_until, target)
            else:
                self._until[route] = max(self._until.get(route, 0.0), target)


class DiscordClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0, limiter: RateLimiter | None = None, retries: int = 4,
                 sleep: Callable[[float], None] = time.sleep):
        parsed = urllib.parse.urlparse(base_url.rstrip("/"))
        self._scheme, self._host, self._port, self._prefix = parsed.scheme, parsed.hostname or "", parsed.port, parsed.path
        self._token = token[4:] if token.startswith("Bot ") else token
        self.kind: str | None = "bot" if token.startswith("Bot ") else None     # 'bot' or 'account', found out on the first request
        self.timeout, self.retries, self._sleep = timeout, retries, sleep
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self._local = threading.local()
        self._kind_lock = threading.Lock()
        self.requests = 0                                                      # for the figures of an export
        self._count_lock = threading.Lock()

    # --- the connection ---------------------------------------------------------------------------------------

    def _connection(self) -> http.client.HTTPConnection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            cls = http.client.HTTPSConnection if self._scheme == "https" else http.client.HTTPConnection
            connection = self._local.connection = cls(self._host, self._port, timeout=self.timeout)
        return connection

    def _drop(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
        self._local.connection = None

    def close(self) -> None:
        self._drop()

    # --- the token --------------------------------------------------------------------------------------------

    def _authorization(self) -> str:
        return f"Bot {self._token}" if self.kind == "bot" else self._token

    def _resolve_kind(self, cancel: Callable[[], bool]) -> None:
        """Account or bot? As the watcher does it: try as an account, then as a bot."""
        with self._kind_lock:
            if self.kind is not None:
                return
            for kind in ("account", "bot"):
                self.kind = kind
                status, _, _ = self._once("GET", "/users/@me", None, "GET /users/@me", cancel)
                if status != 401:
                    return
            self.kind = None
            raise Unauthorized(401, "Le jeton Discord n'est pas valide (jeton absent, périmé ou mal recopié dans .env).")

    # --- requests ---------------------------------------------------------------------------------------------

    def _once(self, method: str, path: str, params: dict | None, route: str, cancel: Callable[[], bool]) -> tuple[int, Any, Any]:
        """One request, with its rate limit. Returns (status, body, headers); the body is None when it is not JSON."""
        self.limiter.wait(route, cancel)
        if cancel():
            raise ExporterCancelled()
        url = f"{self._prefix}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Authorization": self._authorization(), "User-Agent": "Dindon (local exporter)", "Accept": "application/json"}
        with self._count_lock:
            self.requests += 1
        connection = self._connection()
        try:
            connection.request(method, url, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        except (http.client.HTTPException, OSError):
            self._drop()                                    # a dropped keep-alive connection: the caller opens a new one and tries again
            raise
        if response.getheader("Connection", "").lower() == "close":
            self._drop()
        self.limiter.record(route, response.getheader)
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        return response.status, body, response

    def get(self, path: str, params: dict | None = None, *, cancel: Callable[[], bool] = lambda: False) -> Any:
        """The JSON answer of a GET. Raises Unauthorized, Forbidden, NotFound, or ExporterError once the retries are used up."""
        if self.kind is None:
            self._resolve_kind(cancel)
        route = route_of("GET", path)
        failures = rate_limited = 0
        while True:
            try:
                status, body, response = self._once("GET", path, params, route, cancel)
            except (http.client.HTTPException, OSError) as error:
                failures += 1
                if failures > self.retries:
                    raise ExporterError(f"Discord ne répond pas ({type(error).__name__}).") from None
                self._backoff(failures, cancel)
                continue
            if status == 200:
                return body
            if status == 429:
                rate_limited += 1
                retry_after = float((body or {}).get("retry_after") or response.getheader("Retry-After") or 1.0)
                if retry_after > MAX_RETRY_AFTER or rate_limited > 12:
                    raise ExporterError(f"Discord demande d'attendre {retry_after:.0f} s : l'export est arrêté, il pourra reprendre.")
                self.limiter.penalty(route, retry_after, bool((body or {}).get("global")))
                continue
            if status in (500, 502, 503, 504):
                failures += 1
                if failures > self.retries:
                    raise DiscordHTTPError(status, f"Discord a répondu une erreur ({status}) à {path.split('?')[0]}.")
                self._backoff(failures, cancel)
                continue
            where = path.split("?")[0]
            if status == 401:
                raise Unauthorized(status, "Le jeton Discord n'est pas valide (jeton absent, périmé ou mal recopié dans .env).")
            if status == 403:
                raise Forbidden(status, f"Discord refuse l'accès ({status}) à {where} : le bot est-il bien sur ce serveur, avec le droit de voir ce salon ?")
            if status == 404:
                raise NotFound(status, f"Introuvable ({status}) : {where}.")
            raise DiscordHTTPError(status, f"Réponse inattendue de Discord ({status}) pour {where}.")

    def _backoff(self, attempt: int, cancel: Callable[[], bool]) -> None:
        self.limiter._sleep_for(min(0.5 * 2 ** (attempt - 1), 8.0), cancel)
