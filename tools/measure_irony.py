"""Measures the telling of irony from sincerity (analysis/irony.py) on tools/irony_reference.json.

    python tools/measure_irony.py --model qwen3:14b        # the local model only: nothing leaves this machine

What matters: a sincere message must not be taken for irony (it would stop counting as a position), and irony must be found.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dindon.analysis import irony
from dindon.analysis.ollama import Ollama, OllamaError

REFERENCE = Path(__file__).with_name("irony_reference.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.environ.get("DINDON_NAMING_MODEL", "qwen3:8b"))
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    args = parser.parse_args()
    cases = json.loads(REFERENCE.read_text(encoding="utf-8"))["cases"]
    client = Ollama(args.ollama, timeout=300)
    results = []
    for number, case in enumerate(cases, 1):
        try:
            verdict = irony.judge(client, args.model, case["text"], case["context"][-1][1] if case["context"] else "")
        except OllamaError as error:
            sys.exit(f"the model cannot answer ({error}): is Ollama running, and `ollama pull {args.model}` done?")
        results.append((case, verdict))
        print(f"\r  {number}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    ironic = [(c, v) for c, v in results if c["label"] == "ironique"]
    sincere = [(c, v) for c, v in results if c["label"] == "sincère"]
    found = [x for x in ironic if x[1].not_sincere]
    wrong = [x for x in sincere if x[1].not_sincere]
    print(f"IRONIE : {len(results)} messages ({len(ironic)} ironiques, {len(sincere)} sincères), modèle {args.model}")
    print(f"  ironie repérée : {len(found)} sur {len(ironic)} ; sincères pris pour de l'ironie à tort : {len(wrong)} sur {len(sincere)}")
    for c, v in wrong:
        print(f"    ! à tort {c['id']} ({v.tone} {v.certainty}) {c['text'][:90]}")
    for c, v in ironic:
        if not v.not_sincere:
            print(f"    manquée {c['id']} ({v.tone} {v.certainty}) {c['text'][:90]}")


if __name__ == "__main__":
    main()
