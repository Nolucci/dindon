"""The forum where the debates of a server are created, when there is one (docs/regles-du-bot.md, « Un forum pour les débats »).

Many servers keep their debates in a **forum channel** (Discord's type 15): every debate is a *post* with labels (« étiquettes », Discord's *tags*: Économie, Religion…). A moderator tells Dindon
once, with `/dindon param`, which forum it is; from then on a debate that is opened in a thread is created there, as a post, instead of a thread under the channel where the command was
used: the channel is not polluted. Nothing is stored of a person: the channel, its name and, if asked, the label that every debate carries.

**The labels.** Dindon matches the debate topic and axis to the labels actually present in the forum. The optional label chosen by a
moderator is a fallback. A required-label forum without a fallback needs an open general label (Politique or Philosophie).
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
GENERAL_TAGS = ("politique", "philosophie")
# Distinctive words only: generic words such as « droit » or « état » cause false matches.
HINTS = {
    "economie": {"economie", "economique", "salaire", "smic", "impot", "taxe", "budget", "inflation", "emploi", "travail"},
    "religion": {"religion", "religieux", "laicite", "eglise", "islam", "christianisme"},
    "philosophie": {"philosophie", "philosophique", "morale", "ethique", "liberte"},
    "legislation": {"legislation", "loi", "lois", "juridique", "justice", "legalisation"},
    "international": {"international", "europe", "europeen", "etranger", "diplomatie", "geopolitique", "commerce"},
    "immigration": {"immigration", "immigre", "migrants", "migration", "frontiere", "asile"},
    "service public": {"fonctionnaire", "administration", "collectivite"},
    "ecologie": {"ecologie", "ecologique", "climat", "carbone", "pollution", "biodiversite", "environnement"},
    "sante": {"sante", "hopital", "hopitaux", "medecin", "medical", "soins", "vaccin"},
    "identite": {"identite", "nationalite", "culture", "tradition"},
    "genre": {"genre", "femmes", "hommes", "feminisme", "sexiste"},
    "lgbt": {"lgbt", "lgbtq", "homosexualite", "homophobie", "transgenre"},
    "education": {"education", "ecole", "enseignant", "universite", "scolaire", "bac"},
    "securite": {"securite", "police", "criminalite", "delinquance", "violence"},
    "politique": {"politique", "election", "democratie", "parti", "gouvernement"},
    "sport": {"sport", "sportif", "football", "olympique"},
    "territoire": {"territoire", "rural", "region", "commune", "urbanisme"},
    "numerique": {"numerique", "internet", "informatique", "donnees", "algorithme"},
    "jeunesse": {"jeunesse", "jeunes", "adolescent", "mineurs"},
}


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


def general_tag(available: list) -> str | None:
    """An honest, open fallback when a forum requires a label and the subject has no clear match."""
    for name in GENERAL_TAGS:
        for tag in available:
            if isinstance(tag, dict) and not tag.get("moderated") and words(tag.get("name", "")) == set(name.split()) and tag.get("id"):
                return str(tag["id"])
    return None


def pick_tags(available: list, default_id: str | None, axis_name: str | None, topic: str | None = None,
              *, required: bool = False) -> list[str]:
    """Match the topic and axis to available open labels. The moderator's label is used when none match."""
    by_id = {str(t["id"]): t for t in available if isinstance(t, dict) and t.get("id")}
    picked: list[str] = []
    subject = words(" ".join((axis_name or "", topic or "")))
    matches = []
    for tag_id, tag in by_id.items():
        if tag.get("moderated"):
            continue
        name = " ".join(sorted(words(tag.get("name", ""))))
        tag_words = words(tag.get("name", ""))
        exact = bool(tag_words and tag_words <= subject)
        hints = HINTS.get(name, set()) & subject
        if exact or hints:
            matches.append((2 if exact else 1, len(hints), tag_id))
    matches.sort(key=lambda match: (-match[0], -match[1], match[2]))
    picked.extend(tag_id for _, _, tag_id in matches[:MAX_TAGS])
    if default_id and str(default_id) in by_id and str(default_id) not in picked:
        picked.append(str(default_id))
    if not picked and required:
        fallback = general_tag(available)
        if fallback:
            picked.append(fallback)
    return picked[:MAX_TAGS]


POLL_KEY = "debate_polls.{}"


def poll_channel(conn: psycopg.Connection, guild_id: int) -> int | None:
    row = conn.execute("SELECT value FROM runtime_settings WHERE key = %s", (POLL_KEY.format(guild_id),)).fetchone()
    return int(row[0]["channel_id"]) if row and isinstance(row[0], dict) and str(row[0].get("channel_id", "")).isdigit() else None


def save_poll_channel(conn: psycopg.Connection, guild_id: int, channel_id: int) -> None:
    conn.execute("""INSERT INTO runtime_settings (key, value, updated_at) VALUES (%s, %s, now())
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = now()""",
                 (POLL_KEY.format(guild_id), Jsonb({"channel_id": str(channel_id)})))
