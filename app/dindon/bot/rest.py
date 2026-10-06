"""Discord's REST API, for what the bot writes: a thread, a message, an edit. Synchronous (urllib, like the rest of Dindon's Discord calls): the engine
runs it in a thread (`asyncio.to_thread`) so that a slow answer never holds up the Gateway.

* A **429** (rate limit) is waited out and retried, a few times at most: Discord says how long (`retry_after`). After that the 429 is returned like any
  other answer, and the caller decides.
* An answer is always returned, never raised: `status` 0 means Discord could not be reached. Callers look at the status.
* Nothing here logs a path, a body or an answer: they hold messages and identifiers. The token is only ever sent to the API address.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

MAX_WAIT_SECONDS = 10       # a rate limit longer than this is returned to the caller instead of being slept through
MAX_RETRIES = 3


@dataclass(frozen=True)
class Response:
    status: int                       # 0: Discord could not be reached
    data: dict | list | None = None   # the JSON answer, when there is one

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def id(self) -> int | None:
        """The identifier of what was created (a thread, a message), or None."""
        value = self.data.get("id") if isinstance(self.data, dict) else None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def code(self) -> int | None:
        """Discord's own error code (50013: missing permissions, 10003: unknown channel…), when it gave one."""
        value = self.data.get("code") if isinstance(self.data, dict) else None
        return value if isinstance(value, int) else None


class DiscordREST:
    def __init__(self, token: str, api_url: str, *, sleep: Callable[[float], None] = time.sleep, timeout: float = 15):
        self._token = token[4:] if token.startswith("Bot ") else token
        self._api = api_url.rstrip("/")
        self._sleep = sleep
        self._timeout = timeout

    def call(self, method: str, path: str, body: dict | list | None = None, *, authorized: bool = True) -> Response:
        data = None if body is None else json.dumps(body).encode()      # (http.client itself sends « Content-Length: 0 » on a PUT or POST with no body)
        headers = {"User-Agent": "dindon"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if authorized:
            headers["Authorization"] = f"Bot {self._token}"
        response = Response(0)
        for attempt in range(MAX_RETRIES + 1):
            response, wait = self._once(method, path, data, headers)
            if response.status != 429 or attempt == MAX_RETRIES or wait > MAX_WAIT_SECONDS:
                return response
            self._sleep(wait)
        return response

    def _once(self, method: str, path: str, data: bytes | None, headers: dict) -> tuple[Response, float]:
        request = urllib.request.Request(f"{self._api}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as answer:
                return Response(answer.status, _json(answer.read())), 0.0
        except urllib.error.HTTPError as error:
            payload = _json(error.read())
            wait = 0.0
            if error.code == 429:
                wait = _retry_after(payload, error.headers.get("Retry-After"))
            return Response(error.code, payload), wait
        except OSError:
            return Response(0), 0.0


def _json(raw: bytes):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _retry_after(payload, header: str | None) -> float:
    for value in ((payload or {}).get("retry_after") if isinstance(payload, dict) else None, header):
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return 1.0
