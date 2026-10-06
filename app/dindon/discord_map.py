"""The map that `/dindon map` posts on Discord: one picture (PNG) of who talks with whom, and what the admins let it show.

* **Off by default.** The admins switch it on and choose what it shows (page Système, panel « Carte sur Discord »): how many people, how many names, which
  kinds of exchange. The settings are in `runtime_settings` like the automatic reading.
* The data are the ones of the map of the interface (`api/routes.py`: same SQL, same weights), restricted to the settings. Whoever asked not to be recorded
  (`privacy_subjects`) is not on it, nor are bots. A picture is public in the channel: it shows only what the settings allow, never a message.
* With a person in focus the map is their strongest links and the links between those people, so that a question about someone cannot show more than that.
* Drawn with Pillow (twice as large, then reduced, for smooth lines); the places come from a small force-directed layout (numpy), the same every time for the
  same data. The interactive version (Discord Activity) comes with the public URL of the production.
"""
from __future__ import annotations

import contextlib
import functools
import io
import json
import math
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import psycopg
from PIL import Image, ImageDraw, ImageFont, ImageOps
from psycopg.rows import dict_row

from dindon import privacy
from dindon.api.common import LABEL
from dindon.api.routes import _ALL_TIME, _GRAPH, _PERIOD, MEMBER_COLORS, _color
from dindon.automation import _get, _put
from dindon.clock import utc_now

FONTS = Path(__file__).parent / "fonts"      # Inter, as in the interface (licence OFL: fonts/LICENSE-Inter.txt). Pillow's own font has no accents.
KEY = "discord_map"
KINDS = ("reply", "mention", "reaction")
PERIODS = {"7": ("7 derniers jours", 7), "30": ("30 derniers jours", 30), "90": ("90 derniers jours", 90), "all": ("Depuis le début", None)}
# What the card of a person shows (Activity). `roles` and `axes` are readings of what people say of themselves or think: like the automatic reading of the positions, they need
# the admin to confirm that the people are informed (`acknowledged`, docs/CONFORMITE.md), else they are never shown.
SECTIONS = ("activity", "months", "habits", "links", "roles", "axes")
SENSITIVE = ("roles", "axes")
MIN_SCORE = 0.3          # an axis is shown when the person stands at least this far from the middle (as on the card of /dindon card)
DEFAULT = {"enabled": False, "max_people": 40, "names": 15, "kinds": list(KINDS), "sections": ["activity", "months", "habits", "links"], "acknowledged": False}
WIDTH, HEIGHT, SCALE = 1280, 720, 2          # 16:9, like the background (and like the Activity)
ASSETS = Path(__file__).parent / "assets"
PANEL_WIDTH = 350                              # the card of the person, on the right
GOLD = (214, 165, 90)                          # the gold of the frame of the background
BACKGROUND, EDGE, FOCUS_RING, DEFAULT_NODE = (49, 51, 56), (181, 186, 193), (240, 178, 50), (219, 222, 225)   # the colors of the interface (lib/mapgraph.js)


def clean(values: dict) -> dict:
    out = dict(DEFAULT)
    out["enabled"] = bool(values.get("enabled", False))
    for key, (low, high) in {"max_people": (5, 80), "names": (0, 40)}.items():
        with contextlib.suppress(TypeError, ValueError):
            out[key] = min(max(int(values.get(key, DEFAULT[key])), low), high)
    kinds = [k for k in KINDS if k in (values.get("kinds") or [])] if "kinds" in values else list(KINDS)
    out["kinds"] = kinds or list(KINDS)
    out["acknowledged"] = bool(values.get("acknowledged", False))
    sections = [k for k in SECTIONS if k in (values.get("sections") or [])] if "sections" in values else list(DEFAULT["sections"])
    out["sections"] = [k for k in sections if out["acknowledged"] or k not in SENSITIVE]
    return out


def load(conn: psycopg.Connection) -> dict:
    return clean(_get(conn, KEY))


def save(conn: psycopg.Connection, values: dict) -> dict:
    cfg = clean(values)
    _put(conn, KEY, cfg)
    return cfg


def collect(conn: psycopg.Connection, guild_id: int, days: int | None, focus: int | None, cfg: dict) -> dict | None:
    """The people and links to draw, or None when there is nothing to show (or the person in focus is not to be shown)."""
    blocked = privacy.blocked_ids(conn)
    cur = conn.cursor(row_factory=dict_row)             # whatever the rows of the connection are (the bot's are tuples, the API's are dicts)
    if focus in blocked:
        return None
    now = utc_now()
    since = now - timedelta(days=days) if days else datetime(1970, 1, 1, tzinfo=UTC)
    params = {"guild": guild_id, "kinds": cfg["kinds"], "bots": False, "min_weight": 0, "limit": 500 if focus else cfg["max_people"] + len(blocked),
              "max_edges": 5000, "ref": now, "since": since, "until": datetime(2200, 1, 1, tzinfo=UTC)}
    rows = [r for r in cur.execute(_GRAPH.replace("{source}", _PERIOD if days else _ALL_TIME), params).fetchall()
            if r["a"] not in blocked and r["b"] not in blocked]
    if focus is not None:
        near = {}
        for r in rows:
            if focus in (r["a"], r["b"]):
                near[r["b"] if r["a"] == focus else r["a"]] = r["weight"]
        keep = {focus} | set(sorted(near, key=near.get, reverse=True)[:cfg["max_people"] - 1])
        rows = [r for r in rows if r["a"] in keep and r["b"] in keep]
    influence: dict[int, float] = {}
    for r in rows:
        influence[r["a"]] = influence.get(r["a"], 0) + r["weight"]
        influence[r["b"]] = influence.get(r["b"], 0) + r["weight"]
    people = sorted(influence, key=influence.get, reverse=True)[:cfg["max_people"]]
    if not people or (focus is not None and focus not in people):
        return None
    shown = set(people)
    labels = {r["id"]: r["label"] for r in cur.execute(
        f"SELECT u.id, {LABEL} AS label FROM users u LEFT JOIN members m ON m.guild_id = %s AND m.user_id = u.id WHERE u.id = ANY(%s)", (guild_id, people))}
    colors = {r["id"]: _color(r["color"]) for r in cur.execute(MEMBER_COLORS, (guild_id, people))}
    return {"people": [{"id": u, "label": labels.get(u, "?"), "color": colors.get(u), "influence": influence[u]} for u in people],
            "links": [(r["a"], r["b"], r["weight"]) for r in rows if r["a"] in shown and r["b"] in shown], "focus": focus,
            "counts": {(r["a"], r["b"]): int(r["n"]) for r in rows if r["a"] in shown and r["b"] in shown}}


def named(data: dict, cfg: dict) -> set[int]:
    """The people whose name the map shows: the most connected ones, as many as the admins allow, and the person in focus."""
    return {p["id"] for p in data["people"][:cfg["names"]]} | ({data["focus"]} if data["focus"] is not None else set())


def person(conn: psycopg.Connection, guild_id: int, user_id: int, data: dict, cfg: dict) -> dict | None:
    """The card of a person of the map, shorter than the one of the interface, with only the sections that the admins chose (cfg["sections"]). Only for somebody whose name the
    map shows, and the people it names are the ones that the map names too. Never a message, a channel (it may be private), nor another name that they went by."""
    shown = named(data, cfg)
    if user_id not in shown:
        return None
    sections = cfg["sections"]
    cur = conn.cursor(row_factory=dict_row)
    stats = cur.execute(
        """SELECT count(*) AS messages, min(m.sent_at) AS first_at, max(m.sent_at) AS last_at, count(DISTINCT (m.sent_at AT TIME ZONE 'UTC')::date) AS active_days,
                  COALESCE(round(avg(length(m.content))), 0)::int AS average_length, count(*) FILTER (WHERE m.reference_message_id IS NOT NULL) AS replies,
                  count(*) FILTER (WHERE m.sent_at > now() - interval '30 days') AS recent
           FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s AND m.author_id = %s""", (guild_id, user_id)).fetchone()
    if not stats["messages"]:
        return None
    card: dict = {"id": str(user_id), "label": next(p["label"] for p in data["people"] if p["id"] == user_id)}
    if "activity" in sections:
        days = max(stats["active_days"], 1)
        card["activity"] = {"messages": stats["messages"], "active_days": stats["active_days"], "messages_per_active_day": round(stats["messages"] / days, 1),
                            "average_length": stats["average_length"], "share_of_replies": round(stats["replies"] / stats["messages"], 3),
                            "first_message_at": stats["first_at"].isoformat(), "last_message_at": stats["last_at"].isoformat(), "recent": stats["recent"]}
        card["activity"]["rank"] = cur.execute(
            """SELECT 1 + count(*) AS rank FROM (SELECT m.author_id, count(*) n FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s GROUP BY m.author_id) t
               WHERE t.n > %s""", (guild_id, stats["messages"])).fetchone()["rank"]
        card["activity"]["writers"] = cur.execute(
            "SELECT count(DISTINCT m.author_id) AS n FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s", (guild_id,)).fetchone()["n"]
        card["activity"]["reactions_received"] = cur.execute(
            """SELECT COALESCE(sum(r.count), 0)::int AS n FROM reactions r JOIN messages m ON m.id = r.message_id JOIN channels c ON c.id = m.channel_id
               WHERE c.guild_id = %s AND m.author_id = %s""", (guild_id, user_id)).fetchone()["n"]
        card["activity"]["contacts"] = cur.execute(                       # people they exchanged with: not bots, not the people who asked not to be recorded
            """SELECT count(DISTINCT e.other) AS n FROM (SELECT CASE WHEN from_user_id = %(u)s THEN to_user_id ELSE from_user_id END AS other FROM edges
                                                          WHERE guild_id = %(g)s AND (from_user_id = %(u)s OR to_user_id = %(u)s)) e
               JOIN users u ON u.id = e.other WHERE NOT u.is_bot AND u.id <> %(u)s AND NOT EXISTS (SELECT 1 FROM privacy_subjects s WHERE s.user_id = u.id)""",
            {"u": user_id, "g": guild_id}).fetchone()["n"]
    if "habits" in sections:
        hours, weekdays = [0] * 24, [0] * 7
        for r in cur.execute(
                """SELECT extract(hour FROM m.sent_at AT TIME ZONE 'Europe/Paris')::int AS h, extract(isodow FROM m.sent_at AT TIME ZONE 'Europe/Paris')::int AS d, count(*) AS n
                   FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s AND m.author_id = %s GROUP BY 1, 2""", (guild_id, user_id)):
            hours[r["h"]] += r["n"]
            weekdays[r["d"] - 1] += r["n"]
        card["habits"] = {"hours": hours, "weekdays": weekdays}          # Monday first; counts only, never what was said
    if "months" in sections:
        card["by_month"] = list(reversed(cur.execute(
            """SELECT to_char(date_trunc('month', m.sent_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month, count(*) AS messages
               FROM messages m JOIN channels c ON c.id = m.channel_id WHERE c.guild_id = %s AND m.author_id = %s GROUP BY 1 ORDER BY 1 DESC LIMIT 12""",
            (guild_id, user_id)).fetchall()))
    if "links" in sections:
        names = {p["id"]: p["label"] for p in data["people"]}
        links = sorted(((b if a == user_id else a, w) for a, b, w in data["links"] if user_id in (a, b)), key=lambda link: -link[1])
        card["top_links"] = [{"id": str(o), "label": names[o], "weight": round(w, 3), "n": data["counts"].get((min(o, user_id), max(o, user_id)), 0)}
                             for o, w in links if o in shown][:8]
    if "roles" in sections:
        card["roles"] = [r["name"] for r in cur.execute(
            """SELECT DISTINCT i.name FROM claimed_ideologies ci JOIN ideologies i ON i.id = ci.ideology_id WHERE ci.guild_id = %s AND ci.user_id = %s ORDER BY i.name""",
            (guild_id, user_id))]
    if "axes" in sections:
        card["axes"] = [{"name": r["name"], "pole": r["negative_pole"] if r["score"] < 0 else r["positive_pole"], "score": round(float(r["score"]), 2),
                         "uncertainty": None if r["uncertainty"] is None else round(float(r["uncertainty"]), 2)}
                        for r in cur.execute(
            """SELECT a.name, a.negative_pole, a.positive_pole, s.score, s.uncertainty FROM person_axis_scores s JOIN axes a ON a.id = s.axis_id
               WHERE s.guild_id = %s AND s.user_id = %s AND a.is_active AND abs(s.score) >= %s ORDER BY abs(s.score) DESC LIMIT 5""", (guild_id, user_id, MIN_SCORE))]
    return card


def _layout(people: list[dict], links: list[tuple], focus: int | None, seed: int) -> np.ndarray:
    """Fruchterman-Reingold: every point pushes the others away, every link pulls its two points together (the stronger, the closer). The person in focus stays at the
    center, and the others are placed around them."""
    n = len(people)
    index = {p["id"]: i for i, p in enumerate(people)}
    rng = np.random.default_rng(seed)
    pos = rng.random((n, 2)) * 2 - 1
    weight = np.zeros((n, n))
    for a, b, w in links:
        weight[index[a], index[b]] = weight[index[b], index[a]] = w
    weight = weight / weight.max() if weight.max() > 0 else weight
    k = math.sqrt(4 / n)
    heat = 0.3
    for _ in range(250):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.maximum(np.linalg.norm(delta, axis=2), 0.01)
        push = (k * k / dist)[:, :, None] * delta / dist[:, :, None]
        pull = (dist * dist / k * (0.15 + weight))[:, :, None] * delta / dist[:, :, None]
        move = push.sum(axis=1) - pull.sum(axis=1)
        if focus is not None:
            move[index[focus]] = 0
            pos[index[focus]] = 0
        length = np.maximum(np.linalg.norm(move, axis=1), 1e-9)
        pos += move / length[:, None] * np.minimum(length, heat)[:, None]
        heat *= 0.985
    if focus is None:
        pos -= pos.mean(axis=0)
    span = np.abs(pos).max(axis=0)                  # (with a person in focus, they are at 0: the same scale on both sides keeps them at the center)
    return pos / np.where(span > 0, span, 1)


def _printable(label: str) -> str:
    """What the font can draw (Latin, with French accents): a name made of other letters or emoji would come out as squares, so those characters are left out."""
    return "".join(c for c in label if ord(c) < 0x100 or c in "œŒ’…").strip()


@functools.lru_cache(maxsize=8)
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("inter-latin-700-normal.woff" if bold else "inter-latin-600-normal.woff")), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    """The text, cut with … so that it is not wider than `width`."""
    while len(text) > 1 and draw.textlength(text, font=font) > width:
        text = text.rstrip("…")[:-1] + "…"
    return text


def _node_color(hex_color: str | None) -> tuple:
    color = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5)) if hex_color else DEFAULT_NODE
    return tuple(min(255, c + 90) for c in color) if sum(color) < 150 else color      # a black-ish role would vanish on the background


def _portrait(photo: bytes | None, diameter: int, color: tuple, ring: int) -> Image.Image:
    """A person: their photo in a circle with a ring of the color of their name; without photo, a plain disc of that color."""
    big = diameter * 3
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(out).ellipse([0, 0, big - 1, big - 1], fill=color + (255,))
    if photo is not None:
        inner = big - 2 * ring * 3
        try:
            square = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (inner, inner), Image.LANCZOS)
        except OSError:                                                      # not a picture after all: the disc stays
            square = None
        if square is not None:
            mask = Image.new("L", (inner, inner), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, inner - 1, inner - 1], fill=255)
            out.paste(square, (ring * 3, ring * 3), mask)
    return out.resize((diameter, diameter), Image.LANCZOS)


def _background(width: int, height: int) -> Image.Image:
    path = ASSETS / "activity-background.webp"
    if path.exists():
        return Image.open(path).convert("RGBA").resize((width, height), Image.LANCZOS)      # stretched to the picture, so that the golden frame sits on the edges
    return Image.new("RGBA", (width, height), (5, 11, 29, 255))


MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def _date(iso: str) -> str:
    return f"{int(iso[8:10])} {MONTHS[int(iso[5:7]) - 1]} {iso[:4]}"


def _panel(layer: ImageDraw.ImageDraw, box: tuple, fill: int = 175) -> None:
    layer.rounded_rectangle(box, radius=14 * SCALE, fill=(5, 10, 28, fill), outline=GOLD + (70,), width=SCALE)


def _bars(draw: ImageDraw.ImageDraw, values: list[int], box: tuple, labels: dict[int, str]) -> None:
    """Bars in a box (x0, y0, x1, y1): the tallest one in gold, the others in blurple; some labels under them."""
    x0, y0, x1, y1 = box
    top = max(values) or 1
    slot = (x1 - x0) / len(values)
    base = y1 - 14 * SCALE
    for i, value in enumerate(values):
        h = max(2 * SCALE if value else SCALE // 2, (value / top) * (base - y0))
        draw.rounded_rectangle([x0 + i * slot + slot * 0.14, base - h, x0 + i * slot + slot * 0.86, base], radius=SCALE, fill=(GOLD if value == top else (88, 101, 242)) + (255,))
    for i, text in labels.items():
        draw.text((x0 + (0 if i == 0 else i * slot + slot / 2), y1), text, font=_font(False, 9 * SCALE), fill=(181, 186, 193, 255), anchor="ls" if i == 0 else "ms")


def _card(canvas: Image.Image, card: dict, x0: int, y0: int, x1: int, y1: int, pictures: dict, colors: dict) -> None:
    """The card of the person, in the panel on the right: what the admins allowed, in the order of the Activity. A section that does not fit is left out."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))      # everything of the card is drawn here, then laid over the picture: translucent shapes (tiles, lines) need that
    draw = ImageDraw.Draw(layer)
    S = SCALE
    pad = 16 * S
    left, right, y = x0 + pad, x1 - pad, y0 + pad
    small, label, bold, title = _font(False, 10 * S), _font(False, 11 * S), _font(True, 13 * S), _font(True, 21 * S)
    muted, white = (181, 186, 193, 255), (242, 243, 245, 255)
    cid = int(card["id"])
    layer.alpha_composite(_portrait(pictures.get(cid), 62 * S, colors.get(cid, DEFAULT_NODE), 4 * S), (left, y))
    text_x = left + 74 * S
    draw.text((text_x, y + 4 * S), _fit(draw, _printable(card["label"]) or "?", title, right - text_x), font=title, fill=white)
    a = card.get("activity")
    if a:
        draw.text((text_x, y + 32 * S), f"Depuis le {_date(a['first_message_at'])}", font=small, fill=muted)
        badge = f"n° {a['rank']} sur {a['writers']} auteurs"
        w = draw.textlength(badge, font=small) + 14 * S
        draw.rounded_rectangle([text_x, y + 46 * S, text_x + w, y + 62 * S], radius=8 * S, fill=GOLD + (255,))
        draw.text((text_x + 7 * S, y + 54 * S), badge, font=small, fill=(27, 20, 5, 255), anchor="lm")
    y += 76 * S

    def title_of(text: str) -> None:
        nonlocal y
        draw.line([(left, y), (right, y)], fill=GOLD + (60,), width=S)
        draw.text((left, y + 12 * S), text.upper(), font=small, fill=GOLD + (255,))
        y += 24 * S

    if a:
        tiles = [(f"{a['messages']:,}".replace(",", " "), "messages", f"{a['recent']} sur 30 jours"), (str(a["active_days"]), "jours actifs", f"{a['messages_per_active_day']} par jour"),
                 (f"{round(a['share_of_replies'] * 100)} %", "de réponses", f"{a['average_length']} car. en moyenne"), (str(a["contacts"]), "contacts", f"{a['reactions_received']} réactions reçues")]
        width = (right - left - 8 * S) // 2
        for i, (value, name, note) in enumerate(tiles):
            tx, ty = left + (i % 2) * (width + 8 * S), y + (i // 2) * 60 * S
            draw.rounded_rectangle([tx, ty, tx + width, ty + 54 * S], radius=8 * S, fill=(88, 101, 242, 40), outline=(88, 101, 242, 90), width=S)
            draw.text((tx + 9 * S, ty + 8 * S), value, font=_font(True, 19 * S), fill=white)
            draw.text((tx + 9 * S, ty + 31 * S), name.upper(), font=_font(False, 8 * S), fill=muted)
            draw.text((tx + 9 * S, ty + 42 * S), note, font=_font(False, 8 * S), fill=GOLD + (255,))
        y += 124 * S
    if card.get("by_month") and y + 82 * S < y1:
        title_of("Messages par mois")
        months = card["by_month"]
        _bars(draw, [m["messages"] for m in months], (left, y, right, y + 52 * S), {0: MONTHS[int(months[0]["month"][5:]) - 1], len(months) - 1: MONTHS[int(months[-1]["month"][5:]) - 1]} if len(months) > 1 else {})
        y += 60 * S
    if card.get("habits") and y + 82 * S < y1:
        title_of("Rythme")
        hours = card["habits"]["hours"]
        _bars(draw, hours, (left, y, right, y + 46 * S), {0: "0 h", 6: "6 h", 12: "12 h", 18: "18 h"})
        y += 56 * S
    if card.get("roles") and y + 50 * S < y1:
        title_of("Rôles qu'elle s'est donnés")
        draw.text((left, y), _fit(draw, ", ".join(card["roles"]), label, right - left), font=label, fill=white)
        y += 22 * S
    if card.get("axes") and y + 50 * S < y1:
        title_of("Où elle se situe")
        for axis in card["axes"][:3]:
            if y + 18 * S < y1:
                draw.text((left, y), _fit(draw, f"{axis['name']} : {axis['pole']}", label, right - left), font=label, fill=white)
                y += 18 * S
    if card.get("top_links") and y + 56 * S < y1:
        title_of("Liens principaux")
        strongest = max(link["weight"] for link in card["top_links"]) or 1
        for link in card["top_links"]:
            if y + 36 * S > y1:
                break
            lid = int(link["id"])
            layer.alpha_composite(_portrait(pictures.get(lid), 26 * S, colors.get(lid, DEFAULT_NODE), 2 * S), (left, y))
            draw.text((left + 34 * S, y + 1 * S), _fit(draw, _printable(link["label"]) or "?", bold, right - left - 34 * S), font=bold, fill=white)
            draw.text((left + 34 * S, y + 17 * S), f"{link['n']} échanges", font=small, fill=muted)
            draw.rounded_rectangle([left + 34 * S, y + 30 * S, right, y + 32 * S], radius=S, fill=(255, 255, 255, 25))
            draw.rounded_rectangle([left + 34 * S, y + 30 * S, left + 34 * S + max(6 * S, (right - left - 34 * S) * link["weight"] / strongest), y + 32 * S], radius=S, fill=GOLD + (255,))
            y += 38 * S
    canvas.alpha_composite(layer)


def render(data: dict, names: int, pictures: dict[int, bytes] | None = None, card: dict | None = None) -> bytes:
    """The PNG of the map, in the look of the Activity: the background, a panel with the people as their photo in a ring of the color of their name (a plain disc without
    photo), their name for the most connected ones; with a person in focus, them at the center and, on the right, their card (`card`: what `person()` returns)."""
    pictures = pictures or {}
    people, focus = data["people"], data["focus"]
    S = SCALE
    w, h = WIDTH * S, HEIGHT * S
    canvas = _background(w, h)
    margin = 40 * S
    map_right = w - margin - ((PANEL_WIDTH + 10) * S if card else 0)
    shapes = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _panel(ImageDraw.Draw(shapes), (margin, margin, map_right, h - margin))
    if card:
        _panel(ImageDraw.Draw(shapes), (w - margin - PANEL_WIDTH * S, margin, w - margin, h - margin), fill=205)
    canvas.alpha_composite(shapes)

    seed = zlib.crc32(json.dumps([p["id"] for p in people]).encode())
    pos = _layout(people, data["links"], focus, seed)
    inset_x, inset_y = 70 * S, 62 * S
    xy = {p["id"]: (margin + inset_x + (pos[i][0] + 1) / 2 * (map_right - margin - 2 * inset_x), margin + inset_y + (pos[i][1] + 1) / 2 * (h - 2 * margin - 2 * inset_y))
          for i, p in enumerate(people)}
    top = max((p["influence"] for p in people), default=1) or 1
    strongest = max((weight for *_, weight in data["links"]), default=1) or 1
    lines = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    line = ImageDraw.Draw(lines)
    for a, b, weight in sorted(data["links"], key=lambda link: link[2]):
        strength = math.sqrt(weight / strongest)
        lit = focus is not None and focus in (a, b)
        alpha = int(255 * (0.25 + 0.6 * strength) * (1 if focus is None or lit else 0.45))
        line.line([xy[a], xy[b]], fill=(GOLD if lit else EDGE) + (alpha,), width=max(1, int((1 + 4 * strength) * S)))
    canvas.alpha_composite(lines)

    colors = {p["id"]: _node_color(p["color"]) for p in people}
    sizes = {p["id"]: int((24 + 30 * math.sqrt(p["influence"] / top)) * S) if pictures.get(p["id"]) else int((10 + 14 * math.sqrt(p["influence"] / top)) * S) for p in people}
    for p in reversed(people):                                  # the least connected first: the most connected ones are drawn over
        x, y = xy[p["id"]]
        size = sizes[p["id"]] + (6 * S if p["id"] == focus else 0)
        if p["id"] == focus:
            ImageDraw.Draw(canvas).ellipse([x - size / 2 - 5 * S, y - size / 2 - 5 * S, x + size / 2 + 5 * S, y + size / 2 + 5 * S], outline=GOLD + (255,), width=3 * S)
        canvas.alpha_composite(_portrait(pictures.get(p["id"]), size, colors[p["id"]], max(2 * S, size // 11)), (int(x - size / 2), int(y - size / 2)))
    draw = ImageDraw.Draw(canvas)
    shown = {p["id"] for p in people[:names]} | ({focus} if focus is not None else set())
    for p in people:
        label = _printable(p["label"] or "")
        if p["id"] in shown and label:
            x, y = xy[p["id"]]
            draw.text((x, y + sizes[p["id"]] / 2 + 5 * S), label if len(label) <= 22 else label[:21] + "…", font=_font(p["id"] == focus, (16 if p["id"] == focus else 13) * S),
                      fill=(242, 243, 245, 255), anchor="mt", stroke_width=2 * S, stroke_fill=(5, 10, 28, 255))
    if card:
        _card(canvas, card, w - margin - PANEL_WIDTH * S, margin, w - margin, h - margin, pictures, colors)
    out = io.BytesIO()
    canvas.convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()
