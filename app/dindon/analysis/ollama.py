"""Models through Ollama's HTTP API, on this host or trusted computers in a private network.

Two calls are used: the vector of a text (`/api/embed`) and a short answer in a given JSON shape (`/api/chat` with `format`). What is
sent is the text of conversations, so helpers must be the administrator's own trusted computers, reachable only through a private network.
"""
import json
import math
import http.client
import socket
import threading
import time
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from urllib.parse import urlsplit


# A safety net under the grammar of each answer: a model that loops is cut after about a minute on a laptop instead of filling its whole context
MAX_ANSWER_TOKENS = 2500


class OllamaError(Exception):
    """Ollama cannot answer now (not running, model missing, timeout) or answered something unusable."""


class Ollama:
    parallelism = 1
    def __init__(self, base_url: str, timeout: float = 600):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # The limits of the machine (performance.py), set by the analysis while it runs: a function that gives the settings in force, and one that says
        # that the person asked to stop (so that a long pause ends at once)
        self.limits: Callable[[], dict] | None = None
        self.cancelled: Callable[[], bool] = lambda: False
        self.sleep: Callable[[float], None] = time.sleep

    def _settings(self) -> dict:
        try:
            return self.limits() if self.limits else {}
        except Exception:                                  # the limits are a courtesy: never a reason for a call to fail
            return {}

    def _pause(self, started: float, settings: dict) -> None:
        """After a call: wait, so that the models work only `ai_max_load` percent of the time."""
        from dindon.performance import pause_for

        elapsed = time.monotonic() - started
        waited = 0.0
        while not self.cancelled():
            current = self._settings() if self.limits else settings
            wait = pause_for(elapsed, int(current.get("ai_max_load", settings.get("ai_max_load", 100)))) - waited
            if wait <= 0:
                break
            step = min(wait, 0.5)
            self.sleep(step)
            waited += step

    def _call(self, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        """Close the HTTP socket when an analysis is cancelled, including during a model call."""
        url = urlsplit(self.base_url)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise OllamaError(f"Adresse Ollama invalide : {self.base_url}")
        duration = timeout if timeout is not None else self.timeout
        connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(url.hostname, url.port, timeout=min(duration, 5))
        finished = threading.Event()

        def interrupt() -> None:
            while not finished.wait(0.1):
                if self.cancelled():
                    with suppress(OSError):
                        if connection.sock:
                            connection.sock.shutdown(socket.SHUT_RDWR)
                    connection.close()
                    return

        watcher = threading.Thread(target=interrupt, daemon=True, name="ollama-cancel")
        watcher.start()
        try:
            if self.cancelled():
                raise InterruptedError("analyse annulée")
            data = None if body is None else json.dumps(body).encode()
            connection.request("POST" if data is not None else "GET", url.path.rstrip("/") + path, body=data,
                               headers={"Content-Type": "application/json"} if data is not None else {})
            if connection.sock:
                connection.sock.settimeout(duration)
            response = connection.getresponse()
            raw = response.read()
            if self.cancelled():
                raise InterruptedError("analyse annulée")
            if response.status >= 400:
                try:
                    detail = json.loads(raw).get("error", "")
                except (ValueError, AttributeError):
                    detail = ""
                raise OllamaError(f"Ollama a refusé ({response.status}) : {detail or path}")
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise OllamaError("Ollama a répondu autre chose que du JSON") from None
        except (http.client.HTTPException, TimeoutError, ConnectionError, OSError) as error:
            if self.cancelled():
                raise InterruptedError("analyse annulée") from None
            raise OllamaError(f"Ollama ne répond pas à {self.base_url} ({type(error).__name__})") from None
        finally:
            finished.set()
            connection.close()
            watcher.join(timeout=0.2)

    def models(self, timeout: float = 5) -> list[str]:
        """The names of the models that are installed (an empty list is a running Ollama with nothing in it)."""
        return sorted(m["name"] for m in self._call("/api/tags", timeout=timeout).get("models", []))

    def has(self, model: str) -> bool:
        installed = self.models()
        return model in installed or f"{model}:latest" in installed

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """One vector per text, of length 1 (the direction is what counts)."""
        settings = self._settings()
        body = {"model": model, "input": texts, "truncate": False, "keep_alive": settings.get("ai_keep_alive", "10m")}
        if settings.get("ai_threads"):
            body["options"] = {"num_thread": int(settings["ai_threads"])}
        started = time.monotonic()
        answer = self._call("/api/embed", body)
        vectors = answer.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise OllamaError("Ollama n'a pas rendu un vecteur par texte")
        self._pause(started, settings)
        return [_unit(v) for v in vectors]

    def embed_batches(self, model: str, groups: list[list[str]]) -> list[list[list[float]]]:
        return [self.embed(model, group) for group in groups]

    def chat_json(self, model: str, system: str, user: str, schema: dict, num_ctx: int = 8192) -> dict:
        """An answer of the model in the shape of `schema`. Deterministic (temperature 0), without a chain of thought, and never longer than MAX_ANSWER_TOKENS."""
        settings = self._settings()
        options = {"temperature": 0, "num_ctx": num_ctx, "num_predict": MAX_ANSWER_TOKENS}
        if settings.get("ai_threads"):
            options["num_thread"] = int(settings["ai_threads"])
        started = time.monotonic()
        answer = self._call("/api/chat", {
            "model": model, "stream": False, "format": schema, "think": False, "keep_alive": settings.get("ai_keep_alive", "10m"),
            "options": options,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        try:
            value = json.loads(answer["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            raise OllamaError("le modèle n'a pas rendu du JSON") from None
        if not isinstance(value, dict):
            raise OllamaError("le modèle n'a pas rendu un objet JSON")
        self._pause(started, settings)
        return value


class OllamaPool:
    """Share independent inference calls between Ollama instances; the database stays on the server.

    Independent calls use one slot per computer. Failed calls are retried on another
    compatible computer; measured throughput adjusts the targets after each round.
    """

    def __init__(self, local_url: str, helper_urls: tuple[str, ...], timeout: float = 600):
        unique = [url for url in dict.fromkeys(helper_urls) if url and url != local_url] + [local_url]
        self.clients = [Ollama(url, timeout=timeout) for url in unique]
        self.local = self.clients[-1]
        self.limits: Callable[[], dict] | None = None
        self.cancelled: Callable[[], bool] = lambda: False
        self._models: dict[str, set[str]] = {}
        self._digests: dict[str, dict[str, str]] = {}
        self._failed: set[str] = set()
        self._busy: dict[str, int] = {}                  # calls in flight on each computer
        self._activity: dict[str, dict] = {}              # what each computer is doing and has done since the last reset (counts only, never a text)
        self._sent: dict[tuple[str, str, str], int] = {}                  # calls given to each computer since the last reset (for the shares)
        self.shares: dict[str, int] = {}                 # percentage of the work by base_url; empty: equal split
        self._lock = threading.Condition()
        self._measurements: dict[tuple[str, str, str], dict] = {}
        self._baseline: dict[tuple[str, str, str], dict] = {}
        self._rates: dict[tuple[str, str, str], float] = {}
        self._adaptive: dict[tuple[str, str], dict[str, int]] = {}
        self._last_round: dict[str, dict] = {}

    def _act(self, url: str) -> dict:
        return self._activity.setdefault(url, {"active": 0, "kind": None, "since": None, "calls": 0, "items": 0, "seconds": 0.0,
                                               "errors": 0, "last_error": None, "last_at": None})

    def activity(self) -> list[dict]:
        """Live report for the analysis page: no network call, only what this pool has seen."""
        now = time.time()
        with self._lock:
            total = sum(self._act(c.base_url)["calls"] for c in self.clients) or 1
            rows = []
            for client in self.clients:
                a = self._act(client.base_url)
                rows.append({"url": client.base_url, "local": client is self.local, "failed": client.base_url in self._failed,
                             "active": a["active"], "kind": a["kind"] if a["active"] else None,
                             "running_for": round(now - a["since"], 1) if a["active"] and a["since"] else None,
                             "calls": a["calls"], "items": a["items"], "average": round(a["seconds"] / a["calls"], 2) if a["calls"] else None,
                             "errors": a["errors"], "last_error": a["last_error"], "last_at": a["last_at"],
                             "observed": round(100 * a["calls"] / total),
                             "share": self._last_round.get(client.base_url, {}).get("share", self.shares.get(client.base_url)),
                             "round": dict(self._last_round[client.base_url]) if client.base_url in self._last_round else None})
            return rows

    def set_shares(self, shares: dict[str, int] | None) -> None:
        """Percentages by URL (the server included). A computer at 0 gets nothing unless it is the only one able to answer."""
        with self._lock:
            self.shares = {url: int(v) for url, v in (shares or {}).items()}
            self._sent.clear()
            self._adaptive.clear()
            self._last_round.clear()
            self._lock.notify_all()

    def _pick(self, eligible: list[Ollama], shares: dict[str, int], operation: tuple[str, str]) -> Ollama:
        """The computer that is the furthest below its share. Without shares: the least busy one, a helper before the server. Call with the lock held."""
        if not shares:
            return min(eligible, key=lambda c: (self._busy.get(c.base_url, 0), c is self.local))
        client = min(eligible, key=lambda c: ((self._sent.get((*operation, c.base_url), 0) + 1) / max(shares.get(c.base_url, 0), 1),
                                            self._busy.get(c.base_url, 0), c is self.local))
        key = (*operation, client.base_url)
        self._sent[key] = self._sent.get(key, 0) + 1
        return client

    @property
    def parallelism(self) -> int:
        return max(1, len(self._models) - len(self._failed))

    def _sync(self) -> None:
        for client in self.clients:
            client.limits, client.cancelled = self.limits, self.cancelled

    def models(self, timeout: float = 5) -> list[str]:
        found: set[str] = set()
        self._models = {}
        self._digests = {}
        errors = []
        for client in self.clients:
            try:
                # Health checks must not inherit the cancellation callback of an
                # analysis request running (or just stopped) on this client.
                listed = Ollama(client.base_url, timeout=client.timeout)._call("/api/tags", timeout=timeout).get("models", [])
                names = {m["name"] for m in listed}
                self._models[client.base_url] = names
                self._digests[client.base_url] = {m["name"]: m.get("digest", "") for m in listed}
                found.update(names)
            except OllamaError as error:
                errors.append(str(error))
        if not self._models:
            raise OllamaError("Aucun ordinateur d'analyse ne répond : " + "; ".join(errors))
        return sorted(found)

    def reset(self) -> None:
        """Try previously failed helpers again for a new analysis."""
        with self._lock:
            self._failed.clear()
            self._sent.clear()
            self._activity.clear()
            self._measurements.clear()
            self._baseline.clear()
            self._rates.clear()
            self._adaptive.clear()
            self._last_round.clear()

    def status(self, wanted: tuple[str, ...] = ()) -> list[dict]:
        """A fresh, content-free health report for the admin interface."""
        with suppress(OllamaError):
            self.models(timeout=2)
        result = []
        for client in self.clients:
            online = client.base_url in self._models
            usable = [model for model in wanted if online and client in self._eligible(model)] if self._models else []
            result.append({"url": client.base_url, "online": online, "models": sorted(self._models.get(client.base_url, set())),
                           "usable": usable, "local": client is self.local})
        return result

    def _eligible(self, model: str) -> list[Ollama]:
        if not self._models:
            self.models()
        candidates = [client for client in self.clients if client.base_url not in self._failed and (model in self._models.get(client.base_url, set())
                      or f"{model}:latest" in self._models.get(client.base_url, set()))]
        # One vector space must not contain embeddings from different model builds.
        reference = next((self._digests.get(c.base_url, {}).get(model) or self._digests.get(c.base_url, {}).get(f"{model}:latest")
                          for c in reversed(candidates) if self._digests.get(c.base_url, {}).get(model)
                          or self._digests.get(c.base_url, {}).get(f"{model}:latest")), None)
        return [c for c in candidates if not reference or (self._digests.get(c.base_url, {}).get(model)
                or self._digests.get(c.base_url, {}).get(f"{model}:latest")) == reference]

    def parallelism_for(self, model: str) -> int:
        eligible = self._eligible(model)
        if self.shares:
            eligible = [c for c in eligible if self.shares.get(c.base_url, 0) > 0] or eligible
        return max(1, len(eligible))

    def _timed(self, client: Ollama, method: str, *args):
        """One call, recorded for the live report. `args[1]` is the list of texts for the vectors."""
        kind, items = ("vecteurs", len(args[1])) if method == "embed" else ("nommage et lecture", 1)
        started = time.monotonic()
        with self._lock:
            a = self._act(client.base_url)
            a.update(active=a["active"] + 1, kind=kind, since=a["since"] if a["active"] else time.time())
        try:
            result = getattr(client, method)(*args)
        except BaseException as error:
            with self._lock:
                a = self._act(client.base_url)
                a["errors"] += 1
                a["last_error"] = type(error).__name__ if isinstance(error, InterruptedError) else str(error)[:160]
            raise
        else:
            with self._lock:
                a = self._act(client.base_url)
                elapsed = time.monotonic() - started
                a.update(calls=a["calls"] + 1, items=a["items"] + items, seconds=a["seconds"] + elapsed, last_at=time.time())
                key = (client.base_url, method, args[0])
                measured = self._measurements.setdefault(key, {"calls": 0, "items": 0, "seconds": 0.0})
                measured.update(calls=measured["calls"] + 1, items=measured["items"] + items, seconds=measured["seconds"] + elapsed)
            return result
        finally:
            with self._lock:
                a = self._act(client.base_url)
                a["active"] -= 1

    def begin_round(self) -> None:
        with self._lock:
            self._baseline = {key: dict(value) for key, value in self._measurements.items()}

    def finish_round(self, number: int, model: str) -> list[dict]:
        """Snapshot this round and smooth throughput separately for each operation/model.

        Pauses count as occupied time. Sparse samples retain the previous estimate;
        a zero configured share stays excluded. Targets never queue work on a busy host.
        """
        with self._lock:
            totals = {c.base_url: {"number": number, "calls": 0, "items": 0, "seconds": 0.0} for c in self.clients}
            for key, measured in self._measurements.items():
                old = self._baseline.get(key, {"calls": 0, "items": 0, "seconds": 0.0})
                delta = {field: measured[field] - old[field] for field in old}
                row = totals[key[0]]
                for field in delta:
                    row[field] += delta[field]
                if delta["calls"] and delta["seconds"] > 0:
                    rate = delta["items"] / delta["seconds"]
                    self._rates[key] = 0.5 * self._rates[key] + 0.5 * rate if key in self._rates else rate
            self._baseline = {key: dict(value) for key, value in self._measurements.items()}
            for method, name in {(key[1], key[2]) for key in self._rates}:
                eligible = self._eligible(name)
                wanted = [c for c in eligible if not self.shares or self.shares.get(c.base_url, 0) > 0] or eligible
                rates = {c.base_url: self._rates.get((c.base_url, method, name)) for c in wanted}
                # Do not guess the capacity of a computer that has not answered yet.
                if rates and all(rate is not None for rate in rates.values()):
                    total = sum(rates.values())
                    exact = {url: 100 * rate / total for url, rate in rates.items()}
                    target = {url: max(1, int(value)) for url, value in exact.items()}
                    while sum(target.values()) != 100:
                        if sum(target.values()) < 100:
                            url = max(target, key=lambda u: exact[u] - target[u])
                            target[url] += 1
                        else:
                            url = max((u for u in target if target[u] > 1), key=lambda u: target[u] - exact[u])
                            target[url] -= 1
                    self._adaptive[(method, name)] = target
            targets = self._adaptive.get(("chat_json", model), self.shares)
            for url, row in totals.items():
                row["average"] = round(row["seconds"] / row["calls"], 2) if row["calls"] else None
                row["seconds"] = round(row["seconds"], 2)
                row["share"] = targets.get(url, 0) if targets else None
            self._last_round = totals
            self._sent.clear()
            return [{"url": c.base_url, "local": c is self.local, **totals[c.base_url]} for c in self.clients]

    def _dispatch(self, method: str, *args):
        self._sync()
        while True:
            with self._lock:
                while True:
                    if self.cancelled():
                        raise InterruptedError("analyse annulée")
                    eligible = self._eligible(args[0])
                    if not eligible:
                        raise OllamaError(f"Le modèle {args[0]} n'est disponible sur aucun ordinateur d'analyse")
                    wanted = [c for c in eligible if not self.shares or self.shares.get(c.base_url, 0) > 0] or eligible
                    free = [c for c in wanted if not self._busy.get(c.base_url, 0)]
                    if free:
                        shares = self._adaptive.get((method, args[0]), self.shares)
                        client = self._pick(free, shares, (method, args[0]))
                        self._busy[client.base_url] = 1
                        break
                    self._lock.wait(timeout=0.1)
            try:
                return self._timed(client, method, *args)
            except OllamaError:
                with self._lock:
                    self._failed.add(client.base_url)
                if not self._eligible(args[0]):
                    raise
            finally:
                with self._lock:
                    self._busy[client.base_url] = 0
                    self._lock.notify_all()

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return self._dispatch("embed", model, texts)

    def embed_batches(self, model: str, groups: list[list[str]]) -> list[list[list[float]]]:
        if len(groups) < 2:
            return [self.embed(model, group) for group in groups]
        self._sync()
        with ThreadPoolExecutor(max_workers=min(self.parallelism_for(model), len(groups))) as executor:
            return list(executor.map(lambda group: self.embed(model, group), groups))

    def chat_json(self, model: str, system: str, user: str, schema: dict, num_ctx: int = 8192) -> dict:
        return self._dispatch("chat_json", model, system, user, schema, num_ctx)


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)
