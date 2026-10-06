"""Does the AI link propositions to the right axes, in the right direction? A check with a gold set that a person (me, on 2026-10-04) wrote.

For each of the 120 statements of the invented political server (tools/make_political_server.py: 6 arguments for and 6 against, for each of the 10 subjects),
the axes on which AGREEING with it moves someone are known, and in which direction (a statement that defends a stronger State moves toward "Public" and
"Planification", never toward "Privé"). The model of the analysis is asked the same question as in production (analysis/axes.py), and its answer is scored:

  correct       a loading on an axis that is acceptable, in the right direction
  wrong sign    a loading on an acceptable axis, in the OPPOSITE direction: the worst error, it turns a person's score the wrong way
  elsewhere     a loading on an axis that is not in the acceptable list (it may be defensible: the list is short, written by one person)
  nothing       no loading at all for the statement

    .venv/bin/python tools/check_axes.py [--model qwen3:14b] [--limit 120] [--report political/RAPPORT-AXES.md]

It needs Ollama and an analyzed database only for the axes' text: it reads the axes from the database of DATABASE_URL (default: the political server's).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from dindon.analysis import axes as axes_module  # noqa: E402
from dindon.analysis.ollama import Ollama, OllamaError  # noqa: E402
from make_demo_server import THEMES  # noqa: E402,F401  (the first banks of the demo, not used here)
import make_political_server as political  # noqa: E402

# The axes on which AGREEING with a statement that is FOR the proposition of the subject moves someone, and the direction (+1 toward the positive pole).
# Against the proposition: the opposite direction on the same axes. Written by one person, to be argued with.
FOR = {
    "economie": {("economie", -1), ("controle", -1)},
    "europe": {("structure", -1), ("intervention", -1), ("commerce", 1)},
    "immigration": {("immigration", 1)},
    "ecologie": {("technologie", 1), ("controle", -1), ("economie", -1)},
    "laicite": {("religion", -1)},
    "securite": {("pouvoir", -1)},
    "institutions": {("representation", -1)},
    "defense": {("diplomatie", -1), ("intervention", 1)},
    "societe": {("morale", -1)},
    "technologie": {("technologie", -1), ("controle", 1)},
}


# A second set, written AFTER the prompt was tuned on the first one and with other words: the numbers on it are the honest ones. (axis, direction): +1 toward the
# positive pole of the axis, -1 toward the negative one; an empty set: the statement takes no side on any axis, and any link is an error.
HELD_OUT = [
    ("Les régions devraient pouvoir décider seules de leur politique des transports.", {("structure", -1)}),
    ("Il faut une même loi pour tout le territoire, pas vingt-cinq règles différentes.", {("structure", 1)}),
    ("Donnons plus de pouvoir aux communes et aux départements.", {("structure", -1)}),
    ("Un État central fort est la seule garantie d'égalité entre les citoyens.", {("structure", 1)}),
    ("Je préférerais un gouvernement d'experts à des élus qui font de la démagogie.", {("representation", 1)}),
    ("Les élections libres et l'opposition sont non négociables.", {("representation", -1)}),
    ("Un seul chef qui décide, c'est ce qu'il faut à ce pays en crise.", {("representation", 1)}),
    ("Les citoyens doivent pouvoir révoquer leurs élus en cours de mandat.", {("representation", -1)}),
    ("Je ne veux pas qu'on fiche tout le monde pour attraper quelques criminels.", {("pouvoir", 1)}),
    ("Mieux vaut perdre un peu de vie privée que laisser des terroristes agir.", {("pouvoir", -1)}),
    ("La drogue devrait être légalisée, c'est un choix personnel.", {("pouvoir", 1)}),
    ("Il faut des couvre-feux et des contrôles dans les quartiers sensibles.", {("pouvoir", -1)}),
    ("La paix passe par la négociation et l'ONU, pas par les canons.", {("diplomatie", 1)}),
    ("Seule une armée redoutée garantit la paix.", {("diplomatie", -1)}),
    ("Chacun chez soi : la France n'a pas à se mêler des affaires des autres pays.", {("intervention", -1)}),
    ("La France doit défendre ses intérêts partout dans le monde, sans complexe.", {("intervention", 1)}),
    ("Le rail devrait être renationalisé.", {("economie", -1)}),
    ("Les hôpitaux privés sont mieux gérés que les publics.", {("economie", 1)}),
    ("L'État doit fixer les prix de l'énergie.", {("controle", -1)}),
    ("La concurrence fixe les bons prix, l'État doit rester à l'écart.", {("controle", 1)}),
    ("Il faut des droits de douane pour protéger nos agriculteurs.", {("commerce", -1)}),
    ("Les traités de libre-échange font baisser les prix pour tout le monde.", {("commerce", 1)}),
    ("Les crèches de Noël dans les mairies, ça n'a rien à faire dans un lieu public.", {("religion", -1)}),
    ("La foi devrait inspirer nos lois et notre éducation.", {("religion", 1)}),
    ("Le mariage pour tous était une évolution nécessaire.", {("morale", -1)}),
    ("La famille traditionnelle reste le socle de la société.", {("morale", 1)}),
    ("Les OGM nous aideront à nourrir la planète.", {("technologie", -1)}),
    ("Je préfère les produits naturels aux solutions de laboratoire.", {("technologie", 1)}),
    ("Les nouveaux arrivants doivent abandonner leurs coutumes pour adopter les nôtres.", {("immigration", -1)}),
    ("Une société qui accueille des cultures différentes est plus forte.", {("immigration", 1)}),
    ("Ouvrons les frontières aux travailleurs qui veulent venir.", {("immigration", 1)}),
    ("Il faut réduire l'immigration, le pays ne peut plus accueillir.", {("immigration", -1)}),
    ("Ce film était vraiment bien tourné.", set()),
    ("Quelle chaleur aujourd'hui, impossible de travailler.", set()),
    ("J'ai adoré cette recette de tarte aux pommes.", set()),
    ("Privatisons les autoroutes et laissons le marché fixer les péages.", {("economie", 1), ("controle", 1)}),
    ("L'armée doit être plus nombreuse et plus équipée.", {("diplomatie", -1)}),
    ("Les écoles doivent enseigner les valeurs chrétiennes.", {("religion", 1), ("morale", 1)}),
    ("Sortir de l'Union européenne pour retrouver notre souveraineté.", {("intervention", 1), ("structure", 1)}),
    ("Il faut taxer les multinationales pour financer les services publics.", {("economie", -1), ("controle", -1)}),
]


# Statements on the axes that are not active (yet): used to ask whether activating them helps (--all-axes) or blurs the others.
EXTRA = [
    ("La France doit céder davantage de pouvoirs à l'Europe.", {("europe", 1)}),
    ("Les lois doivent être faites à Paris, pas à Bruxelles.", {("europe", -1)}),
    ("Une armée européenne commune est la bonne réponse.", {("europe", 1)}),
    ("Sortons de l'euro pour retrouver notre monnaie.", {("europe", -1)}),
    ("Il faut limiter la croissance pour préserver la planète.", {("ecologie", 1)}),
    ("Priorité à la production et à l'emploi, l'environnement viendra après.", {("ecologie", -1)}),
    ("Interdisons les vols courts pour réduire les émissions.", {("ecologie", 1)}),
    ("Il faut des quotas pour que les femmes accèdent aux postes de direction.", {("genre", -1)}),
    ("Une mère doit rester auprès de ses enfants plutôt que de travailler.", {("genre", 1)}),
    ("À travail égal, salaire égal : il faut sanctionner les entreprises.", {("genre", -1)}),
    ("Les plus riches doivent payer beaucoup plus d'impôts.", {("redistribution", -1)}),
    ("Chacun doit garder le fruit de son travail, l'impôt est un vol.", {("redistribution", 1)}),
    ("Il faut augmenter les allocations pour les plus pauvres.", {("redistribution", -1)}),
    ("L'élevage industriel doit être interdit.", {("animaux", -1)}),
    ("La chasse est une tradition qu'il faut préserver.", {("animaux", 1)}),
]


def gold() -> list[tuple[str, str, set[tuple[str, int]]]]:
    out = []
    for topic in political.TOPICS:
        for side, sign in ((political.PRO, 1), (political.CON, -1)):
            for sentence in side[topic]:
                out.append((topic, sentence, {(axis, direction * sign) for axis, direction in FOR[topic]}))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="qwen3:14b")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--set", choices=["tuning", "held-out", "extended"], default="tuning",
                        help="the 120 statements that the prompt was tuned on; the 40 written afterwards; or those 40 plus 15 on the axes that are not active")
    parser.add_argument("--all-axes", action="store_true", help="give the model all 21 axes, the inactive ones too (to see whether activating them helps)")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is needed (the axes are read from the database)")
    with psycopg.connect(url) as conn:
        axes, ids, anchors = axes_module.load_axes(conn, active_only=not args.all_axes)
    inverse = {v: k for k, v in ids.items()}
    system = axes_module.SYSTEM + "\n\nLes axes :\n" + axes_module.describe(axes, anchors)
    poles = axes_module.poles_of(axes)
    schema = axes_module._schema(list(ids), sorted({name for a in axes for name in (a[3], a[4])}))
    client = Ollama(args.ollama, timeout=600)
    chosen = {"held-out": HELD_OUT, "extended": HELD_OUT + EXTRA}.get(args.set)
    items = ([("autre", sentence, acceptable) for sentence, acceptable in chosen] if chosen else gold())[: args.limit or None]
    results = []
    started = time.monotonic()
    cache_path = ROOT / "political" / "axes-gold-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}      # the answers of the model, per version of the prompt: a rescore asks nothing
    for n, (topic, sentence, acceptable) in enumerate(items, 1):
        key = f"{axes_module.PROMPT_VERSION}|{args.model}|{'all' if args.all_axes else 'active'}|{sentence}"
        if key in cache:
            answer = cache[key]
        else:
            try:
                answer = client.chat_json(args.model, system, f"Phrase : {sentence}", schema)
            except OllamaError as error:
                print(f"{n}: {error}")
                continue
            cache[key] = answer
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        found = [(inverse[axis], 1 if loading > 0 else -1, loading) for axis, loading, _ in axes_module.validate(answer, ids, poles)]
        results.append((topic, sentence, acceptable, found))
        if n % 20 == 0:
            print(f"{n}/{len(items)} ({time.monotonic() - started:.0f} s)", flush=True)

    correct = wrong = elsewhere = nothing = covered = 0
    per_topic: dict[str, Counter] = defaultdict(Counter)
    wrong_examples, elsewhere_axes = [], Counter()
    for topic, sentence, acceptable, found in results:
        good_axes = {axis for axis, _ in acceptable}
        hit = False
        if not found:
            nothing += 1
            per_topic[topic]["nothing"] += 1
            hit = not acceptable                                # a statement that takes no side is rightly left without a link
        for axis, sign, loading in found:
            if (axis, sign) in acceptable:
                correct += 1
                hit = True
                per_topic[topic]["correct"] += 1
            elif axis in good_axes:
                wrong += 1
                per_topic[topic]["wrong sign"] += 1
                wrong_examples.append((topic, sentence, axis, sign))
            else:
                elsewhere += 1
                per_topic[topic]["elsewhere"] += 1
                elsewhere_axes[axis] += 1
        covered += hit or (not acceptable and not found)
    total = correct + wrong + elsewhere
    lines = ["# Les axes de l'IA : vérification sur un jeu de référence", "",
             f"{len(results)} phrases ({'écrites après coup, avec d autres mots' if args.set == 'held-out' else '6 pour et 6 contre pour chacun des 10 sujets de la politique inventée'}), modèle `{args.model}`, la même question qu'en production. "
             "Les axes acceptables et leur sens ont été écrits par une personne (moi, le 4 octobre 2026) : c'est une référence à discuter, pas une vérité.", "",
             "| | |", "| --- | --- |",
             f"| Phrases avec au moins un lien correct (bon axe, bon sens) | **{covered}/{len(results)} ({covered / max(len(results), 1):.0%})** |",
             f"| Liens corrects | {correct}/{total} ({correct / max(total, 1):.0%}) |",
             f"| Liens **dans le mauvais sens** sur un bon axe (le pire) | **{wrong}/{total} ({wrong / max(total, 1):.0%})** |",
             f"| Liens sur un axe hors de la liste | {elsewhere}/{total} ({elsewhere / max(total, 1):.0%}) |",
             f"| Phrases sans aucun lien | {nothing}/{len(results)} |", "",
             "| Sujet | Corrects | Mauvais sens | Ailleurs | Rien |", "| --- | --- | --- | --- | --- |"]
    for topic in (political.TOPICS if args.set == "tuning" else ["autre"]):
        c = per_topic[topic]
        lines.append(f"| {topic} | {c['correct']} | {c['wrong sign']} | {c['elsewhere']} | {c['nothing']} |")
    if elsewhere_axes:
        lines += ["", "Axes les plus souvent choisis hors de la liste : " + ", ".join(f"{a} ({n})" for a, n in elsewhere_axes.most_common(5)) + "."]
    if wrong_examples:
        lines += ["", "**Liens dans le mauvais sens (à relire)** :", ""] + [f"- ({t}) « {s} » → {a} {'+' if g > 0 else '−'}" for t, s, a, g in wrong_examples[:15]]
    lines.insert(2, f"Version de la consigne : `{axes_module.PROMPT_VERSION}`.")
    text = "\n".join(lines)
    print("\n" + text)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
