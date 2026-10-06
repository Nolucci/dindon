"""Does the second reading of the positions (analysis/stances.py) find the position that a person wrote? Measured on a gold set that a person (me, on 2026-10-05) labelled:
political/stance-gold.json, 169 items = a quote of a person + a proposition + the right relation (1 agreement, -1 disagreement, 0 nuance, null: not a position).
140 come from the claims of the invented political server (with what the first reading said), 29 were written by hand, 20 of them contradictions.

    OLLAMA_URL=… .venv/bin/python tools/check_stances.py [--gold political/stance-gold.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from dindon.analysis.ollama import Ollama  # noqa: E402
from dindon.analysis.stances import STANCE, judge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gold", type=Path, default=Path("political/stance-gold.json"))
    parser.add_argument("--model", default="qwen3:14b")
    args = parser.parse_args()
    client = Ollama(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"), timeout=300)
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    confusion: Counter = Counter()
    first_ok = first_n = 0
    for item in gold:
        relation = judge(client, args.model, item["quote"].split(" // "), item["proposition"])
        got = STANCE.get(relation) if relation else "?"
        confusion[(item["gold"], got)] += 1
        if item["origin"] == "base" and item["gold"] is not None:
            first_n += 1
            first_ok += item["extracted"] == item["gold"]
    n = len(gold)
    right = sum(v for (g, r), v in confusion.items() if g == r)
    decided = {k: v for k, v in confusion.items() if k[0] in (1, -1)}
    sign = sum(v for (g, r), v in decided.items() if g == r)
    print(f"second reading: {right}/{n} = {right / n:.0%} (all labels) ; for/against: {sign}/{sum(decided.values())} = {sign / sum(decided.values()):.0%}")
    print(f"first reading (the extraction), on the {first_n} real claims that are positions: {first_ok}/{first_n} = {first_ok / first_n:.0%}")
    print("(gold, answer):", dict(sorted(confusion.items(), key=lambda kv: str(kv[0]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
