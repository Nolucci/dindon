"""Models through Ollama's HTTP API, on this host or trusted computers in a private network.

Two calls are used: the vector of a text (`/api/embed`) and a short answer in a given JSON shape (`/api/chat` with `format`). What is
sent is the text of conversations, so helpers must be the administrator's own trusted computers, reachable only through a private network.
"""
import json
import math
import threading
import time
import urllib.error
import urllib.request
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable


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
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.load(error).get("error", "")
            except Exception:
                detail = ""
            raise OllamaError(f"Ollama a refusé ({error.code}) : {detail or path}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            raise OllamaError(f"Ollama ne répond pas à {self.base_url} ({type(error).__name__})") from None
        except json.JSONDecodeError:
            raise OllamaError("Ollama a répondu autre chose que du JSON") from None

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
        """An answer of the model in the shape of `schema`. Deterministic (temperature 0), without a chain of thought."""
        settings = self._settings()
        options = {"temperature": 0, "num_ctx": num_ctx}
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
        self._lock = threading.Lock()

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
                listed = client._call("/api/tags", timeout=timeout).get("models", [])
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
        return max(1, len(self._eligible(model)))

    def _call_on(self, client: Ollama, method: str, *args):
        try:
            return getattr(client, method)(*args)
        except OllamaError:
            with self._lock:
                self._failed.add(client.base_url)
            if client is self.local or self.local not in self._eligible(args[0]):
                raise
            return getattr(self.local, method)(*args)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        self._sync()
        eligible = self._eligible(model)
        if not eligible:
            raise OllamaError(f"Le modèle {model} n'est installé sur aucun ordinateur d'analyse")
        with self._lock:
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
        # Chats in these stages depend on earlier results. Prefer a helper (typically
        # the Apple Silicon computer), then the server as a fallback.
        client = next((candidate for candidate in eligible if candidate is not self.local), eligible[0])
        return self._call_on(client, "chat_json", model, system, user, schema, num_ctx)


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)
