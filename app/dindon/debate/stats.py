"""The statistics of a debate (docs/regles-du-bot.md « Statistiques de fin »): who took part, what positions, how many messages, the message of each that Dindon picks out, and what was checked.

Everything is computed from the database **each time it is asked** (when the closing message is posted, at every click on its page buttons, by the interface): a message that was deleted since, a
person who erased themselves or asked not to be recorded are simply not there. Nothing is stored that could outlive them.

**The message picked out for each person** (« message phare ») is chosen by one rule, the same for everybody and with no model and no judgement of the content: the message of theirs that got
the most answers in the thread (3 points each) and reactions (1 point each), among those with some substance (40 characters or more) if they have any; the longer one breaks a tie. It is the
message that the debate itself picked, not one that Dindon found right.
"""
from __future__ import annotations

import re
from datetime import datetime

import psycopg
from psycopg.rows import tuple_row

from dindon.clock import utc_now
from dindon.debate import answers as answers_mod
from dindon.debate import claims as claims_mod
from dindon.debate import rules, store

MIN_SUBSTANCE = 40
EXCERPT = 200


def _excerpt(text: str) -> str:
    text = re.sub(r"<a?:\w+:\d+>", "", re.sub(r"<@[!&]?\d+>", "@membre", re.sub(r"<#\d+>", "#salon", text)))
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1].rstrip() + "…"


def collect(conn: psycopg.Connection, debate_id: int, now: datetime | None = None) -> dict | None:
    """Everything the statistics show, or None if the debate does not exist. People who asked not to be recorded are left out of every figure."""
    debate = store.get(conn, debate_id)
    if debate is None:
        return None
    people = store.participants(conn, debate_id)
    with conn.cursor(row_factory=tuple_row) as cur:
        counts = dict(cur.execute(
            """SELECT dm.author_id, count(*) FROM debate_messages dm WHERE dm.debate_id = %s
               AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = dm.author_id) GROUP BY dm.author_id""", (debate_id,)).fetchall())
        history: dict[int, list[str]] = {}
        positions_history: dict[int, list[dict]] = {}
        for user_id, position, chosen_at in cur.execute("SELECT user_id, position, chosen_at FROM debate_positions WHERE debate_id = %s ORDER BY id", (debate_id,)).fetchall():
            if user_id in people:
                history.setdefault(user_id, []).append(position)
                positions_history.setdefault(user_id, []).append({"position": position, "at": chosen_at.isoformat()})
        keys = {}
        for author, message_id, content, replies, reactions in cur.execute(
                """SELECT DISTINCT ON (dm.author_id) dm.author_id, dm.message_id, m.content, rep.n, rea.n
                   FROM debate_messages dm JOIN messages m ON m.id = dm.message_id
                   LEFT JOIN LATERAL (SELECT count(*) AS n FROM messages r WHERE r.reference_message_id = dm.message_id) rep ON true
                   LEFT JOIN LATERAL (SELECT COALESCE(sum(rc.count), 0)::int AS n FROM reactions rc WHERE rc.message_id = dm.message_id) rea ON true
                   WHERE dm.debate_id = %s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = dm.author_id)
                   ORDER BY dm.author_id, (char_length(m.content) >= %s) DESC, (3 * rep.n + rea.n) DESC, char_length(m.content) DESC, dm.message_id""",
                (debate_id, MIN_SUBSTANCE)).fetchall():
            guild = debate.guild_id
            keys[author] = {"message_id": str(message_id), "excerpt": _excerpt(content), "replies": replies, "reactions": reactions,
                            "url": f"https://discord.com/channels/{guild}/{debate.thread_id}/{message_id}" if debate.thread_id else None}
    checked = claims_mod.claims_of(conn, debate_id)
    by_author: dict[str, dict[str, int]] = {}
    for claim in checked:
        row = by_author.setdefault(claim["author_id"], dict.fromkeys(claims_mod.VERDICTS, 0))
        row[claim["verdict"]] += 1
    total_messages = sum(counts.get(p, 0) for p in people)
    participants = []
    for user_id in sorted(people, key=lambda u: (-counts.get(u, 0), u)):
        seen = history.get(user_id, [])
        participants.append({"user_id": str(user_id), "position": seen[-1] if seen else None, "first_position": seen[0] if seen else None, "changed": len(set(seen)) > 1,
                             "messages": counts.get(user_id, 0), "share": round(counts.get(user_id, 0) / total_messages, 3) if total_messages else 0.0,
                             "position_history": positions_history.get(user_id, []), "key_message": keys.get(user_id), "claims": by_author.get(str(user_id), dict.fromkeys(claims_mod.VERDICTS, 0))})
    initial, final = dict.fromkeys([*rules.POSITIONS, "none"], 0), dict.fromkeys([*rules.POSITIONS, "none"], 0)
    for p in participants:
        initial[p["first_position"] or "none"] += 1
        final[p["position"] or "none"] += 1
    verdicts = dict.fromkeys(claims_mod.VERDICTS, 0)
    for claim in checked:
        verdicts[claim["verdict"]] += 1
    given = answers_mod.of_debate(conn, debate_id)
    totals_answers = {"true": sum(a["verdict"] == "true" for a in given), "false": sum(a["verdict"] == "false" for a in given),
                      "valid": sum(a["valid"] for a in given), "invalid": sum(a["invalid"] for a in given), "searched": sum(a["searched"] for a in given)}
    return {
        "debate": {"id": debate.id, "topic": debate.topic, "context": debate.context, "status": debate.status, "close_reason": debate.close_reason, "in_thread": debate.in_thread,
                   "verify": debate.verify, "axis": debate.axis, "quiet_seconds": debate.quiet_seconds, "started_at": debate.started_at.isoformat() if debate.started_at else None,
                   "closed_at": debate.closed_at.isoformat() if debate.closed_at else None, "guild_id": str(debate.guild_id), "thread_id": str(debate.thread_id) if debate.thread_id else None,
                   "rating_ends_at": debate.rating_ends_at.isoformat() if debate.rating_ends_at else None,
                   "rating_open": bool(debate.rating_ends_at and debate.results_message_id is None and (now or utc_now()) < debate.rating_ends_at)},
        "totals": {"participants": len(participants), "messages": total_messages, "initial": initial, "final": final, "changed_mind": sum(p["changed"] for p in participants), "verdicts": verdicts,
                   "answers": totals_answers},
        "participants": participants, "claims": checked, "parity": claims_mod.parity(conn, debate_id), "answers": given,
    }


def list_recent(conn: psycopg.Connection, limit: int = 30) -> list[dict]:
    """The latest debates with their headline figures (for the interface)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        rows = cur.execute("SELECT id FROM debates WHERE status <> 'preparing' ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    found = []
    for (debate_id,) in rows:
        stats = collect(conn, debate_id)
        if stats:
            found.append({**stats["debate"], "participants": stats["totals"]["participants"], "messages": stats["totals"]["messages"], "claims": len(stats["claims"]),
                          "final": stats["totals"]["final"]})
    return found
