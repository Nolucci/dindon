"""The local models, through Ollama's HTTP API. Nothing else: no library, and no address but the one of OLLAMA_URL.

Two calls are used: the vector of a text (`/api/embed`) and a short answer in a given JSON shape (`/api/chat` with `format`). What is
sent is the text of conversations, so the address must be this machine's (the Docker host, or a container of the same Compose project).
"""
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable


class OllamaError(Exception):
    """Ollama cannot answer now (not running, model missing, timeout) or answered something unusable."""


class Ollama:
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


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)
