"""What the AI made of the invented political server, against its ground truth (political/truth.json).

    DATABASE_URL=…/dindon_politique .venv/bin/python tools/evaluate_political.py [--report political/RAPPORT.txt]

Today the AI stages that exist are the conversations, their vectors and the topics (docs/fonctionnement.txt). This measures THAT: do the
conversations that talk about the same subject end up in the same topic, and what did the model call each topic? The extraction of what
each person claims does not exist yet: when it does, its output is to be compared with `stance_told` of truth.json the same way.

Honest reading: the "true" topic of a conversation is the subject that the simulated debaters were given (the majority of its messages);
conversations without any debate message (small talk, bot reminders) count as "hors-sujet".
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row


def nmi(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    a, b, ab = Counter(p[0] for p in pairs), Counter(p[1] for p in pairs), Counter(pairs)
    mi = sum(c / n * math.log((c / n) / ((a[x] / n) * (b[y] / n))) for (x, y), c in ab.items())
    ha = -sum(c / n * math.log(c / n) for c in a.values())
    hb = -sum(c / n * math.log(c / n) for c in b.values())
    return mi / math.sqrt(ha * hb) if ha and hb else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--truth", type=Path, default=Path("political/truth.json"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--coherence-report", type=Path, help="also check the roles against what people say, into this file")
    parser.add_argument("--judge", action="store_true", help="for the positions: a model decides which way each proposition of the AI points (needs Ollama)")
    parser.add_argument("--positions-report", type=Path, help="also compare the positions read by the AI (stage claims) with the truth, into this file")
    args = parser.parse_args()
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is needed (the database of the political server)")
    with psycopg.connect(url, row_factory=tuple_row) as conn:
        run = conn.execute("SELECT max(id) FROM topic_runs").fetchone()[0]
        if run is None:
            sys.exit("no topic search yet: run `dindon analyze` first")
        rows = conn.execute(
            """SELECT c.id, c.kept, t.id, coalesce(t.label, '(sans thème)'), t.status, array_agg(cm.message_id::text ORDER BY cm.message_id)
               FROM conversations c JOIN conversation_messages cm ON cm.conversation_id = c.id
               LEFT JOIN topic_assignments ta ON ta.conversation_id = c.id AND ta.run_id = %s LEFT JOIN topics t ON t.id = ta.topic_id
               GROUP BY c.id, c.kept, t.id, t.label, t.status""", (run,)).fetchall()
        n_messages = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        n_conv = conn.execute("SELECT count(*), count(*) FILTER (WHERE kept) FROM conversations").fetchone()
    messages = truth["messages"]
    per_topic: dict[str, Counter] = defaultdict(Counter)
    pairs = []
    by_source: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for cid, kept, tid, label, status, ids in rows:
        if not kept or tid is None:
            continue
        votes = Counter(messages[i]["topic"] or "hors-sujet" for i in ids if i in messages)
        if not votes:
            continue
        true_topic = votes.most_common(1)[0][0]
        per_topic[f"{tid}|{label}"][true_topic] += 1
        pairs.append((f"{tid}", true_topic))
        sources = Counter(messages[i].get("source", "llm") for i in ids if i in messages and messages[i]["debate"] is not None)
        by_source[sources.most_common(1)[0][0] if sources else "hors-sujet"].append((str(tid), true_topic, label))
    classified = sum(sum(c.values()) for c in per_topic.values())
    purity = sum(c.most_common(1)[0][1] for c in per_topic.values()) / classified if classified else 0
    lines = ["# Ce que l'IA a fait du serveur politique inventé",
             "", f"{n_messages} messages, {n_conv[0]} conversations dont {n_conv[1]} retenues, {classified} classées dans {len(per_topic)} thèmes (recherche n° {run}).",
             "", f"**Pureté** (part des conversations dont le thème correspond au sujet réellement débattu) : **{purity:.0%}** ; **information mutuelle normalisée** : **{nmi(pairs):.2f}** "
             "(1 = les thèmes retrouvent exactement les sujets, 0 = aucun lien).", ""]
    lines += ["**Selon l'origine des débats** (les débats écrits par le modèle ont un langage varié, les débats de gabarit un langage pauvre et répétitif : le premier chiffre est le plus honnête) :", "",
              "| Origine | Conversations | Pureté |", "| --- | --- | --- |"]
    for source, items in sorted(by_source.items()):
        groups: dict[str, Counter] = defaultdict(Counter)
        for tid, true_topic, _ in items:
            groups[tid][true_topic] += 1
        lines.append(f"| {source} | {len(items)} | {sum(c.most_common(1)[0][1] for c in groups.values()) / len(items):.0%} |")
    lines += [""]
    lines += [
             "| Thème proposé par l'IA | Conversations | Sujets réellement débattus dedans |", "| --- | --- | --- |"]
    for key, counter in sorted(per_topic.items(), key=lambda kv: -sum(kv[1].values())):
        tid, label = key.split("|", 1)
        total = sum(counter.values())
        mix = ", ".join(f"{t} {c}" for t, c in counter.most_common(4))
        lines.append(f"| {label} | {total} | {mix} |")
    text = "\n".join(lines)
    print(text)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    if args.coherence_report:
        text2 = coherence_report(url, truth)
        print("\n" + text2)
        args.coherence_report.write_text(text2 + "\n", encoding="utf-8")
    if args.positions_report:
        client = None
        if args.judge:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
            from dindon.analysis.ollama import Ollama
            client = Ollama(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
        positions = positions_report(url, truth, client)
        print("\n" + positions)
        args.positions_report.write_text(positions + "\n", encoding="utf-8")
    return 0



# --- the positions read by the AI, against the instruction given to each simulated author --------------------------------------------


JUDGE_SYSTEM = ("Tu compares deux propositions politiques. Réponds `meme_sens` si être d'accord avec B revient à être d'accord avec A (même idée, même direction), "
                "`sens_oppose` si être d'accord avec B revient à être contre A, `sans_rapport` si B ne parle pas de la même question que A ou n'est pas comparable.")
JUDGE_SCHEMA = {"type": "object", "properties": {"relation": {"type": "string", "enum": ["meme_sens", "sens_oppose", "sans_rapport"]}}, "required": ["relation"]}


def orientation(client, model: str, reference: str, text: str) -> int:
    """+1: the model's proposition goes the same way as the truth's proposition, -1: the opposite way, 0: not about it. (A model judges a model: read some.)"""
    answer = client.chat_json(model, JUDGE_SYSTEM, f"A : {reference}\nB : {text}", JUDGE_SCHEMA)
    return {"meme_sens": 1, "sens_oppose": -1}.get(answer.get("relation"), 0)


def positions_report(url: str, truth: dict, client=None, model: str = "qwen3:14b") -> str:
    messages = truth["messages"]
    with psycopg.connect(url, row_factory=tuple_row) as conn:
        claims = conn.execute(
            """SELECT cl.id, cl.user_id, cl.stance, cl.kind, cl.proposition_id, cl.conversation_id, p.text,
                      (SELECT array_agg(cm.message_id::text) FROM conversation_messages cm JOIN messages m ON m.id = cm.message_id
                        WHERE cm.conversation_id = cl.conversation_id AND m.author_id = cl.user_id)
               FROM claims cl LEFT JOIN propositions p ON p.id = cl.proposition_id WHERE cl.conversation_id IS NOT NULL""").fetchall()
        read = conn.execute("SELECT count(*) FROM conversation_extractions").fetchone()[0]
        refused = conn.execute("SELECT coalesce(sum(refused), 0) FROM conversation_extractions").fetchone()[0]
        n_props = conn.execute("SELECT count(DISTINCT proposition_id) FROM claims WHERE stance IS NOT NULL").fetchone()[0]
    rows, by_prop = [], defaultdict(Counter)
    for cid, uid, stance, kind, pid, conv, ptext, mine in claims:
        told_list = [messages[i] for i in (mine or []) if i in messages and messages[i]["stance_told"] is not None]
        if not told_list or kind != "opinion" or stance is None:
            continue
        told = Counter(t["stance_told"] for t in told_list).most_common(1)[0][0]
        topic = Counter(t["topic"] for t in told_list).most_common(1)[0][0]
        source = Counter(t.get("source", "llm") for t in told_list).most_common(1)[0][0]
        sign = (told > 0) - (told < 0)
        rows.append({"told": told, "sign": sign, "said": stance, "topic": topic, "source": source, "pid": pid, "ptext": ptext})
        by_prop[(pid, ptext)][topic] += 1
    judged: dict[int, int] = {}
    if client is not None:                                         # which way each proposition of the model points, against the truth's proposition of its subject
        for (pid, ptext), counter in by_prop.items():
            judged[pid] = orientation(client, model, truth["propositions"][counter.most_common(1)[0][0]], ptext)
        for r in rows:
            r["said_raw"] = r["said"]
            r["said"] = r["said"] * judged[r["pid"]]
        rows = [r for r in rows if judged[r["pid"]] != 0 or r["said_raw"] == 0]

    def rate(sub, ok):
        return f"{sum(1 for r in sub if ok(r))}/{len(sub)} ({sum(1 for r in sub if ok(r)) / len(sub):.0%})" if sub else "—"

    firm = [r for r in rows if r["sign"] != 0]
    neutral = [r for r in rows if r["sign"] == 0]
    note = ("La **direction de chaque proposition de l'IA** (même sens que la proposition de départ du sujet, sens opposé, sans rapport) a été jugée par un modèle : "
            f"{sum(1 for v in judged.values() if v == 1)} propositions dans le même sens, {sum(1 for v in judged.values() if v == -1)} dans le sens opposé, "
            f"{sum(1 for v in judged.values() if v == 0)} sans rapport (écartées). Un modèle qui en juge un autre : lisez-en quelques-unes." if client is not None else
            "Sans jugement de direction (`--judge`) : une proposition de l'IA formulée dans le sens opposé à celle de départ fausserait ces chiffres.")
    lines = ["# Les positions lues par l'IA, comparées à la consigne donnée à chaque auteur simulé", "",
             f"{read} conversations lues, {len(rows)} positions évaluées (opinions avec une consigne connue), {refused} propositions du modèle refusées faute de preuve exacte, "
             f"{n_props} propositions créées.", "", note, "",
             "| Mesure | Résultat |", "| --- | --- |",
             f"| Bon sens (pour/contre) quand la consigne était tranchée et l'IA tranche | {rate([r for r in firm if r['said'] != 0], lambda r: r['said'] == r['sign'])} |",
             f"| Sens **inverse** | {rate([r for r in firm if r['said'] != 0], lambda r: r['said'] == -r['sign'])} |",
             f"| Consigne tranchée, l'IA répond « nuancé » | {rate(firm, lambda r: r['said'] == 0)} |",
             f"| Consigne « sans avis », l'IA répond nuancé | {rate(neutral, lambda r: r['said'] == 0)} |",
             f"| Consigne « sans avis », l'IA prend parti à tort | {rate(neutral, lambda r: r['said'] != 0)} |", ""]
    lines += ["| Origine des débats | Positions | Bon sens (consigne tranchée) |", "| --- | --- | --- |"]
    for source in sorted({r["source"] for r in rows}):
        sub = [r for r in rows if r["source"] == source]
        f2 = [r for r in sub if r["sign"] != 0 and r["said"] != 0]
        lines.append(f"| {source} | {len(sub)} | {rate(f2, lambda r: r['said'] == r['sign'])} |")
    lines += ["", "**Les propositions** (une proposition devrait correspondre à un sujet ; plusieurs propositions pour un même sujet = éparpillement) :", "",
              "| Proposition créée par l'IA | Positions | Sujets réels |", "| --- | --- | --- |"]
    for (pid, ptext), counter in sorted(by_prop.items(), key=lambda kv: -sum(kv[1].values()))[:25]:
        lines.append(f"| {ptext} | {sum(counter.values())} | {', '.join(f'{t} {c}' for t, c in counter.most_common(3))} |")
    per_topic = Counter()
    for (pid, ptext), counter in by_prop.items():
        per_topic[counter.most_common(1)[0][0]] += 1
    lines += ["", "Propositions par sujet réel : " + ", ".join(f"{t} {c}" for t, c in per_topic.most_common()) + ".", "",
              "Limites : la « vérité » est la consigne donnée à l'auteur simulé, pas une relecture humaine ; les débats « gabarit » sont plus faciles que les vrais messages."]
    return "\n".join(lines)


def coherence_report(url: str, truth: dict) -> str:
    """The check of the roles against what people say: does it flag the people who were given a role that does not fit them (truth: `role_mismatch`)?"""
    people = {p["id"]: p for p in truth["people"]}
    with psycopg.connect(url, row_factory=tuple_row) as conn:
        rows = conn.execute("SELECT user_id::text, role_name, verdict, incompatible_axes, confirmed_axes, compatible_axes FROM claimed_ideology_summary").fetchall()
        n_scores = conn.execute("SELECT count(DISTINCT user_id) FROM person_axis_scores").fetchone()[0]
        n_claims = conn.execute("SELECT count(DISTINCT user_id) FROM claims WHERE stance IS NOT NULL").fetchone()[0]
    per_person: dict[str, list] = defaultdict(list)
    for uid, role, verdict, bad, ok1, ok2 in rows:
        per_person[uid].append((role, verdict))
    def person_verdict(items):
        v = {x[1] for x in items}
        return "discordant" if "discordant" in v else "concordant" if "concordant" in v else "not_verifiable"
    table = defaultdict(Counter)
    for uid, items in per_person.items():
        if uid in people:
            table["rôle qui ne leur correspond pas" if people[uid]["role_mismatch"] else "rôle conforme à leurs idées"][person_verdict(items)] += 1
    lambda c, k: f"{c[k]}" if c else "0"  # noqa: E731
    lines = ["# Les rôles d'idées comparés à ce que disent les personnes", "",
             f"{n_claims} personnes ont au moins une position lue, {n_scores} ont un score sur au moins un axe, {len(per_person)} portent un rôle d'idées dont l'axe est actif.", "",
             "| Personnes | Contradiction | Cohérent | Pas assez de propos |", "| --- | --- | --- | --- |"]
    for k in ("rôle qui ne leur correspond pas", "rôle conforme à leurs idées"):
        c = table[k]
        lines.append(f"| {k} ({sum(c.values())}) | {c['discordant']} | {c['concordant']} | {c['not_verifiable']} |")
    flagged = [(uid, items) for uid, items in per_person.items() if person_verdict(items) == "discordant" and uid in people]
    lines += ["", "**Les personnes signalées en contradiction** (à relire : leur type réel, leurs rôles, leur consigne de départ) :", "",
              "| Personne | Type réel | Rôles d'idées | Rôle fautif d'après le test ? |", "| --- | --- | --- | --- |"]
    for uid, items in sorted(flagged, key=lambda f: people[f[0]]["handle"]):
        p = people[uid]
        lines.append(f"| {p['handle']} | {p['archetype']} | {', '.join(r for r, v in items)} | {'oui' if p['role_mismatch'] else 'non'} |")
    lines += ["", "Limites : le rôle « fautif » est un rôle tiré au hasard sans lien avec les idées de la personne ; un rôle conforme peut aussi être contredit si le tableau des attentes de chaque rôle "
              "(`ideology_axis_ranges`) ne reflète pas ce que dit l'archétype. Ce tableau est celui du projet, à relire par vous."]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
