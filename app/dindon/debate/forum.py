"""The forum where the debates of a server are created, when there is one (docs/DEBAT.md, « Un forum pour les débats »).

Many servers keep their debates in a **forum channel** (Discord's type 15): every debate is a *post* with labels (« étiquettes », Discord's *tags*: Économie, Religion…). A moderator tells Dindon
once, with `/dindon forum`, which forum it is; from then on a debate that is opened in a thread is created there, as a post, instead of a thread under the channel where the command was
used: the channel is not polluted. Nothing is stored of a person: the channel, its name and, if asked, the label that every debate carries.

**The labels.** A post may carry up to 5. Dindon puts the one that the moderator chose (every debate carries it), and, for a debate opened from an axis, the labels of the forum whose name is a
word of the axis (« Religion » for « Religion et État », « International » for « Commerce international »). It never guesses further, and never uses a label that only moderators may apply, unless
the moderator chose that one himself. A forum that requires a label (`REQUIRE_TAG`) is not accepted without a chosen label.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

FORUM_CHANNEL = 15                     # Discord's GUILD_FORUM
REQUIRE_TAG = 1 << 4                   # the flag of a forum that wants a label on every post
MAX_TAGS = 5
KEY = "debate_forum.{}"                # in runtime_settings, one row per server


@dataclass(frozen=True)
class Forum:
    channel_id: int
    name: str
    tag_id: str | None = None
    tag_name: str | None = None


def words(text: str) -> set[str]:
    """The words of a name, without accents, case or punctuation: « Contrôle de l'économie » -> {controle, de, l, economie}."""
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", plain))


def get(conn: psycopg.Connection, guild_id: int) -> Forum | None:
    row = conn.execute("SELECT value FROM runtime_settings WHERE key = %s", (KEY.format(guild_id),)).fetchone()
    if row is None or not isinstance(row[0], dict) or not str(row[0].get("channel_id", "")).isdigit():
        return None
    value = row[0]
    return Forum(int(value["channel_id"]), str(value.get("name") or ""), value.get("tag_id") or None, value.get("tag_name") or None)


def save(conn: psycopg.Connection, guild_id: int, forum: Forum) -> None:
    with conn.transaction():
        conn.execute(
            """INSERT INTO runtime_settings (key, value, updated_at) VALUES (%s, %s, now())
               ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""",
            (KEY.format(guild_id), Jsonb({"channel_id": str(forum.channel_id), "name": forum.name, "tag_id": forum.tag_id, "tag_name": forum.tag_name})))


def clear(conn: psycopg.Connection, guild_id: int) -> bool:
    """Debates go back to threads under the channel. True if there was a forum."""
    with conn.transaction():
        return conn.execute("DELETE FROM runtime_settings WHERE key = %s", (KEY.format(guild_id),)).rowcount > 0


def find_tag(available: list, wanted: str) -> dict | None:
    """The label of the forum that a moderator meant: its name as typed, without accents or case (then as the start of a name, if only one fits)."""
    tags = [t for t in available if isinstance(t, dict) and t.get("id") and t.get("name")]
    exact = [t for t in tags if words(t["name"]) == words(wanted) and words(wanted)]
    if len(exact) == 1:
        return exact[0]
    start = [t for t in tags if words(wanted) and words(t["name"]) >= words(wanted)]
    return start[0] if len(start) == 1 and not exact else None


def tag_names(available: list) -> str:
    return ", ".join(f"« {t['name']} »" for t in available if isinstance(t, dict) and t.get("name"))


def pick_tags(available: list, default_id: str | None, axis_name: str | None) -> list[str]:
    """The labels that a debate carries: the one chosen by the moderator, first, then the (unmoderated) labels whose whole name is made of words of the axis's name. At most 5."""
    by_id = {str(t["id"]): t for t in available if isinstance(t, dict) and t.get("id")}
    picked: list[str] = []
    if default_id and str(default_id) in by_id:
        picked.append(str(default_id))
    if axis_name:
        axis_words = words(axis_name)
        for tag_id, tag in by_id.items():
            if tag_id not in picked and not tag.get("moderated") and words(tag.get("name", "")) and words(tag["name"]) <= axis_words:
                picked.append(tag_id)
    return picked[:MAX_TAGS]
