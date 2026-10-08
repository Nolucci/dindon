"""Measures the judgement of the reread (analysis/reread.py) on tools/reread_reference.json: positions that were read once, with the messages around their proof.

    python tools/measure_reread.py --model qwen3:8b        # the local model only: nothing leaves this machine

What matters: a right position must be left as it is (`wrongly changed`), a wrong one must be corrected (`corrected`), and what is not an opinion of the person must stop counting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dindon.analysis import reread
from dindon.analysis.ollama import Ollama, OllamaError

REFERENCE = Path(__file__).with_name("reread_reference.json")


def run(case: dict, client, model: str) -> tuple[reread.Decision, dict | None]:
    ids: dict[str, int] = {}
    lines = [reread.Line(n, ids.setdefault(who, len(ids) + 1), text, None, None, None, False, n - 1 in case["evidence"]) for n, (who, text) in enumerate(case["lines"], 1)]
    context, person = reread.render(lines, ids[case["person"]])
    item = reread.Item(1, ids[case["person"]], "opinion", case["current"], 7, case["proposition"], context, person, [], None)
    answer = reread.ask_model(client, model, item)
    return reread.decide(item, answer), answer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.environ.get("DINDON_NAMING_MODEL", "qwen3:8b"))
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    args = parser.parse_args()
    cases = json.loads(REFERENCE.read_text(encoding="utf-8"))["cases"]
    client = Ollama(args.ollama, timeout=300)
    rows = []
    for number, case in enumerate(cases, 1):
        try:
            decision, answer = run(case, client, args.model)
        except OllamaError as error:
            sys.exit(f"the model cannot answer ({error}): is Ollama running, and `ollama pull {args.model}` done?")
        exp = case["expected"]
        right_already = exp["own"] and exp["fits"] and exp["stance"] == case["current"]
        after_stance = decision.changes["stance"][1] if "stance" in decision.changes else case["current"]
        stopped = "kind" in decision.changes
        fixed = (not exp["own"] and stopped) or (exp["own"] and not stopped and (exp["stance"] is None or after_stance == exp["stance"]) and (exp["fits"] or decision.new_proposition is not None))
        rows.append({"id": case["id"], "category": case["category"], "right_already": right_already, "changed": decision.verdict == "corrected", "fixed": fixed, "verdict": decision.verdict, "changes": decision.changes})
        print(f"\r  {number}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    right = [r for r in rows if r["right_already"]]
    wrong = [r for r in rows if not r["right_already"]]
    wrongly_changed = [r for r in right if r["changed"]]
    corrected = [r for r in wrong if r["fixed"]]
    print(f"RELECTURE : {len(rows)} positions ({len(right)} justes, {len(wrong)} à corriger), modèle {args.model}")
    print(f"  justes laissées telles quelles : {len(right) - len(wrongly_changed)} sur {len(right)} ; changées à tort : {len(wrongly_changed)}")
    print(f"  fausses bien corrigées : {len(corrected)} sur {len(wrong)}")
    for r in wrongly_changed:
        print(f"    ! changée à tort {r['id']} [{r['category']}] {r['changes']}")
    for r in wrong:
        if not r["fixed"]:
            print(f"    non corrigée {r['id']} [{r['category']}] {r['verdict']} {r['changes']}")


if __name__ == "__main__":
    main()
