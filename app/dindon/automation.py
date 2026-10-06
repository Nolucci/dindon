"""The automatic reading: Dindon reads what the bot records by itself, a little at a time, when the person has asked for it.

**Off by default.** What is read, how often, how much at a time and at which hours are settings (page Système, panel « Lecture automatique »), kept in
`runtime_settings` like the performance limits, which it also obeys (the AI works only the share of the time that was allowed).

* `vectors`: the new messages become conversations, and the conversations get their vector (the first stages; they do not look at people).
* `themes`: the topics are searched again once enough conversations are not in any (a search replaces the proposals that nobody touched).
* `positions`: what each person claims is read in the conversations not read yet (the most important first), then linked to the axes. **This looks at
  what people think**: it cannot be switched on without saying that the people are informed (`positions_acknowledged`, docs/CONFORMITE.md), and it never
  reads the messages of a person who asked to stop being recorded.

A cycle goes through the servers one after the other, only does what there is to do, and does nothing when an analysis is already running (started by a
person, or the previous cycle). `batch` caps the conversations read for the positions in one cycle: a big backlog is cleared over several cycles.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.rows import tuple_row

from dindon.clock import utc_iso, utc_now

KEY, STATE_KEY = "auto_analysis", "auto_analysis_state"
INTERVALS = (10, 15, 30, 60, 180, 360, 1440)          # minutes
DEFAULT = {"enabled": False, "vectors": True, "themes": False, "positions": False, "positions_acknowledged": False,
           "interval_minutes": 30, "batch": 20, "window_from": 0, "window_to": 24}
THEMES_WHEN_UNPLACED = 25                               # conversations that belong to no topic of the latest search before a new search is worth it


def timezone_name() -> str:
    return os.environ.get("DINDON_TIMEZONE", "Europe/Paris")


def _zone() -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name())
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def clean(values: dict) -> dict:
    """A complete, valid set of settings. The positions are only on when the person said that the people are informed."""
    out = dict(DEFAULT)
    for key in ("enabled", "vectors", "themes", "positions", "positions_acknowledged"):
        out[key] = bool(values.get(key, DEFAULT[key]))
    for key, (low, high) in {"batch": (1, 500), "window_from": (0, 23), "window_to": (1, 24)}.items():
        try:
            out[key] = min(max(int(values.get(key, DEFAULT[key])), low), high)
        except (TypeError, ValueError):
            out[key] = DEFAULT[key]
    try:
        wanted = int(values.get("interval_minutes", DEFAULT["interval_minutes"]))
    except (TypeError, ValueError):
        wanted = DEFAULT["interval_minutes"]
    out["interval_minutes"] = min(INTERVALS, key=lambda m: abs(m - wanted))
    if not out["positions_acknowledged"]:
        out["positions"] = False
    return out


def _get(conn: psycopg.Connection, key: str) -> dict:
    try:
        with conn.cursor(row_factory=tuple_row) as cur:
            row = cur.execute("SELECT value FROM runtime_settings WHERE key = %s", (key,)).fetchone()
    except psycopg.errors.UndefinedTable:
        return {}
    return row[0] if row else {}


def _put(conn: psycopg.Connection, key: str, value: dict) -> None:
    conn.execute("""INSERT INTO runtime_settings (key, value) VALUES (%s, %s::jsonb)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""", (key, json.dumps(value)))


def load(conn: psycopg.Connection) -> dict:
    return clean(_get(conn, KEY))


def save(conn: psycopg.Connection, values: dict) -> dict:
    cleaned = clean(values)
    _put(conn, KEY, cleaned)
    return cleaned


def state(conn: psycopg.Connection) -> dict:
    """What the loop did last: when, with what result; and whether a person asked for a cycle now."""
    return {"last_cycle_at": None, "last_result": None, "run_requested_at": None, **_get(conn, STATE_KEY)}


def update_state(conn: psycopg.Connection, **changes) -> dict:
    new = {**state(conn), **changes}
    _put(conn, STATE_KEY, new)
    return new


def request_run(conn: psycopg.Connection) -> None:
    update_state(conn, run_requested_at=utc_iso())


def in_window(settings: dict, now: datetime | None = None) -> bool:
    """Is it an hour at which the reading is allowed (in the time zone of DINDON_TIMEZONE)? from 0 to 24 is always; from 22 to 6 goes over midnight."""
    start, end = settings["window_from"], settings["window_to"]
    if start == 0 and end == 24:
        return True
    hour = (now or utc_now()).astimezone(_zone()).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def due(settings: dict, st: dict, now: datetime | None = None) -> bool:
    """Is it time for a cycle? Yes if a person asked for one now; else if it is on, at an allowed hour, and the interval is over."""
    now = now or utc_now()
    if st.get("run_requested_at") and (not st.get("last_cycle_at") or st["run_requested_at"] > st["last_cycle_at"]):
        return True
    if not settings["enabled"] or not in_window(settings, now):
        return False
    if not st.get("last_cycle_at"):
        return True
    last = datetime.fromisoformat(st["last_cycle_at"])
    return (now - last).total_seconds() >= settings["interval_minutes"] * 60


def next_at(settings: dict, st: dict, now: datetime | None = None) -> str | None:
    """When the next cycle will start at the earliest (None: nothing is planned, it is off)."""
    if not settings["enabled"]:
        return None
    now = now or utc_now()
    if not st.get("last_cycle_at"):
        return now.isoformat()
    from datetime import timedelta
    return max(now, datetime.fromisoformat(st["last_cycle_at"]) + timedelta(minutes=settings["interval_minutes"])).isoformat()


def pending(conn: psycopg.Connection, guild_id: int, embed_model: str) -> dict:
    """What there is to do for a server (cheap counts, no model)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        new_messages = cur.execute(
            """SELECT count(*) FROM messages m JOIN channels c ON c.id = m.channel_id JOIN users u ON u.id = m.author_id
               WHERE c.guild_id = %s AND m.type IN ('Default', 'Reply') AND NOT u.is_bot AND m.sent_at < now() - interval '20 minutes'
                 AND NOT EXISTS (SELECT 1 FROM conversation_messages cm WHERE cm.message_id = m.id)""", (guild_id,)).fetchone()[0]
        without_vector = cur.execute(
            """SELECT count(*) FROM conversations c JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s AND c.kept
               AND NOT EXISTS (SELECT 1 FROM conversation_embeddings e WHERE e.conversation_id = c.id AND e.model = %s)""", (guild_id, embed_model)).fetchone()[0]
        unread = cur.execute(
            """SELECT count(*) FROM conversations c JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s AND c.kept
               AND NOT EXISTS (SELECT 1 FROM conversation_extractions x WHERE x.conversation_id = c.id)""", (guild_id,)).fetchone()[0]
        unlinked = cur.execute(
            """SELECT count(*) FROM propositions p WHERE p.axes_read_at IS NULL AND p.status NOT IN ('rejected', 'merged')
               AND EXISTS (SELECT 1 FROM claims c WHERE c.proposition_id = p.id AND c.guild_id = %s)""", (guild_id,)).fetchone()[0]
        run = cur.execute("SELECT max(id) FROM topic_runs WHERE guild_id = %s", (guild_id,)).fetchone()[0]
        unplaced = cur.execute(
            """SELECT count(*) FROM conversations c JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s AND c.kept
               AND EXISTS (SELECT 1 FROM conversation_embeddings e WHERE e.conversation_id = c.id AND e.model = %s)
               AND NOT EXISTS (SELECT 1 FROM topic_assignments a WHERE a.conversation_id = c.id AND a.run_id = %s)""", (guild_id, embed_model, run)).fetchone()[0]
    return {"new_messages": new_messages, "without_vector": without_vector, "unread": unread, "unlinked": unlinked, "unplaced": unplaced, "topic_run": run is not None}


def stages_for(settings: dict, todo: dict) -> tuple[str, ...]:
    """The stages that are worth running now, given what the person wants read and what is waiting."""
    stages: list[str] = []
    if settings["vectors"] and (todo["new_messages"] or todo["without_vector"]):
        stages += ["conversations", "embeddings"]
    if settings["themes"] and todo["unplaced"] >= THEMES_WHEN_UNPLACED:
        stages += [s for s in ("conversations", "embeddings") if s not in stages] + ["themes"]
    if settings["positions"] and settings["positions_acknowledged"] and (todo["unread"] or todo["unlinked"] or todo["new_messages"]):
        stages += (["conversations"] if todo["new_messages"] and "conversations" not in stages else []) + ["claims"]     # (the positions do not need the vectors)
    order = ["conversations", "embeddings", "themes", "claims"]
    return tuple(s for s in order if s in stages)
