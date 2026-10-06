"""Asks the model, for each proposition of a reference, on which axes it takes sides, and keeps every answer (JSON lines) for tools/score_axes_reference.py --answers.
It does not touch the database (except to read the axes) and never writes a link: it is the way to try a version of the prompt.

    DATABASE_URL=… .venv/bin/python tools/ask_axes.py political/axes-reference-21.json --out political/axes-answers-NAME.jsonl [--prompt base|careful | --system-file prompt.txt] [--split dev|test]

`--system-file` replaces the instructions of the prompt (the axes are still described from the database); `--split` keeps the propositions whose id is even (dev: the ones
that a prompt can be tuned on) or odd (test: the ones that it is judged on). Answers that already are in the output file are not asked again.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dindon.analysis import axes as axes_module  # noqa: E402
from dindon.analysis.ollama import Ollama, OllamaError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt", choices=["base", "careful"], default="base", help="the instructions of the product: the base ones, or the cautious wording (analysis/axes.py)")
    parser.add_argument("--system-file", type=Path, help="other instructions, to try a wording (they replace --prompt)")
    parser.add_argument("--split", choices=["dev", "test"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--examples", type=int, default=0, help="show the model the K most similar propositions of the OTHER half of the reference, with their validated links "
                                                                "(what the product would do with what people validated); needs --split")
    parser.add_argument("--embed-model", default="bge-m3")
    parser.add_argument("--model", default="qwen3:14b")
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is needed (the axes are read from the database)")
    client = Ollama(args.ollama, timeout=600)
    reference = json.loads(args.reference.read_text(encoding="utf-8"))["propositions"]
    items = [(int(k), e["text"]) for k, e in sorted(reference.items(), key=lambda kv: int(kv[0])) if args.split is None or (int(k) % 2 == 0) == (args.split == "dev")]
    if args.limit:
        items = items[: args.limit]
    with psycopg.connect(url) as conn:
        axes, ids, anchors = axes_module.load_axes(conn)
    instructions = args.system_file.read_text(encoding="utf-8").strip() if args.system_file else {"base": axes_module.SYSTEM, "careful": axes_module.SYSTEM_CAREFUL}[args.prompt]
    system = instructions + "\n\nLes axes :\n" + axes_module.describe(axes, anchors)
    schema = axes_module._schema(list(ids), sorted({name for a in axes for name in (a[3], a[4])}))
    shown: dict[str, str] = {}
    if args.examples:
        if not args.split:
            sys.exit("--examples needs --split (the examples come from the other half)")
        pole = {a[0]: (a[3], a[4]) for a in axes}
        others = [(int(k), e) for k, e in reference.items() if (int(k) % 2 == 0) != (args.split == "dev")]
        vec = lambda texts: client.embed(args.embed_model, texts)  # noqa: E731
        other_vectors = [v for i in range(0, len(others), 16) for v in vec([e["text"] for _, e in others[i:i + 16]])]
        for i in range(0, len(items), 16):
            batch = items[i:i + 16]
            for (pid, text), v in zip(batch, vec([t for _, t in batch])):
                near = sorted(range(len(others)), key=lambda j: -sum(a * b for a, b in zip(v, other_vectors[j])))[: args.examples]
                lines = []
                for j in reversed(near):                                   # the closest last, next to the sentence
                    e = others[j][1]
                    links = " ; ".join(f"{c} : {pole[c][1] if loading > 0 else pole[c][0]} ({'forte' if abs(loading) >= 0.8 else 'moyenne'})" for c, loading in e["links"]) or "(aucun axe)"
                    lines.append(f"- « {e['text']} » → {links}")
                shown[text] = "Phrases proches déjà relues par une personne (leurs axes sont justes) :\n" + "\n".join(lines) + "\n\n"
    done = set()
    if args.out.exists():
        done = {json.loads(line)["sentence"] for line in args.out.read_text(encoding="utf-8").splitlines() if line.strip()}
    started = time.monotonic()
    with args.out.open("a", encoding="utf-8") as out:
        for n, (pid, text) in enumerate(items, 1):
            if text in done:
                continue
            try:
                answer = client.chat_json(args.model, system, shown.get(text, "") + f"Phrase : {text}", schema)
            except OllamaError as error:
                print(f"{n}: {error}")
                continue
            out.write(json.dumps({"sentence": text, "answer": answer}, ensure_ascii=False) + "\n")
            out.flush()
            if n % 25 == 0:
                print(f"{n}/{len(items)} ({time.monotonic() - started:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
