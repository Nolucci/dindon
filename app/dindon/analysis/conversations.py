"""Stage 1 and 2 of the cascade: rebuild the conversations from the messages, and keep the ones that are worth reading.

A conversation is the unit that the models read, so that a message comes with what it answers to. It is made in SQL, in one
statement, so that it stays fast on hundreds of thousands of messages:

* the messages of a channel, in order, are cut where nobody wrote for `gap_minutes` (20), and every `max_messages` (40);
* bots and system messages are left out (a bot is not a person who says something);
* a conversation is only made once it is over: while someone may still answer (the last message is younger than the gap), it waits;
* a message belongs to one conversation at most, and a message that is already in one is never moved: running it again only
  makes the conversations of what is new. `rebuild=True` forgets them all (and what was computed from them) and starts again.

The triage is the same pass: a message is *substantive* when it says something (15 letters or more once links, emoji and mentions are
gone), and a conversation is *kept* when it has two such messages, or one long one. Nothing is deleted: a conversation that is not kept
stays in the table, and the later stages simply do not read it.
"""
import logging
from datetime import datetime

import psycopg

from dindon import locks
from dindon.clock import utc_now

log = logging.getLogger("dindon.analysis")


_STAGE = """
CREATE TEMP TABLE stg_conv ON COMMIT DROP AS
WITH todo AS (
    SELECT m.id, m.channel_id, m.author_id, m.sent_at, m.content
    FROM messages m
    JOIN channels c ON c.id = m.channel_id
    JOIN users u ON u.id = m.author_id
    WHERE c.guild_id = %(guild)s AND m.type IN ('Default', 'Reply') AND NOT u.is_bot
      AND NOT EXISTS (SELECT 1 FROM conversation_messages cm WHERE cm.message_id = m.id)
), gapped AS (
    SELECT t.*, CASE WHEN lag(t.sent_at) OVER w IS NULL OR t.sent_at - lag(t.sent_at) OVER w > %(gap)s * interval '1 minute'
                     THEN 1 ELSE 0 END AS brk
    FROM todo t WINDOW w AS (PARTITION BY t.channel_id ORDER BY t.sent_at, t.id)
), grouped AS (
    SELECT g.*, sum(g.brk) OVER (PARTITION BY g.channel_id ORDER BY g.sent_at, g.id) AS grp FROM gapped g
), settled AS (
    SELECT g.*, max(g.sent_at) OVER (PARTITION BY g.channel_id, g.grp) AS grp_end FROM grouped g
), numbered AS (
    SELECT s.*, (row_number() OVER (PARTITION BY s.channel_id, s.grp ORDER BY s.sent_at, s.id) - 1) / %(cap)s AS chunk
    FROM settled s WHERE s.grp_end <= %(now)s - %(gap)s * interval '1 minute'
)
SELECT n.id, n.channel_id, n.author_id, n.sent_at,
       first_value(n.id) OVER (PARTITION BY n.channel_id, n.grp, n.chunk ORDER BY n.sent_at, n.id) AS first_id,
       analysis_substantive(n.content) AS substantive, analysis_letters(n.content) AS letters
FROM numbered n
"""

_CONVERSATIONS = """
INSERT INTO conversations (channel_id, started_at, ended_at, message_count, first_message_id, participants,
                           substantive_count, substantive_chars, importance, kept)
SELECT channel_id, min(sent_at), max(sent_at), count(*), first_id, count(DISTINCT author_id),
       count(*) FILTER (WHERE substantive),
       coalesce(sum(letters) FILTER (WHERE substantive), 0),
       (ln(1 + coalesce(sum(letters) FILTER (WHERE substantive), 0)) * (1 + 0.5 * (count(DISTINCT author_id) - 1)))::real,
       (count(*) FILTER (WHERE substantive) >= 2 OR coalesce(sum(letters) FILTER (WHERE substantive), 0) >= 300)
FROM stg_conv GROUP BY channel_id, first_id
"""

_MEMBERS = """
INSERT INTO conversation_messages (conversation_id, message_id)
SELECT c.id, s.id FROM stg_conv s JOIN conversations c ON c.first_message_id = s.first_id
"""


def build_conversations(conn: psycopg.Connection, guild_id: int, *, gap_minutes: int = 20, max_messages: int = 40,
                        now: datetime | None = None, rebuild: bool = False) -> dict:
    """Makes the conversations of the messages that are in none yet. Returns how many conversations and messages that was,
    and how many conversations are kept in all."""
    now = now or utc_now()
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
        if rebuild:
            conn.execute("DELETE FROM conversations WHERE channel_id IN (SELECT id FROM channels WHERE guild_id = %s)", (guild_id,))
        params = {"guild": guild_id, "gap": gap_minutes, "cap": max_messages, "now": now}
        conn.execute(_STAGE, params)
        made = conn.execute(_CONVERSATIONS).rowcount
        messages = conn.execute(_MEMBERS).rowcount
        total, kept = conn.execute(
            """SELECT count(*), count(*) FILTER (WHERE c.kept) FROM conversations c
               JOIN channels ch ON ch.id = c.channel_id WHERE ch.guild_id = %s""", (guild_id,)).fetchone()
    log.info("conversations: %d made from %d messages; %d in all, %d kept", made, messages, total, kept)
    return {"made": made, "messages": messages, "total": total, "kept": kept}
