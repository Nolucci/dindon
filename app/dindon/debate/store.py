"""The state of the debates in the database: opening, positions, messages, the end. See docs/regles-du-bot.md.

Everything here takes the time as an argument (`now`), so that a test can make a debate last a week in a millisecond; the engine passes the real clock. No function talks to Discord: they answer
what the database says, and the engine does what has to be done on Discord.

* A debate has **no time limit**. It is `preparing` (written, its place on Discord not made yet), `open`, then `closed`: by the button (`ended`), by itself after a silence (`silence`), with nobody
  having taken part (`no_participants`), or because it could not be set up (`failed`). Its place is a thread, or the channel itself: `thread_id` holds the one where its messages are written.
* Every change that depends on the current state locks the debate's row first, so that two events at the same moment (two clicks) are handled one after the other.
* The people who asked not to be recorded (`privacy_subjects`) are refused here, whatever the caller did: they cannot take a position or be counted as having spoken, and they are not among the
  participants.
* If the bot stops between a change of state and what it must announce on Discord, `unannounced` says what is left to post.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from dindon import locks
from dindon.clock import utc_now
from dindon.debate import rules


class DebateRefused(Exception):
    """A request that the rules refuse. `code` says why (the engine turns it into a sentence for the person)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Debate:
    id: int
    guild_id: int
    channel_id: int                    # the channel where the command was used
    thread_id: int | None              # where the messages of the debate are written: its thread, or the channel itself (`in_thread` false). Null while 'preparing'
    topic: str
    context: str | None
    created_by: int | None
    status: str
    close_reason: str | None
    in_thread: bool
    verify: bool                       # the claims of this debate are checked (when the owner has switched the checks on)
    axis: dict | None                  # the axis it was opened from: {code, name, for, against} as shown when it opened (the poles are the answers); None for a subject written by the person
    quiet_seconds: int | None          # it ends by itself after this long without a message
    question_message_id: int | None    # the launch message, with the buttons
    start_message_id: int | None       # what is written after it belongs to the debate
    final_message_id: int | None
    created_at: datetime
    started_at: datetime | None
    last_activity_at: datetime | None
    closed_at: datetime | None


_COLUMNS = ", ".join(f.name for f in fields(Debate))
OPEN = ("open",)


@dataclass(frozen=True)
class Axis:
    """An axis of Dindon (the table `axes`), as the popup offers it: its question, and its two poles that people choose between."""

    code: str
    name: str
    question: str
    negative_pole: str                 # -1: becomes the first answer
    positive_pole: str                 # +1: becomes the last answer

    def snapshot(self) -> dict:
        """What a debate keeps of it (the axes may change later without changing a debate that is running)."""
        return {"code": self.code, "name": self.name, "for": self.negative_pole, "against": self.positive_pole}


MAX_AXES_OFFERED = 25                  # what a list in a popup can hold


def _row(row) -> Debate | None:
    return None if row is None else Debate(*row)


def _blocked(cur: psycopg.Cursor, user_id: int) -> bool:
    return cur.execute("SELECT 1 FROM privacy_subjects WHERE user_id = %s", (user_id,)).fetchone() is not None


def _locked(cur: psycopg.Cursor, debate_id: int) -> Debate:
    debate = _row(cur.execute(f"SELECT {_COLUMNS} FROM debates WHERE id = %s FOR UPDATE", (debate_id,)).fetchone())
    if debate is None:
        raise DebateRefused("unknown")
    return debate


# --- reading ----------------------------------------------------------------------------------------------------------


def offered_axes(conn: psycopg.Connection) -> list[Axis]:
    """The axes that the popup offers (the active ones, in their order, at most 25): only those whose question can be a subject (3 to 200 characters)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        rows = cur.execute("SELECT code, name, question, negative_pole, positive_pole FROM axes WHERE is_active ORDER BY position, id").fetchall()
    return [Axis(*r) for r in rows if rules.clean_topic(r[2]) is not None][:MAX_AXES_OFFERED]


def axis(conn: psycopg.Connection, code: str) -> Axis | None:
    """An axis that is still offered, by its code (what the person chose in the popup may have been switched off since)."""
    return next((a for a in offered_axes(conn) if a.code == code), None)


def get(conn: psycopg.Connection, debate_id: int) -> Debate | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        return _row(cur.execute(f"SELECT {_COLUMNS} FROM debates WHERE id = %s", (debate_id,)).fetchone())


def by_thread(conn: psycopg.Connection, thread_id: int) -> Debate | None:
    """The debate of a place (a thread, or a channel): the latest one, which is the open one if there is one (a channel hosts debates one after another)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return _row(cur.execute(f"SELECT {_COLUMNS} FROM debates WHERE thread_id = %s ORDER BY id DESC LIMIT 1", (thread_id,)).fetchone())


def active(conn: psycopg.Connection) -> list[Debate]:
    """The debates that are not closed: what the engine loads at its start, to go on with them."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return [Debate(*r) for r in cur.execute(f"SELECT {_COLUMNS} FROM debates WHERE status <> 'closed' ORDER BY id").fetchall()]


def participants(conn: psycopg.Connection, debate_id: int) -> set[int]:
    """Who took part: wrote in the debate or took a position. Never someone who asked not to be recorded."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return _participants(cur, debate_id)


def _participants(cur: psycopg.Cursor, debate_id: int) -> set[int]:
    return {r[0] for r in cur.execute(
        """SELECT user_id FROM (SELECT author_id AS user_id FROM debate_messages WHERE debate_id = %(d)s
                                UNION SELECT user_id FROM debate_positions WHERE debate_id = %(d)s) p
           WHERE NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = p.user_id)""", {"d": debate_id}).fetchall()}


def positions(conn: psycopg.Connection, debate_id: int) -> dict[int, str]:
    """The position of each person now (the last they took)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return _positions(cur, debate_id)


def _positions(cur: psycopg.Cursor, debate_id: int) -> dict[int, str]:
    return dict(cur.execute(
        """SELECT DISTINCT ON (p.user_id) p.user_id, p.position FROM debate_positions p
           WHERE p.debate_id = %s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = p.user_id)
           ORDER BY p.user_id, p.id DESC""", (debate_id,)).fetchall())


def last_seen_message(conn: psycopg.Connection, debate_id: int) -> int:
    """Where to go on reading the place of a debate after a gap: just after the last message that was counted, or else just after the launch message (0 if it is not known)."""
    row = conn.execute("SELECT COALESCE((SELECT max(message_id) FROM debate_messages WHERE debate_id = d.id), d.start_message_id, 0) FROM debates d WHERE d.id = %s", (debate_id,)).fetchone()
    return int(row[0]) if row else 0


def position_counts(conn: psycopg.Connection, debate_id: int) -> dict[str, int]:
    """How many people are for, not sure, against (shown on the launch message)."""
    counts = dict.fromkeys(rules.POSITIONS, 0)
    for position in positions(conn, debate_id).values():
        counts[position] += 1
    return counts


def summary(conn: psycopg.Connection, debate_id: int) -> dict:
    """The figures of a debate: who took part, how many messages were counted, the positions now."""
    with conn.cursor(row_factory=tuple_row) as cur:
        messages = cur.execute(
            """SELECT count(*) FROM debate_messages m WHERE m.debate_id = %s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = m.author_id)""",
            (debate_id,)).fetchone()[0]
        counts = dict.fromkeys(rules.POSITIONS, 0)
        for position in _positions(cur, debate_id).values():
            counts[position] += 1
        return {"participants": len(_participants(cur, debate_id)), "messages": messages, "positions": counts}


# --- opening ----------------------------------------------------------------------------------------------------------


def check_can_start(conn: psycopg.Connection, *, guild_id: int, created_by: int, max_per_person: int = rules.MAX_OPEN_PER_PERSON,
                    max_per_server: int = rules.MAX_OPEN_PER_SERVER) -> None:
    """Refuses ('blocked', 'person_limit', 'server_limit') before anything is shown or written: what can be known before the person has filled the popup."""
    with conn.cursor(row_factory=tuple_row) as cur:
        _check_limits(cur, guild_id, created_by, max_per_person, max_per_server)


def _check_limits(cur: psycopg.Cursor, guild_id: int, created_by: int, max_per_person: int, max_per_server: int) -> None:
    if _blocked(cur, created_by):                         # a debate counts who said what: not for someone who asked not to be recorded
        raise DebateRefused("blocked")
    if cur.execute("SELECT count(*) FROM debates WHERE created_by = %s AND status <> 'closed'", (created_by,)).fetchone()[0] >= max_per_person:
        raise DebateRefused("person_limit")
    if cur.execute("SELECT count(*) FROM debates WHERE guild_id = %s AND status <> 'closed'", (guild_id,)).fetchone()[0] >= max_per_server:
        raise DebateRefused("server_limit")


def start(conn: psycopg.Connection, *, guild_id: int, channel_id: int, topic: str, created_by: int, context: str | None = None, in_thread: bool = True, verify: bool = True,
          axis: Axis | None = None, quiet_seconds: int = rules.DEFAULT_QUIET, now: datetime | None = None, max_per_person: int = rules.MAX_OPEN_PER_PERSON,
          max_per_server: int = rules.MAX_OPEN_PER_SERVER) -> Debate:
    """Writes a debate in the state 'preparing': its place on Discord is not made yet (`attach_thread` opens it once it is). Refused ('topic', 'context', 'quiet', 'blocked',
    'person_limit', 'server_limit', 'channel_busy') without writing anything. `in_thread` false: the debate takes place in the channel, and only one can be open there.
    `axis`: the axis whose question this debate asks (`topic` is then that question, and the answers are its poles)."""
    cleaned = rules.clean_topic(topic)
    if cleaned is None:
        raise DebateRefused("topic")
    if context and rules.clean_context(context) is None:
        raise DebateRefused("context")
    if quiet_seconds not in rules.QUIET_CHOICES:
        raise DebateRefused("quiet")
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DEBATE,))
        _check_limits(cur, guild_id, created_by, max_per_person, max_per_server)
        if not in_thread and cur.execute("SELECT 1 FROM debates WHERE channel_id = %s AND NOT in_thread AND status <> 'closed'", (channel_id,)).fetchone():
            raise DebateRefused("channel_busy")
        return _row(cur.execute(
            f"""INSERT INTO debates (guild_id, channel_id, topic, context, created_by, in_thread, verify, axis, quiet_seconds, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}""",
            (guild_id, channel_id, cleaned, rules.clean_context(context) if context else None, created_by, in_thread, verify,
             Jsonb(axis.snapshot()) if axis else None, quiet_seconds, now)).fetchone())


def attach_thread(conn: psycopg.Connection, debate_id: int, *, thread_id: int, question_message_id: int, now: datetime | None = None) -> Debate:
    """The place of the debate (its thread, or the channel) and its launch message exist: the debate opens. What is written after the launch message belongs to it."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        debate = _locked(cur, debate_id)
        if debate.status != "preparing":
            raise DebateRefused("not_preparing")
        return _row(cur.execute(
            f"""UPDATE debates SET status = 'open', thread_id = %s, question_message_id = %s, start_message_id = %s, started_at = %s, last_activity_at = %s
                WHERE id = %s RETURNING {_COLUMNS}""", (thread_id, question_message_id, question_message_id, now, now, debate_id)).fetchone())


def fail(conn: psycopg.Connection, debate_id: int, now: datetime | None = None) -> Debate | None:
    """The debate could not be set up on Discord (no thread, no permission): it is closed without anything to announce."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        debate = _locked(cur, debate_id)
        if debate.status == "closed":
            return debate
        return _close(cur, debate, rules.FAILED, now)


# --- what happens while it is open ------------------------------------------------------------------------------------


def record_message(conn: psycopg.Connection, debate_id: int, *, message_id: int, author_id: int, sent_at: datetime, to_read: bool = False) -> bool:
    """A message was written in the debate. True if it is new and counts; False if it is a repeat, the debate is not open, or the author asked not to be recorded.
    `to_read`: it waits to be read for claims (debate/claims.py) if this debate checks its claims; otherwise it is marked read at once. It counts as activity: the silence starts again."""
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        added = cur.execute(
            """INSERT INTO debate_messages (debate_id, message_id, author_id, sent_at, read_at)
               SELECT d.id, %(m)s, %(a)s, %(t)s, CASE WHEN %(r)s AND d.verify THEN NULL ELSE %(t)s END FROM debates d
               WHERE d.id = %(d)s AND d.status = 'open' AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = %(a)s)
               ON CONFLICT DO NOTHING""", {"d": debate_id, "m": message_id, "a": author_id, "t": sent_at, "r": to_read}).rowcount == 1
        if added:
            cur.execute("UPDATE debates SET last_activity_at = GREATEST(COALESCE(last_activity_at, %s), %s) WHERE id = %s", (sent_at, sent_at, debate_id))
        return added


def set_position(conn: psycopg.Connection, debate_id: int, user_id: int, position: str, now: datetime | None = None) -> str:
    """A person takes (or changes) their position. Returns 'recorded' (the first time), 'changed' or 'unchanged'.
    Refused: 'position', 'unknown', 'not_open' (over), 'blocked'."""
    if position not in rules.POSITIONS:
        raise DebateRefused("position")
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        debate = _locked(cur, debate_id)
        if debate.status != "open":
            raise DebateRefused("not_open")
        if _blocked(cur, user_id):
            raise DebateRefused("blocked")
        last = cur.execute("SELECT position FROM debate_positions WHERE debate_id = %s AND user_id = %s ORDER BY id DESC LIMIT 1", (debate_id, user_id)).fetchone()
        if last is not None and last[0] == position:
            return "unchanged"
        cur.execute("INSERT INTO debate_positions (debate_id, user_id, position, chosen_at) VALUES (%s, %s, %s, %s)", (debate_id, user_id, position, now))
        cur.execute("UPDATE debates SET last_activity_at = %s WHERE id = %s", (now, debate_id))
        return "recorded" if last is None else "changed"


# --- the end ----------------------------------------------------------------------------------------------------------


def end(conn: psycopg.Connection, debate_id: int, reason: str = rules.ENDED, now: datetime | None = None) -> Debate | None:
    """Ends an open debate (the button, or the silence). If nobody took part it is closed as such, whatever the reason. Returns the closed debate, or None if it was not open
    (another click, or the silence, got there first): doing it twice is safe."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        debate = _locked(cur, debate_id)
        if debate.status != "open":
            return None
        if not _participants(cur, debate_id):
            reason = rules.NO_PARTICIPANTS
        return _close(cur, debate, reason, now)


def quiet(conn: psycopg.Connection, now: datetime | None = None) -> list[int]:
    """The open debates in which nobody wrote or took a position for as long as their silence allows: the engine ends them."""
    now = now or utc_now()
    with conn.cursor(row_factory=tuple_row) as cur:
        return [r[0] for r in cur.execute(
            """SELECT id FROM debates WHERE status = 'open' AND quiet_seconds IS NOT NULL AND last_activity_at IS NOT NULL
                  AND last_activity_at + make_interval(secs => quiet_seconds) <= %s ORDER BY id""", (now,)).fetchall()]


def _close(cur: psycopg.Cursor, debate: Debate, reason: str, now: datetime) -> Debate:
    return _row(cur.execute(f"UPDATE debates SET status = 'closed', close_reason = %s, closed_at = %s WHERE id = %s RETURNING {_COLUMNS}", (reason, now, debate.id)).fetchone())


def close_stale(conn: psycopg.Connection, now: datetime, max_age: timedelta) -> int:
    """Closes the debates that were left 'preparing' (a crash between writing the debate and opening its place): they would hold their author's place for ever. Returns how many."""
    with conn.transaction():
        return conn.execute("UPDATE debates SET status = 'closed', close_reason = 'failed', closed_at = %s WHERE status = 'preparing' AND created_at < %s", (now, now - max_age)).rowcount


def close_gone(conn: psycopg.Connection, *, thread_ids: tuple[int, ...] = (), channel_ids: tuple[int, ...] = (), now: datetime | None = None) -> list[int]:
    """The thread of a debate (or the channel it was in) was deleted on Discord: the debate cannot go on, nothing is owed. Returns the places closed."""
    now = now or utc_now()
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        return [r[0] for r in cur.execute(
            """UPDATE debates SET status = 'closed', close_reason = 'failed', closed_at = %s
               WHERE status <> 'closed' AND (thread_id = ANY(%s) OR channel_id = ANY(%s)) RETURNING thread_id""", (now, list(thread_ids), list(channel_ids))).fetchall()]


# --- what is left to announce on Discord ------------------------------------------------------------------------------


def bot_messages_deleted(conn: psycopg.Connection, debate_id: int, message_ids: list[int]) -> list[str]:
    """The bot's own launch message was deleted on Discord (a moderator tidying up…). Its identifier is forgotten, so that `unannounced` says that it is owed again. Returns
    ['question'] if it was that one. (The messages of people are not handled here: the ingestion forgets them, see loader.forget_messages.)"""
    with conn.transaction():
        return ["question"] if conn.execute("UPDATE debates SET question_message_id = NULL WHERE id = %s AND question_message_id = ANY(%s) AND status = 'open'",
                                            (debate_id, message_ids)).rowcount else []


def set_question_message(conn: psycopg.Connection, debate_id: int, message_id: int) -> bool:
    """The launch message was posted again after it was deleted. False if the debate is over or a message is already recorded."""
    with conn.transaction():
        return conn.execute("UPDATE debates SET question_message_id = %s WHERE id = %s AND status = 'open' AND question_message_id IS NULL", (message_id, debate_id)).rowcount == 1


def set_final_message(conn: psycopg.Connection, debate_id: int, message_id: int) -> bool:
    """The statistics were posted. False if the debate is not closed or they are already recorded."""
    with conn.transaction():
        return conn.execute("UPDATE debates SET final_message_id = %s WHERE id = %s AND status = 'closed' AND final_message_id IS NULL", (message_id, debate_id)).rowcount == 1


def unannounced(conn: psycopg.Connection) -> list[Debate]:
    """What the bot owes to Discord after a stop (or after a message of its own was deleted): a launch message that is missing, a closed debate without its statistics.
    (A debate that failed to open has nothing to announce.)"""
    with conn.cursor(row_factory=tuple_row) as cur:
        return [Debate(*r) for r in cur.execute(
            f"""SELECT {_COLUMNS} FROM debates WHERE thread_id IS NOT NULL AND (
                    (status = 'open' AND question_message_id IS NULL) OR (status = 'closed' AND close_reason <> 'failed' AND final_message_id IS NULL))
                ORDER BY id""").fetchall()]
