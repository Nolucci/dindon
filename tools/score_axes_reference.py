"""How close are the links that the AI proposed to the links that a person judged right? On the propositions that a person reviewed.

    DATABASE_URL=… .venv/bin/python tools/score_axes_reference.py political/axes-reference.json [--report political/RAPPORT-AXES-PROPOSITIONS.md]
    DATABASE_URL=… .venv/bin/python tools/score_axes_reference.py reference.json --answers answers.jsonl      # the answers of the model that a run kept, not the database

With `--answers`, what the model said is read from a file (one JSON per line: {"sentence": …, "answer": …}) instead of the links of the database: a link that coincides
with a validated one is not kept by the database, so after a validation only the file tells what the model proposed.

The reference (a JSON file: {"propositions": {"<id>": {"text": …, "links": [["economie", -1.0], …]}}}) is what the reviewer decided for each proposition, an empty list
meaning « it takes no side on any axis ». The links in the database (proposed, not validated) are compared to it; a link counts as:
  - correct          : an axis and a direction that the reviewer kept;
  - wrong direction  : an axis that the reviewer kept, toward the other pole (the worst: it moves a person the wrong way);
  - wrong axis       : an axis that the reviewer did not keep (or a statement that takes no side).
And per proposition: the reviewer's links that the AI did not propose are missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--split", choices=["dev", "test"], help="only the propositions whose id is even (dev) or odd (test), as tools/ask_axes.py does")
    parser.add_argument("--answers", type=Path, help="the answers of the model that a run kept (JSON lines), instead of the proposed links of the database")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is needed")
    reference = json.loads(args.reference.read_text(encoding="utf-8"))["propositions"]
    if args.split:
        reference = {k: e for k, e in reference.items() if (int(k) % 2 == 0) == (args.split == "dev")}
    proposed: dict[int, dict[str, float]] = {}
    with psycopg.connect(url) as conn:
        if args.answers:
            from dindon.analysis import axes as axes_module

            axes, ids, _ = axes_module.load_axes(conn)
            inverse, poles = {v: k for k, v in ids.items()}, axes_module.poles_of(axes)
            by_text = {entry["text"]: int(key) for key, entry in reference.items()}
            for line in args.answers.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                pid = by_text.get(item["sentence"])
                if pid is not None:
                    proposed[pid] = {inverse[axis]: loading for axis, loading, _ in axes_module.validate(item["answer"], ids, poles)}
            unread = len(reference) - len({pid for pid in proposed if str(pid) in reference})
        else:
            rows = conn.execute("""SELECT pa.proposition_id, a.code, pa.loading::float8 FROM proposition_axis pa JOIN axes a ON a.id = pa.axis_id
                                   WHERE NOT pa.is_validated""").fetchall()
            unread = conn.execute("SELECT count(*) FROM propositions WHERE axes_read_at IS NULL AND id = ANY(%s)", ([int(i) for i in reference],)).fetchone()[0]
            for pid, code, loading in rows:
                proposed.setdefault(pid, {})[code] = loading

    count, wrong_examples, wrong_axis_axes, strength = Counter(), [], Counter(), Counter()
    sides_taken = sides_found = silent_ok = silent_wrong = 0
    for key, entry in reference.items():
        pid, truth = int(key), {code: loading for code, loading in entry["links"]}
        found = proposed.get(pid, {})
        if not truth:
            if found:
                silent_wrong += 1
            else:
                silent_ok += 1
        else:
            sides_taken += 1
            sides_found += any(c in truth and (loading > 0) == (truth[c] > 0) for c, loading in found.items())
        for code, loading in found.items():
            if code in truth and (loading > 0) == (truth[code] > 0):
                count["correct"] += 1
            elif code in truth:
                count["wrong direction"] += 1
                strength["strong" if abs(loading) >= 0.8 else "medium"] += 1
                wrong_examples.append((entry["text"], code, loading))
            else:
                count["wrong axis"] += 1
                wrong_axis_axes[code] += 1
        count["missing"] += sum(1 for c, loading in truth.items() if not (c in found and (found[c] > 0) == (loading > 0)))
    total = count["correct"] + count["wrong direction"] + count["wrong axis"]
    wrong_direction = count["wrong direction"]
    lines = ["# Les liens proposés par l'IA, comparés à la relecture d'une personne", "",
             f"{len(reference)} propositions relues ({sides_taken} prennent parti sur au moins un axe, {len(reference) - sides_taken} n'en prennent aucun) ; "
             f"{total} liens proposés par l'IA (aucun n'est validé). Référence : le jugement d'une seule personne (moi), à discuter.", "",
             "| | |", "| --- | --- |",
             f"| Liens corrects (bon axe, bon sens) | **{count['correct']}/{total} ({count['correct'] / total:.0%})** |",
             f"| Liens **dans le mauvais sens** sur un bon axe (le pire) | **{wrong_direction}/{total} ({wrong_direction / total:.0%})** |",
             f"| Liens sur un axe que la relecture n'a pas retenu | {count['wrong axis']}/{total} ({count['wrong axis'] / total:.0%}) |",
             f"| Propositions qui prennent parti, avec au moins un lien correct | {sides_found}/{sides_taken} ({sides_found / max(sides_taken, 1):.0%}) |",
             f"| Propositions sans parti pris, laissées sans lien (à raison) | {silent_ok}/{silent_ok + silent_wrong} |",
             f"| Liens que la relecture a ajoutés (l'IA ne les avait pas proposés) | {count['missing']} |",
             f"| **Précision** (liens corrects / liens proposés) · **rappel** (liens corrects / liens de la référence) | **{count['correct'] / max(total, 1):.0%}** · **{count['correct'] / max(count['correct'] + count['missing'], 1):.0%}** |", ""]
    if unread:
        lines += [f"**Attention : {unread} propositions n'étaient pas encore lues par l'IA au moment de la mesure.**", ""]
    if strength:
        lines += [f"Parmi les liens dans le mauvais sens : {strength['strong']} « forts » et {strength['medium']} « moyens ».", ""]
    if wrong_axis_axes:
        lines += ["Axes les plus souvent proposés à tort : " + ", ".join(f"{a} ({n})" for a, n in wrong_axis_axes.most_common(6)) + ".", ""]
    if wrong_examples:
        lines += ["**Liens dans le mauvais sens (extraits)** :", ""] + [f"- « {t[:110]} » → {code} {'+' if loading > 0 else '−'}" for t, code, loading in wrong_examples[:15]]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
