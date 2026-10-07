"""Stage 6-7 of the cascade: how much each proposition weighs on each axis, then the score of each person on each axis.

The model reads a proposition (never a person, never a message) and the active axes, and says on which axes agreeing with it moves someone,
and toward which pole: `loading` from -1 (toward the negative pole) to +1 (toward the positive one). These loadings are *proposed* (`proposition_axis.is_validated`
stays false): a person confirms them. The score of a person on an axis is then computed by SQL (`refresh_person_axis_scores`, tested
earlier): the mean of their positions on the propositions that weigh on that axis, weighted by confidence and by the loading, pulled
toward 0 by a little doubt, with an uncertainty that only shrinks as the evidence grows. The code decides nothing about a person.

A proposition is read **two or three times, in different ways**. What every reading says (the same axis toward the same pole) is kept. What they disagree on is **not dropped,
it is decided**: a last, narrow question is asked about each disputed axis alone (« where does this sentence stand on this axis: negative pole, positive pole, or nowhere? »),
and its answer is the answer, even if it is the opposite pole of what a reading proposed. The model alone puts about a quarter of its links on an axis that a person would not
choose (tools/score_axes_reference.py measures it) and its errors are not the same from one wording of the question to the next; abstaining on a disagreement would lose real
links, so the tie is broken by a question that is easier than the first one. The readings: the base instructions, a more cautious wording (it prefers « no axis » to a doubtful
one), and, once a person has decided the axes of enough propositions, the same question with the closest of those decided propositions as examples: what people validate makes
the next readings better.
"""
import logging
import re
from collections.abc import Callable
from functools import partial

import psycopg
from psycopg.rows import tuple_row

from dindon.analysis.parallel import pipeline, workers_for
from dindon.analysis.ollama import Ollama, OllamaError

log = logging.getLogger("dindon.analysis")

MAX_AXES_PER_PROPOSITION = 2
MIN_LOADING = 0.5
FAILURES_IN_A_ROW = 3
PROMPT_VERSION = "axes-4"
PERSON_ONLY = re.compile(r"^(?:[Ii]l faut|[Nn]ous devons|[Oo]n doit)\s+soutenir\s+[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ][\w-]+(?:\s+[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ][\w-]+)*[.!?]?$", re.UNICODE)
EXAMPLES = 6                    # validated propositions shown to the third reading
MIN_EXAMPLES = 30               # the third reading exists once a person has decided the axes of this many propositions
# How firmly a statement leans: the model says a word, the code turns it into a number. (Asking the model for a signed number made it give the same sign
# to a statement and to its opposite: see tools/check_axes.py, which measured it. Asking it which POLE a statement leans toward, by the name of the pole,
# does not.)
STRENGTH = {"forte": 1.0, "moyenne": 0.6}

SYSTEM = (
    "Tu relies une phrase politique à des axes. Un axe oppose deux pôles, chacun avec son nom (par exemple `economie` : Public ou Privé). Pour la phrase "
    "donnée, indique les axes (au plus 2) sur lesquels ELLE PREND PARTI, et pour chacun le pôle vers lequel penche l'idée que la phrase DÉFEND : "
    "`toward` est le nom exact d'un des deux pôles de cet axe. Une phrase qui critique une idée penche vers le pôle opposé à cette idée. "
    "`strength` dit à quel point la phrase penche : `forte` si c'est son sujet même, `moyenne` si c'est un aspect net. "
    "Reste sobre : un seul axe suffit presque toujours ; n'en ajoute un deuxième (au plus 2) que si la phrase défend CLAIREMENT une idée sur celui-ci aussi, "
    "jamais parce qu'une personne qui pense cela pourrait penser autre chose. Si la phrase ne prend parti sur aucun axe (un goût, la météo, un fait), rends une liste vide. Respecte le champ « ne couvre pas » de chaque axe : "
    "un sujet n'appartient qu'à un seul axe. Soutenir une personne, une célébrité ou un serveur ne situe pas quelqu'un sur un axe politique : rends une liste vide.\n\n"
    "Exemples (d'autres sujets que ceux de la conversation à traiter) :\n"
    "- « il faut abolir la monarchie et élire tous les chefs » → representation : Démocratie (forte)\n"
    "- « un chef fort décide plus vite qu'un parlement qui discute » → representation : Autocratie (moyenne)\n"
    "- « les entreprises de transport doivent appartenir à l'État » → economie : Public (forte)\n"
    "- « privatiser les autoroutes a fait baisser les coûts » → economie : Privé (forte)\n"
    "- « la police doit pouvoir fouiller sans mandat pour protéger les gens » → pouvoir : Sécurité (forte)\n"
    "- « chacun doit pouvoir faire ce qu'il veut chez lui sans que l'État regarde » → pouvoir : Liberté (forte)\n"
    "- « les frontières doivent rester fermées aux marchandises étrangères » → commerce : Protectionnisme (forte)\n"
    "- « les étrangers qui vivent ici doivent parler français et adopter nos coutumes » → immigration : Assimilation (forte)\n"
    "- « la diversité des origines fait la force d'un pays » → immigration : Multiculturalisme (forte)\n"
    "- « les nouvelles technologies de surveillance sont une avancée » → pouvoir : Sécurité (moyenne), technologie : Technologie (moyenne)\n"
    "- « il fait beau aujourd'hui » → (aucun axe)"
)


SYSTEM_CAREFUL = """Tu relies une phrase politique à des axes. Un axe oppose deux pôles, chacun avec son nom (par exemple `economie` : Public ou Privé). Pour la phrase donnée, indique les axes (au plus 2) sur lesquels ELLE PREND PARTI, et pour chacun le pôle vers lequel penche l'idée que la phrase DÉFEND : `toward` est le nom exact d'un des deux pôles de cet axe. Une phrase qui critique une idée penche vers le pôle opposé à cette idée. `strength` dit à quel point la phrase penche : `forte` si c'est son sujet même, `moyenne` si c'est un aspect net. Reste sobre : un seul axe suffit presque toujours ; n'en ajoute un deuxième (au plus 2) que si la phrase défend CLAIREMENT une idée sur celui-ci aussi, jamais parce qu'une personne qui pense cela pourrait penser autre chose. Si la phrase ne prend parti sur aucun axe, rends une liste vide. C'est le cas d'un goût, de la météo, d'un simple fait, mais AUSSI de tout ce qui ne dit pas de quel côté l'auteur se range : une question, une demande de source ou de précision, « ça dépend des cas », « les deux côtés ont des arguments », un appel à nuancer ou à ne pas simplifier, une critique de la façon de débattre, un constat sans conclusion, une phrase qui cherche seulement un équilibre entre deux idées. En cas de doute, une liste vide vaut mieux qu'un axe douteux : ne choisis un axe que si, en lisant la phrase seule, on voit clairement de quel côté de cet axe son auteur se range. Soutenir une personne, une célébrité ou un serveur ne situe pas quelqu'un sur un axe politique : rends une liste vide. Respecte le champ « ne couvre pas » de chaque axe : un sujet n'appartient qu'à un seul axe.

Exemples (d'autres sujets que ceux de la conversation à traiter) :
- « il faut abolir la monarchie et élire tous les chefs » → representation : Démocratie (forte)
- « un chef fort décide plus vite qu'un parlement qui discute » → representation : Autocratie (moyenne)
- « le pouvoir est beaucoup trop concentré dans les mains du ministre de l'Intérieur » → representation : Démocratie (moyenne)   [une critique de la concentration penche vers l'autre pôle]
- « les entreprises de transport doivent appartenir à l'État » → economie : Public (forte)
- « privatiser les autoroutes a fait baisser les coûts » → economie : Privé (forte)
- « l'État est un mauvais gestionnaire, laissons faire le marché » → controle : Libre marché (forte)
- « les plus riches doivent payer beaucoup plus d'impôts pour financer les hôpitaux » → redistribution : Redistribution (forte)
- « trop d'impôts découragent ceux qui travaillent et les poussent à partir » → redistribution : Mérite individuel (moyenne)
- « la police doit pouvoir fouiller sans mandat pour protéger les gens » → pouvoir : Sécurité (forte)
- « les lois d'exception finissent toujours par servir à surveiller tout le monde » → pouvoir : Liberté (forte)   [une critique de la sécurité penche vers la liberté]
- « les frontières doivent rester fermées aux marchandises étrangères » → commerce : Protectionnisme (forte)
- « les étrangers qui vivent ici doivent parler français et adopter nos coutumes » → immigration : Assimilation (forte)
- « la diversité des origines fait la force d'un pays » → immigration : Multiculturalisme (forte)
- « une armée plus nombreuse finit toujours par être utilisée » → diplomatie : Pacifiste (moyenne)   [une critique de l'armée penche vers le pôle pacifiste]
- « seule une alliance avec les États-Unis nous protège vraiment » → alliances : Atlantisme (forte)
- « décider à Bruxelles ce que nos communes peuvent faire, c'est inacceptable » → europe : Souveraineté nationale (forte)
- « face à la Chine, seule une Europe unie peut compter » → europe : Intégration européenne (forte)
- « on ne peut pas continuer à produire et à consommer comme si les ressources étaient infinies » → ecologie : Écologie (forte)
- « interdire les voitures en ville, c'est ruiner les commerçants et l'emploi » → ecologie : Productivisme (moyenne)
- « les nouvelles technologies de surveillance sont une avancée » → pouvoir : Sécurité (moyenne), technologie : Technologie (moyenne)
- « il faut tout changer d'un coup, les petites réformes ne servent à rien » → rupture : Rupture (forte)
- « il faut avancer par étapes pour ne brusquer personne » → rupture : Réforme (moyenne)
- « je ne sais pas, il y a des arguments des deux côtés » → (aucun axe)
- « c'est un peu simpliste comme vision, non ? » → (aucun axe)
- « tu as une source pour ça ? » → (aucun axe)
- « il faut trouver un équilibre entre liberté et sécurité » → (aucun axe)
- « il fait beau aujourd'hui » → (aucun axe)"""


def _schema(codes: list[str], poles: list[str]) -> dict:
    return {"type": "object", "properties": {"axes": {"type": "array", "items": {"type": "object", "properties": {
        "axis": {"type": "string", "enum": codes}, "toward": {"type": "string", "enum": poles}, "strength": {"type": "string", "enum": list(STRENGTH)}},
        "required": ["axis", "toward", "strength"]}}}, "required": ["axes"]}


def describe(axes: list[tuple], anchors: dict[str, dict[float, str]] | None = None) -> str:
    """The axes as the model reads them: the question, the two poles **with what each one means in a sentence** (the anchors of the database), and what the axis
    does not cover. Without the sentence, the model confuses the words of the poles (« Assimilation » taken for « welcoming »)."""
    out = []
    for code, name, question, negative, positive, _definition, excludes in axes:
        meaning = anchors.get(code, {}) if anchors else {}
        poles = (f"Pôle {negative} : {meaning[-1.0]} Pôle {positive} : {meaning[1.0]}" if -1.0 in meaning and 1.0 in meaning else f"Pôles : {negative} ou {positive}.")
        out.append(f"- `{code}` ({name}) : {question} {poles}" + (f" Ne couvre pas : {excludes}" if excludes else ""))
    return "\n".join(out)


def load_axes(conn: psycopg.Connection, active_only: bool = True) -> tuple[list[tuple], dict[str, int], dict[str, dict[float, str]]]:
    """The active axes (all of them with `active_only=False`, for a check), their ids, and the sentence that says what each pole means."""
    where = "WHERE is_active" if active_only else ""
    with conn.cursor(row_factory=tuple_row) as cur:
        axes = cur.execute(f"SELECT code, name, question, negative_pole, positive_pole, definition, excludes FROM axes {where} ORDER BY position").fetchall()
        ids = dict(cur.execute(f"SELECT code, id FROM axes {where}").fetchall())
        anchors: dict[str, dict[float, str]] = {}
        for code, value, text in cur.execute(f"SELECT a.code, k.value, k.description FROM axis_anchors k JOIN axes a ON a.id = k.axis_id {where.replace('is_active', 'a.is_active')}").fetchall():
            anchors.setdefault(code, {})[float(value)] = text
    return axes, ids, anchors


def poles_of(axes: list[tuple]) -> dict[str, dict[str, int]]:
    """For each axis code, the name of each pole and its direction (-1 negative, +1 positive), compared without case or accents."""
    return {code: {_fold(negative): -1, _fold(positive): 1} for code, _, _, negative, positive, _, _ in axes}


def _fold(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)).casefold().strip()


def validate(answer: dict, ids: dict[str, int], poles: dict[str, dict[str, int]]) -> list[tuple[int, float, float]]:
    """The loadings that hold up: a known axis, a pole that belongs to THAT axis, a known strength, once per axis, at most three."""
    kept: dict[int, tuple[int, float, float]] = {}
    for raw in answer.get("axes", []) if isinstance(answer.get("axes"), list) else []:
        if not isinstance(raw, dict) or raw.get("axis") not in ids or raw["axis"] not in poles:
            continue
        direction = poles[raw["axis"]].get(_fold(raw.get("toward", "")))
        strength = STRENGTH.get(raw.get("strength"))
        if direction is None or strength is None or strength < MIN_LOADING or ids[raw["axis"]] in kept:
            continue
        kept[ids[raw["axis"]]] = (ids[raw["axis"]], round(direction * strength, 2), round(0.5 + strength / 2, 2))
    return sorted(kept.values(), key=lambda t: -abs(t[1]))[:MAX_AXES_PER_PROPOSITION]


JUDGE_SYSTEM = (
    "Tu vérifies un rattachement entre une PHRASE politique et un AXE. L'axe oppose deux pôles. Dis où la phrase se range sur CET axe :\n"
    "- `negatif` : l'idée que défend la phrase penche clairement vers le pôle négatif ;\n- `positif` : elle penche clairement vers le pôle positif ;\n"
    "- `aucun` : elle ne prend pas parti sur cet axe (une question, un « ça dépend », un sujet voisin traité par un autre axe, un simple constat).\n"
    "Une critique d'une idée penche vers le pôle opposé à cette idée. Réponds seulement par le JSON demandé."
)
JUDGE_SCHEMA = {"type": "object", "properties": {"place": {"type": "string", "enum": ["negatif", "positif", "aucun"]}}, "required": ["place"]}
JUDGED_LOADING = 0.6            # a link that a reading did not make alone is as firm as « moyenne »


def judge_axis(client: Ollama, model: str, axis: tuple, anchors: dict[str, dict[float, str]], text: str) -> int | None:
    """Where the sentence stands on this one axis: -1 (negative pole), +1 (positive pole) or None (nowhere, or an answer that is not in the shape asked)."""
    code, name, question, negative, positive, _, excludes = axis
    meaning = anchors.get(code, {})
    described = (f"Axe `{code}` ({name}) : {question}\nPôle négatif = {negative} : {meaning.get(-1.0, '')}\nPôle positif = {positive} : {meaning.get(1.0, '')}"
                 + (f"\nCet axe ne couvre pas : {excludes}" if excludes else ""))
    answer = client.chat_json(model, JUDGE_SYSTEM, f"{described}\n\nPhrase : {text}", JUDGE_SCHEMA)
    return {"negatif": -1, "positif": 1}.get(answer.get("place")) if isinstance(answer, dict) else None


def decide(readings: list[list[tuple[int, float, float]]], judge: Callable[[int], int | None]) -> list[tuple[int, float, float]]:
    """The links of a proposition: those that every reading made (same axis, same pole) as they are, and for each axis on which the readings do not all agree, what
    `judge(axis_id)` says (-1, +1, or None for no link). A link keeps the weakest of the strengths that agreed; a judged one is `JUDGED_LOADING`."""
    seen: dict[int, list[tuple[int, float, float]]] = {}
    for reading in readings:
        for link in reading:
            seen.setdefault(link[0], []).append(link)
    kept = []
    for axis_id, links in seen.items():
        signs = {1 if loading > 0 else -1 for _, loading, _ in links}
        if len(links) == len(readings) and len(signs) == 1:
            kept.append((axis_id, min((link[1] for link in links), key=abs), round(sum(link[2] for link in links) / len(links), 2)))
        elif (sign := judge(axis_id)) is not None:
            kept.append((axis_id, round(sign * JUDGED_LOADING, 2), 0.75))
    return sorted(kept, key=lambda t: -abs(t[1]))[:MAX_AXES_PER_PROPOSITION]


def _decided_examples(conn: psycopg.Connection, proposition_id: int, embed_model: str, axes: list[tuple]) -> str:
    """The propositions closest to this one whose axes a person decided, as lines of examples (« no axis » included), the closest last; empty when there are too few."""
    with conn.cursor(row_factory=tuple_row) as cur:
        near = cur.execute(
            """SELECT p.id, p.text FROM propositions p JOIN proposition_embeddings e ON e.proposition_id = p.id AND e.model = %(model)s
               WHERE p.axes_validated_at IS NOT NULL AND p.id <> %(id)s AND p.status NOT IN ('rejected', 'merged')
               ORDER BY e.embedding <=> (SELECT embedding FROM proposition_embeddings WHERE proposition_id = %(id)s AND model = %(model)s) LIMIT %(k)s""",
            {"model": embed_model, "id": proposition_id, "k": EXAMPLES}).fetchall()
        poles = {a[0]: (a[3], a[4]) for a in axes}
        lines = []
        for pid, text in reversed(near):
            links = cur.execute("""SELECT a.code, pa.loading::float8 FROM proposition_axis pa JOIN axes a ON a.id = pa.axis_id AND a.is_active
                                   WHERE pa.proposition_id = %s AND pa.is_validated ORDER BY abs(pa.loading) DESC""", (pid,)).fetchall()
            words = " ; ".join(f"{code} : {poles[code][1] if loading > 0 else poles[code][0]} ({'forte' if abs(loading) >= 0.8 else 'moyenne'})"
                               for code, loading in links if code in poles) or "(aucun axe)"
            lines.append(f"- « {text} » → {words}")
    return "Phrases proches dont une personne a décidé les axes (ils sont justes) :\n" + "\n".join(lines) + "\n\n" if lines else ""


def _judge(client: Ollama, model: str, by_id: dict[int, tuple], anchors: dict, text: str, axis_id: int) -> int | None:
    """`judge_axis` for the axis with this id (what `decide` asks for: it only knows ids)."""
    return judge_axis(client, model, by_id[axis_id], anchors, text)


def assign_axes(conn: psycopg.Connection, client: Ollama, model: str, guild_id: int, *, progress: Callable[[int, int], None] | None = None,
                cancelled: Callable[[], bool] = lambda: False, embed_model: str = "bge-m3") -> dict:
    """Asks for the weight on the axes of each proposition that a position of this server is about and that was not asked yet (two or three readings, see the top of
    this file), then recomputes the scores of the server. Returns what was done."""
    axes, ids, anchors = load_axes(conn)
    with conn.cursor(row_factory=tuple_row) as cur:
        todo = cur.execute(
            """SELECT p.id, p.text FROM propositions p WHERE p.axes_read_at IS NULL AND p.status NOT IN ('rejected', 'merged')
               AND EXISTS (SELECT 1 FROM claims c WHERE c.proposition_id = p.id AND c.guild_id = %s) ORDER BY p.id""", (guild_id,)).fetchall()
        decided = cur.execute("SELECT count(*) FROM propositions WHERE axes_validated_at IS NOT NULL").fetchone()[0]
    described = "\n\nLes axes :\n" + describe(axes, anchors)
    systems = [SYSTEM + described, SYSTEM_CAREFUL + described]
    poles = poles_of(axes)
    schema = _schema(list(ids), sorted({name for a in axes for name in (a[3], a[4])}))
    by_id = {ids[a[0]]: a for a in axes}
    done = linked = failed = in_a_row = 0

    def propositions():
        """The propositions to ask the model about; the examples decided by a person are looked up here (the database stays in this thread)."""
        for pid, text in todo:
            if cancelled():
                return
            if PERSON_ONLY.fullmatch(text.strip()):
                yield pid, text, None
            else:
                yield pid, text, _decided_examples(conn, pid, embed_model, axes) if decided >= MIN_EXAMPLES else ""

    def ask(item):
        """The weight on the axes of one proposition, on whichever computer is free (no database here: several run at the same time)."""
        _, text, examples = item
        if examples is None:
            return None                                                     # a sentence about a person: nothing to link
        readings = [validate(client.chat_json(model, system, f"Phrase : {text}", schema), ids, poles) for system in systems]
        if examples:
            readings.append(validate(client.chat_json(model, systems[0], examples + f"Phrase : {text}", schema), ids, poles))
        return decide(readings, partial(_judge, client, model, by_id, anchors, text))

    for (pid, _, examples), loadings, error in pipeline(propositions(), ask, workers_for(client, model), cancelled):
        if cancelled():
            break
        if error is not None:
            if not isinstance(error, OllamaError):
                raise error
            failed += 1
            in_a_row += 1
            log.warning("axes: proposition skipped (%s)", str(error)[:80])
            if in_a_row >= FAILURES_IN_A_ROW:
                raise error
            continue
        in_a_row = 0
        with conn.transaction():
            if examples is None:
                conn.execute("UPDATE propositions SET axes_read_at = now() WHERE id = %s", (pid,))
            else:
                # a new reading replaces what an earlier reading proposed (an older version of the prompt, for instance); what a person validated stays
                conn.execute("DELETE FROM proposition_axis WHERE proposition_id = %s AND NOT is_validated", (pid,))
                for axis_id, loading, confidence in loadings:
                    conn.execute("""INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence, is_validated) VALUES (%s, %s, %s, %s, false)
                                    ON CONFLICT (proposition_id, axis_id) DO NOTHING""", (pid, axis_id, loading, confidence))
                conn.execute("UPDATE propositions SET axes_read_at = now() WHERE id = %s", (pid,))
        done += 1
        linked += len(loadings or ())
        if progress:
            progress(done + failed, len(todo))
    scores = conn.execute("SELECT refresh_person_axis_scores(%s)", (guild_id,)).fetchone()[0]
    log.info("axes: %d propositions read (%d links), %d scores", done, linked, scores)
    return {"done": done, "links": linked, "failed": failed, "scores": scores, "waiting": len(todo)}
