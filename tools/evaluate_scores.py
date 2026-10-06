"""Do the scores of the people on the axes agree with what each simulated person was told to think? The end-to-end measure of the cascade
(positions -> propositions -> axes -> scores), on the invented political server (political/truth.json).

    DATABASE_URL=… .venv/bin/python tools/evaluate_scores.py [--truth political/truth.json] [--report out.md]

For every (person, topic) where the person was told an opinion (-2 .. +2, not 0), the scores of the person on the axes of the topic are turned toward
the proposition of the topic (a score on « economie » counts the other way round: agreeing with « l'État doit réguler » is toward the negative pole)
and combined, weighted by the evidence. Measured:
  - coverage    : the share of those pairs where the system says something (an axis of the topic has a score with enough evidence);
  - sign        : among them, the share where the sign is the one that the person was told (the worst error is the opposite sign);
  - correlation : between the combined score and the opinion told, over the pairs that are covered.
The « truth » is the instruction given to the simulated author, not a human reading: it is the best that we have, not a certainty.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

# topic -> the (axis, direction) where being FOR the proposition of the topic moves toward the pole `direction` (-1 negative pole, +1 positive pole)
AXES_OF = {
    "economie": [("economie", -1), ("controle", -1), ("redistribution", -1)],
    "europe": [("europe", 1)],
    "immigration": [("immigration", 1)],
    "ecologie": [("ecologie", 1), ("technologie", 1)],
    "laicite": [("religion", -1)],
    "securite": [("pouvoir", -1)],
    "institutions": [("representation", -1), ("participation", -1)],
    "defense": [("diplomatie", -1)],
    "societe": [("morale", -1), ("genre", -1)],
    "technologie": [("technologie", -1), ("controle", 1)],
}


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx, sy = math.sqrt(sum((x - mx) ** 2 for x in xs)), math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def evaluate(url: str, truth: dict, min_propositions: int | None = None, min_weight: float | None = None) -> dict:
    with psycopg.connect(url) as conn:
        settings = dict(conn.execute("SELECT key, value::float8 FROM scoring_settings").fetchall())
        need_n = settings["min_propositions"] if min_propositions is None else min_propositions
        need_w = settings["min_evidence_weight"] if min_weight is None else min_weight
        rows = conn.execute("""SELECT s.user_id::text, a.code, s.score::float8, s.uncertainty::float8, s.evidence_weight::float8, s.n_propositions
                               FROM person_axis_scores s JOIN axes a ON a.id = s.axis_id""").fetchall()
    scores: dict[tuple[str, str], tuple[float, float, int]] = {(u, c): (sc, w, n) for u, c, sc, _, w, n in rows}
    per_topic: dict[str, dict] = defaultdict(lambda: {"pairs": 0, "covered": 0, "right": 0, "xs": [], "ys": []})
    totals = {"pairs": 0, "covered": 0, "right": 0, "strong_covered": 0, "strong_right": 0}
    for person in truth["people"]:
        for topic, told in person["stance"].items():
            if not told:
                continue
            t = per_topic[topic]
            t["pairs"] += 1
            totals["pairs"] += 1
            oriented, weight = 0.0, 0.0
            for axis, direction in AXES_OF[topic]:
                found = scores.get((person["id"], axis))
                if found and found[2] >= need_n and found[1] >= need_w:
                    oriented += found[0] * direction * found[1]
                    weight += found[1]
            if not weight:
                continue
            value = oriented / weight
            t["covered"] += 1
            totals["covered"] += 1
            right = (value > 0) == (told > 0) and value != 0
            t["right"] += right
            totals["right"] += right
            if abs(told) == 2:
                totals["strong_covered"] += 1
                totals["strong_right"] += right
            t["xs"].append(value)
            t["ys"].append(told)
    allx = [x for t in per_topic.values() for x in t["xs"]]
    ally = [y for t in per_topic.values() for y in t["ys"]]
    return {"totals": totals, "per_topic": dict(per_topic), "r": pearson(allx, ally), "min_propositions": need_n}


def render(result: dict) -> str:
    t = result["totals"]
    pct = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "0/0"  # noqa: E731
    lines = ["# Les scores des personnes comparés à ce que chacune devait penser", "",
             f"Seuil de preuve : au moins {result['min_propositions']:g} proposition(s) sur un axe. Vérité : la consigne donnée à l'auteur simulé (invention, pas une relecture humaine).", "",
             "| | |", "| --- | --- |",
             f"| Cas (personne, sujet) avec un avis donné | {t['pairs']} |",
             f"| **Couverts** (le système dit quelque chose) | **{pct(t['covered'], t['pairs'])}** |",
             f"| **Bon sens** parmi les cas couverts | **{pct(t['right'], t['covered'])}** |",
             f"| Bon sens quand l'avis donné était fort (±2), parmi les cas couverts | {pct(t['strong_right'], t['strong_covered'])} |",
             f"| Corrélation entre le score et l'avis donné | {'' if result['r'] is None else f'{result['r']:.2f}'} |", "",
             "| Sujet | Cas | Couverts | Bon sens | Corrélation |", "| --- | --- | --- | --- | --- |"]
    for topic, v in sorted(result["per_topic"].items()):
        r = pearson(v["xs"], v["ys"])
        lines.append(f"| {topic} | {v['pairs']} | {v['covered']} | {pct(v['right'], v['covered'])} | {'' if r is None else f'{r:.2f}'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--truth", type=Path, default=Path("political/truth.json"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--min-propositions", type=int, help="the least number of propositions behind a score (default: the setting of the role check)")
    parser.add_argument("--min-weight", type=float, help="the least evidence weight behind a score (default: the setting of the role check)")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is needed")
    text = render(evaluate(url, json.loads(args.truth.read_text(encoding="utf-8")), args.min_propositions, args.min_weight))
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
