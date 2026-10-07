"""`/dindon mycard`: a person sets up their own card, privately (docs/regles-du-bot.md, « Ma card »).

The four pages never change; what changes is their **content**, within what the administrator allows (cards.py: `effective_blocks`): which blocks of a page show, which of the positions that were
read of the person are shown (three at most, chosen among those that Dindon read), and a short note under a page or under a position. Everything is read back by `/dindon card @them`: the
notes are public like the rest of the card, which the screen says. Nobody else can change it.

Under each page Dindon **suggests improvements**, made from what it analysed of the person: a position read with little certainty or kept with no proof (« à préciser »), a clearer position
that is not shown, a role that is found in contradiction with what was said, a change of mind that could be explained, a block that has data but is hidden. They are fixed rules on that
data, never a model's opinion on the person; each one that can be done in a click says what it does.
"""
from __future__ import annotations

import json
import re

import psycopg

from dindon import cards

NOTE_MAX = 200
MAX_PINNED = 3
LOW_CONFIDENCE = 0.6
CLEAR_CONFIDENCE = 0.7
PAGE_TITLES = dict(zip(cards.PAGE_KEYS, cards.PAGES, strict=True))
BLOCK_NAMES = {
    "headline": "Chiffres clés", "activity": "Activité", "channels": "Salons", "roles": "Rôles que je me donne", "presence": "Dates de présence",
    "close": "Échanges proches", "replies": "Réponses", "sides": "Accords et désaccords",
    "axes": "Barres des axes", "positions": "Positions avec preuve",
    "verdicts": "Mes rôles face à mes propos", "against": "Rôles contredits", "conflicts": "Rôles qui s'opposent", "changes": "Changements d'avis",
}


def clean_note(raw: object) -> str | None:
    text = " ".join(re.sub(r"https?://\S+", "", str(raw or "")).split())          # a link would be a public advertisement under somebody's card
    return text[:NOTE_MAX] if text else None


def clean(values: dict | None, cfg: dict, candidates: list[int] | None = None) -> dict:
    """What was stored or sent, reduced to what is allowed: blocks within the administrator's, positions among those read, notes of known places and short."""
    values = values if isinstance(values, dict) else {}
    blocks = {}
    for page in cards.PAGE_KEYS:
        chosen = (values.get("blocks") or {}).get(page) if isinstance(values.get("blocks"), dict) else None
        if isinstance(chosen, list):
            blocks[page] = [b for b in cfg["blocks"][page] if b in chosen]
    pinned = []
    for pid in values.get("pinned") or []:
        if isinstance(pid, int) and pid not in pinned and (candidates is None or pid in candidates):
            pinned.append(pid)
    notes = {}
    for key, text in (values.get("notes") or {}).items() if isinstance(values.get("notes"), dict) else []:
        ok = key in {f"section:{p}" for p in cards.PAGE_KEYS} or re.fullmatch(r"pos:\d{1,18}", str(key))
        note = clean_note(text)
        if ok and note:
            notes[key] = note
    return {"blocks": blocks, "pinned": pinned[:MAX_PINNED], "notes": notes}


def load(conn: psycopg.Connection, guild_id: int, user_id: int) -> dict:
    """What the person set up (empty if nothing)."""
    row = conn.execute("SELECT prefs FROM card_prefs WHERE guild_id = %s AND user_id = %s", (guild_id, user_id)).fetchone()
    return row[0] if row else {}


def save(conn: psycopg.Connection, guild_id: int, user_id: int, prefs: dict) -> None:
    with conn.transaction():
        if prefs == {"blocks": {}, "pinned": [], "notes": {}}:
            conn.execute("DELETE FROM card_prefs WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
            return
        conn.execute("""INSERT INTO card_prefs (guild_id, user_id, prefs) VALUES (%s, %s, %s::jsonb)
                        ON CONFLICT (guild_id, user_id) DO UPDATE SET prefs = excluded.prefs, updated_at = now()""", (guild_id, user_id, json.dumps(prefs)))


# --- the suggestions ---------------------------------------------------------------------------------------------------------


def suggestions(card: dict, cfg: dict, prefs: dict) -> dict[str, list[dict]]:
    """For each page: what Dindon suggests, from what it analysed. Each is {'text', 'action'}: action is None (advice only), ('block', block), ('pin', claim id) or ('note', key)."""
    out: dict[str, list[dict]] = {page: [] for page in cards.PAGE_KEYS}
    notes = prefs.get("notes") or {}
    on = {page: cards.effective_blocks(cfg, prefs, page) for page in cards.PAGE_KEYS}

    def hidden_with_data(page: str, block: str, has_data: bool, what: str) -> None:
        if has_data and block in cfg["blocks"][page] and block not in on[page]:
            out[page].append({"text": f"{what} : Dindon en a lu des éléments, mais ce bloc est masqué. Le montrer ?", "action": ("block", block)})

    hidden_with_data("profile", "roles", bool(card["roles"]), "Rôles que vous vous donnez")
    hidden_with_data("interactions", "close", bool(card.get("close")), "Échanges proches")
    hidden_with_data("positions", "axes", bool(card["axes"]), "Barres des axes")
    hidden_with_data("positions", "positions", bool(card["positions"]), "Positions")
    hidden_with_data("contradictions", "changes", bool(card["changes"]), "Changements d'avis")
    if not notes.get("section:profile"):
        out["profile"].append({"text": "Une courte note de présentation sous le profil aiderait à vous situer.", "action": ("note", "section:profile")})
    if card.get("disagree") and not notes.get("section:interactions"):
        out["interactions"].append({"text": "Vous êtes souvent opposé·e à quelqu'un : une note peut nuancer ce que la fiche en dit.", "action": ("note", "section:interactions")})
    shown = cards.shown_positions(card, prefs) if "positions" in on["positions"] else []
    shown_ids = {p["id"] for p in shown}
    for p in shown:
        weak = p["confidence"] < LOW_CONFIDENCE
        if (weak or p["proof"] is None or not (p["proof"][0] or "").strip()) and p["id"] is not None and f"pos:{p['id']}" not in notes:
            why = "lue avec peu de certitude" if weak else "gardée sans preuve"
            out["positions"].append({"text": f"« {cards._cut(p['text'], 70)} » est {why} : une note pour la préciser.", "action": ("note", f"pos:{p['id']}")})
    if len(shown) < MAX_PINNED or shown:
        better = [p for p in card.get("all_positions") or [] if p["id"] not in shown_ids and p["confidence"] >= CLEAR_CONFIDENCE and p["proof"] is not None]
        for p in better[:2]:
            if len(prefs.get("pinned") or []) < MAX_PINNED:
                out["positions"].append({"text": f"Position claire non montrée : « {cards._cut(p['text'], 70)} » (certitude {round(p['confidence'] * 100)} %). L'ajouter ?", "action": ("pin", p["id"])})
    if any(v == "discordant" for _, v in card["verdicts"]) and not notes.get("section:contradictions"):
        out["contradictions"].append({"text": "Un de vos rôles est en contradiction avec vos propos : une note pour l'expliquer.", "action": ("note", "section:contradictions")})
    if card["changes"] and not notes.get("section:contradictions"):
        out["contradictions"].append({"text": "Vous avez changé d'avis sur une proposition : une note peut expliquer pourquoi.", "action": ("note", "section:contradictions")})
    return out


# --- changing it -------------------------------------------------------------------------------------------------------------


def apply(conn: psycopg.Connection, guild_id: int, user_id: int, change: tuple, cfg: dict | None = None) -> dict:
    """One change, then saved: ('blocks', page, [blocks]), ('pinned', [ids]), ('note', key, text|None), ('reset', page), ('suggestion', page, index). Returns the prefs now."""
    cfg = cfg or cards.load(conn)
    card = cards.person_card(conn, guild_id, user_id)
    candidates = [p["id"] for p in (card or {}).get("all_positions", []) if p["id"] is not None]
    prefs = clean(load(conn, guild_id, user_id), cfg, candidates)
    kind = change[0]
    if kind == "blocks":
        prefs["blocks"][change[1]] = list(change[2])
    elif kind == "pinned":
        prefs["pinned"] = list(change[1])
    elif kind == "note":
        prefs["notes"][change[1]] = change[2] or ""
    elif kind == "reset":
        page = change[1]
        prefs["blocks"].pop(page, None)
        prefs["notes"] = {k: v for k, v in prefs["notes"].items() if k != f"section:{page}" and not (page == "positions" and k.startswith("pos:"))}
        if page == "positions":
            prefs["pinned"] = []
    elif kind == "suggestion" and card:
        todo = suggestions(card, cfg, prefs)[change[1]]
        if 0 <= change[2] < len(todo) and todo[change[2]]["action"]:
            what, value = todo[change[2]]["action"]
            if what == "block":
                page = change[1]
                prefs["blocks"][page] = [b for b in cfg["blocks"][page] if b in cards.effective_blocks(cfg, prefs, page) or b == value]
            elif what == "pin":
                base = prefs["pinned"] or [p["id"] for p in cards.shown_positions(card, prefs)]
                prefs["pinned"] = [*[b for b in base if b != value], value][-MAX_PINNED:]
    prefs = clean(prefs, cfg, candidates)
    save(conn, guild_id, user_id, prefs)
    return prefs


# --- the screen --------------------------------------------------------------------------------------------------------------


def view(conn: psycopg.Connection, guild_id: int, user_id: int, page: int = 0, avatar: str | None = None, note: str | None = None) -> dict | None:
    """The private message of `/dindon mycard` for a page: the card as everybody will see it, Dindon's suggestions, and the controls. None if the person has no card."""
    cfg = cards.load(conn)
    card = cards.person_card(conn, guild_id, user_id)
    if card is None:
        return None
    candidates = [p["id"] for p in card.get("all_positions", []) if p["id"] is not None]
    prefs = clean(load(conn, guild_id, user_id), cfg, candidates)
    page = page if 0 <= page < len(cards.PAGE_KEYS) and cards.PAGE_KEYS[page] in cfg["pages"] else cards.PAGE_KEYS.index(cfg["pages"][0])
    key = cards.PAGE_KEYS[page]
    preview = cards.card_page(card, page, avatar, cfg, prefs)
    todo = suggestions(card, cfg, prefs)[key]
    lines = [f"• {s['text']}" for s in todo] or ["Rien à améliorer ici d'après ce que Dindon a lu."]
    helper = {"title": f"💡 Suggestions · {PAGE_TITLES[key]}", "color": 0xF1C40F,
              "description": "\n".join(lines)[:3500] + "\n\n*Ce que vous réglez ici est vu de tout le salon sur votre card. Les parties ne changent pas, seulement leur contenu. "
                                                      "Lecture automatique de vos messages, pas un verdict.*"}
    rows = [{"type": 1, "components": [{"type": 2, "style": 1 if i == page else 2, "label": name, "emoji": {"name": cards.ICONS[i]}, "custom_id": f"dindon:mycard:p:{i}", "disabled": i == page}
                                       for i, name in enumerate(cards.PAGES) if cards.PAGE_KEYS[i] in cfg["pages"]]}]
    allowed = cfg["blocks"][key]
    if allowed:
        current = cards.effective_blocks(cfg, prefs, key)
        rows.append({"type": 1, "components": [{"type": 3, "custom_id": f"dindon:mycard:b:{page}", "placeholder": "Blocs affichés sur cette page", "min_values": 0, "max_values": len(allowed),
                                                "options": [{"label": BLOCK_NAMES[b], "value": b, "default": b in current} for b in allowed]}]})
    if key == "positions" and card.get("all_positions"):
        picked = [p["id"] for p in cards.shown_positions(card, prefs)] if prefs["pinned"] else []
        rows.append({"type": 1, "components": [{"type": 3, "custom_id": "dindon:mycard:s:2", "placeholder": "Positions montrées (3 au plus ; rien = les plus claires)", "min_values": 0,
                                                "max_values": min(MAX_PINNED, len(card["all_positions"])),
                                                "options": [{"label": f"{cards.STANCE.get(p['stance'], '❔')[:2]} {cards._cut(p['text'], 80)}", "value": str(p["id"]), "default": p["id"] in picked}
                                                            for p in card["all_positions"][:25]]}]})
    doable = [(i, s) for i, s in enumerate(todo) if s["action"]]
    if doable:
        rows.append({"type": 1, "components": [{"type": 3, "custom_id": f"dindon:mycard:a:{page}", "placeholder": "Appliquer une suggestion", "min_values": 1, "max_values": 1,
                                                "options": [{"label": cards._cut(s["text"], 95), "value": str(i)} for i, s in doable[:25]]}]})
    rows.append({"type": 1, "components": [{"type": 2, "style": 2, "label": "Note sous cette page", "emoji": {"name": "📝"}, "custom_id": f"dindon:mycard:n:{page}:section"},
                                           {"type": 2, "style": 4, "label": "Revenir au réglage de départ", "custom_id": f"dindon:mycard:r:{page}"}]})
    return {"content": note or "", "embeds": [preview, helper], "components": rows, "allowed_mentions": {"parse": []}}
