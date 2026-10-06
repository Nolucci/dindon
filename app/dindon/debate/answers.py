"""Dindon's first answers, without the Internet, and what the participants say of them (docs/DEBAT.md, « Répondre d'abord, chercher ensuite »).

* A claim that Dindon is **certain** is false gets an answer under the message (`debate_answers`, written with the reading, see claims.finish_reading). The answer comes from the local model
  alone, has **no source**, and says so. A claim that it is certain is true is noted and nothing is said. A claim that it is not sure of goes on the Internet, as before.
* Under the answer, any participant presses **Valide** or **Invalide** (one vote each, changeable). **More Invalide than Valide**: Dindon looks on the Internet, once (`searches_due`), with the
  budget and the trusted sources of every check, and writes the result in its own message, whatever it is. **More Valide, or as many**: nothing more is searched.
* The message that Dindon posts is a row of `debate_corrections` (posted once, tried again if it failed, taken back when the answer goes, and counted in the same hourly limit).
* Never a person who asked not to be recorded: their votes are not counted, their claims are not answered.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import tuple_row

from dindon.clock import utc_now
from dindon.debate import claims as claims_mod

CHOICES = ("valid", "invalid")
ANSWER_MAX_AGE_MINUTES = 30        # an answer that was not posted within this long of being found is not posted any more: the conversation has moved on
ANSWER_ATTEMPTS = claims_mod.CORRECTION_ATTEMPTS
VOTE_REFUSALS = ("unknown", "not_open", "blocked", "choice", "searched")


class VoteRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DueAnswer:
    answer_id: int
    debate_id: int
    thread_id: int
    message_id: int                  # the message that Dindon answers
    claim: str
    answer: str
    correction_id: int | None        # the row that reserved it, if a first attempt failed


@dataclass(frozen=True)
class DueSearch:
    answer_id: int
    debate_id: int
    message_id: int
    author_id: int
    claim: str
    said: str
    query: str


@dataclass(frozen=True)
class AnswerView:
    """An answer as it is on Discord now: its message, and what the participants think of it."""
    answer_id: int
    debate_id: int
    debate_open: bool
    thread_id: int
    message_id: int
    posted_message_id: int
    claim: str
    answer: str
    valid: int
    invalid: int
    searched: bool
    claim_id: int | None


_NOT_BLOCKED = "NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = {col})"


def posts_due(conn: psycopg.Connection, now: datetime | None = None, limit: int = 5) -> list[DueAnswer]:
    """The answers that Dindon is to post: certain that a claim is false, in a running debate that checks its claims, recently, not posted yet (oldest first)."""
    now = now or utc_now()
    with conn.cursor(row_factory=tuple_row) as cur:
        return [DueAnswer(*r) for r in cur.execute(
            f"""SELECT a.id, a.debate_id, d.thread_id, a.message_id, a.claim, a.answer, k.id
                FROM debate_answers a
                JOIN debates d ON d.id = a.debate_id AND d.status = 'open' AND d.verify AND d.thread_id IS NOT NULL
                LEFT JOIN debate_corrections k ON k.answer_id = a.id
                WHERE a.verdict = 'false' AND a.created_at > %s - make_interval(mins => %s)
                  AND (k.id IS NULL OR (k.posted_message_id IS NULL AND k.retracted_at IS NULL AND k.attempts < %s))
                  AND {_NOT_BLOCKED.format(col='a.author_id')}
                ORDER BY a.created_at, a.id LIMIT %s""", (now, ANSWER_MAX_AGE_MINUTES, ANSWER_ATTEMPTS, limit)).fetchall()]


def reserve_post(conn: psycopg.Connection, due: DueAnswer, now: datetime | None = None) -> int:
    """Notes that an answer is being posted (once, whatever happens), and counts the attempt. Returns the number of the row."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        return cur.execute(
            """INSERT INTO debate_corrections (debate_id, claim_id, answer_id, thread_id, reply_to_message_id, attempts, created_at) VALUES (%s, NULL, %s, %s, %s, 1, %s)
               ON CONFLICT (answer_id) WHERE answer_id IS NOT NULL DO UPDATE SET attempts = debate_corrections.attempts + 1 RETURNING id""",
            (due.debate_id, due.answer_id, due.thread_id, due.message_id, now)).fetchone()[0]


def counts(conn: psycopg.Connection, answer_id: int) -> tuple[int, int]:
    """(valid, invalid) votes: only people who are still recorded count."""
    with conn.cursor(row_factory=tuple_row) as cur:                  # (a tuple whatever the connection hands out: the interface's connections give named rows)
        row = cur.execute(
            f"""SELECT count(*) FILTER (WHERE choice = 'valid'), count(*) FILTER (WHERE choice = 'invalid') FROM debate_answer_votes v
                WHERE v.answer_id = %s AND {_NOT_BLOCKED.format(col='v.user_id')}""", (answer_id,)).fetchone()
    return row[0], row[1]


def view(conn: psycopg.Connection, answer_id: int) -> AnswerView | None:
    """The answer as it stands on Discord: None if it is gone, or was never posted."""
    with conn.cursor(row_factory=tuple_row) as cur:
        row = cur.execute(
            """SELECT a.id, a.debate_id, d.status = 'open', k.thread_id, a.message_id, k.posted_message_id, a.claim, a.answer, a.searched_at IS NOT NULL, a.claim_id
               FROM debate_answers a JOIN debates d ON d.id = a.debate_id
               JOIN debate_corrections k ON k.answer_id = a.id AND k.posted_message_id IS NOT NULL AND k.retracted_at IS NULL
               WHERE a.id = %s AND a.verdict = 'false'""", (answer_id,)).fetchone()
        if row is None:
            return None
    valid, invalid = counts(conn, answer_id)
    return AnswerView(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], valid, invalid, row[8], row[9])


def vote(conn: psycopg.Connection, answer_id: int, user_id: int, choice: str, now: datetime | None = None) -> str:
    """A participant judges Dindon's answer: 'recorded' (the first time), 'changed' or 'unchanged'. Refused: 'choice', 'unknown' (gone, or not posted), 'not_open' (the debate is over),
    'searched' (Dindon already looked on the Internet), 'blocked' (asked not to be recorded)."""
    if choice not in CHOICES:
        raise VoteRefused("choice")
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        found = cur.execute(
            """SELECT d.status, a.searched_at IS NOT NULL FROM debate_answers a JOIN debates d ON d.id = a.debate_id
               JOIN debate_corrections k ON k.answer_id = a.id AND k.posted_message_id IS NOT NULL AND k.retracted_at IS NULL
               WHERE a.id = %s AND a.verdict = 'false' FOR UPDATE OF a""", (answer_id,)).fetchone()
        if found is None:
            raise VoteRefused("unknown")
        if found[0] != "open":
            raise VoteRefused("not_open")
        if found[1]:
            raise VoteRefused("searched")
        if cur.execute("SELECT 1 FROM privacy_subjects WHERE user_id = %s", (user_id,)).fetchone():
            raise VoteRefused("blocked")
        before = cur.execute("SELECT choice FROM debate_answer_votes WHERE answer_id = %s AND user_id = %s", (answer_id, user_id)).fetchone()
        if before is not None and before[0] == choice:
            return "unchanged"
        cur.execute("""INSERT INTO debate_answer_votes (answer_id, user_id, choice, voted_at) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (answer_id, user_id) DO UPDATE SET choice = excluded.choice, voted_at = excluded.voted_at""", (answer_id, user_id, choice, now))
        return "recorded" if before is None else "changed"


def searches_due(conn: psycopg.Connection, limit: int = 3) -> list[DueSearch]:
    """The answers that the participants rejected: more **Invalide** than **Valide** (people who are still recorded), in a running debate, not searched yet. Equal, or more Valide: nothing."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return [DueSearch(*r) for r in cur.execute(
            f"""SELECT a.id, a.debate_id, a.message_id, a.author_id, a.claim, a.said, a.query
                FROM debate_answers a JOIN debates d ON d.id = a.debate_id AND d.status = 'open'
                JOIN debate_corrections k ON k.answer_id = a.id AND k.posted_message_id IS NOT NULL AND k.retracted_at IS NULL
                WHERE a.verdict = 'false' AND a.searched_at IS NULL AND {_NOT_BLOCKED.format(col='a.author_id')}
                  AND (SELECT count(*) FROM debate_answer_votes v WHERE v.answer_id = a.id AND v.choice = 'invalid' AND {_NOT_BLOCKED.format(col='v.user_id')})
                    > (SELECT count(*) FROM debate_answer_votes v WHERE v.answer_id = a.id AND v.choice = 'valid' AND {_NOT_BLOCKED.format(col='v.user_id')})
                ORDER BY a.id LIMIT %s""", (limit,)).fetchall()]


def finish_search(conn: psycopg.Connection, due: DueSearch, result: claims_mod.ClaimResult | None, now: datetime | None = None) -> bool:
    """Records what the search found (`None`: it could not be made: no search service) and that it was made. The result is a claim checked like any other, with its sources. False, and
    nothing is written, if the answer is gone (the message was edited or deleted meanwhile) or was already searched."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        if cur.execute("SELECT 1 FROM debate_answers WHERE id = %s AND searched_at IS NULL FOR UPDATE", (due.answer_id,)).fetchone() is None:
            return False
        claim_id = claims_mod.insert_result(cur, due.debate_id, due.message_id, due.author_id, result, now) if result is not None else None
        cur.execute("UPDATE debate_answers SET searched_at = %s, claim_id = %s WHERE id = %s", (now, claim_id, due.answer_id))
    return True


@dataclass(frozen=True)
class ToShow:
    """A searched answer whose message on Discord does not show the result yet."""
    answer_id: int
    debate_id: int
    thread_id: int
    posted_message_id: int
    message_id: int
    claim: str
    answer: str
    verdict: str | None              # what the search found: confirmed / contradicted / ... ; None: no search could be made
    period: str | None
    claim_id: int | None


def to_show(conn: psycopg.Connection, limit: int = 5) -> list[ToShow]:
    with conn.cursor(row_factory=tuple_row) as cur:
        return [ToShow(*r) for r in cur.execute(
            """SELECT a.id, a.debate_id, k.thread_id, k.posted_message_id, a.message_id, a.claim, a.answer, c.verdict, c.period, c.id
               FROM debate_answers a JOIN debate_corrections k ON k.answer_id = a.id AND k.posted_message_id IS NOT NULL AND k.retracted_at IS NULL
               LEFT JOIN debate_claims c ON c.id = a.claim_id
               WHERE a.searched_at IS NOT NULL AND a.shown_at IS NULL ORDER BY a.id LIMIT %s""", (limit,)).fetchall()]


def mark_shown(conn: psycopg.Connection, answer_id: int, now: datetime | None = None) -> None:
    with conn.transaction():
        conn.execute("UPDATE debate_answers SET shown_at = %s WHERE id = %s AND shown_at IS NULL", (now or utc_now(), answer_id))


def of_debate(conn: psycopg.Connection, debate_id: int) -> list[dict]:
    """What Dindon answered in a debate, for its statistics and the interface: each answer with the judgement of the participants. Never people who asked not to be recorded."""
    with conn.cursor(row_factory=tuple_row) as cur:
        rows = cur.execute(
            f"""SELECT a.id, a.message_id, a.author_id, a.claim, a.verdict, a.answer, a.searched_at IS NOT NULL, c.verdict, k.posted_message_id IS NOT NULL
                FROM debate_answers a LEFT JOIN debate_claims c ON c.id = a.claim_id LEFT JOIN debate_corrections k ON k.answer_id = a.id AND k.retracted_at IS NULL
                WHERE a.debate_id = %s AND {_NOT_BLOCKED.format(col='a.author_id')} ORDER BY a.id""", (debate_id,)).fetchall()
    found = []
    for answer_id, message_id, author_id, claim, verdict, answer, searched, found_verdict, posted in rows:
        valid, invalid = counts(conn, answer_id)
        found.append({"id": answer_id, "message_id": str(message_id), "author_id": str(author_id), "claim": claim, "verdict": verdict, "answer": answer, "posted": bool(posted),
                      "valid": valid, "invalid": invalid, "searched": searched, "found": found_verdict})
    return found
