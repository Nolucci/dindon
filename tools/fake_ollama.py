"""A fake Ollama for the tests and for trying the analysis without any model: the same HTTP shape as the real one, for the three calls
that Dindon makes (`/api/tags`, `/api/embed`, `/api/chat`).

The "vector" of a text is a bag of its words hashed into 1024 numbers: two texts that share words point the same way, which is all
that the grouping of conversations needs. The "name" of a topic is made from the frequent words that the request lists.
It understands nothing, and says so in every name. Never use it for a real analysis.

    python tools/fake_ollama.py --port 11435        # then OLLAMA_URL=http://127.0.0.1:11435
"""
import argparse
import hashlib
import json
import math
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = re.compile(r"[a-zàâäçéèêëîïôöùûüÿœæ]{4,}")
DIMENSIONS = 1024


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in TOKEN.findall(text.lower()):
        vector[int.from_bytes(hashlib.md5(word.encode()).digest()[:4], "big") % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


class FakeOllama:
    def __init__(self, models=("bge-m3:latest", "qwen3:14b"), port: int = 0):
        self.models = list(models)
        self.digests = {name: hashlib.sha256(name.encode()).hexdigest() for name in self.models}
        self.requests: list[tuple[str, dict]] = []          # every call, for assertions: (path, body)
        self.fail_chat = 0                                    # the next chat calls answer an error
        self.garbage_chat = 0                                 # the next chat calls answer something that is not the asked JSON
        self.chat_handler = None                              # a function (body) -> dict that answers the chat calls (the tests write what the "model" says)
        self.chat_delay = 0.0                                 # seconds that each chat call takes (to have an analysis that is still running)
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status: int, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                with outer._lock:
                    outer.requests.append((self.path, {}))
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": m, "digest": outer.digests.get(m, "")} for m in outer.models]})
                if self.path == "/api/version":
                    return self._send(200, {"version": "fake"})
                self._send(404, {"error": "unknown"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                with outer._lock:
                    outer.requests.append((self.path, body))
                    model = body.get("model", "")
                    if model not in outer.models and f"{model}:latest" not in outer.models:
                        return self._send(404, {"error": f"model '{model}' not found"})
                    if self.path == "/api/embed":
                        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
                        return self._send(200, {"model": model, "embeddings": [embed_text(t) for t in texts]})
                    if self.path == "/api/chat":
                        if outer.chat_delay:
                            time.sleep(outer.chat_delay)
                        if outer.fail_chat:
                            outer.fail_chat -= 1
                            return self._send(500, {"error": "model runner has unexpectedly stopped"})
                        if outer.garbage_chat:
                            outer.garbage_chat -= 1
                            return self._send(200, {"message": {"role": "assistant", "content": "voici le nom : économie"}})
                        user = body["messages"][-1]["content"]
                        if outer.chat_handler is not None:
                            return self._send(200, {"message": {"role": "assistant", "content": json.dumps(outer.chat_handler(body))}})
                        words = re.search(r"Mots fréquents : (.*)", user)
                        listed = [w.strip() for w in (words.group(1) if words else "").split(",") if w.strip() and w.strip() != "(aucun)"]
                        label = "Sujet (faux modèle) : " + " ".join(listed[:2]) if listed else "Sujet (faux modèle)"
                        return self._send(200, {"message": {"role": "assistant", "content": json.dumps(
                            {"label": label, "description": "Nom fabriqué à partir des mots fréquents, sans rien comprendre."})}})
                self._send(404, {"error": "unknown"})

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "FakeOllama":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    server = FakeOllama(port=args.port).start()
    print(f"fake Ollama on {server.url}  (models: {', '.join(server.models)})")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
