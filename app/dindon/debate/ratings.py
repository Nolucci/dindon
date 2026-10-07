"""The verdict of a debate (docs/regles-du-bot.md, « Verdict »): who won.

When a debate has ended, everybody who took a position (participants and witnesses) may rate **each participant out of 10**, with two decimals, never themselves, until the window closes
(`debates.rating_ends_at`). The final score of a participant is **half the average of the ratings** they received and **half Dindon's analysis**, out of 10 too. The highest final score wins
(a tie is shared). If nobody rated anybody, the analysis counts alone, and the verdict says so.

Dindon's analysis is made of fixed rules on what the database already knows, with no judgement of the content by a model, the same for everybody; it is the mean of three parts:

* **sources**: the claims of the person that were confirmed by a trusted, verified source, against the person who has the most in this debate (nobody has any: 5);
* **logic**: among the claims that were checked and settled, how many held (a confirmed claim counts 1, a partly true one 0.5, a contradicted one 0); none settled: 5;
* **values**: faithfulness to the roles that the person gave themselves: the share of those roles that are not found incompatible with what they said on the server; no role given: 5.

Each part is shown with the figures it comes from. Never people who asked not to be recorded.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from dindon.clock import utc_now
from dindon.debate import rules, store
from dindon.debate.store import DebateRefused

NEUTRAL = Decimal("5")
TEN = Decimal("10")
CENT = Decimal("0.01")


def parse_score(raw: object) -> Decimal | None:
    """« 7 », « 7,5 », « 7.25 », « 10 »: a number from 0 to 10, rounded to two decimals. None for anything else."""
    text = str(raw or "").strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,2}(\.\d{1,6})?", text):
        return None
    value = Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)
    return value if 0 <= value <= TEN else None


def _two(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _open(cur: psycopg.Cursor, debate_id: int, now: datetime) -> store.Debate:
    debate = store._locked(cur, debate_id)
    if debate.status != "closed" or debate.rating_ends_at is None:
        raise DebateRefused("not_rating")
    if now >= debate.rating_ends_at or debate.results_message_id is not None:
        raise DebateRefused("rating_over")
    return debate


def targets(conn: psycopg.Connection, debate_id: int) -> list[int]:
    """Who can be rated: those who were participants when the debate ended."""
    return sorted(store.participants(conn, debate_id))


def voters(conn: psycopg.Connection, debate_id: int) -> set[int]:
    """Who can rate: everybody who took a position at any moment (participants and witnesses), never somebody who asked not to be recorded."""
    return {r[0] for r in conn.execute(
        """SELECT DISTINCT p.user_id FROM debate_positions p WHERE p.debate_id = %s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = p.user_id)""", (debate_id,)).fetchall()}


def rate(conn: psycopg.Connection, debate_id: int, rater: int, target: int, score: Decimal, now: datetime | None = None) -> str:
    """A rating, given or changed. Returns 'recorded' or 'changed'. Refused: 'unknown', 'not_rating', 'rating_over', 'self', 'blocked', 'not_voter', 'not_target'."""
    now = now or utc_now()
    if rater == target:
        raise DebateRefused("self")
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        if store.get(conn, debate_id) is None:
            raise DebateRefused("unknown")
        _open(cur, debate_id, now)
        if store._blocked(cur, rater):
            raise DebateRefused("blocked")
        if rater not in voters(conn, debate_id):
            raise DebateRefused("not_voter")
        if target not in targets(conn, debate_id):
            raise DebateRefused("not_target")
        had = cur.execute("SELECT 1 FROM debate_ratings WHERE debate_id = %s AND rater_id = %s AND target_id = %s", (debate_id, rater, target)).fetchone() is not None
        cur.execute("""INSERT INTO debate_ratings (debate_id, rater_id, target_id, score, rated_at) VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (debate_id, rater_id, target_id) DO UPDATE SET score = EXCLUDED.score, rated_at = EXCLUDED.rated_at""", (debate_id, rater, target, score, now))
        return "changed" if had else "recorded"


def given(conn: psycopg.Connection, debate_id: int, rater: int) -> dict[int, Decimal]:
    """What a person has rated so far: target -> score."""
    return {t: s for t, s in conn.execute("SELECT target_id, score FROM debate_ratings WHERE debate_id = %s AND rater_id = %s", (debate_id, rater)).fetchall()}


# --- Dindon's analysis ------------------------------------------------------------------------------------------------------


def analysis(conn: psycopg.Connection, debate_id: int, people: list[int]) -> dict[int, dict]:
    """For each person: {'sources', 'logic', 'values', 'score'} (each out of 10) and the figures they come from."""
    debate = store.get(conn, debate_id)
    sourced = dict.fromkeys(people, 0)
    verdicts = {u: {"confirmed": 0, "partly": 0, "contradicted": 0} for u in people}
    for author, verdict, has_source in conn.execute(
            """SELECT c.author_id, c.verdict, EXISTS (SELECT 1 FROM debate_sources s WHERE s.claim_id = c.id AND s.stance = 'supports')
               FROM debate_claims c WHERE c.debate_id = %s""", (debate_id,)).fetchall():
        if author not in verdicts:
            continue
        if verdict in verdicts[author]:
            verdicts[author][verdict] += 1
        if verdict == "confirmed" and has_source:
            sourced[author] += 1
    best = max(sourced.values(), default=0)
    found: dict[int, dict] = {}
    for user in people:
        v = verdicts[user]
        settled = sum(v.values())
        roles = conn.execute(
            """SELECT count(*), count(*) FILTER (WHERE verdict = 'discordant') FROM claimed_ideology_summary WHERE guild_id = %s AND user_id = %s""", (debate.guild_id, user)).fetchone()
        parts = {
            "sources": _two(TEN * sourced[user] / best) if best else NEUTRAL,
            "logic": _two(TEN * (Decimal(v["confirmed"]) + Decimal(v["partly"]) / 2) / settled) if settled else NEUTRAL,
            "values": _two(TEN * (roles[0] - roles[1]) / roles[0]) if roles[0] else NEUTRAL,
        }
        found[user] = {**parts, "score": _two(sum(parts.values()) / 3),
                       "figures": {"sourced_claims": sourced[user], "settled_claims": settled, **v, "roles": roles[0], "roles_discordant": roles[1]}}
    return found


# --- the verdict ------------------------------------------------------------------------------------------------------------


def due(conn: psycopg.Connection, now: datetime | None = None) -> list[int]:
    """The debates whose rating window is over and whose verdict has not been given."""
    now = now or utc_now()
    return [r[0] for r in conn.execute(
        "SELECT id FROM debates WHERE status = 'closed' AND rating_ends_at IS NOT NULL AND rating_ends_at <= %s AND results_message_id IS NULL ORDER BY id", (now,)).fetchall()]


def finalize(conn: psycopg.Connection, debate_id: int) -> list[dict]:
    """Computes and keeps the results of a debate (once: asking again returns what was kept), best first."""
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        store._locked(cur, debate_id)
        if not cur.execute("SELECT 1 FROM debate_results WHERE debate_id = %s", (debate_id,)).fetchone():
            people = [u for u in targets(conn, debate_id)]
            ai = analysis(conn, debate_id, people)
            votes = {t: (a, n) for t, a, n in cur.execute(
                """SELECT target_id, avg(score), count(*) FROM debate_ratings r WHERE debate_id = %s
                   AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = r.rater_id) GROUP BY target_id""", (debate_id,)).fetchall()}
            weight = Decimal(str(rules.VOTE_WEIGHT))
            rows = []
            for user in people:
                avg, n = votes.get(user, (None, 0))
                avg = _two(Decimal(avg)) if avg is not None else None
                final = _two(avg * weight + ai[user]["score"] * (1 - weight)) if avg is not None else ai[user]["score"]
                rows.append((user, avg, n, ai[user], final))
            top = max((r[4] for r in rows), default=None)
            for user, avg, n, detail, final in rows:
                cur.execute("""INSERT INTO debate_results (debate_id, user_id, vote_score, vote_count, ai_score, ai_detail, final_score, winner) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                            (debate_id, user, avg, n, detail["score"], Jsonb({k: (str(v) if isinstance(v, Decimal) else v) for k, v in detail.items() if k != "score"}), final, final == top))
        return _results(cur, debate_id)


def results(conn: psycopg.Connection, debate_id: int) -> list[dict]:
    with conn.cursor(row_factory=tuple_row) as cur:
        return _results(cur, debate_id)


def _results(cur: psycopg.Cursor, debate_id: int) -> list[dict]:
    return [{"user_id": u, "vote": v, "votes": n, "ai": a, "detail": d, "final": f, "winner": w} for u, v, n, a, d, f, w in cur.execute(
        """SELECT user_id, vote_score, vote_count, ai_score, ai_detail, final_score, winner FROM debate_results r WHERE debate_id = %s
           AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = r.user_id) ORDER BY final_score DESC, user_id""", (debate_id,)).fetchall()]


def set_results_message(conn: psycopg.Connection, debate_id: int, message_id: int) -> bool:
    with conn.transaction():
        return conn.execute("UPDATE debates SET results_message_id = %s WHERE id = %s AND status = 'closed' AND results_message_id IS NULL", (message_id, debate_id)).rowcount == 1
