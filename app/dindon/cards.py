"""The card of a person: what Dindon knows of them in one server, as four pages of embeds that `/dindon card @someone` posts in the channel and that buttons
turn: **Profil** (who, how much, where), **Interactions** (with whom), **Positions** (what they said, with the proof) and **Contradictions** (what they say
against the roles that they gave themselves, with the proof, and the times they changed their mind).

Every position and every contradiction is a reading made by a program of the messages, said as such, and carries its proof: a short quote and the link to the
message (Discord checks on the click that the reader may see it). A person who asked not to be recorded, a bot, and somebody Dindon has never seen have no card
(the caller says so); people who asked not to be recorded never appear on the card of another either. Read only.
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from dindon.api.common import LABEL

BLURPLE = 0x5865F2
MIN_SCORE = 0.3          # an axis is shown when the person stands at least this far from the middle
CDN = "https://cdn.discordapp.com"
PAGES = ("Profil", "Interactions", "Positions", "Contradictions")
ICONS = ("🪪", "🤝", "💬", "⚖️")
COLORS = (BLURPLE, 0x1ABC9C, 0xE67E22, 0xE74C3C)
QUOTE_CHARS = 110
KEY = "discord_card"
PAGE_KEYS = ("profile", "interactions", "positions", "contradictions")          # the four pages, in the order of PAGES
BLOCKS = {                                                                      # what each page is made of: the administrator switches each block on or off
    "profile": ("headline", "activity", "channels", "roles", "presence"),
    "interactions": ("close", "replies", "sides"),
    "positions": ("axes", "positions"),
    "contradictions": ("verdicts", "against", "conflicts", "changes"),
}
DEFAULT = {"pages": list(PAGE_KEYS), "blocks": {page: list(blocks) for page, blocks in BLOCKS.items()}}
HIDDEN = "NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = {user})"     # the people who asked not to be recorded
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def clean(values: dict | None) -> dict:
    """The settings of the card, whatever was stored or sent: only known pages and blocks, at least one page. What is missing is shown (the card as it always was)."""
    values = values or {}
    pages = [p for p in PAGE_KEYS if p in values["pages"]] if isinstance(values.get("pages"), list) else list(PAGE_KEYS)
    blocks = {}
    for page, known in BLOCKS.items():
        chosen = (values.get("blocks") or {}).get(page) if isinstance(values.get("blocks"), dict) else None
        blocks[page] = [b for b in known if b in chosen] if isinstance(chosen, list) else list(known)
    return {"pages": pages or list(PAGE_KEYS), "blocks": blocks}


def load(conn: psycopg.Connection) -> dict:
    from dindon.automation import _get
    return clean(_get(conn, KEY))


def save(conn: psycopg.Connection, values: dict) -> dict:
    from dindon.automation import _put
    cfg = clean(values)
    _put(conn, KEY, cfg)
    return cfg


def person_card(conn: psycopg.Connection, guild_id: int, user_id: int) -> dict | None:
    """Everything the four pages need, or None (never seen, a bot, or somebody who asked not to be recorded)."""
    who = conn.execute(f"""SELECT {LABEL}, m.color, u.is_bot, u.name FROM users u LEFT JOIN members m ON m.guild_id = %s AND m.user_id = u.id
                           WHERE u.id = %s AND {HIDDEN.format(user='u.id')}""", (guild_id, user_id)).fetchone()
    if who is None or who[2]:
        return None
    stats = conn.execute(
        """SELECT count(*), count(DISTINCT m.sent_at::date), min(m.sent_at), max(m.sent_at), count(*) FILTER (WHERE m.reference_message_id IS NOT NULL),
                  COALESCE(avg(length(m.content)), 0)::int, count(*) FILTER (WHERE m.sent_at > now() - interval '30 days')
           FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s AND m.author_id = %s""", (guild_id, user_id)).fetchone()
    if not stats[0]:
        return None
    card: dict = {"id": user_id, "guild": guild_id, "name": who[0], "color": who[1], "username": who[3],
                  "messages": stats[0], "days": stats[1], "first": stats[2], "last": stats[3], "replies": stats[4], "length": stats[5], "recent": stats[6]}
    card["rank"] = conn.execute(
        """SELECT 1 + count(*) FROM (SELECT m.author_id, count(*) n FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s GROUP BY m.author_id) t
           WHERE t.n > %s""", (guild_id, stats[0])).fetchone()[0]
    card["writers"] = conn.execute("SELECT count(DISTINCT m.author_id) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s", (guild_id,)).fetchone()[0]
    when = conn.execute(
        """SELECT extract(hour FROM m.sent_at AT TIME ZONE 'Europe/Paris')::int h, extract(isodow FROM m.sent_at AT TIME ZONE 'Europe/Paris')::int d, count(*)
           FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s AND m.author_id = %s GROUP BY 1, 2""", (guild_id, user_id)).fetchall()
    hours: dict[int, int] = {}
    weekdays: dict[int, int] = {}
    for hour, day, n in when:
        hours[hour] = hours.get(hour, 0) + n
        weekdays[day] = weekdays.get(day, 0) + n
    card["hour"] = max(hours, key=hours.get) if hours else None
    card["weekday"] = DAYS[max(weekdays, key=weekdays.get) - 1] if weekdays else None
    card["channels"] = conn.execute(
        """SELECT c.name, count(*) FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s AND m.author_id = %s
           GROUP BY c.id, c.name ORDER BY count(*) DESC LIMIT 5""", (guild_id, user_id)).fetchall()
    card["received"] = conn.execute(
        """SELECT COALESCE(sum(r.count), 0)::int, (SELECT count(*) FROM mentions mn JOIN messages x ON x.id = mn.message_id JOIN channels cx ON cx.id = x.channel_id
                                                    WHERE cx.guild_id = %(g)s AND mn.user_id = %(u)s)
           FROM reactions r JOIN messages m ON m.id = r.message_id JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %(g)s AND m.author_id = %(u)s""",
        {"g": guild_id, "u": user_id}).fetchone()
    card["roles"] = [r[0] for r in conn.execute(
        """SELECT DISTINCT i.name FROM claimed_ideologies ci JOIN ideologies i ON i.id = ci.ideology_id WHERE ci.guild_id = %s AND ci.user_id = %s ORDER BY i.name""",
        (guild_id, user_id))]
    _interactions(conn, card)
    _positions(conn, card)
    _contradictions(conn, card)
    return card


def _link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _interactions(conn: psycopg.Connection, card: dict) -> None:
    g, u = card["guild"], card["id"]
    people = lambda direction, kinds, limit: conn.execute(  # noqa: E731
        f"""SELECT {LABEL}, round(sum(e.n))::int FROM edges e JOIN users u ON u.id = e.{'to' if direction == 'out' else 'from'}_user_id
            LEFT JOIN members m ON m.guild_id = e.guild_id AND m.user_id = u.id
            WHERE e.guild_id = %s AND e.{'from' if direction == 'out' else 'to'}_user_id = %s AND e.kind = ANY(%s) AND NOT u.is_bot AND u.id <> %s
              AND {HIDDEN.format(user='u.id')} GROUP BY u.id, m.nickname, u.global_name, u.name ORDER BY sum(e.weight) DESC LIMIT {limit}""", (g, u, kinds, u)).fetchall()
    card["close"] = conn.execute(
        f"""SELECT {LABEL}, round(sum(e.n))::int FROM (SELECT CASE WHEN from_user_id = %(u)s THEN to_user_id ELSE from_user_id END AS other, weight, n FROM edges
                                                        WHERE guild_id = %(g)s AND (from_user_id = %(u)s OR to_user_id = %(u)s)) e
            JOIN users u ON u.id = e.other LEFT JOIN members m ON m.guild_id = %(g)s AND m.user_id = u.id
            WHERE NOT u.is_bot AND u.id <> %(u)s AND {HIDDEN.format(user='u.id')} GROUP BY u.id, m.nickname, u.global_name, u.name ORDER BY sum(e.weight) DESC LIMIT 5""",
        {"u": u, "g": g}).fetchall()
    card["replies_to"] = people("out", ["reply"], 3)
    card["replied_by"] = people("in", ["reply"], 3)
    card["mentions"] = conn.execute(
        """SELECT COALESCE(sum(n) FILTER (WHERE from_user_id = %(u)s AND kind = 'mention'), 0)::int, COALESCE(sum(n) FILTER (WHERE to_user_id = %(u)s AND kind = 'mention'), 0)::int
           FROM edges WHERE guild_id = %(g)s""", {"u": u, "g": g}).fetchone()
    # Who they take the same side as, and who the opposite, on the propositions that both took a position on (at least two shared)
    sides = conn.execute(
        f"""SELECT {LABEL}, sum((a.stance = b.stance)::int)::int, sum((a.stance = -b.stance AND a.stance <> 0)::int)::int, count(*)::int
            FROM current_stances a JOIN current_stances b ON b.guild_id = a.guild_id AND b.proposition_id = a.proposition_id AND b.user_id <> a.user_id
            JOIN users u ON u.id = b.user_id LEFT JOIN members m ON m.guild_id = a.guild_id AND m.user_id = u.id
            WHERE a.guild_id = %s AND a.user_id = %s AND NOT u.is_bot AND {HIDDEN.format(user='u.id')}
            GROUP BY u.id, m.nickname, u.global_name, u.name HAVING count(*) >= 2""", (g, u)).fetchall()
    card["agree"] = sorted((s for s in sides if s[1] > s[2]), key=lambda s: (-s[1], s[0]))[:3]
    card["disagree"] = sorted((s for s in sides if s[2] > s[1]), key=lambda s: (-s[2], s[0]))[:3]


def _evidence(conn: psycopg.Connection, guild_id: int, claim_ids: list[int]) -> dict[int, tuple[str, str, datetime]]:
    """For each claim, its first proof: the quote, the link to the message, its date."""
    out: dict[int, tuple[str, str, datetime]] = {}
    if not claim_ids:
        return out
    for claim, quote, channel, message, at in conn.execute(
            """SELECT e.claim_id, e.quote, m.channel_id, m.id, m.sent_at FROM claim_evidence e JOIN messages m ON m.id = e.message_id
               WHERE e.claim_id = ANY(%s) ORDER BY m.sent_at, m.id""", (claim_ids,)):
        out.setdefault(claim, ((quote or "").strip(), _link(guild_id, channel, message), at))
    return out


def _positions(conn: psycopg.Connection, card: dict) -> None:
    g, u = card["guild"], card["id"]
    card["axes"] = conn.execute(
        """SELECT a.name, a.negative_pole, a.positive_pole, s.score::float8, s.uncertainty::float8, s.n_propositions FROM person_axis_scores s
           JOIN axes a ON a.id = s.axis_id AND a.is_active WHERE s.guild_id = %s AND s.user_id = %s AND abs(s.score) >= %s ORDER BY abs(s.score) DESC LIMIT 5""",
        (g, u, MIN_SCORE)).fetchall()
    rows = conn.execute(
        """SELECT p.text, s.stance, s.confidence::float8, s.stated_at, s.claim_id FROM current_stances s JOIN propositions p ON p.id = s.proposition_id
           WHERE s.guild_id = %s AND s.user_id = %s AND p.status NOT IN ('rejected', 'merged') ORDER BY s.confidence DESC, s.stated_at DESC LIMIT 5""", (g, u)).fetchall()
    card["total_positions"] = conn.execute("SELECT count(*) FROM current_stances WHERE guild_id = %s AND user_id = %s", (g, u)).fetchone()[0]
    proofs = _evidence(conn, g, [r[4] for r in rows])
    card["positions"] = [(text, stance, confidence, at, proofs.get(claim)) for text, stance, confidence, at, claim in rows]


def _contradictions(conn: psycopg.Connection, card: dict) -> None:
    g, u = card["guild"], card["id"]
    card["verdicts"] = conn.execute(
        """SELECT role_name, verdict FROM claimed_ideology_summary WHERE guild_id = %s AND user_id = %s ORDER BY (verdict = 'discordant') DESC, role_name""", (g, u)).fetchall()
    bad = conn.execute(
        """SELECT c.axis_id, c.role_name, ax.name, ax.negative_pole, ax.positive_pole, c.score::float8, c.uncertainty::float8, c.min_score::float8, c.max_score::float8
           FROM ideology_concordance c JOIN axes ax ON ax.id = c.axis_id WHERE c.guild_id = %s AND c.user_id = %s AND c.verdict = 'incompatible' ORDER BY abs(c.score) DESC LIMIT 4""",
        (g, u)).fetchall()
    claims = {}
    for axis in {r[0] for r in bad}:
        claims[axis] = conn.execute(
            """SELECT p.text, s.stance, s.claim_id FROM current_stances s JOIN proposition_axis pa ON pa.proposition_id = s.proposition_id AND pa.loading <> 0
               JOIN propositions p ON p.id = s.proposition_id WHERE s.guild_id = %s AND s.user_id = %s AND pa.axis_id = %s AND p.status NOT IN ('rejected', 'merged')
               ORDER BY abs(pa.loading * s.stance * s.confidence) DESC LIMIT 2""", (g, u, axis)).fetchall()
    proofs = _evidence(conn, g, [c[2] for rows in claims.values() for c in rows])
    card["against"] = [(role, axis, negative, positive, score, uncertainty, low, high,
                        [(text, stance, proofs.get(claim)) for text, stance, claim in claims[axis_id]])
                       for axis_id, role, axis, negative, positive, score, uncertainty, low, high in bad]
    card["conflicts"] = conn.execute(
        """SELECT ia.name, ib.name, ax.name FROM claimed_ideology_conflicts c JOIN ideologies ia ON ia.id = c.ideology_a JOIN ideologies ib ON ib.id = c.ideology_b
           JOIN axes ax ON ax.id = c.axis_id WHERE c.guild_id = %s AND c.user_id = %s""", (g, u)).fetchall()
    # Changes of mind: a proposition on which the person took a different side later
    changes = conn.execute(
        """SELECT p.text, array_agg(cl.stance ORDER BY cl.stated_at), array_agg(cl.stated_at ORDER BY cl.stated_at), array_agg(cl.id ORDER BY cl.stated_at)
           FROM claims cl JOIN propositions p ON p.id = cl.proposition_id WHERE cl.guild_id = %s AND cl.user_id = %s AND cl.stance IS NOT NULL
             AND cl.review_status <> 'rejected' AND p.status NOT IN ('rejected', 'merged') GROUP BY p.id, p.text HAVING count(DISTINCT cl.stance) > 1 LIMIT 3""", (g, u)).fetchall()
    proofs = _evidence(conn, g, [claim for _, _, _, ids in changes for claim in ids])
    card["changes"] = [(text, stances, dates, [proofs.get(claim) for claim in ids]) for text, stances, dates, ids in changes]


# --- the look ---------------------------------------------------------------------------------------------------------


def _date(value: datetime) -> str:
    return value.strftime("%d/%m/%Y")


def _color(text: str | None) -> int:
    try:
        return int(text.lstrip("#"), 16) if text and text.upper() != "#000000" else BLURPLE
    except ValueError:
        return BLURPLE


def avatar_url(user: dict | None) -> str | None:
    """The avatar of a user of an interaction (`resolved.users`), as Discord's CDN gives it; None when the person has the default one."""
    if user and user.get("avatar") and user.get("id"):
        return f"{CDN}/avatars/{user['id']}/{user['avatar']}.png?size=128"
    return None


def _cut(text: str, size: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def _gauge(score: float, size: int = 9) -> str:
    """A line with a dot where the score stands between the two poles (-1 left, +1 right)."""
    place = max(0, min(size - 1, round((score + 1) / 2 * (size - 1))))
    return "─" * place + "●" + "─" * (size - 1 - place)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _proof(proof: tuple[str, str, datetime] | None) -> str:
    """The quote on its own line (a block quote), then the link: easy to see where it begins and ends."""
    if proof is None:
        return "> *pas de preuve gardée*"
    quote, link, at = proof
    return (f"> « {_cut(quote, QUOTE_CHARS)} »\n" if quote else "") + f"> [voir le message]({link}) · {_date(at)}"


def _section(title: str, lines: list[str]) -> str:
    return f"**{title}**\n" + "\n".join(lines)


def _page_profile(card: dict, on: tuple | list = BLOCKS["profile"]) -> str:
    share = round(100 * card["replies"] / card["messages"])
    habits = [f"{card['recent']} messages ces 30 derniers jours · {share} % de réponses"]
    if card["hour"] is not None and card["weekday"]:
        habits.append(f"Écrit surtout le {card['weekday']}, vers {card['hour']} h (Paris)")
    reactions, mentions = card["received"]
    habits.append(f"{_plural(reactions, 'réaction reçue', 'réactions reçues')} · {_plural(mentions, 'mention', 'mentions')}")
    blocks = []
    if "headline" in on:
        blocks.append(f"**{card['messages']:,} messages**".replace(",", " ") + f" · {card['days']} jours actifs · n°{card['rank']} sur {card['writers']}")
    if "activity" in on:
        blocks.append(_section("Activité", habits))
    if "channels" in on:
        blocks.append(_section("Salons", [f"#{name} · {n}" for name, n in card["channels"][:3]]))
    if card["roles"] and "roles" in on:
        blocks.append(_section("Se réclame de", [", ".join(card["roles"])]))
    if "presence" in on:
        blocks.append(f"*Présent·e du {_date(card['first'])} au {_date(card['last'])}*")
    return "\n\n".join(blocks) or _EMPTY


def _page_interactions(card: dict, on: tuple | list = BLOCKS["interactions"]) -> str:
    names = lambda rows: ", ".join(name for name, *_ in rows)  # noqa: E731
    blocks = [_section("Échange surtout avec", [f"{name} · {_plural(n, 'échange', 'échanges')}" for name, n in card["close"][:3]] or ["*pas encore d'échange*"])] if "close" in on else []
    replies = [f"Répond surtout à {names(card['replies_to'][:2])}" if card["replies_to"] else "", f"Reçoit surtout des réponses de {names(card['replied_by'][:2])}" if card["replied_by"] else ""]
    if any(replies) and "replies" in on:
        blocks.append("\n".join(line for line in replies if line))
    sides = [f"Du même avis que {names(card['agree'][:2])}" if card["agree"] else "", f"Souvent opposé·e à {names(card['disagree'][:2])}" if card["disagree"] else ""]
    if "sides" in on:
        blocks.append(_section("Accords et désaccords", [line for line in sides if line] or ["*pas assez de positions communes pour le dire*"]))
    return "\n\n".join(blocks) or _EMPTY


_EMPTY = "*Rien à montrer ici.*"
STANCE = {1: "✅ pour", -1: "❌ contre", 0: "➖ nuancé"}


def _page_positions(card: dict, on: tuple | list = BLOCKS["positions"]) -> str:
    blocks = []
    if card["axes"] and "axes" in on:
        blocks.append(_section("Où il·elle se situe", [f"{negative} `{_gauge(score)}` {positive}" for _, negative, positive, score, _, _ in card["axes"][:3]]))
    for text, stance, _confidence, _at, proof in (card["positions"][:3] if "positions" in on else []):
        blocks.append(f"**{STANCE.get(stance, '❔')}** · {_cut(text, 160)}\n{_proof(proof)}")
    if not card["positions"] and not card["axes"]:
        return "*L'analyse n'a pas encore lu de position de cette personne.*"
    if not blocks:
        return _EMPTY
    more = card["total_positions"] - len(card["positions"][:3]) if "positions" in on else 0
    blocks.append("*Lecture automatique de ses messages, pas un verdict.*" + (f" {_plural(more, 'autre position non montrée', 'autres positions non montrées')}." if more > 0 else ""))
    return "\n\n".join(blocks)


VERDICT = {"concordant": "✅ cohérent", "discordant": "⚠️ en contradiction", "not_verifiable": "pas assez de propos pour juger"}


def _page_contradictions(card: dict, on: tuple | list = BLOCKS["contradictions"]) -> str:
    if not card["verdicts"]:
        return "*Cette personne ne s'est donné aucun rôle d'idée : rien à comparer.*"
    blocks = [_section("Ses rôles face à ses propos", [f"{role} · {VERDICT[verdict]}" for role, verdict in card["verdicts"][:4]])] if "verdicts" in on else []
    for role, axis, negative, positive, score, _uncertainty, low, high, claims in (card["against"][:2] if "against" in on else []):
        side = positive if score > 0 else negative
        lines = [f"Le rôle attend plutôt : {positive if low > 0 else negative if high < 0 else 'le milieu'}. Ses propos vont vers : {side}."]
        for text, stance, proof in claims[:1]:
            lines += [f"{STANCE.get(stance, '❔')} · {_cut(text, 110)}", _proof(proof)]
        blocks.append(_section(f"⚠️ {role} · {axis}", lines))
    for a, b, axis in (card["conflicts"][:2] if "conflicts" in on else []):
        blocks.append(_section(f"🔀 {a} et {b}", [f"Deux rôles qui s'opposent sur « {axis} » : une contradiction, quoi qu'il·elle dise."]))
    for text, stances, dates, proofs in (card["changes"][:2] if "changes" in on else []):
        path = " → ".join(f"{STANCE.get(st, '❔')} ({d.strftime('%d/%m')})" for st, d in zip(stances, dates, strict=False))
        blocks.append(_section(f"🔁 A changé d'avis · {_cut(text, 100)}", [path] + [_proof(pr) for pr in proofs[:1]]))
    if not (card["against"] or card["conflicts"] or card["changes"]) and {"against", "conflicts", "changes"} & set(on):
        blocks.append("🕊️ Aucune contradiction trouvée (sous réserve de ce que l'analyse a pu lire).")
    return "\n\n".join(blocks) or _EMPTY


def card_page(card: dict, page: int = 0, avatar: str | None = None, cfg: dict | None = None) -> dict:
    """One page of the card as a Discord embed (https://discord.com/developers/docs/resources/message#embed-object): one block of text, titles in bold,
    a blank line between the blocks, never more than three items in a list."""
    cfg = cfg or DEFAULT
    page = page if 0 <= page < len(PAGES) and PAGE_KEYS[page] in cfg["pages"] else PAGE_KEYS.index(cfg["pages"][0])    # a page that the administrator switched off is never shown
    description = (_page_profile, _page_interactions, _page_positions, _page_contradictions)[page](card, cfg["blocks"][PAGE_KEYS[page]])
    color = COLORS[page] if page else _color(card["color"])
    if page == 3 and not (card["against"] or card["conflicts"] or card["changes"]):
        color = 0x2ECC71
    shown = [i for i, key in enumerate(PAGE_KEYS) if key in cfg["pages"]]
    embed: dict = {"title": f"{ICONS[page]}  {card['name']} · {PAGES[page]}", "description": _cut_block(description, 3800), "color": color,
                   "footer": {"text": f"Page {shown.index(page) + 1}/{len(shown)} · /dindon info pour savoir comment les données sont gérées"}}
    if avatar:
        embed["thumbnail"] = {"url": avatar}
    return embed


def _cut_block(text: str, size: int) -> str:
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def card_embed(card: dict, avatar: str | None = None) -> dict:
    """The first page (kept for what only needs one embed)."""
    return card_page(card, 0, avatar)


def card_buttons(user_id: int, page: int = 0, cfg: dict | None = None) -> list[dict]:
    """The row of buttons that turns the pages: the current one is blue and cannot be clicked. The id says the person (anybody can turn the pages)."""
    return [{"type": 1, "components": [
        {"type": 2, "style": 1 if i == page else 2, "label": name, "emoji": {"name": ICONS[i]}, "custom_id": f"dindon:card:{i}:{user_id}", "disabled": i == page}
        for i, name in enumerate(PAGES) if PAGE_KEYS[i] in (cfg or DEFAULT)["pages"]]}]
