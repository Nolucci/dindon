"""Compares language models on the one thing that the analysis asks of them so far: naming a topic from its keywords and a few of its
typical conversations. It reads the topics of the latest run of a database (run `dindon analyze` first), asks each model to name
them again, and prints what each said next to what the others said, with what can be checked by machine:

* the answer is the JSON that was asked (it is forced by Ollama, so this mostly checks the model's limits);
* the name is 2 to 6 words, does not contain a mention, does not name a person of the server, is not a generic word;
* the time of each call, and the median.

What cannot be checked by machine is whether the name is *right*: read the table. On invented conversations (make demo) a name is easy;
the real question is how a model does on the conversations of the real server, with the same command (that data stays on this machine).

    .venv/bin/python tools/bench_models.py --database-url postgresql://… qwen3:14b gemma4:12b
"""
import argparse
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import psycopg  # noqa: E402

from dindon.analysis.embeddings import conversation_texts  # noqa: E402
from dindon.analysis.ollama import Ollama, OllamaError  # noqa: E402
from dindon.analysis.themes import NAMING_SCHEMA, NAMING_SYSTEM  # noqa: E402
from dindon.config import load_settings  # noqa: E402

GENERIC = re.compile(r"^(discussions?|sujets?( divers| variés)?|débats?|échanges?|divers|général|conversations?)$", re.I)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="+")
    parser.add_argument("--database-url")
    parser.add_argument("--ollama-url")
    parser.add_argument("--topics", type=int, default=10, help="how many topics (the biggest first)")
    args = parser.parse_args()
    settings = load_settings()
    url = args.database_url or settings.database_url
    client = Ollama(args.ollama_url or ("http://127.0.0.1:11434" if "host.docker" in settings.ollama_url else settings.ollama_url))

    with psycopg.connect(url, autocommit=True) as conn:
        run = conn.execute("SELECT max(id) FROM topic_runs").fetchone()[0]
        if run is None:
            sys.exit("No topics yet: run the analysis first.")
        topics = conn.execute(
            """SELECT t.id, t.keywords, count(*) AS n FROM topics t JOIN topic_assignments a ON a.topic_id = t.id
               WHERE t.run_id = %s GROUP BY t.id ORDER BY n DESC LIMIT %s""", (run, args.topics)).fetchall()
        names = {n.casefold() for (n,) in conn.execute(
            "SELECT unnest(ARRAY[u.name, u.global_name, m.nickname]) FROM users u LEFT JOIN members m ON m.user_id = u.id") if n and len(n) > 3}
        cases = []
        for topic_id, words, size in topics:
            picked = [r[0] for r in conn.execute(
                "SELECT conversation_id FROM topic_assignments WHERE topic_id = %s ORDER BY similarity DESC LIMIT 6", (topic_id,))]
            texts = conversation_texts(conn, picked)
            cases.append((topic_id, size, words, [texts.get(i, "").replace("\n", " / ")[:400] for i in picked]))

    results: dict[str, list[dict]] = {}
    for model in args.models:
        print(f"\n== {model}", flush=True)
        client.chat_json(model, "Réponds en JSON.", "Dis bonjour.", {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]})  # loads it
        rows = []
        for topic_id, size, words, excerpts in cases:
            listing = "\n".join(f"{i}. {e}" for i, e in enumerate(excerpts, 1))
            user = f"Mots fréquents : {', '.join(words)}\n\nExtraits de conversations sur ce sujet :\n{listing}\n\nDonne le nom du sujet et une description."
            started = time.monotonic()
            try:
                answer = client.chat_json(model, NAMING_SYSTEM, user, NAMING_SCHEMA)
                label, description = str(answer.get("label", "")).strip(), str(answer.get("description", "")).strip()
                error = None
            except OllamaError as problem:
                label, description, error = "", "", str(problem)
            seconds = time.monotonic() - started
            count = len(label.split())
            checks = {"words 2-6": 2 <= count <= 6, "no mention": "@" not in label, "no generic word": not GENERIC.match(label),
                      "no person's name": not any(n in label.casefold() for n in names), "has description": 10 <= len(description) <= 400}
            rows.append({"id": topic_id, "label": label, "description": description, "seconds": seconds, "error": error, "checks": checks})
            flags = "".join("." if ok else "!" for ok in checks.values())
            print(f"  {seconds:5.1f}s [{flags}] {label or error}", flush=True)
        results[model] = rows

    print("\n== Summary")
    print(f"{'model':<16} {'median':>7} {'valid':>6} " + " ".join(f"{k:>16}" for k in next(iter(results.values()))[0]["checks"]))
    for model, rows in results.items():
        valid = sum(r["error"] is None for r in rows)
        cells = " ".join(f"{sum(r['checks'][k] for r in rows):>13}/{len(rows)}" for k in rows[0]["checks"])
        print(f"{model:<16} {statistics.median(r['seconds'] for r in rows):>6.1f}s {valid:>3}/{len(rows)} {cells}")
    print("\n== Side by side (the size of the topic, then each model's name)")
    for i, (topic_id, size, words, _) in enumerate(cases):
        print(f"\n[{size} conversations] mots : {', '.join(words[:6])}")
        for model, rows in results.items():
            print(f"   {model:<14} {rows[i]['label']}")


if __name__ == "__main__":
    main()
