"""What is kept of the claims that were checked in a debate, and the queue of messages that wait to be read (docs/DEBAT.md).

* **The queue is the database**: a counted message (`debate_messages`) whose `read_at` is null waits to be read, in the order they were written. Nothing is lost by a restart; a message
  that is edited becomes unread again and loses its claims (ingest/loader.py); a message that is deleted loses them too. The text of a message is read from `messages` (where the ingestion
  put it), never copied here.
* **A result is written whole or not at all**: the claims, their sources and the `read_at` of the message go in one transaction, and only if the message still says what was read (an edit
  or a deletion during the minutes that a check takes cancels the result).
* **Nothing is kept about what was not checked**: an opinion, a question, a claim about a private person leaves no trace. A page that settled nothing leaves none either.
* Never a person who asked not to be recorded (`privacy_subjects`): their messages are not read and their claims are not shown.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import tuple_row

from dindon.clock import utc_now
from dindon.debate import rules

VERDICTS = ("confirmed", "contradicted", "partly", "disputed", "unverifiable")
MAX_CHECKS_PER_HOUR = 20            # claims checked per debate and per hour: what a debate may ask of the Internet and of the local model, however chatty it is


@dataclass(frozen=True)
class Evidence:
    """A page that grounds a verdict: trusted, and quoted word for word (verified)."""
    url: str
    title: str
    tier: str                       # official | checker
    stance: str                     # supports | contradicts | partly
    quote: str
    page_period: str | None
    via: str | None
    sha256: str


@dataclass(frozen=True)
class ClaimResult:
    claim: str
    said: str
    verdict: str
    reason: str | None = None       # for `unverifiable`: no_source | error
    period: str | None = None
    queries: int = 0
    pages: int = 0
    model: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class AnswerFound:
    """Dindon's own answer to a claim, from its local model and without the Internet (debate/local.py): `true` (it is certain that the claim is exact: nothing is said) or `false` (certain
    that it is not: `answer` is what it says). `query` is the neutral phrase that is searched if the participants judge the answer invalid."""
    claim: str
    said: str
    query: str
    verdict: str
    answer: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class Considered:
    """What came of one message when Dindon answers first: the claims that it answered itself, and the claims that it could not answer and checked on the Internet."""
    answers: tuple[AnswerFound, ...] = ()
    results: tuple[ClaimResult, ...] = ()


@dataclass(frozen=True)
class Unread:
    debate_id: int
    message_id: int
    author_id: int
    text: str


GRACE_MINUTES = 5                  # a debate that just ended keeps reading what is left for this long, so that its statistics are complete (then they are posted as they are)


def next_unread(conn: psycopg.Connection, limit: int = 20, now: datetime | None = None) -> list[Unread]:
    """The oldest messages of running debates (and of the one that ended less than 10 minutes ago, whose statistics wait for it) that were not read yet, whose text the ingestion has stored."""
    now = now or utc_now()
    with conn.cursor(row_factory=tuple_row) as cur:
        return [Unread(*r) for r in cur.execute(
            """SELECT dm.debate_id, dm.message_id, dm.author_id, m.content
               FROM debate_messages dm
               JOIN debates d ON d.id = dm.debate_id AND (d.status = 'open' OR (d.status = 'closed' AND d.final_message_id IS NULL AND d.closed_at > %s - interval '10 minutes'))
               JOIN messages m ON m.id = dm.message_id
               WHERE dm.read_at IS NULL AND m.content IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = dm.author_id)
               ORDER BY dm.message_id LIMIT %s""", (now, limit)).fetchall()]


STALE_MINUTES = 60                 # a message that waited this long is not read any more: in a busy channel the queue must not run for ever behind the conversation


def expire_unread(conn: psycopg.Connection, now: datetime | None = None) -> int:
    """Marks as read, without reading them, the messages that waited too long (the checks are for what is being said now). Returns how many."""
    now = now or utc_now()
    with conn.transaction():
        return conn.execute("UPDATE debate_messages SET read_at = %s WHERE read_at IS NULL AND sent_at < %s - make_interval(mins => %s)", (now, now, STALE_MINUTES)).rowcount


def unread_for(conn: psycopg.Connection, debate_id: int) -> int:
    """How many messages of this debate are still to be read (those of people who asked not to be recorded are never read, and are not counted)."""
    return conn.execute("""SELECT count(*) FROM debate_messages dm WHERE dm.debate_id = %s AND dm.read_at IS NULL
                           AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = dm.author_id)""", (debate_id,)).fetchone()[0]


def unread_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM debate_messages dm JOIN debates d ON d.id = dm.debate_id AND d.status = 'open' WHERE dm.read_at IS NULL").fetchone()[0]


def checks_last_hour(conn: psycopg.Connection, debate_id: int, now: datetime | None = None) -> int:
    now = now or utc_now()
    return conn.execute("SELECT count(*) FROM debate_claims WHERE debate_id = %s AND checked_at > %s - interval '1 hour'", (debate_id, now)).fetchone()[0]


def insert_result(cur: psycopg.Cursor, debate_id: int, message_id: int, author_id: int, result: ClaimResult, now: datetime) -> int:
    """Writes one checked claim with the sources behind it. Returns its number."""
    claim_id = cur.execute(
        """INSERT INTO debate_claims (debate_id, message_id, author_id, claim, said, verdict, reason, period, queries, pages, model, checked_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (debate_id, message_id, author_id, result.claim, result.said, result.verdict, result.reason, result.period, result.queries, result.pages, result.model, now)).fetchone()[0]
    for e in result.evidence:
        cur.execute(
            """INSERT INTO debate_sources (claim_id, url, title, tier, stance, quote, page_period, via, sha256, fetched_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (claim_id, e.url, e.title[:300] or None, e.tier, e.stance, e.quote, e.page_period, e.via, e.sha256, now))
    return claim_id


def finish_reading(conn: psycopg.Connection, unread: Unread, claims: list[ClaimResult], now: datetime | None = None, answers: tuple[AnswerFound, ...] | list[AnswerFound] = ()) -> bool:
    """Records what was found in a message (possibly nothing) and marks it read. False, and nothing is written, if the message was edited, deleted or already read since it was
    taken, or if its author stopped being recorded meanwhile. `answers`: what Dindon answered itself, without the Internet (debate/answers.py)."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        current = cur.execute("SELECT content FROM messages WHERE id = %s", (unread.message_id,)).fetchone()
        if current is None or current[0] != unread.text:
            return False
        if not cur.execute("UPDATE debate_messages SET read_at = %s WHERE debate_id = %s AND message_id = %s AND read_at IS NULL",
                           (now, unread.debate_id, unread.message_id)).rowcount:
            return False
        if cur.execute("SELECT 1 FROM privacy_subjects WHERE user_id = %s", (unread.author_id,)).fetchone():
            return True                                                                   # read, and nothing kept of somebody who asked not to be recorded
        for result in claims:
            insert_result(cur, unread.debate_id, unread.message_id, unread.author_id, result, now)
        for found in answers:
            cur.execute(
                """INSERT INTO debate_answers (debate_id, message_id, author_id, claim, said, query, verdict, answer, model, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (unread.debate_id, unread.message_id, unread.author_id, found.claim, found.said, found.query, found.verdict, found.answer, found.model, now))
    return True


def claims_of(conn: psycopg.Connection, debate_id: int) -> list[dict]:
    """What was checked in a debate, each claim with its sources (for the owner's report; never people who asked not to be recorded)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        rows = cur.execute(
            """SELECT c.id, c.message_id, c.author_id, c.claim, c.said, c.verdict, c.reason, c.period, c.queries, c.pages, c.model, c.checked_at
               FROM debate_claims c WHERE c.debate_id = %s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = c.author_id) ORDER BY c.id""", (debate_id,)).fetchall()
        found = []
        for cid, message_id, author_id, claim, said, verdict, reason, period, queries, pages, model, checked_at in rows:
            sources = cur.execute("SELECT url, title, tier, stance, quote, page_period, via FROM debate_sources WHERE claim_id = %s ORDER BY id", (cid,)).fetchall()
            found.append({"id": cid, "message_id": str(message_id), "author_id": str(author_id), "claim": claim, "said": said, "verdict": verdict, "reason": reason, "period": period,
                          "queries": queries, "pages": pages, "model": model, "checked_at": checked_at.isoformat(),
                          "sources": [{"url": u, "title": t, "tier": tier, "stance": s, "quote": q, "page_period": p, "via": v} for u, t, tier, s, q, p, v in sources]})
    return found


def parity(conn: psycopg.Connection, debate_id: int) -> dict:
    """How many claims of each verdict were checked, by the position of the person who made them (their last, `none` if they took none). Where bias would show: the same
    standard for every side means that the proportions do not depend on the side."""
    table: dict[str, dict[str, int]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        for position, verdict, count in cur.execute(
                """SELECT COALESCE(p.position, 'none'), c.verdict, count(*) FROM debate_claims c
                   LEFT JOIN LATERAL (SELECT position FROM debate_positions WHERE debate_id = c.debate_id AND user_id = c.author_id ORDER BY id DESC LIMIT 1) p ON true
                   WHERE c.debate_id = %s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = c.author_id) GROUP BY 1, 2""", (debate_id,)).fetchall():
            table.setdefault(position, dict.fromkeys(VERDICTS, 0))[verdict] = count
    return {position: {**counts, "total": sum(counts.values())} for position, counts in sorted(table.items(), key=lambda item: ([*rules.POSITIONS, "none"].index(item[0])))}


# --- the corrections posted in public (docs/DEBAT.md, « Corrections publiques ») ------------------------------------------------------------------------

CORRECTION_MAX_AGE_MINUTES = 30      # a claim checked longer ago than this is not corrected any more: a late correction in a conversation that has moved on does more harm than good
CORRECTION_SPACING_SECONDS = 20      # between two corrections in the same debate
CORRECTIONS_PER_HOUR = 10            # at most, per debate
CORRECTION_ATTEMPTS = 5


@dataclass(frozen=True)
class DueCorrection:
    claim_id: int
    debate_id: int
    thread_id: int
    message_id: int                  # the message that the correction answers
    claim: str
    period: str | None
    correction_id: int | None        # the row that reserved it, if a first attempt failed


def corrections_due(conn: psycopg.Connection, now: datetime | None = None, limit: int = 5) -> list[DueCorrection]:
    """The claims that trusted sources contradicted, in running debates, recently, and that were not corrected yet (oldest first). Never a person who asked not to be recorded."""
    now = now or utc_now()
    with conn.cursor(row_factory=tuple_row) as cur:
        return [DueCorrection(*r) for r in cur.execute(
            """SELECT c.id, c.debate_id, d.thread_id, c.message_id, c.claim, c.period, k.id
               FROM debate_claims c
               JOIN debates d ON d.id = c.debate_id AND d.status = 'open' AND d.verify AND d.thread_id IS NOT NULL
               LEFT JOIN debate_corrections k ON k.claim_id = c.id
               WHERE c.verdict = 'contradicted' AND c.checked_at > %s - make_interval(mins => %s)
                 AND NOT EXISTS (SELECT 1 FROM debate_answers a WHERE a.claim_id = c.id)
                 AND (k.id IS NULL OR (k.posted_message_id IS NULL AND k.retracted_at IS NULL AND k.attempts < %s))
                 AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = c.author_id)
               ORDER BY c.checked_at, c.id LIMIT %s""", (now, CORRECTION_MAX_AGE_MINUTES, CORRECTION_ATTEMPTS, limit)).fetchall()]


def claim_evidence(conn: psycopg.Connection, claim_id: int, stance: str = "contradicts") -> list[Evidence]:
    with conn.cursor(row_factory=tuple_row) as cur:
        return [Evidence(u, t or "", tier, st, q, p, v, h) for u, t, tier, st, q, p, v, h in cur.execute(
            "SELECT url, title, tier, stance, quote, page_period, via, sha256 FROM debate_sources WHERE claim_id = %s AND stance = %s ORDER BY (tier = 'official') DESC, id",
            (claim_id, stance)).fetchall()]


def corrections_recent(conn: psycopg.Connection, debate_id: int, now: datetime | None = None) -> tuple[int, datetime | None]:
    """(how many corrections were posted in this debate in the last hour, when the last one was)."""
    now = now or utc_now()
    row = conn.execute("SELECT count(*) FILTER (WHERE posted_at > %s - interval '1 hour'), max(posted_at) FROM debate_corrections WHERE debate_id = %s AND posted_message_id IS NOT NULL",
                       (now, debate_id)).fetchone()
    return row[0], row[1]


def reserve_correction(conn: psycopg.Connection, due: DueCorrection, now: datetime | None = None) -> int:
    """Notes that a correction is being posted (once per claim, whatever happens), and counts the attempt. Returns its number."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        row = cur.execute(
            """INSERT INTO debate_corrections (debate_id, claim_id, thread_id, reply_to_message_id, attempts, created_at) VALUES (%s, %s, %s, %s, 1, %s)
               ON CONFLICT (claim_id) WHERE claim_id IS NOT NULL DO UPDATE SET attempts = debate_corrections.attempts + 1 RETURNING id""",
            (due.debate_id, due.claim_id, due.thread_id, due.message_id, now)).fetchone()
        return row[0]


def set_correction_posted(conn: psycopg.Connection, correction_id: int, message_id: int, now: datetime | None = None) -> None:
    with conn.transaction():
        conn.execute("UPDATE debate_corrections SET posted_message_id = %s, posted_at = %s WHERE id = %s AND posted_message_id IS NULL", (message_id, now or utc_now(), correction_id))


def give_up_correction(conn: psycopg.Connection, correction_id: int, now: datetime | None = None) -> None:
    """Nothing more is tried for it (posting kept failing)."""
    with conn.transaction():
        conn.execute("UPDATE debate_corrections SET retracted_at = %s WHERE id = %s AND posted_message_id IS NULL", (now or utc_now(), correction_id))


def corrections_to_retract(conn: psycopg.Connection) -> list[tuple[int, int, int]]:
    """(correction, thread, message on Discord) of the corrections whose claim is gone (its message was edited or deleted, its author erased): they are taken back."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return cur.execute("SELECT id, thread_id, posted_message_id FROM debate_corrections WHERE claim_id IS NULL AND answer_id IS NULL AND posted_message_id IS NOT NULL AND retracted_at IS NULL ORDER BY id LIMIT 20").fetchall()


def mark_retracted(conn: psycopg.Connection, correction_id: int, now: datetime | None = None) -> None:
    with conn.transaction():
        conn.execute("UPDATE debate_corrections SET retracted_at = %s WHERE id = %s", (now or utc_now(), correction_id))
