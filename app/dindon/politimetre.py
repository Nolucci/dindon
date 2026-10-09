"""Portrait political position card. Existing map permissions and mycard choices apply.

Axes cover the guild; quoted highlights only come from the destination channel.
No model call, invented axis or judgement of the quality of somebody's opinions.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageOps

from dindon import cards, discord_map, mycard, privacy
from dindon.api.common import LABEL

WIDTH, HEIGHT = 1024, 1536
AXIS_HEIGHT = 107
BASE_AXIS_ROWS = 5
BACKGROUND = discord_map.ASSETS / "politimetre-background.webp"
GOLD = "#e7bd78"
WHITE = "#f4efe5"
MUTED = "#aeb9c9"
COLORS = {-1: "#f18d85", 0: "#e7bd78", 1: "#68d6c6"}
STANCES = {-1: "CONTRE", 0: "NE SAIT PAS", 1: "POUR"}


def collect(conn, guild_id: int, user_id: int, channel_id: int) -> dict | None:
    if user_id in privacy.blocked_ids(conn):
        return None
    who = conn.execute(
        f"""SELECT {LABEL}, m.avatar_url FROM users u JOIN members m ON m.user_id = u.id AND m.guild_id = %s
            WHERE u.id = %s AND NOT u.is_bot""", (guild_id, user_id)).fetchone()
    if not who:
        return None
    cfg = cards.load(conn)
    prefs = mycard.clean(mycard.load(conn, guild_id, user_id), cfg)
    on = cards.effective_blocks(cfg, prefs, "positions") if "positions" in cfg["pages"] else []
    data = {"name": who[0], "avatar": who[1], "axes": [], "positions": []}
    if "axes" in on:
        data["axes"] = conn.execute(
            """SELECT a.name, a.negative_pole, a.positive_pole, s.score::float8, s.uncertainty::float8, s.n_propositions
               FROM person_axis_scores s JOIN axes a ON a.id = s.axis_id AND a.is_active
               WHERE s.guild_id = %s AND s.user_id = %s AND s.n_propositions > 0
               ORDER BY a.position, a.id""", (guild_id, user_id)).fetchall()
    if "positions" in on:
        # Lateral selection avoids duplicate highlights when a claim has several proofs.
        # The author and guild checks prevent borrowed quotes or cross-server evidence.
        rows = conn.execute(
            """SELECT s.claim_id, p.text, s.stance, s.confidence::float8, e.quote, e.id, e.sent_at
               FROM current_stances s JOIN propositions p ON p.id = s.proposition_id
               JOIN claims cl ON cl.id = s.claim_id AND cl.kind <> 'humour'
               JOIN LATERAL (
                   SELECT ce.quote, m.id, m.sent_at FROM claim_evidence ce
                   JOIN messages m ON m.id = ce.message_id JOIN channels c ON c.id = m.channel_id
                   WHERE ce.claim_id = s.claim_id AND m.author_id = s.user_id
                     AND m.channel_id = %(channel)s AND c.guild_id = s.guild_id
                     AND length(trim(COALESCE(ce.quote, ''))) > 0
                   ORDER BY m.sent_at DESC, m.id DESC LIMIT 1
               ) e ON true
               WHERE s.guild_id = %(guild)s AND s.user_id = %(user)s AND s.confidence >= 0.7
                 AND p.status NOT IN ('rejected', 'merged')
               ORDER BY (s.claim_id = ANY(%(pinned)s)) DESC,
                        array_position(%(pinned)s::bigint[], s.claim_id), s.confidence DESC, s.stated_at DESC, s.claim_id DESC
               LIMIT 3""", {"guild": guild_id, "user": user_id, "channel": channel_id, "pinned": prefs["pinned"]}).fetchall()
        data["positions"] = [{"id": pid, "text": text, "stance": stance, "confidence": confidence, "quote": quote,
                              "url": cards._link(guild_id, channel_id, message), "at": at}
                             for pid, text, stance, confidence, quote, message, at in rows]
        chosen = [p for p in data["positions"] if p["id"] in prefs["pinned"]]
        if chosen:
            data["positions"] = chosen
    return data if data["axes"] or data["positions"] else None


def _prefix(draw, text: str, font, width: int, suffix: str = "") -> int:
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if draw.textlength(text[:middle] + suffix, font=font) <= width:
            low = middle
        else:
            high = middle - 1
    return low


def _text(draw, text: str, x: int, y: int, size: int, width: int, *, color=WHITE, lines=1, bold=False) -> None:
    """Bounded, accent-safe wrapping, including unbroken usernames/URLs."""
    font = discord_map._font(bold, size)
    remaining = " ".join(discord_map._printable(text).split())
    for line in range(lines):
        if not remaining:
            break
        if draw.textlength(remaining, font=font) <= width:
            piece, remaining = remaining, ""
        elif line == lines - 1:
            piece, remaining = remaining[:_prefix(draw, remaining, font, width, "…")].rstrip() + "…", ""
        else:
            end = max(1, _prefix(draw, remaining, font, width))
            space = remaining.rfind(" ", 0, end + 1)
            end = space if space > 0 else end
            piece, remaining = remaining[:end], remaining[end:].lstrip()
        draw.text((x, y + line * (size + 6)), piece, font=font, fill=color)


def render(data: dict, photo: bytes | None = None) -> bytes:
    extra = max(0, len(data["axes"]) - BASE_AXIS_ROWS) * AXIS_HEIGHT
    height = HEIGHT + extra
    with Image.open(BACKGROUND) as background:
        base = ImageOps.fit(background.convert("RGBA"), (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
    image = base
    if extra:
        # Extend only the middle: the turkey, top trim and bottom frame retain their proportions.
        top, bottom = 290, HEIGHT - 600
        image = Image.new("RGBA", (WIDTH, height))
        image.paste(base.crop((0, 0, WIDTH, top)), (0, 0))
        middle = base.crop((0, top, WIDTH, bottom)).resize((WIDTH, bottom - top + extra), Image.Resampling.LANCZOS)
        image.paste(middle, (0, top))
        image.paste(base.crop((0, bottom, WIDTH, HEIGHT)), (0, bottom + extra))
    overlay = Image.new("RGBA", image.size)
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle((48, 290, 976, height - 62), radius=24, fill=(7, 17, 34, 130))
    image = Image.alpha_composite(image, overlay)
    d = ImageDraw.Draw(image)
    _text(d, "LE POLITIMÈTRE", 76, 99, 44, 710, color=GOLD, bold=True)
    portrait = discord_map._portrait(photo, 100, (231, 189, 120), 3)
    image.alpha_composite(portrait, (76, 174))
    if not photo:
        _text(d, data["name"][:1].upper(), 108, 198, 38, 45, color="#122039", bold=True)
    _text(d, data["name"], 200, 187, 36, 660, bold=True)
    _text(d, "SES POSITIONS", 200, 237, 18, 720, color=MUTED)
    _text(d, "SES POSITIONS PAR AXE", 76, 317, 22, 872, color=GOLD, bold=True)
    if not data["axes"]:
        _text(d, "Pas assez de données pour situer ses positions.", 76, 413, 25, 872, color=MUTED, lines=2)
    for index, (name, negative, positive, score, uncertainty, count) in enumerate(data["axes"]):
        y = 371 + index * AXIS_HEIGHT
        _text(d, name, 76, y, 23, 700, bold=True)
        _text(d, f"{count} position{'s' if count != 1 else ''}", 804, y + 3, 16, 144, color=MUTED)
        left, right, center = 92, 932, y + 53
        for x in range(left, right):
            t = (x - left) / (right - left)
            color = tuple(round(a * (1 - t) + b * t) for a, b in zip((241, 141, 133), (104, 214, 198), strict=True))
            d.line((x, center - 3, x, center + 3), fill=color)
        d.line((512, center - 9, 512, center + 9), fill=MUTED, width=2)
        position = lambda value, left=left, right=right: left + round((max(-1, min(1, value)) + 1) / 2 * (right - left))  # noqa: E731
        lo, hi = position(score - uncertainty), position(score + uncertainty)
        d.rounded_rectangle((lo, center - 7, max(lo + 1, hi), center + 7), radius=6, fill=(231, 189, 120, 100))
        x = position(score)
        d.ellipse((x - 11, center - 11, x + 11, center + 11), fill=WHITE, outline="#102039", width=3)
        _text(d, negative, 76, y + 73, 17, 417, color=MUTED)
        font = discord_map._font(False, 17)
        label = discord_map._printable(positive)
        if d.textlength(label, font=font) > 417:
            label = label[:_prefix(d, label, font, 417, "…")].rstrip() + "…"
        d.text((948 - d.textlength(label, font=font), y + 73), label, font=font, fill=MUTED)
    _text(d, "SES MEILLEURES PRISES DE POSITION", 76, 943 + extra, 25, 872, color=GOLD, bold=True)
    if not data["positions"]:
        _text(d, "Aucune prise de position suffisamment étayée dans ce salon.", 76, 1035 + extra, 25, 872, color=MUTED, lines=3)
    for index, p in enumerate(data["positions"]):
        y = 997 + extra + index * 155
        d.rounded_rectangle((64, y - 5, 960, y + 144), radius=16, fill="#12253c")
        color = COLORS.get(p["stance"], GOLD)
        d.rounded_rectangle((64, y - 5, 70, y + 144), radius=3, fill=color)
        _text(d, f"{index + 1:02d}  {STANCES.get(p['stance'], 'NE SAIT PAS')}", 88, y + 7, 17, 650, color=color, bold=True)
        _text(d, p["at"].strftime("%d/%m/%Y"), 822, y + 7, 16, 120, color=MUTED)
        _text(d, p["text"], 88, y + 32, 21, 844, lines=2, bold=True)
        _text(d, f"« {p['quote']} »", 88, y + 91, 18, 844, color=MUTED, lines=2)
    output = io.BytesIO()
    image.convert("RGB").save(output, "PNG", optimize=True)
    return output.getvalue()
