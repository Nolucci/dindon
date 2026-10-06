"""An invented POLITICAL Discord server, as realistic as can be made without real people, with a ground truth to test the AI against.

Everything is made up. The people are made from archetypes (what they think on ten subjects, how they talk), with roles that mostly
follow their ideas, and sometimes do not (that is what the role check has to catch). The conversations are written by the local model
(Ollama), one debate at a time, each person keeping their opinion; they are cached in a file so that the work can be stopped and
resumed, and extended (`--count`). `build` turns them into JSON v2 exports (one file per channel) and a `truth.json`.

    .venv/bin/python tools/make_political_server.py generate --count 110      # long (about 15 s per debate); pauses on a low battery
    .venv/bin/python tools/make_political_server.py build --out political/    # exports + truth.json, from what exists

WHAT `truth.json` IS, AND IS NOT: for every message, the opinion that the simulated author was **told to hold** on the subject, and the
kind of message that the model said it wrote (affirmation, question, irony, ...). It is the instruction given to a simulated person, not
a human re-reading of each message: a model can drift. Use it to measure, and read a sample by hand before trusting a score.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from make_demo_server import (AGE_ROLES, CHANNEL_THEME, EMOJIS, IDEOLOGY_ROLES, NOTIF_ROLES, OFF_TOPIC,  # noqa: E402
                              SMALL_TALK, STAFF_ROLES, Channel, Person, World, parse_iso, write_exports)

TOPICS = ["economie", "europe", "immigration", "ecologie", "laicite", "securite", "institutions", "defense", "societe", "technologie"]
PROPOSITIONS = {
    "economie": "L'État doit réguler fortement l'économie : SMIC plus haut, services publics, impôts progressifs.",
    "europe": "La France doit approfondir l'intégration européenne.",
    "immigration": "La France doit mener une politique d'accueil et de régularisation plus ouverte.",
    "ecologie": "La transition écologique doit primer sur la croissance, par la sobriété et les énergies renouvelables.",
    "laicite": "La laïcité doit être appliquée strictement : aucune expression religieuse dans l'espace public et à l'école.",
    "securite": "Il faut renforcer les moyens et les pouvoirs de la police et durcir les peines.",
    "institutions": "Il faut changer de régime : VIe République, référendum d'initiative citoyenne, moins de pouvoir au président.",
    "defense": "La France doit augmenter fortement son budget militaire.",
    "societe": "Il faut faire évoluer vite les normes de société (fin de vie, égalité, nouvelles familles).",
    "technologie": "Il faut accélérer le développement de l'IA et des nouvelles technologies sans les freiner par la réglementation.",
}
LEVELS = {2: "tout à fait d'accord", 1: "plutôt d'accord", 0: "sans avis tranché (hésite, nuance, pose des questions)", -1: "plutôt contre", -2: "totalement contre"}

# name, how many people, stance on TOPICS in order, ideology roles that fit, a way of thinking
ARCHETYPES = [
    ("socialiste", 11, [2, 1, 1, 1, 1, 0, 1, 0, 2, 0], ["Socialiste", "Centre-Gauche", "Keynésien", "Égalitariste"], "social-démocrate, attaché aux services publics et au compromis"),
    ("radical", 7, [2, -1, 2, 1, 1, -1, 2, -2, 2, -1], ["Communiste", "Gauche Radicale", "Extrême-Gauche", "Antifasciste"], "anticapitaliste, méfiant envers la police et les armées"),
    ("ecologiste", 12, [1, 1, 1, 2, 1, -1, 1, -1, 2, -1], ["Écologiste", "Écosocialiste", "Animaliste", "Alter-Mondialiste"], "écologiste, sobriété, méfiant envers la technologie"),
    ("liberal", 9, [-2, 1, 0, -1, 0, 1, 0, 1, 1, 2], ["Mondialiste", "Pragmatique", "Européiste"], "libéral : moins d'État, entreprise, innovation"),
    ("souverainiste", 8, [0, -2, -1, 0, 1, 1, -1, 1, -1, 0], ["Gaulliste", "Eurosceptique", "Protectionnisme", "Patriote"], "souverainiste, attaché à la nation et à l'indépendance"),
    ("nationaliste", 6, [0, -2, -2, -1, 1, 2, -1, 1, -2, 0], ["Patriote", "Eurosceptique", "Républicain"], "nationaliste, identité et ordre, très ferme sur l'immigration (sans insulte)"),
    ("conservateur", 6, [-1, 0, -1, -1, -2, 1, -1, 1, -2, -1], ["Spiritualité", "Républicain", "Patriote"], "conservateur, valeurs chrétiennes, famille, tradition"),
    ("centriste", 9, [0, 2, 0, 0, 1, 0, 0, 1, 0, 1], ["Pragmatique", "Européiste", "Démocrate", "Centre-Gauche"], "centriste pragmatique, aime les compromis et les faits"),
    ("laic", 8, [1, 1, -1, 0, 2, 1, 0, 1, 0, 0], ["Républicain", "Démocrate", "Humaniste"], "républicain laïc intransigeant sur l'école et l'espace public"),
    ("libertarien", 5, [-2, 0, 1, -1, 0, -1, 0, -1, 1, 2], ["Pragmatique", "Autre voie", "Mondialiste"], "libertarien technophile, méfiant envers l'État"),
    ("humaniste", 7, [1, 1, 2, 1, 0, -1, 1, -1, 2, 0], ["Humaniste", "Progressiste", "Multiculturaliste", "Féministe"], "humaniste progressiste, droits et solidarité"),
    ("apolitique", 10, [0] * 10, [], "peu informé, pose des questions, change facilement d'avis, pas de rôle d'idée"),
    ("provocateur", 2, [-2, -2, -2, -2, -2, 2, -2, 2, -2, 2], ["Autre voie"], "provocateur sarcastique qui prend le contre-pied de tout, souvent ironique (sans insulte)"),
]
TONES = ["posé et argumenté", "sarcastique", "passionné, écrit parfois en majuscules", "concis, phrases très courtes", "pédant, cite des chiffres",
         "écrit vite avec des fautes de frappe et des abréviations", "blagueur", "agacé et direct"]
FIRST = ["Lucas", "Emma", "Hugo", "Léa", "Nathan", "Chloé", "Théo", "Manon", "Louis", "Camille", "Jules", "Inès", "Arthur", "Sarah", "Adam", "Zoé", "Tom", "Jade",
         "Maxime", "Lola", "Antoine", "Clara", "Paul", "Anna", "Yanis", "Eva", "Noah", "Alice", "Raphaël", "Juliette", "Enzo", "Louise", "Gabriel", "Mila", "Victor", "Nina"]
HANDLE = ["{f}", "{f}_{n}", "{f}{n}", "xX_{f}_Xx", "le_{f}", "{f}.fr", "{f}_off", "dr_{f}", "{f}2a", "the_{f}", "{f}_{w}", "{w}_{f}"]
WORDS = ["bleu", "rouge", "vieux", "nuit", "sage", "rebelle", "libre", "citoyen", "pionnier", "lyon", "nord", "sud", "paris", "marmotte", "hibou", "tricolore", "cynique", "idéaliste"]
TRIGGERS = {
    "economie": ["la hausse du SMIC annoncée par un gouvernement étranger", "une grève dans le secteur de l'énergie", "le débat sur la retraite à 64 ans", "les prix de l'alimentation qui flambent",
                 "la privatisation d'une entreprise ferroviaire", "un rapport sur la dette publique", "la taxe sur les très hauts revenus"],
    "europe": ["un nouveau traité européen en discussion", "le budget commun européen", "un référendum de sortie dans un pays voisin", "l'euro numérique", "les règles européennes sur l'agriculture"],
    "immigration": ["un projet de loi sur les titres de séjour", "un reportage sur des travailleurs sans papiers", "les quotas annuels proposés par un parti", "l'accueil de réfugiés après une crise", "la langue et l'intégration"],
    "ecologie": ["l'implantation d'éoliennes près d'un village", "la relance du nucléaire", "une canicule record", "la taxe sur le kérosène", "l'interdiction des voitures thermiques en 2035"],
    "laicite": ["une polémique sur le port de signes religieux à l'école", "le financement de lieux de culte", "un débat sur les racines chrétiennes de la France", "la neutralité des agents publics"],
    "securite": ["une série de faits divers qui fait la une", "un projet de caméras de reconnaissance faciale", "la surpopulation carcérale", "les peines planchers pour les récidivistes"],
    "institutions": ["l'usage du 49.3 pour faire passer un budget", "une proposition de référendum d'initiative citoyenne", "le non-cumul des mandats", "la réduction du nombre de parlementaires"],
    "defense": ["une hausse du budget de l'armée", "le débat sur l'OTAN", "une opération militaire à l'étranger", "l'industrie de l'armement"],
    "societe": ["une proposition de loi sur la fin de vie", "l'égalité salariale femmes-hommes", "un débat sur la GPA", "l'écriture inclusive"],
    "technologie": ["un nouveau modèle d'IA qui écrit des articles", "une loi européenne sur l'IA", "le télétravail et l'automatisation", "les réseaux sociaux et les adolescents"],
}
MIX_TRIGGERS = ["la rentrée politique", "un sondage sur la présidentielle", "une manifestation dans la capitale", "un débat télévisé entre candidats", "l'abstention aux dernières élections"]
SCHEMA = {"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object", "properties": {
    "speaker": {"type": "integer"}, "text": {"type": "string"}, "reply_to": {"type": ["integer", "null"]},
    "kind": {"type": "string", "enum": ["affirmation", "question", "ironie", "citation", "accord", "desaccord", "hors_sujet"]}},
    "required": ["speaker", "text", "reply_to", "kind"]}}}, "required": ["messages"]}
END = datetime(2026, 9, 30, tzinfo=UTC)
DAYS = 150
CONV_PER_TOPIC = {"economie": 14, "europe": 10, "immigration": 12, "ecologie": 12, "laicite": 8, "securite": 9, "institutions": 7, "defense": 6, "societe": 10, "technologie": 6}
MIXED = 20
SCALE = 3        # debates in the whole plan: 3 x 114


# --- the people -----------------------------------------------------------------------------------------------------------


def make_cast(rng: random.Random) -> list[dict]:
    """The people, with what they REALLY think (stance), how they talk, and which roles they will wear. Pure: same seed, same cast."""
    cast, used = [], set()
    for kind, count, base, roles, how in ARCHETYPES:
        for _ in range(count):
            while True:
                handle = rng.choice(HANDLE).format(f=rng.choice(FIRST), n=rng.randint(2, 99), w=rng.choice(WORDS))
                if handle not in used:
                    used.add(handle)
                    break
            stance = {t: max(-2, min(2, v + (rng.choice([-1, 1]) if rng.random() < 0.3 and kind != "apolitique" else 0))) for t, v in zip(TOPICS, base)}
            mismatch = rng.random() < 0.12 and bool(roles)
            ideology = []
            if roles and rng.random() < 0.8:
                ideology = rng.sample(roles, min(len(roles), 1 if rng.random() < 0.8 else 2))
            if mismatch:                                                    # a role that does not fit what the person says
                ideology = [rng.choice([r for r in IDEOLOGY_ROLES if r not in roles])]
            cast.append({"handle": handle, "archetype": kind, "how": how, "tone": rng.choice(TONES), "stance": stance, "ideology_roles": ideology,
                         "role_mismatch": mismatch, "age_band": rng.choice(AGE_ROLES), "gender": rng.choice(["Homme", "Femme"]),
                         "age_role": rng.random() < 0.8, "gender_role": rng.random() < 0.7, "notif": [r for r in NOTIF_ROLES if rng.random() < 0.3],
                         "shifts": {}})
    rng.shuffle(cast)
    for i, person in enumerate(cast):
        person["activity"] = 1.0 / (i + 1) ** 0.85
    for person in rng.sample([c for c in cast if c["archetype"] != "apolitique"], 7):          # people who change their minds, on a date
        topic = rng.choice(TOPICS)
        if person["stance"][topic] != 0:
            person["shifts"][topic] = {"day": rng.randint(60, 110), "stance": -person["stance"][topic] if rng.random() < 0.3 else 0}
    for person in rng.sample(cast, 3):
        person["staff"] = rng.choice(STAFF_ROLES)
    return cast


def stance_at(person: dict, topic: str, day: int) -> int:
    shift = person["shifts"].get(topic)
    return shift["stance"] if shift and day >= shift["day"] else person["stance"][topic]


# --- the debates -----------------------------------------------------------------------------------------------------------


def plan(rng: random.Random, cast: list[dict]) -> list[dict]:
    """Who debates what, when. Deterministic. Each debate has people who disagree when the cast allows it."""
    plans = []
    spec = [(t, n * SCALE) for t, n in CONV_PER_TOPIC.items()] + [("mixte", MIXED * SCALE)]
    for topic, n in spec:
        for _ in range(n):
            day = rng.randint(0, DAYS - 1)
            chosen_topic = rng.choice(TOPICS) if topic == "mixte" else topic
            weights = [p["activity"] for p in cast]
            starter = rng.choices(range(len(cast)), weights)[0]
            members = [starter]
            for _ in range(rng.randint(2, 4)):
                pick = rng.choices(range(len(cast)), weights)[0]
                if pick not in members:
                    members.append(pick)
            if len({stance_at(cast[i], chosen_topic, day) for i in members}) < 2:                     # nobody disagrees: add someone who does
                others = [i for i in range(len(cast)) if i not in members and abs(stance_at(cast[i], chosen_topic, day) - stance_at(cast[starter], chosen_topic, day)) >= 2]
                if others:
                    members.append(rng.choice(others))
            plans.append({"topic": chosen_topic, "channel_topic": topic, "day": day, "hour": rng.choice([8, 12, 13, 18, 19, 20, 21, 22, 23]),
                          "members": members, "trigger": rng.choice(TRIGGERS[chosen_topic] if topic != "mixte" else MIX_TRIGGERS + TRIGGERS[chosen_topic])})
    plans.sort(key=lambda p: (p["day"], p["hour"]))
    for i, p in enumerate(plans):
        p["id"] = i
    return plans


SYSTEM = ("Tu écris des échanges réalistes dans un salon Discord politique francophone, entre des personnes fictives. Style oral d'internet : phrases courtes, "
          "abréviations, parfois des fautes, parfois un emoji, parfois des questions ou une pique ironique. Chacun GARDE SON OPINION (il peut nuancer ou concéder un point, "
          "pas changer de camp). Tout le monde ne réagit pas à tout. Pas de noms de personnes ou de partis réels, pas d'insultes graves, rien de haineux : on peut être très "
          "en désaccord et poli. Les réponses sont de 1 à 3 phrases, quelques-unes un peu plus longues et argumentées. "
          "CHAQUE message apporte quelque chose de nouveau (un exemple, une objection, une anecdote, un chiffre inventé, une question précise) : ne répète jamais un message "
          "précédent ni les mêmes mots. N'écris jamais le prénom des autres en majuscules ; les majuscules servent seulement à un mot crié de temps en temps. "
          "Les participants « sans avis tranché » s'intéressent, demandent des précisions, et peuvent finir par pencher d'un côté sans l'affirmer.")


def prompt(p: dict, cast: list[dict]) -> str:
    lines = [f"Sujet de la discussion : {p['topic']}. Déclencheur : {p['trigger']}.",
             f"Proposition débattue : « {PROPOSITIONS[p['topic']]} »", "", "Participants (numéro : profil) :"]
    for n, i in enumerate(p["members"]):
        c = cast[i]
        level = stance_at(c, p["topic"], p["day"])
        lines.append(f"{n} : {c['handle']} ({c['age_band'].lower()}, {c['gender'].lower()}), {c['how']}. Ton : {c['tone']}. Sur la proposition : {LEVELS[level]}.")
    lines += ["", f"Écris {random.Random(p['id']).randint(8, 14)} messages au total. Le premier lance le sujet à partir du déclencheur. `speaker` est le numéro du participant, "
              "`reply_to` est le rang (à partir de 0) du message auquel il répond (ou null), `kind` le genre du message. Un participant « sans avis tranché » ne prend pas parti : "
              "il questionne ou nuance. Quelqu'un d'ironique peut dire le contraire de ce qu'il pense : mets alors kind = ironie."]
    return "\n".join(lines)


def battery_wait() -> None:
    """On a laptop: do not drain the battery for a test."""
    while True:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
        m = re.search(r"(\d+)%; (\w+)", out)
        if not m or m.group(2) != "discharging" or int(m.group(1)) >= 30:
            return
        print(f"battery at {m.group(1)}%: pausing 2 minutes", flush=True)
        time.sleep(120)


def clean(raw: dict, n_members: int) -> list[dict] | None:
    out = []
    for m in raw.get("messages", []):
        text = re.sub(r"\s+", " ", str(m.get("text", ""))).strip()
        if not text or len(text) > 700 or not isinstance(m.get("speaker"), int) or not 0 <= m["speaker"] < n_members:
            continue
        reply = m.get("reply_to")
        reply = reply if isinstance(reply, int) and 0 <= reply < len(out) and out[reply]["speaker"] != m["speaker"] else None
        out.append({"speaker": m["speaker"], "text": text, "reply_to": reply, "kind": m.get("kind", "affirmation")})
    return out if len(out) >= 5 and len({o["speaker"] for o in out}) >= 2 else None


def generate(args) -> None:
    from dindon.analysis.ollama import Ollama, OllamaError

    rng = random.Random(args.seed)
    cast = make_cast(rng)
    plans = plan(rng, cast)
    cache = Path(args.cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["id"] for line in cache.read_text().splitlines()} if cache.exists() else set()
    todo = [p for p in plans if p["id"] not in done][: args.count - len(done) if args.count else None]
    ollama = Ollama(args.ollama, timeout=300)
    print(f"{len(done)} debates already written, {len(todo)} to write ({args.model})", flush=True)
    lock = threading.Lock()

    def one(k: int, p: dict) -> None:
        for attempt in range(3):
            battery_wait()
            start = time.monotonic()
            try:
                answer = ollama._call("/api/chat", {"model": args.model, "stream": False, "format": SCHEMA, "think": False, "keep_alive": "30m",
                                                    "options": {"temperature": 0.9, "num_ctx": 8192, "seed": p["id"] * 7 + attempt, "repeat_penalty": 1.15},
                                                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(p, cast)}]})
                messages = clean(json.loads(answer["message"]["content"]), len(p["members"]))
            except (OllamaError, KeyError, json.JSONDecodeError) as error:
                print(f"debate {p['id']}: {error}", flush=True)
                messages = None
            if messages:
                with lock, cache.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({**p, "messages": messages}, ensure_ascii=False) + "\n")
                print(f"[{k}/{len(todo)}] debate {p['id']} ({p['topic']}): {len(messages)} messages in {time.monotonic() - start:.0f} s", flush=True)
                return
        print(f"debate {p['id']} abandoned", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda kp: one(*kp), enumerate(todo, 1)))



# --- debates written from templates (when the model has not written them yet) -------------------------------------------------
# Hand-written arguments for and against each proposition. They give VOLUME with an exact ground truth; their language is poorer and more
# repetitive than the model's, so an AI score on them is optimistic: the report keeps the two sources apart.
PRO = {
    "economie": ["avec le SMIC actuel des gens bossent à plein temps et dorment dans leur voiture, c'est pas normal", "les hôpitaux et les écoles c'est pas une marchandise, ça doit rester public",
                 "taxer les grosses fortunes c'est le seul moyen de financer les services publics sans écraser les classes moyennes", "le marché seul n'a jamais réglé les inégalités, il faut un État qui rééquilibre",
                 "quand l'énergie est privatisée les prix explosent et les actionnaires se gavent", "un salaire minimum plus haut ça relance aussi la consommation, c'est pas qu'un coût"],
    "europe": ["sur le climat, la défense, le numérique : seuls on pèse rien, ensemble on peut", "l'euro nous a évité des dévaluations en chaîne, demande aux Grecs ce qu'ils en pensent",
               "les normes européennes protègent les consommateurs plus que n'importe quelle loi nationale", "une vraie armée européenne ça nous rendrait moins dépendants de Washington",
               "le marché commun c'est des millions d'emplois chez nous, pas un détail", "les pays qui sortent de l'UE finissent par le regretter, regarde les exemples"],
    "immigration": ["la moitié de nos secteurs en tension tournent grâce à des travailleurs étrangers, on le sait tous", "régulariser ceux qui bossent déjà c'est du bon sens, pas de la charité",
                    "accueillir des réfugiés c'est une obligation du droit international, pas un choix", "l'intégration marche quand on donne des papiers et un travail, pas quand on laisse dans le flou",
                    "la France s'est faite par vagues successives, les Italiens et les Polonais ont eu les mêmes procès", "les chiffres réels sont bien plus bas que ce que raconte la télé"],
    "ecologie": ["les scientifiques sont clairs, on n'a plus le temps de faire du business as usual", "la sobriété ça coûte moins cher que de réparer les dégâts de la canicule",
                 "le solaire et l'éolien sont devenus les énergies les moins chères, faut arrêter de se mentir", "continuer la croissance infinie sur une planète finie c'est mathématiquement impossible",
                 "taxer le kérosène et les jets privés c'est le minimum syndical", "les villes doivent se refaire autour du vélo et du train, pas de la voiture"],
    "laicite": ["à l'école publique on est élève avant d'être croyant, c'est le principe", "la loi de 1905 est claire : l'État ne reconnaît ni ne finance aucun culte",
                "les signes religieux ostensibles n'ont pas leur place chez les agents publics, neutralité oblige", "la laïcité protège justement les croyants comme les non-croyants",
                "quand on laisse la religion entrer dans l'espace public les pressions communautaires suivent", "c'est une exception française et c'est ce qui nous garde unis"],
    "securite": ["la police est sous-équipée et sous-payée, faut investir sinon ça va pas aller mieux", "une peine qui n'est pas appliquée ne dissuade personne, il faut de la fermeté",
                 "la vidéosurveillance a élucidé plein d'affaires, c'est factuel", "les victimes de récidivistes ça existe, on ne peut pas toujours leur dire que c'est la société",
                 "des quartiers entiers vivent sous la loi des trafics, l'État doit reprendre la main", "plus de juges et de procureurs pour que les peines tombent vraiment"],
    "institutions": ["la Ve République concentre trop de pouvoir dans les mains d'un seul homme", "le RIC permettrait de débloquer des sujets que les partis évitent",
                     "le 49.3 c'est un passage en force, point, ça n'a rien de démocratique", "une assemblée à la proportionnelle représenterait enfin tout le monde",
                     "les gens ont l'impression de ne servir que le jour du vote, faut les associer en continu", "les citoyens tirés au sort ça marche très bien dans d'autres pays"],
    "defense": ["on vit dans un monde plus dangereux, ne pas réarmer c'est naïf", "la dissuasion nucléaire et une armée crédible nous protègent d'abord nous-mêmes",
                "notre industrie d'armement c'est de l'emploi et de l'indépendance", "nos alliés nous respectent parce qu'on peut agir, pas parce qu'on parle",
                "les stocks de munitions sont ridicules, c'est une faiblesse stratégique", "un budget militaire à 3% du PIB ce serait raisonnable vu la situation"],
    "societe": ["l'aide à mourir avec des garde-fous, c'est la liberté de choisir sa fin de vie", "l'égalité salariale on l'attend depuis 50 ans, faut des sanctions réelles",
                "les familles ne ressemblent plus à un seul modèle, la loi doit suivre", "attendre que tout le monde soit d'accord c'est ne jamais rien changer",
                "les droits des uns ne retirent rien aux autres, c'est tout le principe", "la société a déjà changé, c'est la loi qui est en retard"],
    "technologie": ["l'IA va augmenter la productivité comme l'imprimerie ou l'électricité", "freiner la recherche en France c'est laisser les États-Unis et la Chine décider seuls",
                    "la plupart des peurs sur l'IA ressemblent à celles sur le train au XIXe siècle", "les entreprises qui s'y mettent tôt créent des emplois, les autres disparaissent",
                    "trop de réglementation tue les startups, c'est déjà visible en Europe", "l'innovation a toujours été le moteur de la croissance et du progrès médical"],
}
CON = {
    "economie": ["un SMIC trop haut c'est des petites boîtes qui ferment ou qui n'embauchent plus", "l'État est un mauvais gestionnaire, regarde les entreprises publiques qui perdent de l'argent",
                 "on est déjà le pays le plus taxé d'Europe, encore des impôts et les gens partent", "la dette c'est nos enfants qui la paieront, il faut réduire les dépenses",
                 "ce sont les entreprises qui créent la richesse, l'État la redistribue seulement", "moins de normes et de charges et on relance l'industrie en deux ans"],
    "europe": ["Bruxelles décide pour nous et personne n'a voté pour ces gens", "l'euro nous a enlevé tout moyen d'ajuster notre économie, c'est un carcan",
               "la souveraineté c'est choisir nos lois, pas les recevoir toutes faites", "on paie plus qu'on ne reçoit et on nous donne des leçons en prime",
               "chaque pays a sa culture, l'uniformité européenne ça ne marche pas", "le Royaume-Uni s'en sort très bien, on nous avait promis l'apocalypse"],
    "immigration": ["on n'arrive plus à loger, soigner et former tout le monde, il faut des limites", "l'assimilation ça marchait avant, aujourd'hui on laisse faire le communautarisme",
                    "régulariser c'est envoyer le message que passer par la porte de derrière paie", "les quotas votés chaque année, c'est la démocratie, pas du racisme",
                    "les services publics sont saturés dans plein de villes, faut le dire", "il faut être ferme sur les expulsions sinon la loi ne veut plus rien dire"],
    "ecologie": ["le nucléaire c'est la vraie réponse au climat, l'éolien c'est du vent", "l'écologie punitive va nous mettre les gens dans la rue, regarde les gilets jaunes",
                 "la décroissance c'est un luxe de gens qui ont déjà tout", "la Chine pollue plus que nous tous réunis, nos efforts ne changent presque rien",
                 "l'innovation technique réglera plus de choses que les interdictions", "on ferme des usines ici pour les rouvrir ailleurs, résultat net : zéro"],
    "laicite": ["la laïcité est devenue une arme contre une seule religion, il faut de la mesure", "nos racines chrétiennes ont leur place, les clochers ça fait partie du paysage",
                "interdire partout, c'est confondre neutralité de l'État et effacement des croyants", "les gens ont le droit de vivre leur foi en public",
                "il y a des lois qui suffisent déjà, pas besoin d'en rajouter", "la liberté religieuse est dans la déclaration de 1789, on l'oublie souvent"],
    "securite": ["la surveillance de masse c'est la porte ouverte à tous les abus, ça finit toujours mal", "enfermer plus ne fait pas baisser la récidive, tous les chiffres le disent",
                 "mieux vaut de la prévention et des éducateurs que des caméras partout", "les lois sécuritaires sont toujours étendues bien au-delà de leur but initial",
                 "des policiers mieux formés ça compte plus que des policiers plus armés", "on ne règle pas des problèmes sociaux avec du pénal"],
    "institutions": ["un exécutif fort c'est la stabilité, la IVe République ça a fini par s'écrouler", "le RIC finirait dans les mains des lobbies et des algorithmes des réseaux",
                     "la Ve a tenu 60 ans, on ne change pas de régime pour une humeur passagère", "gouverner c'est décider, un Parlement éclaté ne décide plus rien",
                     "les référendums se transforment en vote contre le gouvernement, jamais sur la question", "avant de refaire une constitution, faisons marcher celle qu'on a"],
    "defense": ["la diplomatie coûte moins cher que les chars et elle a déjà évité des guerres", "on dépense déjà beaucoup, mieux vaut des hôpitaux que des missiles en plus",
                "sortir de l'OTAN et ne plus suivre Washington partout, ça me paraît sain", "intervenir à l'étranger n'a jamais produit de stabilité durable",
                "une armée plus grosse donne surtout l'envie de s'en servir", "il y a mieux à faire de l'argent public aujourd'hui"],
    "societe": ["attention aux changements trop rapides, la famille reste un repère pour beaucoup", "sur la fin de vie la pente est glissante, regardez ce qui se passe ailleurs",
                "tout n'a pas à être réglé par la loi, la société évolue à son rythme", "certaines traditions méritent d'être préservées, c'est pas du conservatisme borné",
                "on divise les gens avec ces débats qui ne concernent qu'une minorité", "les gens sont fatigués qu'on leur dise quoi penser sur ces sujets"],
    "technologie": ["on ne maîtrise déjà plus rien des algorithmes, on devrait ralentir", "l'IA va détruire des métiers et personne n'a de plan pour les gens derrière",
                    "protéger le vivant avant de lancer n'importe quelle innovation, c'est du bon sens", "les géants du numérique deviennent plus puissants que des États",
                    "on a déjà vu ce que les réseaux ont fait aux ados, on recommence avec l'IA", "il faut une réglementation sérieuse avant, pas des excuses après"],
}
NEUTRAL = ["je suis un peu perdu sur le sujet, vous en pensez quoi ?", "j'avoue que je n'ai pas d'avis tranché, les deux côtés ont des points", "quelqu'un a un article sérieux sur la question ?",
           "c'est quoi concrètement la proposition ? parce que j'ai du mal à me positionner", "ça dépend vraiment des cas, non ?", "je lis vos arguments, ça m'intéresse, continuez"]
CONCEDE = ["je te l'accorde sur ce point, mais ", "ok c'est vrai que ", "bon point, cela dit ", "je comprends l'argument, mais "]
IRONY_MARK = ["ah oui bien sûr, ", "génial comme idée, ", "évidemment, ", "oh la belle trouvaille : "]
Q_BACK = ["t'as une source pour ça ?", "et tu fais comment pour financer ça ?", "c'est pas un peu simpliste comme vision ?", "tu parles de quel pays au juste ?"]


def style(text: str, tone: str, rng: random.Random) -> str:
    if tone.startswith("passionné") and rng.random() < 0.5:
        words = text.split()
        i = rng.randrange(len(words))
        words[i] = words[i].upper()
        text = " ".join(words) + " !"
    elif tone.startswith("écrit vite"):
        text = text.replace("est ", "est ", 1).replace("pas ", "pa ", 1).replace(" que ", " ke ", 1).replace("é", "e", 2).lower()
    elif tone.startswith("concis"):
        text = text.split(",")[0]
    elif tone.startswith("sarcastique") and rng.random() < 0.4:
        text += " mdr"
    return text


def template_debate(rng: random.Random, cast: list[dict], d: dict) -> list[dict]:
    """A debate from the banks: each person says things that fit the opinion they hold (6 to 12 messages), with replies, concessions, questions."""
    members = d["members"]
    topic = d["topic"]
    out: list[dict] = []
    last_by: dict[int, int] = {}
    for step in range(rng.randint(6, 12)):
        n = rng.randrange(len(members)) if step else 0
        if step and out and out[-1]["speaker"] == n:
            n = (n + 1) % len(members)
        c = cast[members[n]]
        level = stance_at(c, topic, d["day"])
        reply = None
        if step and rng.random() < 0.75:
            candidates = [i for i, m in enumerate(out) if m["speaker"] != n]
            reply = candidates[-1] if rng.random() < 0.7 else rng.choice(candidates)
        kind = "affirmation"
        if level == 0:
            text = rng.choice(NEUTRAL) if rng.random() < 0.7 else rng.choice(Q_BACK)
            kind = "question"
        else:
            bank = PRO[topic] if level > 0 else CON[topic]
            text = rng.choice(bank)
            if abs(level) == 1 and rng.random() < 0.6:
                text = rng.choice(CONCEDE) + text
                kind = "affirmation"
            elif reply is not None and rng.random() < 0.15:
                text, kind = rng.choice(Q_BACK), "question"
            elif c["archetype"] == "provocateur" or (c["tone"] == "sarcastique" and rng.random() < 0.15):
                # irony: says the opposite of what is held, with a mark: the truth stays the held opinion
                other = CON[topic] if level > 0 else PRO[topic]
                text, kind = rng.choice(IRONY_MARK) + rng.choice(other) + " 🙄", "ironie"
        out.append({"speaker": n, "text": style(text, c["tone"], rng), "reply_to": reply, "kind": kind})
        last_by[n] = len(out) - 1
    return out


# --- the server --------------------------------------------------------------------------------------------------------------


class PoliticalWorld(World):
    """The invented server, built from the cast and the written debates."""

    def __init__(self, cast: list[dict], seed: int = 1):
        self.cast = cast
        super().__init__(seed=seed, people=len(cast))
        self.name = "Agora — serveur politique de test"
        self.truth_messages: dict[str, dict] = {}

    def _make_people(self, count: int) -> None:
        for i, c in enumerate(self.cast):
            names = [r for r in (c["ideology_roles"] + [c.get("staff")] + c["notif"]) if r]
            if c["age_role"]:
                names.append(c["age_band"])
            if c["gender_role"]:
                names.append(c["gender"])
            names = sorted(set(names + ["Membre"]), key=lambda n: -self.roles[n]["position"])
            name = c["handle"].lower().replace(" ", "")
            person = Person(id=self._flake(datetime(2023, 1, 3, tzinfo=UTC) + timedelta(minutes=i)), name=name,
                            global_name=c["handle"] if self.rng.random() < 0.75 else None, nickname=None, is_bot=False,
                            role_ids=[int(self.roles[n]["id"]) for n in names], community=0, activity=c["activity"], stance=dict(c["stance"]),
                            color=next((self.roles[n]["color"] for n in names if "color" in self.roles[n]), None))
            c["id"], c["role_names"] = str(person.id), names
            self.people.append(person)
        from make_demo_server import Person as P
        self.bot = P(id=self._flake(datetime(2023, 1, 2, 12, tzinfo=UTC)), name="modbot", global_name=None, nickname=None, is_bot=True,
                     role_ids=[], community=-1, activity=0.0, stance={})

    def channel_for(self, topic: str, channel_topic: str) -> Channel:
        name = {"mixte": "actualité"}.get(channel_topic, next(k for k, v in CHANNEL_THEME.items() if v == topic))
        return next(c for c in self.channels if c.name == name)

    def play(self, debates: list[dict]) -> None:
        rng = self.rng
        start = END - timedelta(days=DAYS)
        by_handle = {c["handle"]: p for c, p in zip(self.cast, self.people)}
        for d in sorted(debates, key=lambda d: (d["day"], d["hour"])):
            channel = self.channel_for(d["topic"], d["channel_topic"])
            now = start + timedelta(days=d["day"], hours=d["hour"], minutes=rng.randint(0, 59))
            members = [self.cast[i] for i in d["members"]]
            posted: list[dict] = []
            for m in d["messages"]:
                author = by_handle[members[m["speaker"]]["handle"]]
                reply = posted[m["reply_to"]] if m["reply_to"] is not None else None
                content = m["text"]
                mention = None
                if reply is not None and rng.random() < 0.25:
                    mention = [self.person_by_id(reply["authorId"])]
                    content = f"@{mention[0].display_name} {content}"
                now += timedelta(seconds=rng.randint(6, 150))
                if channel.messages and now <= parse_iso(channel.messages[-1]["timestamp"]):
                    now = parse_iso(channel.messages[-1]["timestamp"]) + timedelta(milliseconds=rng.randint(1, 900))
                reactors = None
                if m["kind"] == "accord" and reply is not None and rng.random() < 0.6:
                    reactors = [(rng.choice(EMOJIS[:1] + EMOJIS[4:5])[0], [self.person_by_id(reply["authorId"])])]
                elif rng.random() < 0.1:
                    reactors = [(rng.choice(EMOJIS)[0], rng.sample(self.people, rng.randint(1, 4)))]
                message = self.post(channel, author, content, now, reply, mention, reactors)
                # the simulated author's opinion: what they were told (the person's, on the subject, on that day)
                day = d["day"]
                message["__truth"] = {"debate": d["id"], "source": d.get("source", "llm"), "topic": d["topic"], "kind": m["kind"],
                                      "stance_told": stance_at(members[m["speaker"]], d["topic"], day)}
                posted.append(message)

    def filler(self, count: int) -> None:
        rng = self.rng
        start = END - timedelta(days=DAYS)
        chans = [c for c in self.channels if not c.theme and c.name != "actualité"]
        for _ in range(count):
            channel = rng.choice(chans)
            now = start + timedelta(seconds=rng.random() * DAYS * 86400)
            author = rng.choices(self.people, [p.activity for p in self.people])[0]
            if channel.messages and now <= parse_iso(channel.messages[-1]["timestamp"]):
                now = parse_iso(channel.messages[-1]["timestamp"]) + timedelta(seconds=rng.randint(1, 600))
            m = self.post(channel, author, rng.choice(OFF_TOPIC + SMALL_TALK), now)
            m["__truth"] = {"debate": None, "topic": None, "kind": "hors_sujet", "stance_told": None}
        general = next(c for c in self.channels if c.name == "général")
        for k in range(12):
            now = start + timedelta(days=k * 12, hours=9)
            if general.messages and now <= parse_iso(general.messages[-1]["timestamp"]):
                now = parse_iso(general.messages[-1]["timestamp"]) + timedelta(minutes=5)
            m = self.post(general, self.bot, rng.choice(["Rappel : restez courtois, on débat des idées, pas des personnes.", "Un nouveau débat est ouvert dans #économie.",
                                                         "Pensez à lire les règles du serveur avant de poster."]), now)
            m["__truth"] = {"debate": None, "topic": None, "kind": "bot", "stance_told": None}


def build(args) -> None:
    rng = random.Random(args.seed)
    cast = make_cast(rng)
    cache = Path(args.cache)
    written = {}
    for line in cache.read_text(encoding="utf-8").splitlines() if cache.exists() else []:
        d = json.loads(line)
        written[d["id"]] = {**d, "source": "llm"}
    plans = plan(rng, cast)
    trng = random.Random(args.seed + 1)
    debates = list(written.values())                                  # every debate that the model has written, and templates for the rest of the plan
    for p in plans:
        if p["id"] not in written and not args.llm_only:
            debates.append({**p, "messages": template_debate(trng, cast, p), "source": "gabarit"})
    world = PoliticalWorld(cast, seed=args.seed)
    world.play(debates)
    world.filler(150)
    truth_messages = {}
    for channel in world.channels:
        for m in channel.messages:
            t = m.pop("__truth", None)
            if t:
                truth_messages[m["id"]] = {"channel": channel.name, "author": m["authorId"], **t}
    out = Path(args.out)
    exports = out / "exports"
    for old in exports.glob("*.json") if exports.exists() else []:
        old.unlink()
    files = write_exports(world, exports)
    truth = {
        "about": "Ground truth of an INVENTED server. `stance_told` is the opinion that the simulated author was told to hold (-2 totally against .. +2 totally for), "
                 "`kind` what the model said it wrote. It is an instruction, not a human re-reading: read a sample by hand before trusting a score.",
        "propositions": PROPOSITIONS, "levels": LEVELS, "guild_id": str(world.guild_id),
        "people": [{"id": c["id"], "handle": c["handle"], "archetype": c["archetype"], "tone": c["tone"], "age_band": c["age_band"], "gender": c["gender"],
                    "roles": c["role_names"], "role_mismatch": c["role_mismatch"], "stance": c["stance"], "shifts": c["shifts"]} for c in cast],
        "debates": [{"id": d["id"], "source": d["source"], "topic": d["topic"], "channel": world.channel_for(d["topic"], d["channel_topic"]).name, "trigger": d["trigger"],
                     "participants": [cast[i]["id"] for i in d["members"]]} for d in debates],
        "messages": truth_messages,
    }
    (out / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(c.messages) for c in world.channels)
    n_llm = sum(1 for d in debates if d["source"] == "llm")
    print(f"{total} messages ({sum(1 for t in truth_messages.values() if t['debate'] is not None)} in {len(debates)} debates: {n_llm} written by the model, {len(debates) - n_llm} from templates), {len(world.people)} people, "
          f"{len(files)} files in {exports}; truth in {out / 'truth.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "build"):
        p = sub.add_parser(name)
        p.add_argument("--seed", type=int, default=11)
        p.add_argument("--cache", default="political/debates.jsonl")
        if name == "generate":
            p.add_argument("--count", type=int, default=0, help="stop when this many debates are written in total (default: all of the plan, 130)")
            p.add_argument("--model", default="qwen3:14b")
            p.add_argument("--ollama", default="http://127.0.0.1:11434")
            p.add_argument("--workers", type=int, default=2, help="requests at the same time (Ollama shares the GPU between them)")
        else:
            p.add_argument("--out", default="political")
            p.add_argument("--llm-only", action="store_true", help="only the debates that the model has written (no template debate)")
    args = parser.parse_args()
    generate(args) if args.command == "generate" else build(args)


if __name__ == "__main__":
    main()
