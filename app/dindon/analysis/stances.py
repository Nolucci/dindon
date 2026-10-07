"""Stage 5 bis of the cascade: is the position of each claim the right one?

The first reading (extraction.py) gives a position (for / against / nuanced) *and* the proposition, in one pass over a whole conversation. Measured on the invented
political server, it often got the position wrong: it judged whether the subject is approved ("le 49.3 est antidémocratique" -> against) instead of whether the person
agrees with the proposition (the person writes it, so: for), and the position was kept when a proposition was matched to one worded the other way.

This stage reads again, narrowly: one claim at a time, **only** the person's own quotes (those that proved the claim) and the proposition as it is now, and asks for
one word: agreement, disagreement, nuance, or no position (a question, a request for a source). Nothing else is in front of the model, which makes the task much
easier. The answer replaces the position, the first one is kept in `stance_before`; a quote that is "no position" turns the claim into a question (it stays, with its
proof, but no longer counts). A claim that a person confirmed or rejected by hand is never touched. A claim is read once (`stance_check`): this can be stopped and resumed.
"""
import logging
from collections.abc import Callable

import psycopg
from psycopg.rows import tuple_row

from dindon.analysis.ollama import Ollama, OllamaError

log = logging.getLogger("dindon.analysis")

PROMPT_VERSION = "stance-1"
MAX_QUOTES = 3
FAILURES_IN_A_ROW = 3

SYSTEM = (
    "Tu compares ce qu'une personne a ÉCRIT dans un salon Discord avec une PROPOSITION (une phrase). Tu dis quelle est sa position vis-à-vis de la proposition :\n"
    "- `accord` : ce que la personne écrit dit la même chose que la proposition, ou la soutient, même avec d'autres mots. Une critique (« le 49.3 est antidémocratique ») "
    "est un ACCORD avec la proposition « Le 49.3 est antidémocratique » : on juge si les DEUX PHRASES disent la même chose, pas si le sujet est apprécié ou non ;\n"
    "- `desaccord` : la personne dit le contraire de la proposition, ou la rejette (« Non », « Au contraire », « Faux »…) ;\n"
    "- `nuance` : la personne hésite, dit que ça dépend, que les deux côtés ont des arguments (« les deux côtés ont des points » → nuance, même si la proposition dit "
    "la même chose), ou dit qu'elle n'a pas d'avis ;\n"
    "- `aucune` : les citations ne prouvent pas que cette personne soutient, rejette ou nuance CETTE proposition. C'est le cas d'une "
    "question, d'un symptôme personnel, d'un simple fait sans avis, d'une réponse vague (« il a raison », « pareil »), ou d'un propos "
    "dont le sujet manque. N'utilise pas la proposition pour inventer le sens absent de la citation.\n"
    "Réponds seulement par le JSON demandé."
)
SCHEMA = {"type": "object", "properties": {"relation": {"type": "string", "enum": ["accord", "desaccord", "nuance", "aucune"]}}, "required": ["relation"]}
STANCE = {"accord": 1, "desaccord": -1, "nuance": 0, "aucune": None}

_TODO = """
SELECT cl.id, cl.stance, p.text,
       (SELECT array_agg(e.quote ORDER BY e.message_id) FROM claim_evidence e WHERE e.claim_id = cl.id AND e.quote IS NOT NULL)
FROM claims cl JOIN propositions p ON p.id = cl.proposition_id
WHERE cl.guild_id = %s AND cl.kind = 'opinion' AND cl.stance IS NOT NULL AND cl.stance_check IS NULL AND cl.review_status = 'auto'
ORDER BY cl.id
"""


def judge(client: Ollama, model: str, quotes: list[str], proposition: str) -> str | None:
    """The relation of the person's words to the proposition (a key of STANCE), or None when the model did not answer in the shape asked."""
    shown = "\n".join(f"- {q}" for q in quotes[:MAX_QUOTES])
    answer = client.chat_json(model, SYSTEM, f"Ce que la personne a écrit :\n{shown}\n\nProposition : « {proposition} »", SCHEMA)
    relation = answer.get("relation") if isinstance(answer, dict) else None
    return relation if relation in STANCE else None


def verify_stances(conn: psycopg.Connection, client: Ollama, model: str, guild_id: int, *, progress: Callable[[int, int], None] | None = None,
                   cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Reads again the position of the claims that were not read yet. Returns what was done."""
    with conn.cursor(row_factory=tuple_row) as cur:
        todo = cur.execute(_TODO, (guild_id,)).fetchall()
    checked = changed = questions = unclear = failed = in_a_row = 0
    for n, (claim_id, before, proposition, quotes) in enumerate(todo, 1):
        if cancelled():
            break
        if not quotes:
            continue
        try:
            relation = judge(client, model, quotes, proposition)
            in_a_row = 0
        except OllamaError as error:
            failed += 1
            in_a_row += 1
            log.warning("stances: claim skipped (%s)", str(error)[:80])
            if in_a_row >= FAILURES_IN_A_ROW:
                raise
            continue
        if relation is None:                                        # an answer that is not in the shape asked: the first reading stays, to be read again later
            unclear += 1
            continue
        after = STANCE[relation]
        with conn.transaction():
            if after is None:                                       # not a position: it stays with its proof, but it is a question and counts for nothing
                conn.execute("UPDATE claims SET kind = 'question', stance = NULL, proposition_id = NULL, stance_before = %s, stance_check = %s WHERE id = %s",
                             (before, PROMPT_VERSION, claim_id))
                questions += 1
            else:
                conn.execute("UPDATE claims SET stance = %s, stance_before = %s, stance_check = %s WHERE id = %s", (after, before, PROMPT_VERSION, claim_id))
                changed += after != before
        checked += 1
        if progress:
            progress(n, len(todo))
    scores = conn.execute("SELECT refresh_person_axis_scores(%s)", (guild_id,)).fetchone()[0] if checked else None
    log.info("stances: %d claims read, %d positions changed, %d turned into questions, %d unclear, %d failed", checked, changed, questions, unclear, failed)
    return {"checked": checked, "changed": changed, "questions": questions, "unclear": unclear, "failed": failed, "waiting": len(todo), "scores": scores}
