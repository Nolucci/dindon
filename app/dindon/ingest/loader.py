"""Imports one JSON v2 export into the database, by batches.

The behaviour is the one of the reference loader (tools/load_export.py), but a whole file is written
at once: rows go to temporary tables with COPY, then a few SQL statements apply them to the real
tables. Everything happens in one transaction, so an interrupted import leaves nothing behind.

* A file already imported (same SHA-256) is skipped. Two exports that overlap create no duplicates.
* A message that was edited is updated, and its attachments, mentions, emoji and reactions are
  replaced as a block. An export older than what the database already knows never overwrites it.
* The links between people (`edges`) are updated from the difference between what the database knew
  of these messages and what the file says: exact, even when a message is edited or an export arrives
  late. rebuild_edges() (db/migrations/0001_edges.sql) computes the same thing from zero.
* Analysis jobs are queued, and NOTIFY tells the interface what changed.
* The same pipeline takes a file (ingest_file) or a document built in memory (ingest_document), which is how the
  live bot feeds it: there is one ingestion, whatever the source.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

INGEST_LOCK = 7_262_025  # one import at a time: they all touch the same people and the same links
GATEWAY_SOURCE = "gateway"  # the name, in the ledger of imports, of what the live bot writes: it is not an import of a history
NOTIFY_CHANNEL = "dindon"
MAX_EDGE_EVENTS = 200  # beyond this, the interface is told to reload instead of one event per link
MESSAGE_EXTRA_KEYS = ("embeds", "stickers", "poll", "forwardedMessage")
# A re-export that seems to lack more than this share of a window (and at least this many messages) is more likely a
# broken export than real deletions: nothing is removed then
PRUNE_MAX_SHARE = 0.3
PRUNE_MIN_COUNT = 50


class InvalidExport(Exception):
    """The file is not a JSON v2 export that can be read."""


@dataclass
class IngestResult:
    name: str
    status: str  # 'imported' or 'duplicate'
    sha256: str = ""
    run_id: int | None = None
    messages_in_file: int = 0
    messages_new: int = 0
    messages_updated: int = 0
    messages_removed: int = 0
    prune_skipped: int = 0  # messages that seemed deleted but were kept, see PRUNE_MAX_SHARE
    edges_changed: int = 0
    seconds: float = 0.0


# ---------------------------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------------------------


def _text(s: str | None) -> str | None:
    """PostgreSQL text cannot hold a NUL character."""
    return s.replace("\x00", "") if s and "\x00" in s else s


def parse_export(raw: bytes, name: str) -> dict:
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise InvalidExport(f"{name}: not valid JSON ({error})") from None
    return check_document(document, name)


def check_document(document: object, name: str) -> dict:
    """The top-level shape of a JSON v2 document (a file that was read, or one that the bot built)."""
    if not isinstance(document, dict):
        raise InvalidExport(f"{name}: not a JSON v2 export")
    if document.get("schemaVersion") != 2:
        raise InvalidExport(f"{name}: schemaVersion {document.get('schemaVersion')!r} is not supported (expected 2)")
    for key in ("users", "roles", "emojis", "guild", "channel", "exportedAt", "messages"):
        if key not in document:
            raise InvalidExport(f"{name}: missing '{key}'")
    return document


def _when(value: str | None) -> datetime | None:
    """A timestamp of the export (always UTC, 'Z') as a real date, so that PostgreSQL does not have to guess its type."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _int_or_none(value) -> int | None:
    return int(value) if value is not None else None


def _stage(cur: psycopg.Cursor, document: dict, guild_id: int) -> None:
    """Creates the temporary tables and fills them with the content of the file."""
    cur.execute(
        """
        CREATE TEMP TABLE stg_users (id bigint, name text, discriminator text, global_name text, is_bot boolean,
            nickname text, color text, avatar_url text, has_member boolean) ON COMMIT DROP;
        CREATE TEMP TABLE stg_user_roles (user_id bigint, role_id bigint) ON COMMIT DROP;
        CREATE TEMP TABLE stg_roles (id bigint, name text, color text, position integer) ON COMMIT DROP;
        CREATE TEMP TABLE stg_emojis (key text, id bigint, name text, code text, is_animated boolean, image_url text) ON COMMIT DROP;
        CREATE TEMP TABLE stg_messages (id bigint, author_id bigint, type text, sent_at timestamptz, edited_at timestamptz,
            call_ended_at timestamptz, is_pinned boolean, content text, reference_type text, reference_message_id bigint,
            reference_channel_id bigint, reference_guild_id bigint, reference_author_id bigint, reference_content text,
            interaction_id bigint, interaction_name text, interaction_user_id bigint, extra text) ON COMMIT DROP;
        CREATE TEMP TABLE stg_attachments (id bigint, message_id bigint, url text, file_name text, size_bytes bigint) ON COMMIT DROP;
        CREATE TEMP TABLE stg_mentions (message_id bigint, user_id bigint) ON COMMIT DROP;
        CREATE TEMP TABLE stg_message_emojis (message_id bigint, emoji_key text) ON COMMIT DROP;
        CREATE TEMP TABLE stg_reactions (message_id bigint, emoji_key text, count integer) ON COMMIT DROP;
        CREATE TEMP TABLE stg_reaction_users (message_id bigint, emoji_key text, user_id bigint) ON COMMIT DROP;
        """
    )

    users: dict[int, tuple] = {}
    user_roles: list[tuple] = []
    for u in document["users"]:
        uid = int(u["id"])
        role_ids = u.get("roleIds", [])
        users[uid] = (uid, _text(u["name"]), u.get("discriminator", "0000"), _text(u.get("globalName")), bool(u.get("isBot", False)),
                      _text(u.get("nickname")), u.get("color"), u.get("avatarUrl"),
                      # An ex-member has no member data at all: that must not erase what was known
                      bool(u.get("nickname") or u.get("color") or role_ids))
        user_roles.extend((uid, int(r)) for r in role_ids)
    roles = {int(r["id"]): (int(r["id"]), _text(r["name"]), r.get("color"), r["position"]) for r in document["roles"]}
    emojis = {}
    for e in document["emojis"]:
        key = e.get("id") or e["name"]
        emojis[key] = (key, _int_or_none(e.get("id")), _text(e["name"]), e.get("code"), bool(e.get("isAnimated", False)), e["imageUrl"])

    messages, attachments, mentions, message_emojis, reactions, reaction_users = [], [], [], [], [], []
    source = document.pop("messages")  # taken out of the document: they are freed as soon as they are rows
    for m in source:
        mid = int(m["id"])
        ref = m.get("reference") or {}
        inter = m.get("interaction")
        extra = {k: m[k] for k in MESSAGE_EXTRA_KEYS if k in m}
        messages.append((
            mid, int(m["authorId"]), m["type"], m["timestamp"], m.get("timestampEdited"), m.get("callEndedTimestamp"),
            bool(m.get("isPinned", False)), _text(m["content"]),
            ref.get("type"), _int_or_none(ref.get("messageId")), _int_or_none(ref.get("channelId")), _int_or_none(ref.get("guildId")),
            _int_or_none(ref.get("authorId")), _text(ref.get("content")),
            _int_or_none(inter["id"]) if inter else None, inter.get("name") if inter else None, _int_or_none(inter.get("userId")) if inter else None,
            json.dumps(extra, ensure_ascii=False) if extra else None))
        for a in m.get("attachments", ()):
            attachments.append((int(a["id"]), mid, a["url"], _text(a["fileName"]), a["fileSizeBytes"]))
        for uid in m.get("mentionedUserIds", ()):
            mentions.append((mid, int(uid)))
        for key in m.get("inlineEmojis", ()):
            message_emojis.append((mid, key))
        for r in m.get("reactions", ()):
            reactions.append((mid, r["emoji"], r["count"]))
            for uid in r.get("userIds", ()):
                reaction_users.append((mid, r["emoji"], int(uid)))
    del source

    columns = {
        "stg_users": "id, name, discriminator, global_name, is_bot, nickname, color, avatar_url, has_member",
        "stg_user_roles": "user_id, role_id",
        "stg_roles": "id, name, color, position",
        "stg_emojis": "key, id, name, code, is_animated, image_url",
        "stg_messages": "id, author_id, type, sent_at, edited_at, call_ended_at, is_pinned, content, reference_type, reference_message_id, "
                        "reference_channel_id, reference_guild_id, reference_author_id, reference_content, interaction_id, "
                        "interaction_name, interaction_user_id, extra",
        "stg_attachments": "id, message_id, url, file_name, size_bytes",
        "stg_mentions": "message_id, user_id",
        "stg_message_emojis": "message_id, emoji_key",
        "stg_reactions": "message_id, emoji_key, count",
        "stg_reaction_users": "message_id, emoji_key, user_id",
    }
    batches = {"stg_users": users.values(), "stg_user_roles": user_roles, "stg_roles": roles.values(), "stg_emojis": emojis.values(),
               "stg_messages": messages, "stg_attachments": attachments, "stg_mentions": mentions,
               "stg_message_emojis": message_emojis, "stg_reactions": reactions, "stg_reaction_users": reaction_users}
    del messages, attachments, mentions, message_emojis, reactions, reaction_users
    for table in list(batches):
        rows = batches.pop(table)  # each batch is freed once it is written
        with cur.copy(f"COPY {table} ({columns[table]}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        del rows


# ---------------------------------------------------------------------------------------------
# Writing it
# ---------------------------------------------------------------------------------------------

# The links, from the staged messages (what the file says) and from the tables (what is known).
# They must stay the same as the `interactions` view: reply, mention, reaction; never a person to themselves.
_NEW_EVENTS = """
CREATE TEMP TABLE new_events ON COMMIT DROP AS
SELECT m.author_id AS f, m.reference_author_id AS t, 'reply'::text AS kind, m.id AS message_id, m.sent_at, 1 AS c
FROM stg_messages m JOIN applied a ON a.id = m.id
WHERE m.reference_author_id IS NOT NULL AND m.author_id <> m.reference_author_id
UNION ALL
SELECT m.author_id, mn.user_id, 'mention', m.id, m.sent_at, 1
FROM stg_messages m JOIN applied a ON a.id = m.id JOIN stg_mentions mn ON mn.message_id = m.id
WHERE m.author_id <> mn.user_id
UNION ALL
SELECT ru.user_id, m.author_id, 'reaction', m.id, m.sent_at, 1
FROM stg_messages m JOIN applied a ON a.id = m.id JOIN stg_reaction_users ru ON ru.message_id = m.id
WHERE ru.user_id <> m.author_id
"""
_OLD_EVENTS = """
CREATE TEMP TABLE old_events ON COMMIT DROP AS
SELECT m.author_id AS f, m.reference_author_id AS t, 'reply'::text AS kind, m.id AS message_id, m.sent_at, 1 AS c
FROM messages m JOIN touched a ON a.id = m.id
WHERE m.reference_author_id IS NOT NULL AND m.author_id <> m.reference_author_id
UNION ALL
SELECT m.author_id, mn.user_id, 'mention', m.id, m.sent_at, 1
FROM messages m JOIN touched a ON a.id = m.id JOIN mentions mn ON mn.message_id = m.id
WHERE m.author_id <> mn.user_id
UNION ALL
SELECT ru.user_id, m.author_id, 'reaction', m.id, m.sent_at, 1
FROM messages m JOIN touched a ON a.id = m.id JOIN reaction_users ru ON ru.message_id = m.id
WHERE ru.user_id <> m.author_id
"""
# Exchanges that the file adds (+) or that are no longer there (-), per message and pair
_EDGE_DELTA = """
CREATE TEMP TABLE edge_delta ON COMMIT DROP AS
SELECT COALESCE(n.f, o.f) AS f, COALESCE(n.t, o.t) AS t, COALESCE(n.kind, o.kind) AS kind,
       COALESCE(n.sent_at, o.sent_at) AS sent_at, COALESCE(n.c, 0) - COALESCE(o.c, 0) AS k
FROM (SELECT f, t, kind, message_id, min(sent_at) AS sent_at, sum(c) AS c FROM new_events GROUP BY 1, 2, 3, 4) n
FULL JOIN (SELECT f, t, kind, message_id, min(sent_at) AS sent_at, sum(c) AS c FROM old_events GROUP BY 1, 2, 3, 4) o
  ON (n.f, n.t, n.kind, n.message_id) = (o.f, o.t, o.kind, o.message_id)
WHERE COALESCE(n.c, 0) <> COALESCE(o.c, 0)
"""
# New weight of each changed link, "as of" its latest exchange: the old weight, aged up to that date,
# plus the exchanges that arrive, minus the ones that disappear (see 0001_edges.sql)
_EDGE_MERGE = """
CREATE TEMP TABLE edge_merged ON COMMIT DROP AS
WITH hl AS (
    SELECT 86400 * COALESCE((SELECT value FROM scoring_settings WHERE key = 'edge_half_life_days'), 90)::double precision AS s
), keys AS (
    SELECT d.f, d.t, d.kind, e.weight AS w0, e.n AS n0, e.last_at AS l0,
           GREATEST(e.last_at, max(d.sent_at) FILTER (WHERE d.k > 0)) AS tt
    FROM edge_delta d
    LEFT JOIN edges e ON e.guild_id = %(guild)s AND e.from_user_id = d.f AND e.to_user_id = d.t AND e.kind = d.kind
    GROUP BY d.f, d.t, d.kind, e.weight, e.n, e.last_at
)
SELECT k.f, k.t, k.kind, k.tt,
       COALESCE(k.w0 * power(0.5, extract(epoch FROM (k.tt - k.l0)) / hl.s), 0)
         + sum(d.k * power(0.5, extract(epoch FROM (k.tt - d.sent_at)) / hl.s)) AS w1,
       COALESCE(k.n0, 0) + sum(d.k) AS n1,
       COALESCE(sum(d.k) FILTER (WHERE d.k > 0), 0) AS added,
       hl.s AS half_life
FROM keys k
JOIN edge_delta d ON d.f = k.f AND d.t = k.t AND d.kind = k.kind
CROSS JOIN hl
WHERE k.tt IS NOT NULL
GROUP BY k.f, k.t, k.kind, k.tt, k.w0, k.n0, k.l0, hl.s
"""


def _apply(conn: psycopg.Connection, document: dict, run_id: int, params: dict, prune: bool, only_new: bool,
           result: IngestResult) -> list[dict]:
    # (the messages are in the staging tables by now: document["messages"] is gone)
    """Writes the staged data. Returns the notifications to send."""
    cur = conn.cursor()
    exported_at = params["exported_at"]
    guild_id, channel_id = params["guild"], params["channel"]
    cur.execute("SELECT NOT EXISTS (SELECT 1 FROM ingest_runs WHERE guild_id = %s AND exported_at > %s)", (guild_id, exported_at))
    newest = cur.fetchone()[0]
    params = {**params, "newest": newest, "run": run_id, "only_new": only_new}

    # Where the messages come from. An export older than what is known only adds what is missing.
    g = document["guild"]
    cur.execute("""INSERT INTO guilds (id, name, icon_url) VALUES (%s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = excluded.name, icon_url = excluded.icon_url WHERE %s""",
                (guild_id, _text(g["name"]), g.get("iconUrl"), newest))
    c = document["channel"]
    cur.execute("""INSERT INTO channels (id, guild_id, parent_id, parent_name, type, name, topic, icon_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = excluded.name, topic = excluded.topic, type = excluded.type,
                       parent_id = excluded.parent_id, parent_name = excluded.parent_name, icon_url = excluded.icon_url WHERE %s""",
                (channel_id, guild_id, _int_or_none(c.get("categoryId")), _text(c.get("category")), c["type"], _text(c["name"]),
                 _text(c.get("topic")), c.get("iconUrl"), newest))
    cur.execute("""INSERT INTO roles (id, guild_id, name, color, position) SELECT id, %(guild)s, name, color, position FROM stg_roles
                   ON CONFLICT (id) DO UPDATE SET name = excluded.name, color = excluded.color, position = excluded.position WHERE %(newest)s""", params)
    cur.execute("""INSERT INTO emojis (key, id, name, code, is_animated, image_url) SELECT key, id, name, code, is_animated, image_url FROM stg_emojis
                   ON CONFLICT (key) DO UPDATE SET image_url = excluded.image_url WHERE %(newest)s""", params)

    # People. The account (name, display name) is always known in an export; what belongs to the server
    # (nickname, roles) is not for someone who left: then it is not touched.
    cur.execute("""INSERT INTO users (id, name, discriminator, global_name, is_bot, first_seen_at, last_seen_at)
                   SELECT id, name, discriminator, global_name, is_bot, %(exported_at)s, %(exported_at)s FROM stg_users
                   ON CONFLICT (id) DO UPDATE SET
                       name = CASE WHEN excluded.last_seen_at >= users.last_seen_at THEN excluded.name ELSE users.name END,
                       discriminator = CASE WHEN excluded.last_seen_at >= users.last_seen_at THEN excluded.discriminator ELSE users.discriminator END,
                       global_name = CASE WHEN excluded.last_seen_at >= users.last_seen_at THEN excluded.global_name ELSE users.global_name END,
                       is_bot = CASE WHEN excluded.last_seen_at >= users.last_seen_at THEN excluded.is_bot ELSE users.is_bot END,
                       first_seen_at = least(users.first_seen_at, excluded.first_seen_at),
                       last_seen_at = greatest(users.last_seen_at, excluded.last_seen_at)""", params)
    cur.execute("""CREATE TEMP TABLE fresh_members ON COMMIT DROP AS
                   SELECT s.id AS user_id FROM stg_users s
                   WHERE s.has_member AND NOT EXISTS (SELECT 1 FROM members m WHERE m.guild_id = %(guild)s AND m.user_id = s.id AND m.observed_at > %(exported_at)s)""", params)
    cur.execute("""INSERT INTO members (guild_id, user_id, nickname, color, avatar_url, observed_at)
                   SELECT %(guild)s, id, nickname, color, avatar_url, %(exported_at)s FROM stg_users
                   ON CONFLICT (guild_id, user_id) DO NOTHING""", params)
    cur.execute("""UPDATE members m SET nickname = s.nickname, color = s.color, avatar_url = COALESCE(s.avatar_url, m.avatar_url),
                          observed_at = %(exported_at)s
                   FROM stg_users s JOIN fresh_members f ON f.user_id = s.id
                   WHERE m.guild_id = %(guild)s AND m.user_id = s.id""", params)
    cur.execute("DELETE FROM member_roles WHERE guild_id = %(guild)s AND user_id IN (SELECT user_id FROM fresh_members)", params)
    cur.execute("""INSERT INTO member_roles (guild_id, user_id, role_id)
                   SELECT DISTINCT %(guild)s, r.user_id, r.role_id FROM stg_user_roles r JOIN fresh_members f ON f.user_id = r.user_id""", params)
    cur.execute("""INSERT INTO identity_history (user_id, guild_id, field, value, first_seen_at, last_seen_at)
                   SELECT DISTINCT user_id, guild_id, field, value, %(exported_at)s, %(exported_at)s FROM (
                       SELECT id AS user_id, 0::bigint AS guild_id, 'name' AS field, name AS value FROM stg_users
                       UNION ALL SELECT id, 0, 'globalName', global_name FROM stg_users WHERE global_name IS NOT NULL
                       UNION ALL SELECT id, %(guild)s, 'nickname', nickname FROM stg_users WHERE nickname IS NOT NULL
                   ) names
                   ON CONFLICT (user_id, guild_id, field, value) DO UPDATE SET
                       first_seen_at = least(identity_history.first_seen_at, excluded.first_seen_at),
                       last_seen_at = greatest(identity_history.last_seen_at, excluded.last_seen_at)""", params)

    # Which messages does this file really change? Not the ones of an older export than what is known.
    # (`only_new`: messages that the database already has are not touched at all, see ingest_document)
    cur.execute("""CREATE TEMP TABLE applied ON COMMIT DROP AS
                   SELECT DISTINCT ON (s.id) s.id, (m.id IS NOT NULL) AS existing
                   FROM stg_messages s
                   LEFT JOIN messages m ON m.id = s.id
                   LEFT JOIN ingest_runs r ON r.id = m.last_seen_run_id
                   WHERE m.id IS NULL OR (NOT %(only_new)s AND (r.id IS NULL OR r.exported_at <= %(exported_at)s))
                   ORDER BY s.id""", params)
    cur.execute("CREATE TEMP TABLE pruned (id bigint) ON COMMIT DROP")
    if prune and result.messages_in_file and "after" in document.get("dateRange", {}):
        # A complete re-export of a window: what the database has in it and the file has not was deleted.
        # Nothing newer than the newest message of the file is judged: it may have arrived since.
        cur.execute("""INSERT INTO pruned SELECT m.id FROM messages m
                       WHERE m.channel_id = %(channel)s AND m.sent_at > %(after)s
                         AND m.sent_at <= (SELECT max(sent_at) FROM stg_messages)
                         AND NOT EXISTS (SELECT 1 FROM stg_messages s WHERE s.id = m.id)""",
                    {**params, "after": _when(document["dateRange"]["after"])})
        cur.execute("SELECT count(*) FROM pruned")
        seems_deleted = cur.fetchone()[0]
        if seems_deleted >= PRUNE_MIN_COUNT:
            cur.execute("""SELECT count(*) FROM messages m WHERE m.channel_id = %(channel)s AND m.sent_at > %(after)s
                             AND m.sent_at <= (SELECT max(sent_at) FROM stg_messages)""",
                        {**params, "after": _when(document["dateRange"]["after"])})
            if seems_deleted > PRUNE_MAX_SHARE * cur.fetchone()[0]:
                cur.execute("DELETE FROM pruned")
                result.prune_skipped = seems_deleted
    cur.execute("CREATE TEMP TABLE touched ON COMMIT DROP AS SELECT id FROM applied UNION ALL SELECT id FROM pruned")
    cur.execute("ANALYZE applied; ANALYZE touched")

    # The links, before anything is written: what the database knew against what the file says
    cur.execute(_NEW_EVENTS)
    cur.execute(_OLD_EVENTS)
    cur.execute(_EDGE_DELTA)
    cur.execute(_EDGE_MERGE, params)

    cur.execute("""WITH up AS (
                       INSERT INTO messages (id, channel_id, author_id, type, sent_at, edited_at, call_ended_at, is_pinned, content,
                           reference_type, reference_message_id, reference_channel_id, reference_guild_id, reference_author_id, reference_content,
                           interaction_id, interaction_name, interaction_user_id, extra, last_seen_run_id)
                       SELECT s.id, %(channel)s, s.author_id, s.type, s.sent_at, s.edited_at, s.call_ended_at, s.is_pinned, s.content,
                           s.reference_type, s.reference_message_id, s.reference_channel_id, s.reference_guild_id, s.reference_author_id, s.reference_content,
                           s.interaction_id, s.interaction_name, s.interaction_user_id, s.extra::jsonb, %(run)s
                       FROM (SELECT DISTINCT ON (id) * FROM stg_messages ORDER BY id) s JOIN applied a ON a.id = s.id
                       ON CONFLICT (id) DO UPDATE SET type = excluded.type, edited_at = excluded.edited_at,
                           call_ended_at = excluded.call_ended_at, is_pinned = excluded.is_pinned, content = excluded.content,
                           reference_type = excluded.reference_type, reference_content = excluded.reference_content,
                           interaction_name = excluded.interaction_name, extra = excluded.extra, last_seen_run_id = excluded.last_seen_run_id
                       RETURNING (xmax = 0) AS inserted)
                   SELECT count(*) FILTER (WHERE inserted), count(*) FILTER (WHERE NOT inserted) FROM up""", params)
    result.messages_new, result.messages_updated = cur.fetchone()

    # Children are replaced as a whole, so that an edited message ends up exactly as exported
    for table in ("attachments", "mentions", "message_emojis", "reactions"):  # reactions: also removes who reacted
        cur.execute(f"DELETE FROM {table} WHERE message_id IN (SELECT id FROM applied WHERE existing)")
    cur.execute("""INSERT INTO attachments (id, message_id, url, file_name, size_bytes)
                   SELECT s.id, s.message_id, s.url, s.file_name, s.size_bytes FROM stg_attachments s JOIN applied a ON a.id = s.message_id
                   ON CONFLICT (id) DO NOTHING""")
    cur.execute("""INSERT INTO mentions (message_id, user_id) SELECT DISTINCT s.message_id, s.user_id FROM stg_mentions s
                   JOIN applied a ON a.id = s.message_id ON CONFLICT DO NOTHING""")
    cur.execute("""INSERT INTO message_emojis (message_id, emoji_key) SELECT DISTINCT s.message_id, s.emoji_key FROM stg_message_emojis s
                   JOIN applied a ON a.id = s.message_id ON CONFLICT DO NOTHING""")
    cur.execute("""INSERT INTO reactions (message_id, emoji_key, count)
                   SELECT DISTINCT ON (s.message_id, s.emoji_key) s.message_id, s.emoji_key, s.count FROM stg_reactions s
                   JOIN applied a ON a.id = s.message_id ORDER BY s.message_id, s.emoji_key ON CONFLICT DO NOTHING""")
    cur.execute("""INSERT INTO reaction_users (message_id, emoji_key, user_id)
                   SELECT DISTINCT s.message_id, s.emoji_key, s.user_id FROM stg_reaction_users s
                   JOIN applied a ON a.id = s.message_id ON CONFLICT DO NOTHING""")
    cur.execute("DELETE FROM messages WHERE id IN (SELECT id FROM pruned)")
    result.messages_removed = cur.rowcount

    # The links, now
    cur.execute("""INSERT INTO edges (guild_id, from_user_id, to_user_id, kind, weight, n, last_at)
                   SELECT %(guild)s, f, t, kind, GREATEST(w1, 0), n1, tt FROM edge_merged WHERE n1 > 0
                   ON CONFLICT (guild_id, from_user_id, to_user_id, kind) DO UPDATE
                       SET weight = excluded.weight, n = excluded.n, last_at = excluded.last_at""", params)
    result.edges_changed = cur.rowcount
    cur.execute("""DELETE FROM edges e USING edge_merged m
                   WHERE m.n1 <= 0 AND e.guild_id = %(guild)s AND e.from_user_id = m.f AND e.to_user_id = m.t AND e.kind = m.kind""", params)

    # The analysis of a channel is worth redoing as soon as it has changed
    if result.messages_new or result.messages_updated or result.messages_removed:
        cur.execute("""INSERT INTO jobs (kind, subject_id) SELECT 'conversations', %(channel)s
                       WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE kind = 'conversations' AND subject_id = %(channel)s)""", params)

    # What the interface is told: the links that gained an exchange (the one to light up), and the messages
    events: list[dict] = []
    cur.execute("""SELECT f, t, kind, n1, tt, w1 * power(0.5, GREATEST(extract(epoch FROM (now() - tt)), 0) / half_life) AS weight_now
                   FROM edge_merged WHERE added > 0 AND n1 > 0 ORDER BY tt DESC LIMIT %s""", (MAX_EDGE_EVENTS + 1,))
    changed = cur.fetchall()
    if len(changed) > MAX_EDGE_EVENTS:
        events.append({"type": "graph", "guild": str(guild_id)})
    else:
        events.extend({"type": "edge", "guild": str(guild_id), "from": str(f), "to": str(t), "kind": kind, "n": int(n),
                       "weight": round(float(weight), 4), "at": tt.isoformat()} for f, t, kind, n, tt, weight in changed)
    if result.messages_new:
        cur.execute("SELECT max(id) FROM messages WHERE channel_id = %s", (channel_id,))
        events.append({"type": "messages", "guild": str(guild_id), "channel": str(channel_id),
                       "count": result.messages_new, "last": str(cur.fetchone()[0])})
    return events


def ingest_document(conn: psycopg.Connection, document: dict, name: str, sha256: str, prune: bool = False,
                    only_new: bool = False, consume: bool = False) -> IngestResult:
    """Imports one JSON v2 document, whatever its origin (an export file, the live bot). `sha256` identifies it: a document
    that was already imported (same hash) is skipped.

    `prune` is for a complete re-export of a window of time (the nightly catch-up): the messages that the database has
    in that window and the document has not were deleted on Discord.

    `only_new` is for a source that only announces new messages (the bot, on MESSAGE_CREATE): a message that the database
    already has is left exactly as it is. Such a document knows nothing of reactions or edits that the database may have
    learned elsewhere, and importing it as a snapshot would erase them. It is what makes a duplicate event harmless.

    `consume` lets the import take the messages out of `document` as they become rows, so that a very big file is not held
    twice in memory (ingest_file does). Without it the document is left intact: a failed attempt can be sent again."""
    started = time.monotonic()
    check_document(document, name)
    if not consume:
        document = {**document}  # _stage takes "messages" out of the dict it is given
    result = IngestResult(name=name, status="imported", sha256=sha256, messages_in_file=len(document["messages"]))
    try:
        guild_id = int(document["guild"]["id"])
        channel_id = int(document["channel"]["id"])
        exported_at = _when(document["exportedAt"])
        date_range = document.get("dateRange", {})
        date_after, date_before = _when(date_range.get("after")), _when(date_range.get("before"))
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise InvalidExport(f"{name}: unexpected content ({type(error).__name__}: {error})") from None
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (INGEST_LOCK,))
        cur.execute("SELECT id FROM ingest_runs WHERE source_sha256 = %s", (sha256,))
        if cur.fetchone():
            result.status = "duplicate"
            result.seconds = time.monotonic() - started
            return result
        cur.execute("""INSERT INTO ingest_runs (source_file, source_sha256, schema_version, exported_at, guild_id, channel_id,
                           message_count, date_after, date_before) VALUES (%s, %s, 2, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (name, sha256, exported_at, guild_id, channel_id, len(document["messages"]), date_after, date_before))
        result.run_id = cur.fetchone()[0]
        try:
            _stage(cur, document, guild_id)
        except (KeyError, ValueError, TypeError, AttributeError) as error:  # a field that is missing or has the wrong shape
            raise InvalidExport(f"{name}: unexpected content ({type(error).__name__}: {error})") from None
        params = {"guild": guild_id, "channel": channel_id, "exported_at": exported_at}
        events = _apply(conn, document, result.run_id, params, prune, only_new, result)
        for event in events:
            cur.execute("SELECT pg_notify(%s, %s)", (NOTIFY_CHANNEL, json.dumps(event)))
    result.seconds = time.monotonic() - started
    return result


def ingest_file(conn: psycopg.Connection, path: Path, prune: bool = False) -> IngestResult:
    """Imports one export file (see ingest_document for `prune`)."""
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    document = parse_export(raw, path.name)
    del raw  # a big file is about ten times its size in memory: nothing else keeps it alive
    return ingest_document(conn, document, path.name, sha, prune=prune, consume=True)
