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

    A disconnected helper is retried on the local instance. Only embedding batches are
    parallelised: the other analysis stages currently depend on previous results.
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
        self._cursor = 0
        self._busy: dict[str, int] = {}                  # calls in flight on each computer
        self._activity: dict[str, dict] = {}              # what each computer is doing and has done since the last reset (counts only, never a text)
        self._sent: dict[str, int] = {}                  # calls given to each computer since the last reset (for the shares)
        self.shares: dict[str, int] = {}                 # percentage of the work by base_url; empty: equal split
        self._lock = threading.Lock()

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
                             "observed": round(100 * a["calls"] / total), "share": self.shares.get(client.base_url) if self.shares else None})
            return rows

    def set_shares(self, shares: dict[str, int] | None) -> None:
        """Percentages by URL (the server included). A computer at 0 gets nothing unless it is the only one able to answer."""
        with self._lock:
            self.shares = {url: int(v) for url, v in (shares or {}).items()}
            self._sent.clear()

    def _pick(self, eligible: list[Ollama]) -> Ollama:
        """The computer that is the furthest below its share. Without shares: the least busy one, a helper before the server. Call with the lock held."""
        if not self.shares:
            return min(eligible, key=lambda c: (self._busy.get(c.base_url, 0), c is self.local))
        wanted = [c for c in eligible if self.shares.get(c.base_url, 0) > 0] or eligible
        client = min(wanted, key=lambda c: ((self._sent.get(c.base_url, 0) + 1) / max(self.shares.get(c.base_url, 0), 1),
                                            self._busy.get(c.base_url, 0), c is self.local))
        self._sent[client.base_url] = self._sent.get(client.base_url, 0) + 1
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
                a.update(calls=a["calls"] + 1, items=a["items"] + items, seconds=a["seconds"] + time.monotonic() - started, last_at=time.time())
            return result
        finally:
            with self._lock:
                a = self._act(client.base_url)
                a["active"] -= 1

    def _call_on(self, client: Ollama, method: str, *args):
        try:
            return self._timed(client, method, *args)
        except OllamaError:
            with self._lock:
                self._failed.add(client.base_url)
            if client is self.local or self.local not in self._eligible(args[0]):
                raise
            return self._timed(self.local, method, *args)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        self._sync()
        eligible = self._eligible(model)
        if not eligible:
            raise OllamaError(f"Le modèle {model} n'est installé sur aucun ordinateur d'analyse")
        with self._lock:
            if self.shares:
                client = self._pick(eligible)
            else:
                client = eligible[self._cursor % len(eligible)]
                self._cursor += 1
        return self._call_on(client, "embed", model, texts)

    def embed_batches(self, model: str, groups: list[list[str]]) -> list[list[list[float]]]:
        if len(groups) < 2:
            return [self.embed(model, group) for group in groups]
        self._sync()
        with ThreadPoolExecutor(max_workers=min(self.parallelism_for(model), len(groups))) as executor:
            return list(executor.map(lambda group: self.embed(model, group), groups))

    def chat_json(self, model: str, system: str, user: str, schema: dict, num_ctx: int = 8192) -> dict:
        self._sync()
        eligible = self._eligible(model)
        if not eligible:
            raise OllamaError(f"Le modèle {model} n'est installé sur aucun ordinateur d'analyse")
        # The computer with the fewest calls in flight; at equal load a helper (typically the Apple Silicon computer) before the server, which is the fallback.
        # With one call at a time this is the helper; with two at a time (see parallel.py) the second one goes to the server.
        with self._lock:
            client = self._pick(eligible)
            self._busy[client.base_url] = self._busy.get(client.base_url, 0) + 1
        try:
            return self._call_on(client, "chat_json", model, system, user, schema, num_ctx)
        finally:
            with self._lock:
                self._busy[client.base_url] -= 1


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)
