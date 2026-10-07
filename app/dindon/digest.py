"""A short digest of a server: its themes, the positions taken on them, and the contradictions found.

One screen of text (or JSON) made only of what the analysis already holds, with the people who asked not to be recorded left out. Read only.
Every line is a reading made by a program of the messages, not a fact: the proofs (quotes and links) are on the cards of the people (`/dindon card`).
"""
from __future__ import annotations

import psycopg
from psycopg.rows import tuple_row

from dindon.api.common import LABEL

HIDDEN = "NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = {user})"
LIVE = "p.status NOT IN ('rejected', 'merged')"


def build(conn: psycopg.Connection, guild_id: int, *, limit: int = 10) -> dict:
    """The themes, positions and contradictions of one server, each list cut to `limit` lines (the most telling first)."""
    previous = conn.row_factory           # the web pool gives dictionaries; the queries below read tuples
    conn.row_factory = tuple_row
    try:
        return {"guild": guild_id, "themes": _themes(conn, guild_id, limit), "positions": _positions(conn, guild_id, limit),
                "contradictions": _contradictions(conn, guild_id, limit)}
    finally:
        conn.row_factory = previous


def _themes(conn: psycopg.Connection, guild_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        f"""SELECT t.label, t.status, count(DISTINCT p.id)::int, count(DISTINCT s.user_id)::int
            FROM topics t JOIN propositions p ON p.topic_id = t.id AND {LIVE}
            JOIN current_stances s ON s.proposition_id = p.id AND s.guild_id = %s AND {HIDDEN.format(user='s.user_id')}
            WHERE (t.guild_id = %s OR t.guild_id IS NULL) AND t.status NOT IN ('rejected', 'merged')
            GROUP BY t.id, t.label, t.status ORDER BY count(DISTINCT s.user_id) DESC, t.label LIMIT %s""", (guild_id, guild_id, limit)).fetchall()
    return [{"theme": label, "status": status, "propositions": props, "people": people} for label, status, props, people in rows]


def _positions(conn: psycopg.Connection, guild_id: int, limit: int) -> list[dict]:
    """The propositions on which the most people took a side, with how the sides split."""
    rows = conn.execute(
        f"""SELECT p.text, t.label, count(*) FILTER (WHERE s.stance = 1)::int, count(*) FILTER (WHERE s.stance = -1)::int, count(*) FILTER (WHERE s.stance = 0)::int
            FROM current_stances s JOIN propositions p ON p.id = s.proposition_id AND {LIVE} LEFT JOIN topics t ON t.id = p.topic_id
            WHERE s.guild_id = %s AND {HIDDEN.format(user='s.user_id')}
            GROUP BY p.id, p.text, t.label ORDER BY count(*) DESC, p.text LIMIT %s""", (guild_id, limit)).fetchall()
    return [{"position": text, "theme": theme, "for": pour, "against": contre, "nuanced": nuance} for text, theme, pour, contre, nuance in rows]


def _contradictions(conn: psycopg.Connection, guild_id: int, limit: int) -> dict:
    against = conn.execute(
        f"""SELECT {LABEL}, c.role_name, ax.name FROM ideology_concordance c JOIN axes ax ON ax.id = c.axis_id
            JOIN users u ON u.id = c.user_id LEFT JOIN members m ON m.guild_id = c.guild_id AND m.user_id = u.id
            WHERE c.guild_id = %s AND c.verdict = 'incompatible' AND NOT u.is_bot AND {HIDDEN.format(user='u.id')}
            ORDER BY abs(c.score) DESC LIMIT %s""", (guild_id, limit)).fetchall()
    roles = conn.execute(
        f"""SELECT {LABEL}, ia.name, ib.name, ax.name FROM claimed_ideology_conflicts c JOIN ideologies ia ON ia.id = c.ideology_a
            JOIN ideologies ib ON ib.id = c.ideology_b JOIN axes ax ON ax.id = c.axis_id JOIN users u ON u.id = c.user_id
            LEFT JOIN members m ON m.guild_id = c.guild_id AND m.user_id = u.id
            WHERE c.guild_id = %s AND NOT u.is_bot AND {HIDDEN.format(user='u.id')} ORDER BY 1 LIMIT %s""", (guild_id, limit)).fetchall()
    changes = conn.execute(
        f"""SELECT {LABEL}, p.text, count(DISTINCT cl.stance)::int FROM claims cl JOIN propositions p ON p.id = cl.proposition_id AND {LIVE}
            JOIN users u ON u.id = cl.user_id LEFT JOIN members m ON m.guild_id = cl.guild_id AND m.user_id = u.id
            WHERE cl.guild_id = %s AND cl.stance IS NOT NULL AND cl.review_status <> 'rejected' AND NOT u.is_bot AND {HIDDEN.format(user='u.id')}
            GROUP BY u.id, m.nickname, u.global_name, u.name, p.id, p.text HAVING count(DISTINCT cl.stance) > 1
            ORDER BY count(DISTINCT cl.stance) DESC, 1 LIMIT %s""", (guild_id, limit)).fetchall()
    return {"against_own_roles": [{"person": who, "role": role, "axis": axis} for who, role, axis in against],
            "opposed_roles": [{"person": who, "roles": [a, b], "axis": axis} for who, a, b, axis in roles],
            "changed_mind": [{"person": who, "position": text} for who, text, _ in changes]}


PARTS = ("themes", "positions", "contradictions")


def only(digest: dict, part: str) -> dict:
    """The digest cut to one part ("all" keeps everything)."""
    return digest if part == "all" else {"guild": digest["guild"], part: digest[part]}


def to_markdown(digest: dict) -> str:
    """The digest as short Markdown: a title and a few bullets per part present."""
    lines = [f"# Synthèse du serveur {digest['guild']}"]
    if "themes" in digest:
        lines += ["", "## Thèmes"]
        lines += [f"- **{t['theme']}** : {t['propositions']} positions, {t['people']} personnes" for t in digest["themes"]] or ["- aucun thème"]
    if "positions" in digest:
        lines += ["", "## Positions"]
        lines += [f"- {p['position']} : {p['for']} pour, {p['against']} contre, {p['nuanced']} nuancé" + (f" ({p['theme']})" if p["theme"] else "")
                  for p in digest["positions"]] or ["- aucune position"]
    if "contradictions" in digest:
        c = digest["contradictions"]
        lines += ["", "## Contradictions"]
        lines += [f"- {x['person']} : rôle « {x['role']} » incompatible avec ses propos sur « {x['axis']} »" for x in c["against_own_roles"]]
        lines += [f"- {x['person']} : rôles opposés {x['roles'][0]} / {x['roles'][1]} sur « {x['axis']} »" for x in c["opposed_roles"]]
        lines += [f"- {x['person']} : a changé d'avis sur « {x['position']} »" for x in c["changed_mind"]]
        if not (c["against_own_roles"] or c["opposed_roles"] or c["changed_mind"]):
            lines.append("- aucune contradiction trouvée")
    return "\n".join(lines) + "\n"
