"""The rights of the people whose messages Dindon holds: to stop being recorded, to be erased, to see what is held, and the limit of
how long things are kept. See docs/regles-du-bot.md for the reasons, and what this does not do.

* **The register** (`privacy_subjects`) keeps the Discord id, and nothing else, of whoever asked to stop. It is read before anything is
  written (ingest/loader.py, the live bot): a later export, a catch-up or a new Gateway event never brings the person back.
* **Erasing** deletes the person and everything that was made from them: their messages, reactions, mentions, names and profile, what
  others quoted of them in replies, the links between people, the conversations that contain their messages (and so the vectors and the
  topic placements made from them: they are made again, without the person, by the next analysis), and their traces in the files that
  Dindon keeps (archive/, inbox/). It takes the ingestion's lock, so that no import is writing at the same time.
* **What stays**, and is said: the id in the register; copies in database backups until they expire (14 days); what other people
  wrote *about* the person in their own messages (their text, their business); aggregated topics (words of many people).
* Every action is logged in `privacy_log` with counts only, never a content.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

from dindon import locks
from dindon.clock import utc_iso

log = logging.getLogger("dindon.privacy")

STOPPED, ERASED = "stopped", "erased"

# The tables of the debates that hold a person's id (db/migrations/0015_debates.sql): erased with the person, listed in their export
DEBATE_PERSON_COLUMNS = (("debate_messages", "author_id"), ("debate_positions", "user_id"), ("debate_claims", "author_id"), ("debate_answers", "author_id"),
                         ("debate_answer_votes", "user_id"), ("debate_end_votes", "user_id"), ("debate_ratings", "rater_id"), ("debate_ratings", "target_id"), ("debate_results", "user_id"))


def blocked_ids(conn: psycopg.Connection) -> set[int]:
    """The people who must not be recorded."""
    with conn.cursor(row_factory=tuple_row) as cur:
        return {row[0] for row in cur.execute("SELECT user_id FROM privacy_subjects").fetchall()}


def _log(cur: psycopg.Cursor, user_id: int | None, action: str, source: str, detail: dict) -> None:
    cur.execute("INSERT INTO privacy_log (user_id, action, source, detail) VALUES (%s, %s, %s, %s::jsonb)", (user_id, action, source, json.dumps(detail)))


def status_of(conn: psycopg.Connection, user_id: int) -> str | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        row = cur.execute("SELECT status FROM privacy_subjects WHERE user_id = %s", (user_id,)).fetchone()
    return row[0] if row else None


# --- stopping and erasing --------------------------------------------------------------------------------------------


def stop_recording(conn: psycopg.Connection, user_id: int, *, reason: str = "objection", source: str = "interface") -> dict:
    """From now on nothing of this person is recorded. What is already held is left (see `erase_person` to remove it)."""
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
        cur.execute("""INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', %s, %s)
                       ON CONFLICT (user_id) DO NOTHING""", (user_id, reason, source))   # an erased person stays erased
        _log(cur, user_id, "stop", source, {"reason": reason})
    return {"user_id": str(user_id), "status": status_of(conn, user_id)}


def erase_person(conn: psycopg.Connection, user_id: int, *, reason: str = "erasure", source: str = "interface",
                 file_directories: tuple[Path, ...] = ()) -> dict:
    """Stops recording the person AND deletes everything held of them. Returns counts (never contents)."""
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
        cur.execute("""INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'erased', %s, %s)
                       ON CONFLICT (user_id) DO UPDATE SET status = 'erased'""", (user_id, reason, source))
        counts = {
            "messages": cur.execute("SELECT count(*) FROM messages WHERE author_id = %s", (user_id,)).fetchone()[0],
            "reactions": cur.execute("SELECT count(*) FROM reaction_users WHERE user_id = %s", (user_id,)).fetchone()[0],
            "mentions": cur.execute("SELECT count(*) FROM mentions WHERE user_id = %s", (user_id,)).fetchone()[0],
        }
        # What was made from their messages: the conversations that contain one (the vectors and the placements in topics go with them)
        counts["conversations"] = cur.execute(
            """DELETE FROM conversations WHERE id IN (SELECT cm.conversation_id FROM conversation_messages cm
                                                        JOIN messages m ON m.id = cm.message_id WHERE m.author_id = %s)""", (user_id,)).rowcount
        # Their reactions to other people's messages were counted there
        cur.execute("""UPDATE reactions r SET count = GREATEST(r.count - 1, 0) FROM reaction_users ru
                       WHERE ru.user_id = %s AND ru.message_id = r.message_id AND ru.emoji_key = r.emoji_key""", (user_id,))
        # A reply keeps a copy of what it answered, with the author id if it is known: forget_user() finds those by author, this by message
        cur.execute("""UPDATE messages SET reference_content = NULL, reference_author_id = NULL
                       WHERE reference_message_id IN (SELECT id FROM messages WHERE author_id = %s)""", (user_id,))
        # Their part in debates (docs/regles-du-bot.md): the messages counted, the positions, the claims read in their messages. The debate itself stays, without them as its author.
        counts["debate_traces"] = sum(cur.execute(f"DELETE FROM {table} WHERE {column} = %s", (user_id,)).rowcount
                                      for table, column in DEBATE_PERSON_COLUMNS)
        cur.execute("UPDATE debates SET created_by = NULL WHERE created_by = %s", (user_id,))
        cur.execute("SELECT forget_user(%s)", (user_id,))     # the person, their messages, names, links; what others quoted of them
        cur.execute("UPDATE privacy_subjects SET erased_at = now() WHERE user_id = %s", (user_id,))
        _log(cur, user_id, "erase", source, counts)
    counts["files"] = scrub_files(file_directories, user_id) if file_directories else {"files": 0, "messages": 0}
    log.info("a person was erased: %s", counts)
    return counts


def release(conn: psycopg.Connection, user_id: int, *, source: str = "interface") -> bool:
    """The person asked to be recorded again: they come out of the register. Nothing that was erased comes back."""
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        removed = cur.execute("DELETE FROM privacy_subjects WHERE user_id = %s", (user_id,)).rowcount
        if removed:
            _log(cur, user_id, "release", source, {})
    return bool(removed)


def erase_server(conn: psycopg.Connection, guild_id: int, *, source: str = "removal", file_directories: tuple[Path, ...] = ()) -> dict:
    """Deletes everything held of one server: its channels, messages, members, links, scores, conversations, topics, claims (all go with the
    server row), the people seen nowhere else, the propositions that nothing refers to any more, and the files of that server. Cannot be undone.
    The register of people who are not recorded stays: it is a promise, not data of the server. Returns counts (never contents)."""
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
        counts = {
            "channels": cur.execute("SELECT count(*) FROM channels WHERE guild_id = %s", (guild_id,)).fetchone()[0],
            "messages": cur.execute("SELECT count(*) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s", (guild_id,)).fetchone()[0],
            "members": cur.execute("SELECT count(*) FROM members WHERE guild_id = %s", (guild_id,)).fetchone()[0],
        }
        known = cur.execute("SELECT 1 FROM guilds WHERE id = %s", (guild_id,)).fetchone() is not None
        cur.execute("DELETE FROM guilds WHERE id = %s", (guild_id,))
        counts["debates"] = cur.execute("DELETE FROM debates WHERE guild_id = %s", (guild_id,)).rowcount   # their messages, positions and claims go with them
        cur.execute("DELETE FROM runtime_settings WHERE key = %s", (f"debate_forum.{guild_id}",))        # the forum that was chosen for its debates
        cur.execute("DELETE FROM identity_history WHERE guild_id = %s", (guild_id,))      # the nicknames used there
        counts["people"] = cur.execute(
            """DELETE FROM users u WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.author_id = u.id)
                                     AND NOT EXISTS (SELECT 1 FROM members mb WHERE mb.user_id = u.id)""").rowcount
        counts["propositions"] = cur.execute(
            """DELETE FROM propositions p WHERE p.status IN ('proposed', 'rejected')
                                            AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.proposition_id = p.id)""").rowcount
        cur.execute("DELETE FROM ingest_runs WHERE guild_id = %s", (guild_id,))
        if known or any(counts.values()):
            _log(cur, None, "erase_server", source, counts)
    counts["files"] = delete_server_files(file_directories, guild_id) if file_directories else 0
    log.info("a server was erased: %s", counts)
    return counts


def delete_server_files(directories: tuple[Path, ...], guild_id: int) -> int:
    """The exports of that server, archived or waiting in inbox/, are deleted (a file holds one channel of one server)."""
    wanted = str(guild_id)
    removed = 0
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.json"):
            try:
                raw = path.read_bytes()
                if wanted.encode() not in raw:
                    continue
                if str((json.loads(raw).get("guild") or {}).get("id")) != wanted:
                    continue
                path.unlink()
                removed += 1
            except (OSError, ValueError, AttributeError):
                continue
    return removed


# --- the files that Dindon keeps ------------------------------------------------------------------------------------


def scrub_document(document: dict, user_id: str) -> int:
    """Removes a person from a JSON v2 export, in place: their messages, their reactions and mentions on others', what a reply quoted of
    them, their line in `users`. Returns how many messages were removed."""
    messages = document.get("messages", [])
    kept = [m for m in messages if str(m.get("authorId")) != user_id]
    for message in kept:
        for reaction in message.get("reactions", []):
            if "userIds" in reaction:
                reaction["userIds"] = [u for u in reaction["userIds"] if str(u) != user_id]
        if "mentionedUserIds" in message:
            message["mentionedUserIds"] = [u for u in message["mentionedUserIds"] if str(u) != user_id]
        reference = message.get("reference")
        if reference and str(reference.get("authorId")) == user_id:
            reference.pop("authorId", None)
            reference.pop("content", None)
        interaction = message.get("interaction")
        if interaction and str(interaction.get("userId")) == user_id:
            interaction.pop("userId", None)
    removed = len(messages) - len(kept)
    document["messages"] = kept
    document["users"] = [u for u in document.get("users", []) if str(u.get("id")) != user_id]
    return removed


def scrub_files(directories: tuple[Path, ...], user_id: int) -> dict:
    """The archived exports and the files waiting in inbox/ hold the person's messages too: they are rewritten without them."""
    uid = str(user_id)
    files = messages = 0
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.json"):
            try:
                raw = path.read_bytes()
                if uid.encode() not in raw:                    # cheap: most files do not hold the person at all
                    continue
                document = json.loads(raw)
            except (OSError, ValueError):
                continue
            removed = scrub_document(document, uid)
            fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".part")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump(document, out, ensure_ascii=False)
                os.replace(temp, path)
            except OSError:
                Path(temp).unlink(missing_ok=True)
                raise
            files += 1
            messages += removed
    return {"files": files, "messages": messages}


# --- seeing what is held (the right of access) ------------------------------------------------------------------------


def export_person(conn: psycopg.Connection, user_id: int) -> dict:
    """Everything that is held of a person, as plain data: who they are for Dindon, what they wrote and where, what they reacted to, what
    mentions them. Never what other people wrote, except the words of replies that quote them."""
    with conn.cursor(row_factory=tuple_row) as cur:
        who = cur.execute("SELECT name, global_name, discriminator, is_bot, first_seen_at, last_seen_at FROM users WHERE id = %s", (user_id,)).fetchone()
        names = cur.execute("SELECT field, value, first_seen_at FROM identity_history WHERE user_id = %s ORDER BY first_seen_at", (user_id,)).fetchall()
        roles = cur.execute("""SELECT r.name FROM member_roles mr JOIN roles r ON r.id = mr.role_id WHERE mr.user_id = %s ORDER BY r.position DESC""",
                            (user_id,)).fetchall()
        messages = cur.execute(
            """SELECT m.id, c.name, g.name, m.sent_at, m.edited_at, m.content FROM messages m JOIN channels c ON c.id = m.channel_id
               JOIN guilds g ON g.id = c.guild_id WHERE m.author_id = %s ORDER BY m.sent_at, m.id""", (user_id,)).fetchall()
        reactions = cur.execute("SELECT message_id, emoji_key FROM reaction_users WHERE user_id = %s ORDER BY message_id", (user_id,)).fetchall()
        mentions = cur.execute("SELECT message_id FROM mentions WHERE user_id = %s ORDER BY message_id", (user_id,)).fetchall()
        register = cur.execute("SELECT status, reason, requested_at FROM privacy_subjects WHERE user_id = %s", (user_id,)).fetchone()
        debates = _debates_of(cur, user_id)
        _log(cur, user_id, "export", "interface", {"messages": len(messages), "debates": len(debates)})
    iso = lambda value: value.astimezone(UTC).isoformat() if value else None  # noqa: E731
    return {
        "generated_at": utc_iso(), "discord_id": str(user_id),
        "account": None if who is None else {"name": who[0], "global_name": who[1], "discriminator": who[2], "is_bot": who[3],
                                              "first_seen_at": iso(who[4]), "last_seen_at": iso(who[5])},
        "names_seen": [{"field": f, "value": v, "since": iso(s)} for f, v, s in names],
        "roles": [r[0] for r in roles],
        "messages": [{"id": str(i), "channel": c, "server": s, "sent_at": iso(t), "edited_at": iso(e), "content": text} for i, c, s, t, e, text in messages],
        "reactions": [{"message_id": str(i), "emoji": e} for i, e in reactions],
        "mentioned_in_messages": [str(i[0]) for i in mentions],
        "register": None if register is None else {"status": register[0], "reason": register[1], "requested_at": iso(register[2])},
        "debates": [{**d, "started_at": iso(d["started_at"]), "positions": [{"position": p, "at": iso(t)} for p, t in d["positions"]],
                     "votes_on_answers": [{**v, "at": iso(v["at"])} for v in d["votes_on_answers"]]} for d in debates],
    }


def _debates_of(cur: psycopg.Cursor, user_id: int) -> list[dict]:
    """What a person did in debates: the subject, their positions in order, how many messages were counted, the claims read in them. Not what others did."""
    rows = cur.execute(
        """SELECT d.id, d.topic, d.created_at, d.created_by = %(u)s FROM debates d WHERE d.created_by = %(u)s OR d.id IN (
               SELECT debate_id FROM debate_messages WHERE author_id = %(u)s UNION SELECT debate_id FROM debate_positions WHERE user_id = %(u)s
               UNION SELECT debate_id FROM debate_claims WHERE author_id = %(u)s UNION SELECT debate_id FROM debate_answers WHERE author_id = %(u)s
               UNION SELECT a.debate_id FROM debate_answer_votes v JOIN debate_answers a ON a.id = v.answer_id WHERE v.user_id = %(u)s) ORDER BY d.id""", {"u": user_id}).fetchall()
    return [{"debate_id": str(i), "topic": topic, "started_at": at, "started_by_them": bool(mine),
             "positions": cur.execute("SELECT position, chosen_at FROM debate_positions WHERE debate_id = %s AND user_id = %s ORDER BY id", (i, user_id)).fetchall(),
             "messages_counted": cur.execute("SELECT count(*) FROM debate_messages WHERE debate_id = %s AND author_id = %s", (i, user_id)).fetchone()[0],
             "answers_to_them": [{"claim": c, "said": said, "answer": a, "verdict": v, "valid": valid, "invalid": invalid, "searched": searched}
                                 for c, said, a, v, valid, invalid, searched in cur.execute(
                                     """SELECT a.claim, a.said, a.answer, a.verdict, (SELECT count(*) FROM debate_answer_votes WHERE answer_id = a.id AND choice = 'valid'),
                                               (SELECT count(*) FROM debate_answer_votes WHERE answer_id = a.id AND choice = 'invalid'), a.searched_at IS NOT NULL
                                        FROM debate_answers a WHERE a.debate_id = %s AND a.author_id = %s ORDER BY a.id""", (i, user_id)).fetchall()],
             "votes_on_answers": [{"choice": ch, "at": at_} for ch, at_ in cur.execute(
                 """SELECT v.choice, v.voted_at FROM debate_answer_votes v JOIN debate_answers a ON a.id = v.answer_id WHERE a.debate_id = %s AND v.user_id = %s ORDER BY v.voted_at""", (i, user_id)).fetchall()],
             "claims_checked": [{"claim": c, "said": said, "verdict": v, "period": p,
                                 "sources": [{"url": u, "quote": q, "stance": s} for u, q, s in cur.execute(
                                     "SELECT url, quote, stance FROM debate_sources WHERE claim_id = %s ORDER BY id", (cid,)).fetchall()]}
                                for cid, c, said, v, p in cur.execute(
                                    "SELECT id, claim, said, verdict, period FROM debate_claims WHERE debate_id = %s AND author_id = %s ORDER BY id", (i, user_id)).fetchall()]}
            for i, topic, at, mine in rows]


# --- keeping things for a limited time -------------------------------------------------------------------------------


PURGE_BATCH = 20_000


def purge_older_than(conn: psycopg.Connection, days: int, batch: int = PURGE_BATCH) -> dict:
    """Deletes the messages older than `days` (and what was made from them), so that nothing is kept longer than that. 0 does nothing.

    Done in batches, each in its own transaction under the ingestion's lock: on a big server one huge deletion would hold that lock for
    minutes and make the live bot wait. The links are rebuilt (one server at a time) once at the end."""
    if days <= 0:
        return {"messages": 0, "debates": 0}
    total = 0
    guilds: set[int] = set()
    while True:
        with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
            cur.execute("""CREATE TEMP TABLE IF NOT EXISTS purge_batch (id bigint, channel_id bigint) ON COMMIT DELETE ROWS""")
            cur.execute("""INSERT INTO purge_batch SELECT id, channel_id FROM messages WHERE sent_at < now() - make_interval(days => %s) LIMIT %s""",
                        (days, batch))
            n = cur.execute("SELECT count(*) FROM purge_batch").fetchone()[0]
            if n == 0:
                break
            guilds.update(g for (g,) in cur.execute("SELECT DISTINCT c.guild_id FROM purge_batch p JOIN channels c ON c.id = p.channel_id").fetchall())
            cur.execute("""DELETE FROM conversations WHERE id IN (SELECT cm.conversation_id FROM conversation_messages cm
                                                                   JOIN purge_batch p ON p.id = cm.message_id)""")
            cur.execute("DELETE FROM messages WHERE id IN (SELECT id FROM purge_batch)")
            total += n
    for guild in sorted(guilds):                           # the weights of the links came from the exchanges that are gone
        with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
            cur.execute("SELECT rebuild_edges(%s)", (guild,))
    with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:           # the debates that ended long enough ago (small tables: one go)
        debates = cur.execute("DELETE FROM debates WHERE status = 'closed' AND closed_at < now() - make_interval(days => %s)", (days,)).rowcount
        if total or debates:
            _log(cur, None, "retention", "scheduled", {"days": days, "messages": total, "debates": debates})
    return {"messages": total, "debates": debates}
