"""What a debate says on Discord: the messages and their buttons, built as plain data (no network), so that they can be read and tested as they are.

Every message carries `allowed_mentions: {"parse": []}`: a subject or a name that contains @everyone pings nobody. The buttons carry the emojis asked for
(for, not sure, against; go on, stop) and an identifier `dindon:debat:<kind>:<debate>:<value>` that says which debate and which choice, whatever the
message it is on (see `parse_custom_id`).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from dindon.debate import rules
from dindon.debate.store import Debate

BLURPLE, GREY = 0x5865F2, 0x99AAB5
NO_MENTIONS = {"parse": []}
POSITION_BUTTONS = {"for": ("✅", "Pour"), "unsure": ("❔", "Ne sait pas"), "against": ("❌", "Contre")}
CAMP_EMOJIS = ("🔵", "🟠")                     # the two poles of an axis: neutral colours, never ✅ / ❌ (they would say that one pole is the right one)


def position_buttons(axis: dict | None = None) -> dict[str, tuple[str, str]]:
    """The three answers of a debate, each with its emoji: pour / ne sait pas / contre for a subject written by a person; for a question of Dindon (an axis), its two poles, in the order of the
    axis (-1 first), and « Ne sait pas » in the middle."""
    if not axis:
        return POSITION_BUTTONS
    return {"for": (CAMP_EMOJIS[0], str(axis["for"])[:60]), "unsure": POSITION_BUTTONS["unsure"], "against": (CAMP_EMOJIS[1], str(axis["against"])[:60])}


def position_names(axis: dict | None = None) -> dict:
    """The same, written out (« ✅ Pour »), with the word for a person who took no position."""
    return {**{key: f"{emoji} {label}" for key, (emoji, label) in position_buttons(axis).items()}, None: "— pas de position"}
SECONDARY, SUCCESS, DANGER = 2, 3, 4          # Discord's button styles
THREAD_PREFIX = "Débat · "

# The notice to the members when the claims of a debate are checked on the Internet (validated by the owner, 2026-10-06). It says what leaves the machine, and nothing else leaves.
# It is shown in the launch message of every debate that is checked and by `/dindon info`, whenever the checks are on. (2026-10-06, with the free-form debates: « dans les fils de débat » became
# « dans les débats », since a debate can now take place in a channel. To be confirmed by the owner.)
NOTICE_TITLE = "Vérification des affirmations"
NOTICE = ("Pour vérifier ce qu'une personne affirme dans un débat, Dindon envoie à un moteur de recherche une phrase neutre qui décrit l'affirmation — sans votre nom, sans votre message — "
          "et lit au plus trois des pages trouvées. Il ne cherche rien d'autre, ne vérifie rien de ce qui concerne une personne privée, n'ouvre pas les liens que vous écrivez, et ne prend pas "
          "parti : il dit ce que des sources de confiance établissent, ou qu'il ne peut pas trancher. Rien d'autre ne quitte cet ordinateur, à part ce que Dindon écrit dans les débats "
          "de ce serveur. Pour l'instant, il note ses vérifications sans rien publier.")

REASONS = {
    rules.ENDED: "Le débat a été terminé à la demande de la personne qui l'a lancé ou d'un modérateur.",
    rules.SILENCE: "Plus personne n'a écrit depuis un moment : le débat s'est terminé de lui-même.",
    rules.NO_PARTICIPANTS: "Personne n'a pris part au débat : il est fermé.",
}

REFUSALS = {                                    # what a person is told when a rule refuses them (store.DebateRefused.code)
    "topic": "Le sujet doit faire entre 3 et 200 caractères.",
    "context": "Le contexte ne peut pas dépasser 1 000 caractères.",
    "quiet": "Cette durée de silence n'est pas possible.",
    "blocked": "Vous avez demandé à ne pas être enregistré·e : vous ne pouvez pas prendre part à un débat. `/dindon reprendre` change cela.",
    "person_limit": "Vous avez déjà un débat ouvert : terminez-le pour en lancer un autre.",
    "server_limit": "Il y a déjà trop de débats ouverts sur ce serveur ({n}) : réessayez quand l'un d'eux sera terminé.",
    "channel_busy": "Un débat est déjà ouvert dans ce salon : terminez-le, ou ouvrez celui-ci dans un fil.",
    "not_open": "Ce débat est terminé.",
    "unknown": "Ce débat n'existe plus.",
    "not_allowed": "Seuls la personne qui a lancé le débat et les modérateurs peuvent le terminer.",
    "searched": "Dindon a déjà cherché sur Internet : sa réponse est corrigée.",
    "answer_gone": "Cette réponse n'existe plus.",
}

NOTICE_LIVE = NOTICE.replace("Pour l'instant, il note ses vérifications sans rien publier.",
                             "Quand des sources de confiance contredisent une affirmation, il le dit dans le fil, avec ces sources (sur lesquelles vous pouvez cliquer pour vérifier) ; sinon il ne dit rien.")


# When Dindon answers first (DINDON_DEBATE_CHECKS=answer or live): what it says, what the participants can do, and what leaves the machine. (Written 2026-10-06 for the owner to confirm.)
NOTICE_ANSWER = ("Pour vérifier ce qu'une personne affirme dans un débat, Dindon répond d'abord avec son IA locale, sans rien chercher sur Internet : quand il est certain qu'une affirmation est fausse, "
                 "il le dit sous le message, en précisant qu'il n'a pas de source et qu'il peut se tromper. Chacun peut alors appuyer sur Valide ou Invalide : s'il y a plus d'Invalide, Dindon cherche "
                 "sur Internet (il envoie à un moteur de recherche une phrase neutre qui décrit l'affirmation — sans votre nom, sans votre message — et lit au plus trois des pages trouvées) et corrige "
                 "sa réponse avec ce que disent des sources de confiance, quel que soit le résultat. Il ne vérifie rien de ce qui concerne une personne privée, n'ouvre pas les liens que vous écrivez "
                 "et ne prend pas parti. Rien d'autre ne quitte cet ordinateur, à part ce que Dindon écrit dans les débats de ce serveur.")
NOTICE_LOCAL = ("Pour vérifier ce qu'une personne affirme dans un débat, Dindon répond d'abord avec son IA locale : quand il est certain qu'une affirmation est fausse, il le dit sous le message, "
                "en précisant qu'il n'a pas de source et qu'il peut se tromper. Chacun peut appuyer sur Valide ou Invalide sous sa réponse. Dindon ne cherche rien sur Internet : rien ne quitte "
                "cet ordinateur, à part ce que Dindon écrit dans les débats de ce serveur. Il ne vérifie rien de ce qui concerne une personne privée et ne prend pas parti.")


# The same, in one line, for the launch message of every debate (the whole text is in `/dindon info`): what Dindon does, and what leaves the machine.
NOTICE_SHORT = {
    "observe": "🔎 Dindon note les affirmations de fait en les cherchant sur Internet (phrase neutre, sans votre nom), sans rien publier. Détails : `/dindon info`.",
    "answer": "🔎 Sûr qu'une affirmation est fausse, Dindon répond sans source (il peut se tromper) : ✅ Valide / ❌ Invalide ; plus d'Invalide, il cherche sur Internet (phrase neutre, sans votre nom). Détails : `/dindon info`.",
    "local": "🔎 Sûr qu'une affirmation est fausse, Dindon répond sans source (il peut se tromper) : ✅ Valide / ❌ Invalide. Il ne cherche rien sur Internet. Détails : `/dindon info`.",
    "live": "🔎 Dindon répond sans source quand il est sûr qu'une affirmation est fausse (✅ Valide / ❌ Invalide ; plus d'Invalide, il cherche sur Internet) ; des sources de confiance peuvent aussi le corriger. Détails : `/dindon info`.",
}


def notice_short(mode: bool | str = "observe") -> str:
    mode = "live" if mode is True else "observe" if mode is False else mode
    return NOTICE_SHORT.get(mode, NOTICE_SHORT["observe"])


def notice(mode: bool | str = "observe") -> str:
    """What the members are told, by what Dindon does: `observe` (it checks and notes, publishes nothing), `answer` (it answers first and looks on the Internet if the participants reject its
    answer), `local` (the same with no search service: nothing leaves the machine), `live` (answers, and corrections by trusted sources). A boolean is accepted: True is `live`."""
    mode = "live" if mode is True else "observe" if mode is False else mode
    return {"live": NOTICE_LIVE, "answer": NOTICE_ANSWER, "local": NOTICE_LOCAL}.get(mode, NOTICE)


LINK = 5                                       # the style of a Discord button that opens an address


def _plain(text: str) -> str:
    """A text shown as it is: Discord's markdown characters are escaped, so that a quotation is displayed as it was written."""
    return re.sub(r"([\\*_~|`>\[\]])", r"\\\1", text)


def _source_name(url: str) -> str:
    host = (urlsplit(url).hostname or url).lower()
    return host[4:] if host.startswith("www.") else host


def correction(claim: str, period: str | None, evidence: list, reply_to: int) -> dict:
    """What Dindon posts when trusted sources contradict a claim. The same words for everybody and whatever the subject: what was checked, what the sources say with their exact words, and links to
    click. It names nobody, mentions nobody (it answers the message), gives no opinion and says nothing of who is right in the debate."""
    shown = evidence[:3]
    lines = [f"**Affirmation vérifiée** : « {_plain(claim)} »", "", "**Ce que disent les sources**" + (f" ({_plain(period)})" if period else "") + " :"]
    for e in shown:
        link = e.url.replace("(", "%28").replace(")", "%29")
        lines.append(f"• [{_plain(_source_name(e.url))}]({link}) : « {_plain(e.quote)} »")
    embed = {"title": "🔎 Vérification", "description": "\n".join(lines)[:4000], "color": BLURPLE,
             "footer": {"text": "Dindon ne prend pas parti : il rapporte ce que disent des sources de confiance. Cliquez pour vérifier par vous-même."}}
    buttons = [{"type": 2, "style": LINK, "label": _source_name(e.url)[:80], "url": e.url} for e in shown if len(e.url) <= 512]
    payload = {"content": "", "embeds": [embed], "allowed_mentions": {"parse": [], "replied_user": False},
               "message_reference": {"message_id": str(reply_to), "fail_if_not_exists": False}}
    if buttons:
        payload["components"] = _row(buttons)
    return payload


def answer_buttons(answer_id: int, valid: int, invalid: int) -> list[dict]:
    return _row([{"type": 2, "style": SECONDARY, "label": f"Valide · {valid}", "emoji": {"name": "✅"}, "custom_id": custom_id("val", answer_id, "valid")},
                 {"type": 2, "style": SECONDARY, "label": f"Invalide · {invalid}", "emoji": {"name": "❌"}, "custom_id": custom_id("val", answer_id, "invalid")}])


def local_answer(claim: str, answer: str, answer_id: int, reply_to: int, valid: int = 0, invalid: int = 0) -> dict:
    """What Dindon says under a message when it is certain that a claim is false, from its local model alone: the claim, what it knows, and that it has **no source**. Under it, Valide and
    Invalide for the participants. It answers the message, names nobody, mentions nobody."""
    lines = [f"**Affirmation** : « {_plain(claim)} »", "", _plain(answer), "",
             "*Réponse de l'IA locale de Dindon, **sans recherche sur Internet et sans source** : elle peut se tromper. Valide ou invalide ? S'il y a plus d'invalide que de valide, Dindon cherchera sur Internet.*"]
    embed = {"title": "💬 Réponse de Dindon", "description": "\n".join(lines)[:4000], "color": GREY, "footer": {"text": "Dindon ne prend pas parti. Votre vote juge cette réponse, pas la personne."}}
    return {"content": "", "embeds": [embed], "components": answer_buttons(answer_id, valid, invalid), "allowed_mentions": {"parse": [], "replied_user": False},
            "message_reference": {"message_id": str(reply_to), "fail_if_not_exists": False}}


SEARCH_RESULT = {                                # what Dindon says of its own answer once it has looked on the Internet, by what it found
    "contradicted": "Les sources de confiance **contredisent** l'affirmation. Ma première réponse, donnée sans source, peut aussi contenir des erreurs.",
    "confirmed": "Les sources de confiance **confirment** l'affirmation : **ma réponse était fausse**.",
    "partly": "Les sources de confiance confirment l'affirmation **en partie** (ou pour une autre période) : ma réponse était trop catégorique.",
    "disputed": "Des sources de confiance **se contredisent** : je ne peux pas trancher.",
    "unverifiable": "Je n'ai **pas trouvé de source de confiance** qui tranche : ma réponse reste sans source, à prendre avec prudence.",
    None: "Je **ne peux pas chercher sur Internet** (aucun service de recherche n'est réglé) : ma réponse reste sans source, à prendre avec prudence.",
}
SEARCH_STANCE = {"contradicted": ("contradicts",), "confirmed": ("supports",), "partly": ("partly",), "disputed": ("supports", "contradicts"), "unverifiable": (), None: ()}


def after_search(claim: str, answer: str, verdict: str | None, period: str | None, evidence: list) -> dict:
    """Dindon's own message, written again once the participants rejected its answer and it looked on the Internet: what it found, whatever it is, with the sources to click and their exact
    words. The buttons are gone: the answer has been checked. It says plainly when the first answer was wrong."""
    wanted = SEARCH_STANCE.get(verdict, ())
    shown = [e for e in evidence if e.stance in wanted][:3]
    lines = [f"**Affirmation** : « {_plain(claim)} »", "", SEARCH_RESULT.get(verdict, SEARCH_RESULT["unverifiable"])]
    if shown:
        lines += ["", "**Ce que disent les sources**" + (f" ({_plain(period)})" if period else "") + " :"]
        for e in shown:
            link = e.url.replace("(", "%28").replace(")", "%29")
            lines.append(f"• [{_plain(_source_name(e.url))}]({link}) : « {_plain(e.quote)} »")
    lines += ["", f"*Ma première réponse, sans recherche : {_plain(answer)}*"]
    title = "🔎 Recherche impossible" if verdict is None else "🔎 Dindon a cherché sur Internet"
    footer = ("Dindon ne prend pas parti : il rapporte ce que disent des sources de confiance. Cliquez pour vérifier par vous-même."
              if shown else "Dindon ne prend pas parti. Aucune source n'étaye cette réponse.")
    embed = {"title": title, "description": "\n".join(lines)[:4000], "color": BLURPLE, "footer": {"text": footer}}
    buttons = [{"type": 2, "style": LINK, "label": _source_name(e.url)[:80], "url": e.url} for e in shown if len(e.url) <= 512]
    return {"content": "", "embeds": [embed], "components": _row(buttons) if buttons else [], "allowed_mentions": {"parse": [], "replied_user": False}}


def stamp(when: datetime, style: str = "R") -> str:
    """A time that Discord shows in the reader's own language and zone (`R`: « dans 5 minutes »; `t`: « 14:30 »)."""
    return f"<t:{int(when.timestamp())}:{style}>"


def custom_id(kind: str, debate_id: int, value: str) -> str:
    return f"dindon:debat:{kind}:{debate_id}:{value}"


def parse_custom_id(raw: object) -> tuple[str, int, str] | None:
    """(kind, debate, value) of a button of ours; None for anything else or anything malformed. For `val`, the number is the one of the answer that is judged."""
    parts = str(raw).split(":")
    if len(parts) != 5 or parts[:2] != ["dindon", "debat"] or parts[2] not in ("pos", "end", "stats", "val") or not parts[3].isdigit():
        return None
    if parts[2] == "val":                                     # Valide / Invalide under an answer of Dindon (the number is the answer's, not the debate's)
        return ("val", int(parts[3]), parts[4]) if parts[4] in ("valid", "invalid") else None
    if parts[2] == "stats":                                   # the page of the statistics to show
        return ("stats", int(parts[3]), parts[4]) if parts[4].isdigit() and len(parts[4]) <= 3 else None
    if parts[2] == "end":
        return ("end", int(parts[3]), "now") if parts[4] == "now" else None
    return ("pos", int(parts[3]), parts[4]) if parts[4] in rules.POSITIONS else None


def thread_name(topic: str) -> str:
    """Discord threads are named in 100 characters at most."""
    name = THREAD_PREFIX + topic
    return name if len(name) <= 100 else name[:99] + "…"


def _row(buttons: list[dict]) -> list[dict]:
    return [{"type": 1, "components": buttons}]


def question(debate: Debate, counts: dict[str, int], *, verifying: bool = False, live: bool | str = False) -> dict:
    """The message that launches the debate: the subject, its context, the three position buttons (each shows how many people chose it) and the button that ends it. Without buttons
    once the debate is over."""
    over = debate.status == "closed"
    lines = [f"**{_plain(debate.topic)}**"]
    if debate.axis:
        lines.append(f"*Question posée par Dindon · axe « {_plain(str(debate.axis['name']))} »*")
    if debate.context:
        lines += ["", _plain(debate.context)]
    lines.append("")
    if over:
        lines.append("Ce débat est terminé.")
    else:
        quiet = f" ou après {rules.quiet_label(debate.quiet_seconds)} sans message" if debate.quiet_seconds else ""
        lines.append(f"{'Répondez' if debate.axis else 'Prenez position'} avec les boutons (modifiable). Fin : « Terminer le débat » (lanceur ou modérateur){quiet}.")
        if verifying and debate.verify:
            lines.append(notice_short(live))
        if not debate.in_thread:
            lines.append("**Dans ce salon, Dindon lit tous les messages écrits tant que le débat est ouvert.**")
    embed = {"title": "🗳️ Débat", "description": "\n".join(lines), "color": GREY if over else BLURPLE,
             "footer": {"text": "Dindon compte les messages de ce débat pour les statistiques de fin. /dindon stop vous en exclut."}}
    positions = [{"type": 2, "style": SECONDARY, "label": f"{label} · {counts.get(key, 0)}", "emoji": {"name": emoji}, "custom_id": custom_id("pos", debate.id, key)}
                 for key, (emoji, label) in position_buttons(debate.axis).items()]
    finish = [{"type": 2, "style": DANGER, "label": "Terminer le débat", "emoji": {"name": "🏁"}, "custom_id": custom_id("end", debate.id, "now")}]
    return {"content": "", "embeds": [embed], "components": [] if over else [*_row(positions), *_row(finish)], "allowed_mentions": NO_MENTIONS}


# --- the popup where the person chooses the parameters of the debate ----------------------------------------------------------------------------------

SETUP = "dindon:debat:setup"
QUIET_LABELS = {3_600: "1 heure", 21_600: "6 heures", 86_400: "24 heures", 259_200: "3 jours", 604_800: "7 jours"}


def setup_custom_id(user_id: int, channel_id: int) -> str:
    return f"{SETUP}:{user_id}:{channel_id}"


def parse_setup_id(raw: object) -> tuple[int, int] | None:
    """(the person, the channel) of the popup that this identifier belongs to; None for anything else."""
    parts = str(raw).split(":")
    return (int(parts[3]), int(parts[4])) if len(parts) == 5 and ":".join(parts[:3]) == SETUP and parts[3].isdigit() and parts[4].isdigit() else None


def _label(text: str, component: dict, description: str | None = None) -> dict:
    return {"type": 18, "label": text[:45], **({"description": description[:100]} if description else {}), "component": component}


OPTION_THREAD = ("thread", "Ouvrir un fil pour ce débat", "Sinon il a lieu ici ; Dindon y lit tous les messages tant qu'il est ouvert.", True)     # ticked: a thread reads only those who come
OPTION_VERIFY = ("verify", "Vérifier les affirmations sur Internet", "Une phrase de recherche neutre sort de la machine : voir /dindon info.", True)


def _choices_field(options: list[tuple], style: str) -> dict | None:
    """The yes-or-no choices of the popup (open a thread, check the claims), in one field. Two or more: a group of checkboxes (Discord asks for two at least). One: a checkbox of its own, named
    after the option. If Discord does not accept the checkboxes (`style="select"`): a list in which each option is ticked or not. None of them can be required: unticked is a valid answer."""
    if not options:
        return None
    if style == "checkbox" and len(options) == 1:
        name, text, description, default = options[0]
        return _label(text, {"type": 23, "custom_id": name, "default": default, "required": False}, description)
    items = [{"label": text, "value": name, "description": description, "default": default} for name, text, description, default in options]
    kind = 22 if style == "checkbox" else 3
    return _label("Options du débat", {"type": kind, "custom_id": "options", "required": False, "min_values": 0, "max_values": len(items), "options": items})


def setup_modal(user_id: int, channel_id: int, topic: str, *, can_thread: bool, can_verify: bool, axes: list | tuple = (), forum: str | None = None, style: str = "checkbox") -> dict:
    """The popup shown to the person who asked for a debate (Discord allows five fields): the subject (as they typed it, which they can change), the context, **an axis** (when they do not know what
    to debate: Dindon then asks the question of that axis), the options (open a thread; check the claims, only offered when the owner switched the checks on: it can only be turned off, never above
    what the owner allows) and the silence after which the debate ends by itself. The subject is only required when there is no axis to choose."""
    topic_input = {"type": 4, "custom_id": "topic", "style": 1, "min_length": rules.TOPIC_MIN, "max_length": rules.TOPIC_MAX, "required": not axes}
    if topic:
        topic_input["value"] = topic[: rules.TOPIC_MAX]
    fields = [_label("Sujet", topic_input, "Laissez vide pour que Dindon pose la question d'un axe." if axes else None),
              _label("Contexte (facultatif)", {"type": 4, "custom_id": "context", "style": 2, "max_length": rules.CONTEXT_MAX, "required": False},
                     "Ce qui cadre le débat : il sera publié dans le message de lancement.")]
    if axes:
        offered = [{"label": a.name[:100], "value": a.code, "description": f"{a.negative_pole} ↔ {a.positive_pole}"[:100]} for a in axes[:25]]
        fields.append(_label("Pas de sujet ? Choisissez un axe", {"type": 3, "custom_id": "axis", "required": False, "min_values": 0, "max_values": 1,
                                                                    "placeholder": "Dindon posera la question de l'axe", "options": offered},
                             "Dindon pose la question de l'axe. Ignoré si vous avez écrit un sujet."))
    thread = (OPTION_THREAD[0], OPTION_THREAD[1], f"Dans le forum « {forum[:30]} » ; sinon ici, où Dindon lit tous les messages.", OPTION_THREAD[3]) if forum else OPTION_THREAD
    choices = _choices_field([*([thread] if can_thread else []), *([OPTION_VERIFY] if can_verify else [])], style)
    if choices is not None:
        fields.append(choices)
    fields.append(_label("Fin automatique après un silence de", {"type": 3, "custom_id": "quiet", "required": True, "options": [
        {"label": name, "value": str(seconds), "default": seconds == rules.DEFAULT_QUIET} for seconds, name in QUIET_LABELS.items()]},
        "Sans message ni position pendant ce temps, le débat se termine seul."))
    return {"custom_id": setup_custom_id(user_id, channel_id), "title": "Paramètres du débat", "components": fields}


def modal_values(components: list) -> dict[str, object]:
    """What was answered in a popup, by field: the text, `True`/`False` for a checkbox, the list of values for a list. Walks the fields wherever they sit."""
    found: dict[str, object] = {}
    for item in components or []:
        if not isinstance(item, dict):
            continue
        custom = item.get("custom_id")
        if custom is not None and "values" in item:
            found[str(custom)] = [str(v) for v in item["values"]]
        elif custom is not None and "value" in item:
            found[str(custom)] = item["value"]
        for nested in (item.get("component"), *(item.get("components") or [])):
            if isinstance(nested, dict):
                found.update(modal_values([nested]))
    return found


def ticked(values: dict, name: str) -> bool:
    """Whether an option of the popup was ticked: a checkbox of its own (`True`/`False`), or one of the values of the group or the list `options`. An option that does not appear in the answer is
    not ticked: what the popup showed as ticked is the person's to keep, not something that is assumed."""
    if isinstance(values.get(name), bool):
        return values[name]
    chosen = values.get("options")
    return isinstance(chosen, list) and name in chosen


# --- the statistics at the end (debate/stats.py) -----------------------------------------------------------------------------------------------------

PEOPLE_PER_PAGE = 6
CLAIMS_PER_PAGE = 6
VERDICT_LABEL = {"confirmed": ("✅", "confirmée"), "contradicted": ("❌", "contredite"), "partly": ("🟡", "en partie vraie"), "disputed": ("⚖️", "contestée"), "unverifiable": ("❔", "non vérifiable")}
KEY_RULE = "Message phare : le plus commenté et le plus apprécié du fil (réponses ×3 + réactions), le même critère pour tout le monde."


def _duration(debate: dict) -> str:
    """How long the debate lasted, in words (from the launch message to its end)."""
    try:
        seconds = int((datetime.fromisoformat(debate["closed_at"]) - datetime.fromisoformat(debate["started_at"])).total_seconds())
    except (KeyError, TypeError, ValueError):
        return "—"
    if seconds < 90:
        return f"{max(seconds, 1)} s"
    days, rest = divmod(seconds, 86_400)
    hours, minutes = divmod(rest, 3_600)[0], rest % 3_600 // 60
    return " ".join(part for part in (f"{days} j" if days else "", f"{hours} h" if hours or days else "", f"{minutes} min" if not days else "") if part)


def _pages(items: int, per_page: int) -> int:
    return -(-items // per_page) if items else 0


def stats_pages(stats: dict) -> int:
    """How many pages the statistics have: the summary, the people, and the checked claims if there are any."""
    return 1 + _pages(len(stats["participants"]), PEOPLE_PER_PAGE) + _pages(len(stats["claims"]), CLAIMS_PER_PAGE)


def _verdict_line(counts: dict) -> str:
    return ", ".join(f"{n} {VERDICT_LABEL[v][1]}" for v, n in counts.items() if n)


def stats_page(stats: dict, page: int, *, checks_on: bool = False) -> dict:
    """One page of the statistics, as a message: the summary (why it ended, the figures, the positions, what was checked), then the people (each with their position, their messages and the
    message picked out), then the checked claims. Buttons turn the pages; the message is made again from the database at each click."""
    total = stats_pages(stats)
    page = max(0, min(page, total - 1))
    debate, totals = stats["debate"], stats["totals"]
    names, buttons = position_names(debate.get("axis")), position_buttons(debate.get("axis"))
    people_pages = _pages(len(stats["participants"]), PEOPLE_PER_PAGE)
    if page == 0:
        final = totals["final"]
        lines = [f"**{_plain(debate['topic'])}**", REASONS.get(debate["close_reason"] or "", "Le débat est terminé."),
                 f"**{totals['participants']}** participant(s) · **{totals['messages']}** message(s) · durée **{_duration(debate)}**"]
        if totals["participants"]:
            lines.append("Positions : " + " · ".join(f"{buttons[k][0]} {buttons[k][1]} **{final[k]}**" for k in rules.POSITIONS) + (f" · sans position **{final['none']}**" if final["none"] else ""))
            if totals["changed_mind"]:
                lines.append(f"{totals['changed_mind']} personne(s) ont changé de position pendant le débat.")
        if stats["claims"]:
            lines.append(f"**{len(stats['claims'])}** affirmation(s) vérifiée(s) : {_verdict_line(totals['verdicts'])}.")
        elif checks_on and debate.get("verify", True) and not totals.get("answers", {}).get("false") and not totals.get("answers", {}).get("true"):   # (a debate opened without verification says nothing of it)
            lines.append("Aucune affirmation de fait n'a été vérifiée.")
        given = totals.get("answers") or {}
        if given.get("false"):
            lines.append(f"Dindon a répondu à **{given['false']}** affirmation(s) sans chercher sur Internet : {given['valid']} vote(s) Valide, {given['invalid']} vote(s) Invalide, "
                         f"**{given['searched']}** recherche(s) sur Internet ensuite.")
        title, color = "🏁 Débat terminé", GREY
    elif page <= people_pages:
        chunk = stats["participants"][(page - 1) * PEOPLE_PER_PAGE: page * PEOPLE_PER_PAGE]
        lines = []
        for p in chunk:
            head = f"<@{p['user_id']}> — {names[p['position']]}" + (f" (avant : {names[p['first_position']]})" if p["changed"] else "")
            claim_line = f" · vérifiées : {_verdict_line(p['claims'])}" if any(p["claims"].values()) else ""
            lines += [head, f"**{p['messages']}** message(s) ({round(p['share'] * 100)} %){claim_line}"]
            key = p["key_message"]
            if key:
                lines.append(f"> « {_plain(key['excerpt'])} »" + (f" · [message phare]({key['url']})" if key["url"] else "") + f" ({key['replies']} réponse(s), {key['reactions']} réaction(s))")
            lines.append("")
        title, color = f"👥 Les participants ({page}/{people_pages})", BLURPLE
    else:
        first = page == people_pages + 1
        chunk = stats["claims"][(page - people_pages - 1) * CLAIMS_PER_PAGE: (page - people_pages) * CLAIMS_PER_PAGE]
        lines = []
        if first:
            for position, row in stats["parity"].items():
                lines.append(f"{names[position if position != 'none' else None]} : {row['total']} vérifiée(s) ({_verdict_line({k: v for k, v in row.items() if k != 'total'})})")
            lines.append("")
        for c in chunk:
            emoji, label = VERDICT_LABEL[c["verdict"]]
            jump = f"https://discord.com/channels/{debate['guild_id']}/{debate['thread_id']}/{c['message_id']}" if debate["thread_id"] else None
            links = " ".join(f"[{_source_name(s['url'])}]({s['url'].replace('(', '%28').replace(')', '%29')})" for s in c["sources"][:2])
            lines.append(f"{emoji} « {_plain(c['claim'])} » : **{label}**" + (f" ({_plain(c['period'])})" if c["period"] else "")
                         + (f" · [le message]({jump})" if jump else "") + (f" · {links}" if links else ""))
        title, color = f"🔎 Affirmations vérifiées ({page - people_pages}/{_pages(len(stats['claims']), CLAIMS_PER_PAGE)})", BLURPLE
    embed = {"title": title, "description": "\n".join(lines).strip()[:4000], "color": color, "footer": {"text": f"Page {page + 1}/{total} · {KEY_RULE}"[:2000]}}
    payload = {"content": "", "embeds": [embed], "allowed_mentions": NO_MENTIONS}
    if total > 1:
        buttons = [{"type": 2, "style": SECONDARY, "label": "Précédent", "emoji": {"name": "◀️"}, "custom_id": custom_id("stats", debate["id"], str(max(page - 1, 0))), "disabled": page == 0},
                   {"type": 2, "style": SECONDARY, "label": "Suivant", "emoji": {"name": "▶️"}, "custom_id": custom_id("stats", debate["id"], str(min(page + 1, total - 1))), "disabled": page == total - 1}]
        payload["components"] = _row(buttons)
    else:
        payload["components"] = []
    return payload
