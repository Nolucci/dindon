"""Reading the weights that the AI proposed between propositions and axes, and recording the decisions of the person who reads them.

    DATABASE_URL=… .venv/bin/python tools/review_axes.py dump [--from ID] [--limit N]      # one line per proposition: what the AI proposed, in words
    DATABASE_URL=… .venv/bin/python tools/review_axes.py apply decisions.json               # records what the reader decided

`decisions.json`: {"fix": {"<proposition id>": [["economie", -1.0], ["controle", -0.6]]}, "skip": [ids that are unclear: left proposed], "reviewer": "name"}.
Every proposition that is in neither list is **validated as the AI proposed it**; `fix` replaces its links (an empty list: it weighs on no axis) and validates them;
`skip` leaves them proposed (not validated). Nothing is recorded for a proposition that has no link and is not in `fix`. The decisions file is kept next to the data
(it is the trace of who decided what).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def dump(conn, start: int, limit: int) -> None:
    rows = conn.execute(
        """SELECT p.id, p.text, (SELECT count(*) FROM claims c WHERE c.proposition_id = p.id) FROM propositions p
           WHERE p.status NOT IN ('rejected', 'merged') AND p.id >= %s AND EXISTS (SELECT 1 FROM claims c WHERE c.proposition_id = p.id) ORDER BY p.id LIMIT %s""", (start, limit)).fetchall()
    for pid, text, people in rows:
        links = conn.execute(
            """SELECT a.code, a.negative_pole, a.positive_pole, pa.loading::float8, pa.is_validated FROM proposition_axis pa JOIN axes a ON a.id = pa.axis_id
               WHERE pa.proposition_id = %s ORDER BY abs(pa.loading) DESC""", (pid,)).fetchall()
        words = " ; ".join(f"{code}→{pos if loading > 0 else neg}{'' if abs(loading) >= 0.8 else '(m)'}{'✓' if validated else ''}" for code, neg, pos, loading, validated in links) or "(aucun)"
        print(f"{pid}|{text[:150]}|{words}")


def apply(conn, path: Path) -> None:
    decisions = json.loads(path.read_text(encoding="utf-8"))
    fix = {int(k): v for k, v in decisions.get("fix", {}).items()}
    skip = {int(i) for i in decisions.get("skip", [])}
    ids = {code: aid for code, aid in conn.execute("SELECT code, id FROM axes WHERE is_active").fetchall()}
    done = {"validated as proposed": 0, "corrected": 0, "left proposed": 0}
    with conn.transaction():
        for pid, links in fix.items():
            conn.execute("DELETE FROM proposition_axis WHERE proposition_id = %s", (pid,))
            for code, loading in links:
                conn.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence, is_validated) VALUES (%s, %s, %s, 1, true)", (pid, ids[code], loading))
            conn.execute("UPDATE propositions SET axes_read_at = COALESCE(axes_read_at, now()), axes_validated_at = now() WHERE id = %s", (pid,))
            done["corrected"] += 1
        for (pid,) in conn.execute("SELECT DISTINCT proposition_id FROM proposition_axis WHERE NOT is_validated").fetchall():
            if pid in skip:
                done["left proposed"] += 1
            elif pid not in fix:
                conn.execute("UPDATE proposition_axis SET is_validated = true WHERE proposition_id = %s", (pid,))
                conn.execute("UPDATE propositions SET axes_validated_at = now() WHERE id = %s", (pid,))
                done["validated as proposed"] += 1
        conn.execute("SELECT refresh_person_axis_scores(%s)", (conn.execute("SELECT id FROM guilds LIMIT 1").fetchone()[0],))
    print(json.dumps(done))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--from", dest="start", type=int, default=0)
    d.add_argument("--limit", type=int, default=100)
    a = sub.add_parser("apply")
    a.add_argument("decisions", type=Path)
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is needed")
    with psycopg.connect(url, autocommit=True) as conn:
        dump(conn, args.start, args.limit) if args.command == "dump" else apply(conn, args.decisions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
