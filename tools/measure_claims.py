"""Measures the checking of claims against tools/claims_reference.json (docs/regles-du-bot.md « Mesure »). Prints the figures and writes what was predicted, so that it can be scored again.

    python tools/measure_claims.py reading                     # the local model only: nothing leaves this machine
    python tools/measure_claims.py local                       # what Dindon answers WITHOUT the Internet (the local model only: nothing leaves this machine)
    python tools/measure_claims.py verify --searxng http://127.0.0.1:8088   # the search service, the pages and the model: THIS SENDS SEARCHES (see the notice of docs/regles-du-bot.md)
    python tools/measure_claims.py score reading|local|verify FILE   # the figures again, from a file that was written before

`verify` sends, for each claim of the reference set, one or two neutral searches and reads at most three trusted pages (the same limits as in a debate). The claims of the reference set are public
facts about France and Europe, with no person in them. It waits between claims, to be polite to the services. The labels of the reference set are to be verified by a human: see the file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dindon.analysis.ollama import Ollama, OllamaError
from dindon.debate import local, measure, reading, verify
from dindon.debate.reading import Reading, read_message
from dindon.debate.scope import Lookup
from dindon.debate.search import FactCheckSearch, SearxSearch
from dindon.debate.trust import Trust
from dindon.debate.verify import verify_claim
from dindon.debate.web import Fetcher

REFERENCE = Path(__file__).with_name("claims_reference.json")


def split_of(items: list[dict], which: str) -> list[dict]:
    """`dev` is for tuning the instructions; `test` is for the figures that are reported, and is not looked at while tuning. `all` is the whole set. Groups alternate between the two: a
    mirrored pair stays whole on one side (its two claims are compared with each other), anything else is a group of one."""
    if which == "all":
        return items
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item.get("pair") or item["id"], []).append(item)
    return [x for i, group in enumerate(groups.values()) if (i % 2 == 0) == (which == "dev") for x in group]


def run_reading(args, reference) -> dict:
    llm, found, started = Ollama(args.ollama, timeout=300), {}, time.monotonic()
    for index, message in enumerate(split_of(reference["messages"], args.split)[: args.limit or None], 1):
        try:
            found[message["id"]] = [r.claim for r in read_message(llm, args.model, message["text"])]
        except OllamaError as error:
            sys.exit(f"the model cannot answer ({error}): is Ollama running, and `ollama pull {args.model}` done?")
        print(f"\r  {index}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return {"kind": "reading", "split": args.split, "prompt": reading.PROMPT_VERSION, "model": args.model, "seconds": round(time.monotonic() - started), "predictions": found}


def run_local(args, reference) -> dict:
    llm, said, started = Ollama(args.ollama, timeout=300), {}, time.monotonic()
    for index, claim in enumerate(split_of(reference["claims"], args.split)[: args.limit or None], 1):
        try:
            answered = local.answer_claim(llm, args.model, Reading(claim["claim"], claim["claim"], claim["query"]))
        except OllamaError as error:
            sys.exit(f"the model cannot answer ({error}): is Ollama running, and `ollama pull {args.model}` done?")
        said[claim["id"]] = {"verdict": answered.verdict, "answer": answered.answer}
        print(f"\r  {index} {answered.verdict:<6}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return {"kind": "local", "split": args.split, "prompt": local.PROMPT_VERSION, "model": args.model, "seconds": round(time.monotonic() - started), "predictions": said}


def run_verify(args, reference) -> dict:
    searchers = []
    if os.environ.get("DINDON_FACTCHECK_API_KEY"):
        searchers.append(FactCheckSearch(os.environ["DINDON_FACTCHECK_API_KEY"]))
    if args.searxng:
        searchers.append(SearxSearch(args.searxng))
    if not searchers:
        sys.exit("no search service: give --searxng ADDRESS and/or set DINDON_FACTCHECK_API_KEY")
    llm, fetcher, trust, predicted, started = Ollama(args.ollama, timeout=300), Fetcher(), Trust(), {}, time.monotonic()
    for index, claim in enumerate(split_of(reference["claims"], args.split)[: args.limit or None], 1):
        result = verify_claim(Lookup(searchers, fetcher), llm, args.model, trust, Reading(claim["claim"], claim["claim"], claim["query"]))
        predicted[claim["id"]] = {"verdict": result.verdict, "reason": result.reason, "period": result.period, "queries": result.queries, "pages": result.pages,
                                  "evidence": [{"url": e.url, "tier": e.tier, "stance": e.stance, "quote": e.quote} for e in result.evidence]}
        print(f"\r  {index} {result.verdict:<13}", end="", file=sys.stderr, flush=True)
        time.sleep(args.pause)
    print(file=sys.stderr)
    return {"kind": "verify", "split": args.split, "prompt": verify.PROMPT_VERSION, "model": args.model, "searxng": bool(args.searxng), "seconds": round(time.monotonic() - started), "predictions": predicted}


def score(kind: str, saved: dict, reference: dict) -> dict:
    if kind == "reading":
        return measure.score_reading([m for m in reference["messages"] if m["id"] in saved["predictions"]], saved["predictions"])
    wanted = [c for c in reference["claims"] if c["id"] in saved["predictions"]]
    return (measure.score_local if kind == "local" else measure.score_verification)(wanted, saved["predictions"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("reading", "local", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--model", default=os.environ.get("DINDON_DEBATE_MODEL", "qwen3:14b"))
        p.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
        p.add_argument("--reference", default=str(REFERENCE), help="the reference set (default: tools/claims_reference.json; tools/claims_everyday.json: everyday claims)")
        p.add_argument("--limit", type=int, default=0, help="only the first N (to try it)")
        p.add_argument("--split", choices=("dev", "test", "all"), default="all", help="dev: to tune the instructions; test: the figures to report (do not tune on it)")
        p.add_argument("--out", help="where to write what was predicted (default: political/measure-<kind>.json)")
        if name == "verify":
            p.add_argument("--searxng", help="address of your SearXNG")
            p.add_argument("--pause", type=float, default=4.0, help="seconds to wait between two claims")
    scoring = sub.add_parser("score")
    scoring.add_argument("kind", choices=("reading", "local", "verify"))
    scoring.add_argument("file")
    args = parser.parse_args()
    reference = json.loads(Path(getattr(args, "reference", REFERENCE)).read_text(encoding="utf-8"))
    if args.mode == "score":
        saved = json.loads(Path(args.file).read_text(encoding="utf-8"))
        kind = args.kind
    else:
        saved = {"reading": run_reading, "local": run_local, "verify": run_verify}[args.mode](args, reference)
        kind = args.mode
        out = Path(args.out or Path(__file__).resolve().parents[1] / "political" / f"measure-{kind}-{args.split}.json")
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"written: {out}")
    scores = score(kind, saved, reference)
    print(measure.report(kind, scores))
    if kind == "verify":
        print(json.dumps(scores["ready_for_live"], ensure_ascii=False))


if __name__ == "__main__":
    main()
