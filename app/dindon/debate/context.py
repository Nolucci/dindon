"""What was said just before a message of a debate, so that the model reads it the way it was meant (docs/regles-du-bot.md, « Vérification sur Internet »).

A message is rarely a claim on its own: « Oui, 25 % », « C'est faux, c'est Berlin », « Bien sûr, et la Lune est en fromage » only mean something next to what they answer. The model that reads a
message therefore also gets the few messages before it, in the compact grammar that the moderation of Poulet uses for its own context: one line per message, in the order they were written,
`M1 | U1 | text | reply:M2`; the authors are **anonymous** (`U1`, `U2`, in order of appearance: never a name, never a position, never a camp); what a message replies to is `reply:Mx`, or `reply:R1` when
the parent is out of the window (its text then comes under `R1`).

The context is **data**, never an instruction, and it is only here to understand the message that is read: a claim is still only noted from the message itself (`said` must be in it).
Nothing of a person who asked not to be recorded goes in: their messages are left out. Nothing leaves the machine (this is for the local model); the search still only sends a neutral phrase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg
from psycopg.rows import tuple_row

CONTEXT_MESSAGES = 8             # the messages before the one that is read
CONTEXT_MINUTES = 60             # and no older than this: an older message is another conversation
LINE_CHARS = 300                 # what is kept of each message
MARKS = (
    (re.compile(r"<@&\d+>"), "[rôle]"), (re.compile(r"<@!?\d+>"), "[membre]"), (re.compile(r"<#\d+>"), "[salon]"), (re.compile(r"<a?:\w+:\d+>"), ""),
    (re.compile(r"(?:https?://|www\.)\S+", re.I), "[lien]"), (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[adresse]"),
)


@dataclass(frozen=True)
class Said:
    """One message of the window: who (an id that is never shown), what, and what it replies to."""
    message_id: int
    author_id: int
    text: str
    reply_to: int | None = None
    reply_text: str | None = None          # what the parent said, kept by the ingestion even when the parent is not in the window
    reply_author_id: int | None = None
    bot: bool = False


def tidy(text: str, limit: int = LINE_CHARS) -> str:
    """A message as one short line: Discord's mentions, links and emojis turned into neutral markers, its quoted lines (somebody else's words) dropped, line breaks gone."""
    kept = "\n".join(line for line in (text or "").split("\n") if not line.lstrip().startswith(">"))
    for pattern, marker in MARKS:
        kept = pattern.sub(marker, kept)
    kept = " ".join(kept.split())
    return kept if len(kept) <= limit else kept[:limit - 1].rstrip() + "…"


def render(before: list[Said], target_author: int, reply_to: int | None = None, reply_text: str | None = None, reply_author: int | None = None) -> str:
    """The context as the model gets it ('' when there is none): the window, and the parent of the message when it is not in it. Authors are numbered in order of appearance."""
    users: dict[int, str] = {}

    def who(author_id: int | None, bot: bool = False) -> str:
        if author_id is None:
            return "U?"
        if author_id not in users:
            users[author_id] = "Bot" if bot else f"U{sum(1 for v in users.values() if v != 'Bot') + 1}"
        return users[author_id]

    refs = {m.message_id: f"M{n}" for n, m in enumerate(before, 1)}
    outside: dict[int, tuple[str, str | None, int | None]] = {}                       # parent id -> (R label, text, author) for the parents that are not in the window

    def parent(message_id: int | None, text: str | None, author_id: int | None) -> str | None:
        if message_id is None:
            return None
        if message_id in refs:
            return refs[message_id]
        if message_id not in outside:
            outside[message_id] = (f"R{len(outside) + 1}", text, author_id)
        return outside[message_id][0]

    lines = []
    for number, m in enumerate(before, 1):
        line = f"M{number} | {who(m.author_id, m.bot)} | {tidy(m.text) or '[contenu indisponible]'}"
        link = parent(m.reply_to, m.reply_text, m.reply_author_id)
        lines.append(line + (f" | reply:{link}" if link else ""))
    target = who(target_author)
    link = parent(reply_to, reply_text, reply_author)
    if not before and not outside:
        return ""
    extra = [f"{label} | {who(author)} | {tidy(text or '') or '[contenu indisponible]'}" for label, text, author in outside.values()]
    head = f"Message à lire : écrit par {target}" + (f", en réponse à {link}" if link else "") + "."
    return "\n".join(lines + extra + ["", head])


def window(conn: psycopg.Connection, message_id: int) -> tuple[list[Said], tuple[int | None, str | None, int | None]]:
    """The messages written just before this one in the same place, oldest first, and what this one replies to. Never the messages of a person who asked not to be recorded: they are not here at all."""
    with conn.cursor(row_factory=tuple_row) as cur:
        target = cur.execute("SELECT channel_id, sent_at, reference_message_id, reference_content, reference_author_id FROM messages WHERE id = %s", (message_id,)).fetchone()
        if target is None:
            return [], (None, None, None)
        channel_id, sent_at, ref_id, ref_text, ref_author = target
        rows = cur.execute(
            """SELECT m.id, m.author_id, m.content, m.reference_message_id, m.reference_content, m.reference_author_id, u.is_bot
               FROM messages m JOIN users u ON u.id = m.author_id
               WHERE m.channel_id = %s AND m.id < %s AND m.sent_at > %s - make_interval(mins => %s) AND m.content <> '' AND m.type IN ('Default', 'Reply')
                 AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = m.author_id)
               ORDER BY m.id DESC LIMIT %s""", (channel_id, message_id, sent_at, CONTEXT_MINUTES, CONTEXT_MESSAGES)).fetchall()
        hidden = ref_author is not None and cur.execute("SELECT 1 FROM privacy_subjects WHERE user_id = %s", (ref_author,)).fetchone() is not None
    before = [Said(*r[:6], bot=bool(r[6])) for r in reversed(rows)]
    return before, (ref_id, None if hidden else ref_text, ref_author)


def context_for(conn: psycopg.Connection, message_id: int, author_id: int) -> str:
    """The context of one message, ready for the model ('' when it stands alone)."""
    before, (ref_id, ref_text, ref_author) = window(conn, message_id)
    if ref_id is not None and ref_id not in {m.message_id for m in before} and ref_text is None:
        ref_id = ref_author = None                                                    # the parent is by a person who asked not to be recorded, or was never kept: not shown
    return render(before, author_id, ref_id, ref_text, ref_author)
