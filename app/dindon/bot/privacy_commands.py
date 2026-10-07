"""The commands that every member can use on Discord to control what Dindon holds of them: `/dindon info | mes-donnees | stop | effacer | reprendre | card @someone`.

* They arrive on the Gateway as INTERACTION_CREATE (the commands) and, for the confirmation button of `effacer`, as a component interaction.
  Everything is answered **ephemerally**: only the person sees it. Except `card`, whose point is to be posted in the channel (cards.py).
* Discord gives **3 seconds** to answer an interaction. Anything that touches the database (it may wait for an import that holds the lock, or
  rewrite many files) is therefore *deferred*: the interaction is acknowledged at once, and the real answer replaces it when it is ready.
* `stop`: nothing more is recorded of the person; what is held stays (reversible with `reprendre`). `effacer`: stop AND delete what is held
  (messages, reactions, what was made from them, their traces in archive/ and inbox/). It is irreversible, so it asks for a click first.
* `mes-donnees`: a JSON file with everything held of the person, sent to them alone (counts only if it is too big for Discord).
* The commands are registered at each READY (a global command; Discord takes a little while to show it on a new server). This needs the
  `applications.commands` scope in the invitation link (api/invite.py).
* A person can act on **themselves** only (the id comes from Discord's interaction, and the button carries it and is checked again). Every
  action is rate-limited per person, and the database work is done one at a time.
* Nothing here logs a message, a name or an id: counts only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg

from dindon import discord_map, privacy
from dindon.db import connect

log = logging.getLogger("dindon.bot.privacy")

EPHEMERAL = 64
CHANNEL_MESSAGE, DEFERRED_MESSAGE, UPDATE_MESSAGE, MODAL = 4, 5, 7, 9
DEFERRED_UPDATE = 6
SUBCOMMANDS = ("info", "mes-donnees", "stop", "effacer", "reprendre", "card", "mycard", "map", "debat", "param")
COOLDOWN_SECONDS = 15
MAX_FILE_BYTES = 7_000_000          # under every limit of Discord for an attachment

COMMAND = {
    "name": "dindon",
    "description": "Vos données dans Dindon (la carte de ce serveur)",
    "type": 1,
    "options": [
        {"type": 1, "name": "info", "description": "Ce que Dindon enregistre, et vos droits"},
        {"type": 1, "name": "mes-donnees", "description": "Recevoir un fichier avec tout ce que Dindon garde de moi"},
        {"type": 1, "name": "stop", "description": "Arrêter l'enregistrement de mes messages (ce qui est déjà gardé reste)"},
        {"type": 1, "name": "effacer", "description": "Arrêter l'enregistrement ET effacer tout ce que Dindon garde de moi (définitif)"},
        {"type": 1, "name": "reprendre", "description": "Accepter de nouveau l'enregistrement de mes messages"},
        {"type": 1, "name": "card", "description": "La carte d'une personne : un résumé de ce que Dindon sait d'elle, postée dans ce salon",
         "options": [{"type": 6, "name": "pseudo", "description": "La personne", "required": True}]},
        {"type": 1, "name": "mycard", "description": "Régler ma propre card : le contenu de chaque partie, avec les suggestions de Dindon (privé)"},
        {"type": 1, "name": "map", "description": "La carte du serveur : qui parle avec qui, en image, postée dans ce salon",
         "options": [{"type": 3, "name": "periode", "description": "La période (30 jours par défaut)", "required": False,
                      "choices": [{"name": label, "value": key} for key, (label, _) in discord_map.PERIODS.items()]},
                     {"type": 6, "name": "personne", "description": "Se centrer sur une personne : ses liens les plus forts", "required": False},
                     {"type": 3, "name": "forme", "description": "La forme du graphique autour de la personne (normale par défaut)", "required": False,
                      "choices": [{"name": label, "value": key} for key, label in discord_map.SHAPES.items()]}]},
        {"type": 1, "name": "debat", "description": "Ouvrir un débat : une fenêtre pour choisir ses paramètres, des positions, des statistiques à la fin",
         "options": [{"type": 3, "name": "sujet", "description": "La question débattue (vide : vous pourrez choisir un axe dans la fenêtre)", "required": False, "min_length": 3, "max_length": 200}]},
        {"type": 1, "name": "param", "description": "Choisir le forum des débats et le salon des sondages (modérateurs)",
         "options": [{"type": 7, "name": "forum", "description": "Le forum des débats : chaque débat y devient un post", "channel_types": [15]},
                     {"type": 7, "name": "sondages", "description": "Le salon texte où publier les sondages liés aux débats", "channel_types": [0, 5]},
                     {"type": 3, "name": "etiquette", "description": "Étiquette de secours si le sujet ne correspond à aucune", "max_length": 20},
                     {"type": 5, "name": "retirer", "description": "Retirer le forum des débats et le salon des sondages"}]},
    ],
}


# What makes the application appear in the rocket of a voice channel (the Activity, docs/fonctionnement.md): a command of type 4 that Discord itself handles. The list of
# commands is replaced as a whole at each start, so a command that is not in it is deleted: the entry point must be in it, or the Activity disappears from the channels.
ENTRY_POINT = {"name": "carte", "description": "Ouvrir la carte de Dindon dans le salon vocal", "type": 4, "handler": 2, "integration_types": [0], "contexts": [0]}


@dataclass
class Reply:
    text: str
    file: tuple[str, bytes] | None = None
    embed: dict | None = None
    components: list | None = None


def _text(retention_days: int = 0) -> dict[str, str]:
    kept = f"**{retention_days} jours**, puis les messages sont supprimés automatiquement" if retention_days else "sans limite de durée (jusqu'à ce que vous demandiez l'effacement)"
    return {
        "info": ("**Dindon**, c'est la carte de ce serveur : qui parle avec qui, et de quoi.\n"
                 "**Ce qui est gardé** : le texte de vos messages, leur date et leur salon, vos réactions, qui vous mentionne ou vous répond, "
                 "votre pseudo et vos rôles sur le serveur.\n"
                 f"**Où et combien de temps** : sur le serveur de la personne qui héberge Dindon, rien n'est envoyé à un service d'IA extérieur ; {kept}. "
                 "Une copie de sauvegarde de la base disparaît d'elle-même sous 14 jours.\n"
                 "**À quoi ça sert** : la carte des échanges, le regroupement des conversations par sujets, et une IA sur le serveur ou sur les autres ordinateurs privés de l'hébergeur "
                 "peut résumer ce que chacun défend (avec la citation qui le prouve). Si ces ordinateurs sont activés, des extraits de conversation leur sont transmis. Rien n'est vendu ni partagé avec un tiers.\n"
                 "**Si vous modifiez ou supprimez un message**, Dindon le modifie ou le supprime aussi, avec ce qui en avait été tiré.\n"
                 "**Vos droits, à tout moment :**\n"
                 "• `/dindon mes-donnees` : un fichier avec tout ce qui est gardé de vous\n"
                 "• `/dindon stop` : on arrête de vous enregistrer (ce qui est déjà gardé reste)\n"
                 "• `/dindon effacer` : on arrête **et** on efface tout ce qui est gardé de vous (définitif)\n"
                 "• `/dindon reprendre` : vous acceptez de nouveau l'enregistrement\n"
                 "• `/dindon card @quelqu'un` : poste la carte (le résumé) d'une personne dans ce salon\n"
                 "• `/dindon map` : poste l'image de la carte du serveur (qui parle avec qui), si les administrateurs l'ont activée\n"
                 "• `/dindon debat sujet` : ouvre un débat ; vos messages et votre position y sont comptés, et à la fin des statistiques sont publiées (`/dindon stop` vous en exclut)"),
        "no_debates": "Les débats ne sont pas disponibles pour le moment.",
        "card_none": "Dindon n'a rien à montrer pour cette personne (jamais vue, un bot, ou elle a demandé à ne pas être enregistrée).",
        "map_off": "La carte n'est pas activée sur ce serveur : les administrateurs peuvent le faire depuis l'interface de Dindon.",
        "map_none": "Dindon n'a rien à montrer pour cette période (pas d'échanges, ou la personne demandée n'est pas enregistrée).",
        "map_failed": "La carte n'a pas pu être faite. Réessayez dans un instant.",
        "card_failed": "La carte n'a pas pu être faite. Réessayez dans un instant.",
        "ask_erase": ("**Effacer définitivement** tout ce que Dindon garde de vous ? Vos messages, réactions et ce qui en a été tiré seront supprimés et "
                      "vous ne serez plus enregistré·e. Cela ne peut pas être annulé."),
        "erasing": "Effacement en cours…",
        "cancelled": "Annulé : rien n'a été effacé.",
        "stopped": "C'est fait : **vos messages ne sont plus enregistrés.** Ce qui était déjà gardé reste ; `/dindon effacer` le supprime.",
        "erased": ("C'est fait : **vos messages ne sont plus enregistrés** et ce qui était gardé de vous a été effacé ({counts}). "
                   "Les copies de sauvegarde disparaissent d'elles-mêmes sous 14 jours. "
                   "Les messages d'autres personnes qui parlent de vous ne sont pas les vôtres et restent."),
        "resumed": "C'est noté : vos messages peuvent de nouveau être enregistrés. Ce qui avait été effacé ne revient pas. `/dindon stop` l'arrête à tout moment.",
        "not_stopped": "Vous n'étiez pas dans la liste des personnes qui ne sont pas enregistrées : rien à reprendre.",
        "wait": "Un instant : une demande de vous est déjà en cours ou vient d'être faite. Réessayez dans quelques secondes.",
        "failed": "Une erreur est survenue, rien n'a été modifié. Réessayez dans un instant" + ".",
    }


class PrivacyService:
    """What the commands do to the database, and the short list of people not to record (kept in memory, refreshed by the engine)."""

    def __init__(self, database_url: str, directories: tuple[Path, ...] = (), clock=time.monotonic, retention_days: int = 0):
        self._url, self.directories, self.retention_days = database_url, directories, retention_days
        self._conn: psycopg.Connection | None = None
        self._register_conn: psycopg.Connection | None = None   # its own: reading the register must never wait for a long job
        self._lock = threading.Lock()                      # one database job at a time: they all queue on the import's lock anyway
        self._clock = clock
        self._last: dict[int, float] = {}
        self.blocked: set[str] = set()

    def _connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = connect(self._url)
            self._conn.autocommit = True
        return self._conn

    def refresh(self) -> None:
        """Reads the register again (called every few seconds by the engine: a stop made from the interface applies within that)."""
        try:
            if self._register_conn is None or self._register_conn.closed:
                self._register_conn = connect(self._url)
                self._register_conn.autocommit = True
            self.blocked = {str(i) for i in privacy.blocked_ids(self._register_conn)}   # (the ingestion filters anyway: a late read cannot record anyone)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self._register_conn = None
            raise

    def too_soon(self, user_id: int) -> bool:
        """At most one request per person every few seconds (a script cannot make the bot erase and record again in a loop)."""
        now = self._clock()
        if now - self._last.get(user_id, -1e9) < COOLDOWN_SECONDS:
            return True
        self._last = {u: t for u, t in self._last.items() if now - t < COOLDOWN_SECONDS}
        self._last[user_id] = now
        return False

    def card(self, guild_id: int, user_id: int, avatar: str | None, page: int = 0) -> Reply:
        """The card of a person (see cards.py), or why there is none. Read only."""
        from dindon import cards

        text = _text()
        if str(user_id) in self.blocked:
            return Reply(text["card_none"])
        with self._lock:
            try:
                data = cards.person_card(self._connection(), guild_id, user_id)
                cfg = cards.load(self._connection())
                from dindon import mycard
                prefs = mycard.clean(mycard.load(self._connection(), guild_id, user_id), cfg)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self._conn = None
                return Reply(text["card_failed"])
            except Exception as error:
                log.error("a card could not be made (%s)", type(error).__name__)
                return Reply(text["card_failed"])
        return Reply(text["card_none"]) if data is None else Reply("", embed=cards.card_page(data, page, avatar, cfg, prefs), components=cards.card_buttons(user_id, page, cfg))

    def mycard(self, guild_id: int, user_id: int, avatar: str | None, page: int = 0, change: tuple | None = None, note: str | None = None) -> dict | None:
        """The private screen of `/dindon mycard` (see mycard.py), after a change if there is one. None: this person has no card (never seen, or asked not to be recorded)."""
        from dindon import mycard

        if str(user_id) in self.blocked:
            return None
        with self._lock:
            try:
                conn = self._connection()
                if change is not None:
                    mycard.apply(conn, guild_id, user_id, change)
                return mycard.view(conn, guild_id, user_id, page, avatar, note)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self._conn = None
                raise
            except Exception as error:
                log.error("the screen of a card could not be made (%s)", type(error).__name__)
                raise

    @staticmethod
    def _pictures(guild_id: int, urls: dict[int, str]) -> dict[int, bytes]:
        """The photos of the people on the map, a few at a time (they are kept in memory, shared with the Activity). A photo that cannot be had is left out: a plain disc is drawn."""
        from concurrent.futures import ThreadPoolExecutor

        from dindon.api.activity import cached_picture

        def get(item: tuple[int, str]) -> tuple[int, bytes | None]:
            try:
                return item[0], cached_picture(guild_id, item[0], item[1])[0]
            except Exception:
                return item[0], None

        with ThreadPoolExecutor(max_workers=8) as pool:
            return {uid: body for uid, body in pool.map(get, urls.items()) if body is not None}

    def map(self, guild_id: int, period: str, focus: int | None, shape: str = "normal") -> Reply:
        """The picture of the map (see discord_map.py) with the menu of periods under it, or why there is none. Read only; what it shows follows the settings."""
        text = _text()
        days = discord_map.PERIODS[period][1]
        with self._lock:
            try:
                conn = self._connection()
                cfg = discord_map.load(conn)
                if not cfg["enabled"]:
                    return Reply(text["map_off"])
                data = discord_map.collect(conn, guild_id, days, focus, cfg)
                card, urls = None, {}
                if data is not None:
                    card = discord_map.person(conn, guild_id, focus, data, cfg) if focus is not None else None       # the card on the right: what the admins allowed
                    if cfg["names"] >= 1:                                                                                # a photo is shown like a name: only for the people named
                        urls = {r[0]: r[1] for r in conn.execute("SELECT user_id, avatar_url FROM members WHERE guild_id = %s AND user_id = ANY(%s) AND avatar_url IS NOT NULL",
                                                                 (guild_id, sorted(discord_map.named(data, cfg))))}
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self._conn = None
                return Reply(text["map_failed"])
            except Exception as error:
                log.error("a map could not be made (%s)", type(error).__name__)
                return Reply(text["map_failed"])
        if data is None:
            return Reply(text["map_none"])
        pictures = self._pictures(guild_id, urls)
        who = next((p["label"] for p in data["people"] if p["id"] == focus), None)
        title = f"**{discord_map.PERIODS[period][0]}** · {len(data['people'])} personnes, {len(data['links'])} liens" + (f" · autour de **{who}**" if who else "")
        shape = shape if focus is not None and shape in discord_map.SHAPES else "normal"
        menu = {"type": 3, "custom_id": f"dindon:map:{focus or 0}" + (f":{shape}" if shape != "normal" else ""), "placeholder": "Changer la période",
                "options": [{"label": label, "value": key, "default": key == period} for key, (label, _) in discord_map.PERIODS.items()]}
        rows = [{"type": 1, "components": [menu]}]
        if focus is not None:                                                    # the shape of the picture: only around a person
            rows.append({"type": 1, "components": [{"type": 3, "custom_id": f"dindon:shape:{focus}:{period}", "placeholder": "Changer la forme",
                                                    "options": [{"label": label, "value": key, "default": key == shape} for key, label in discord_map.SHAPES.items()]}]})
        return Reply(title, file=("carte.png", discord_map.render(data, cfg["names"], pictures, card, shape)), components=rows)

    def run(self, user_id: int, sub: str) -> Reply:
        """Does what a member asked, and returns what to tell them."""
        text = _text(self.retention_days)
        if sub == "info":
            return Reply(text["info"])
        with self._lock:
            try:
                conn = self._connection()
                if sub == "stop":
                    privacy.stop_recording(conn, user_id, reason="discord command", source="discord")
                    self.blocked.add(str(user_id))
                    return Reply(text["stopped"])
                if sub == "effacer":
                    counts = privacy.erase_person(conn, user_id, reason="discord command", source="discord", file_directories=self.directories)
                    self.blocked.add(str(user_id))
                    return Reply(text["erased"].format(counts=f"{counts['messages']} messages, {counts['reactions']} réactions"))
                if sub == "reprendre":
                    if privacy.release(conn, user_id, source="discord"):
                        self.blocked.discard(str(user_id))
                        return Reply(text["resumed"])
                    return Reply(text["not_stopped"])
                if sub == "mes-donnees":
                    held = privacy.export_person(conn, user_id)
                    lines = [f"Dindon garde de vous : **{len(held['messages'])} messages**, {len(held['reactions'])} réactions, "
                             f"{len(held['mentioned_in_messages'])} mentions de vous, {len(held['names_seen'])} noms vus."]
                    if held["debates"]:
                        lines.append(f"Vous avez pris part à **{len(held['debates'])} débat(s)** : vos positions, le nombre de vos messages comptés et les affirmations vérifiées sont dans le fichier.")
                    if held["register"]:
                        lines.append("Vous êtes dans la liste des personnes **qui ne sont pas enregistrées**.")
                    raw = json.dumps(held, ensure_ascii=False, indent=2).encode()
                    if len(raw) <= MAX_FILE_BYTES:
                        lines.append("Le fichier ci-joint contient tout : il n'est visible que de vous.")
                        return Reply("\n".join(lines), (f"dindon-{user_id}.json", raw))
                    lines.append("C'est trop volumineux pour Discord, demandez la copie à la personne qui héberge Dindon.")
                    return Reply("\n".join(lines))
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self._conn = None
            except Exception as error:
                log.error("a privacy command failed (%s)", type(error).__name__)
        return Reply(text["failed"])


class Interactions:
    """Registers the command and answers it. REST calls are made in a thread, with urllib, like the rest of the Discord calls of Dindon."""

    def __init__(self, token: str, api_url: str, service: PrivacyService, activity: bool = False):
        self.activity = activity        # the Activity is set up (DISCORD_CLIENT_ID): the entry point is registered with the command
        self._token = token[4:] if token.startswith("Bot ") else token
        self._api = api_url.rstrip("/")
        self.service = service
        self.registered = False
        self.debates = None             # the debates (bot/debate_commands.py), or None: their command and buttons are then not answered
        self.live = False               # …and the corrections are posted in public
        self.verification = False       # the claims of the debates are checked on the Internet: `/dindon info` then says what leaves the machine (debate/texts.py NOTICE)

    def _request(self, method: str, path: str, body, authorized: bool, attachment: tuple[str, bytes] | None = None) -> int:
        headers = {"User-Agent": "dindon"}
        if authorized:
            headers["Authorization"] = f"Bot {self._token}"
        if attachment is None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        else:                                           # a message with a file: multipart, the JSON part first
            boundary = uuid.uuid4().hex
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            name, content = attachment
            body = {**body, "attachments": [{"id": 0, "filename": name}]}
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'
                    f'{json.dumps(body)}\r\n--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{name}"\r\n'
                    f"Content-Type: {'image/png' if name.endswith('.png') else 'application/json'}\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(f"{self._api}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
        except OSError:
            return 0

    async def register(self, application_id: str) -> None:
        commands = [COMMAND, ENTRY_POINT] if self.activity else [COMMAND]
        status = await asyncio.to_thread(self._request, "PUT", f"/applications/{application_id}/commands", commands, True)
        if status != 200 and self.activity:                 # the Activity is not enabled in the Developer Portal: the members' command must still be there
            log.warning("the entry point of the Activity was refused (HTTP %s): enable Activities in the Developer Portal", status)
            status = await asyncio.to_thread(self._request, "PUT", f"/applications/{application_id}/commands", [COMMAND], True)
        self.registered = status == 200
        if self.registered:
            log.info("the command /dindon is registered")
        else:
            log.warning("the command /dindon could not be registered (HTTP %s)", status)

    async def _callback(self, data: dict, kind: int, content: str | None = None, components: list | None = None, public: bool = False) -> None:
        body: dict = {"type": kind}
        if content is not None:
            body["data"] = {"content": content, "flags": EPHEMERAL, "allowed_mentions": {"parse": []}, "components": components or []}
        elif kind == DEFERRED_MESSAGE:
            body["data"] = {"flags": 0 if public else EPHEMERAL}
        status = await asyncio.to_thread(self._request, "POST", f"/interactions/{data['id']}/{data['token']}/callback", body, False)
        if status >= 300 or status == 0:
            log.warning("the answer to a command was refused (HTTP %s)", status)

    async def modal(self, data: dict, payload: dict, fallback: dict | None = None) -> bool:
        """Answers a command with a popup. If Discord refuses it (it has just begun to accept some of the fields), the same popup in a plainer form is tried. False if neither was accepted."""
        for attempt in (payload, fallback):
            if attempt is None:
                continue
            status = await asyncio.to_thread(self._request, "POST", f"/interactions/{data['id']}/{data['token']}/callback", {"type": MODAL, "data": attempt}, False)
            if 200 <= status < 300:
                return True
            if status != 400:
                break
        log.warning("a popup was refused by Discord")
        return False

    async def show(self, data: dict, payload: dict) -> None:
        """Replaces the message that a button belongs to by another one (the page of the statistics that was asked for)."""
        status = await asyncio.to_thread(self._request, "POST", f"/interactions/{data['id']}/{data['token']}/callback", {"type": UPDATE_MESSAGE, "data": payload}, False)
        if status >= 300 or status == 0:
            log.warning("the page of a message was refused (HTTP %s)", status)

    async def _followup(self, data: dict, content: str) -> None:
        """Another private message after the answer, with the same interaction (Discord keeps it open 15 minutes)."""
        body = {"content": content, "flags": EPHEMERAL, "allowed_mentions": {"parse": []}}
        status = await asyncio.to_thread(self._request, "POST", f"/webhooks/{data.get('application_id')}/{data['token']}", body, False)
        if status >= 300 or status == 0:
            log.warning("a second message of an answer was refused (HTTP %s)", status)

    # What the debates need to answer a person, without reaching into this class's private methods
    async def say(self, data: dict, text: str) -> None:
        """A private answer, at once."""
        await self._callback(data, CHANNEL_MESSAGE, text)

    async def say_with(self, data: dict, text: str, components: list) -> None:
        """A private answer with a list or buttons under it."""
        await self._callback(data, CHANNEL_MESSAGE, text, components)

    async def defer(self, data: dict) -> None:
        """'Thinking…' (private), when the answer takes longer than the 3 seconds that Discord gives."""
        await self._callback(data, DEFERRED_MESSAGE)

    async def finish(self, data: dict, reply: Reply) -> None:
        """The real answer, after `defer`."""
        await self._edit(data, reply)

    async def _edit(self, data: dict, reply: Reply) -> None:
        """Replaces the 'thinking…' of a deferred answer by the real one."""
        path = f"/webhooks/{data.get('application_id')}/{data['token']}/messages/@original"
        body: dict = {"content": reply.text, "components": reply.components or [], "allowed_mentions": {"parse": []}}
        if reply.embed:
            body["embeds"] = [reply.embed]
        if reply.file is None:
            body["attachments"] = []                    # a message that turns into text (or a card) lets go of the picture of the map it had
        status = await asyncio.to_thread(self._request, "PATCH", path, body, False, reply.file)
        if status >= 300 or status == 0:
            log.warning("the final answer to a command was refused (HTTP %s)", status)

    async def answer(self, data: dict) -> None:
        """INTERACTION_CREATE: a member used the command, or clicked its button. Always answered, even when it fails."""
        user = (data.get("member") or {}).get("user") or data.get("user") or {}
        try:
            user_id = int(user["id"])
        except (KeyError, ValueError, TypeError):
            return
        text = _text(self.service.retention_days)
        if data.get("type") == 5:                                                 # a popup that was filled and sent: the parameters of a debate
            custom_id = str((data.get("data") or {}).get("custom_id", ""))
            if self.debates is not None and custom_id.startswith("dindon:debat:setup:"):
                await self.debates.modal_submit(data, user_id)
            elif self.debates is not None and custom_id.startswith("dindon:debat:rate:"):
                await self.debates.rating_submit(data, user_id)
            elif custom_id.startswith("dindon:mycard:note:"):
                await self._mycard_note(data, user_id)
            return
        if data.get("type") == 3:                                                 # a button: `effacer`, or a page of a card
            custom_id = str((data.get("data") or {}).get("custom_id", ""))
            if custom_id.startswith("dindon:card:"):
                await self._page(data)
            elif custom_id.startswith("dindon:mycard:"):
                await self._mycard_component(data, user_id)
            elif custom_id.startswith(("dindon:map:", "dindon:shape:")):
                await self._map_period(data)
            elif custom_id.startswith("dindon:debat:"):
                if self.debates is not None:
                    await self.debates.button(data, user_id)
            else:
                await self._button(data, user_id, text)
            return
        if data.get("type") != 2 or (data.get("data") or {}).get("name") != "dindon":
            return
        options = (data.get("data") or {}).get("options") or [{}]
        sub = options[0].get("name", "info")
        sub = sub if sub in SUBCOMMANDS else "info"
        if sub == "info":
            await self._callback(data, CHANNEL_MESSAGE, text["info"])
            if self.verification:                                                   # a second message: the first is close to the 2000 characters that Discord allows
                from dindon.debate.texts import NOTICE_TITLE, notice

                await self._followup(data, f"**{NOTICE_TITLE}.** {notice(self.live)}")
        elif sub == "card":
            await self._card(data, user_id, options[0], text)
        elif sub == "mycard":
            await self._mycard(data, user_id, text)
        elif sub == "map":
            await self._map(data, user_id, options[0], text)
        elif sub in ("debat", "param"):
            if self.debates is None:
                await self._callback(data, CHANNEL_MESSAGE, text["no_debates"])
            elif sub == "param":
                await self.debates.param_command(data, user_id, options[0])
            else:
                await self.debates.command(data, user_id, options[0])
        elif self.service.too_soon(user_id):
            await self._callback(data, CHANNEL_MESSAGE, text["wait"])
        elif sub == "effacer":                                                    # irreversible: one more click, by this person
            buttons = [{"type": 2, "style": 4, "label": "Oui, effacer définitivement", "custom_id": f"dindon:erase:{user_id}"},
                       {"type": 2, "style": 2, "label": "Annuler", "custom_id": f"dindon:cancel:{user_id}"}]
            await self._callback(data, CHANNEL_MESSAGE, text["ask_erase"], [{"type": 1, "components": buttons}])
        else:
            await self._callback(data, DEFERRED_MESSAGE)
            await self._edit(data, await asyncio.to_thread(self.service.run, user_id, sub))

    async def _card(self, data: dict, user_id: int, option: dict, text: dict) -> None:
        """`/dindon card @someone`: the card is posted in the channel where it was asked (everybody sees it: that is what it is for)."""
        try:
            target = int(option["options"][0]["value"])
            guild_id = int(data["guild_id"])
        except (KeyError, ValueError, TypeError, IndexError):
            await self._callback(data, CHANNEL_MESSAGE, text["card_none"])
            return
        if self.service.too_soon(user_id):
            await self._callback(data, CHANNEL_MESSAGE, text["wait"])
            return
        resolved = ((data.get("data") or {}).get("resolved") or {}).get("users") or {}
        from dindon.cards import avatar_url

        await self._callback(data, DEFERRED_MESSAGE, public=True)
        await self._edit(data, await asyncio.to_thread(self.service.card, guild_id, target, avatar_url(resolved.get(str(target)))))

    async def _mycard_screen(self, data: dict, user_id: int, page: int, change: tuple | None = None, note: str | None = None, *, update: bool) -> None:
        """Shows (or shows again, after a change) the private screen of `/dindon mycard`."""
        from dindon.cards import avatar_url

        try:
            guild_id = int(data["guild_id"])
            avatar = avatar_url((data.get("member") or {}).get("user") or data.get("user"))
            payload = await asyncio.to_thread(self.service.mycard, guild_id, user_id, avatar, page, change, note)
        except (KeyError, ValueError, TypeError):
            await self._callback(data, CHANNEL_MESSAGE, _text()["card_none"])
            return
        except Exception:
            await self._callback(data, CHANNEL_MESSAGE, _text()["card_failed"])
            return
        if payload is None:
            await self._callback(data, CHANNEL_MESSAGE, _text()["card_none"])
        elif update:
            await self.show(data, payload)
        else:
            body = {"type": CHANNEL_MESSAGE, "data": {**payload, "flags": EPHEMERAL}}
            status = await asyncio.to_thread(self._request, "POST", f"/interactions/{data['id']}/{data['token']}/callback", body, False)
            if status >= 300 or status == 0:
                log.warning("the screen of a card was refused (HTTP %s)", status)

    async def _mycard(self, data: dict, user_id: int, text: dict) -> None:
        """`/dindon mycard`: only for the person, private. Cooldown like the other commands."""
        if self.service.too_soon(user_id):
            await self._callback(data, CHANNEL_MESSAGE, text["wait"])
            return
        await self._mycard_screen(data, user_id, 0, update=False)

    async def _mycard_component(self, data: dict, user_id: int) -> None:
        """A button or a list of the screen: change the page, the blocks, the positions, apply a suggestion, open the popup of a note, go back to the start."""
        from dindon import cards

        parts = str((data.get("data") or {}).get("custom_id", "")).split(":")
        values = (data.get("data") or {}).get("values") or []
        try:
            kind, arg = parts[2], int(parts[3])
            page_key = cards.PAGE_KEYS[arg if kind != "s" else 2]
            if kind == "p":
                await self._mycard_screen(data, user_id, arg, update=True)
            elif kind == "b":
                await self._mycard_screen(data, user_id, arg, ("blocks", page_key, [str(v) for v in values]), update=True)
            elif kind == "s":
                await self._mycard_screen(data, user_id, 2, ("pinned", [int(v) for v in values]), update=True)
            elif kind == "r":
                await self._mycard_screen(data, user_id, arg, ("reset", page_key), update=True)
            elif kind == "n":
                await self.modal(data, self._note_modal(arg, "s", None))
            elif kind == "a":
                todo = await asyncio.to_thread(self._suggestion, int(data["guild_id"]), user_id, page_key, int(values[0]))
                if todo is not None and todo[0] == "note":
                    target = "s" if todo[1].startswith("section:") else f"p{todo[1].split(':')[1]}"
                    await self.modal(data, self._note_modal(arg, target, None))
                else:
                    await self._mycard_screen(data, user_id, arg, ("suggestion", page_key, int(values[0])), update=True)
        except (IndexError, ValueError, TypeError, KeyError):
            await self._callback(data, CHANNEL_MESSAGE, _text()["card_failed"])

    def _suggestion(self, guild_id: int, user_id: int, page_key: str, index: int):
        from dindon import cards, mycard

        with self._lock:
            conn = self._connection()
            cfg = cards.load(conn)
            card = cards.person_card(conn, guild_id, user_id)
            if card is None:
                return None
            todo = mycard.suggestions(card, cfg, mycard.clean(mycard.load(conn, guild_id, user_id), cfg))[page_key]
            return todo[index]["action"] if 0 <= index < len(todo) else None

    @staticmethod
    def _note_modal(page: int, target: str, current: str | None) -> dict:
        return {"custom_id": f"dindon:mycard:note:{page}:{target}", "title": "Note sous votre card", "components": [
            {"type": 1, "components": [{"type": 4, "custom_id": "note", "style": 2, "label": "Note (200 caractères, vide : l'enlever)", "required": False, "max_length": 200,
                                        **({"value": current} if current else {})}]}]}

    async def _mycard_note(self, data: dict, user_id: int) -> None:
        """The popup of a note was sent: it is kept (empty: removed), and the screen is shown again."""
        from dindon import cards, mycard
        from dindon.debate.texts import modal_values

        parts = str((data.get("data") or {}).get("custom_id", "")).split(":")
        try:
            page, target = int(parts[3]), parts[4]
            key = f"section:{cards.PAGE_KEYS[page]}" if target == "s" else f"pos:{int(target[1:])}"
            note = mycard.clean_note(modal_values((data.get("data") or {}).get("components")).get("note"))
        except (IndexError, ValueError, TypeError):
            return
        await self._mycard_screen(data, user_id, page, ("note", key, note), "Note enregistrée." if note else "Note retirée.", update=True)

    async def _map(self, data: dict, user_id: int, option: dict, text: dict) -> None:
        """`/dindon map [periode] [personne] [forme]`: the picture is posted in the channel. Only the choices that the command offers are taken."""
        given = {o.get("name"): o.get("value") for o in option.get("options") or []}
        period = given.get("periode") if given.get("periode") in discord_map.PERIODS else "30"
        try:
            focus = int(given["personne"]) if "personne" in given else None
            guild_id = int(data["guild_id"])
        except (KeyError, ValueError, TypeError):
            await self._callback(data, CHANNEL_MESSAGE, text["map_none"])
            return
        if self.service.too_soon(user_id):
            await self._callback(data, CHANNEL_MESSAGE, text["wait"])
            return
        await self._callback(data, DEFERRED_MESSAGE, public=True)
        shape = given.get("forme") if given.get("forme") in discord_map.SHAPES else "normal"
        await self._edit(data, await asyncio.to_thread(self.service.map, guild_id, period, focus, shape))

    async def _map_period(self, data: dict) -> None:
        """A menu under a map (the period, or the shape): the same message is drawn again for the choice (the person in focus, and the shape or the period that the
        other menu holds, are in the id of the menu, and read again)."""
        try:
            parts = str((data.get("data") or {})["custom_id"]).split(":")
            focus = int(parts[2]) or None
            choice = (data["data"].get("values") or [""])[0]
            guild_id = int(data["guild_id"])
        except (IndexError, ValueError, KeyError, TypeError):
            return
        if parts[1] == "shape":
            period, shape = (parts[3] if len(parts) > 3 else "30"), choice
        else:
            period, shape = choice, (parts[3] if len(parts) > 3 else "normal")
        if period not in discord_map.PERIODS or shape not in discord_map.SHAPES:
            return
        await self._callback(data, DEFERRED_UPDATE)
        await self._edit(data, await asyncio.to_thread(self.service.map, guild_id, period, focus, shape))

    async def _page(self, data: dict) -> None:
        """A button of a card: the same message turns to another page. Anybody can turn the pages (the card is public); the person is read again, so that a card
        of somebody who asked not to be recorded since is gone at the next click."""
        parts = str((data.get("data") or {}).get("custom_id", "")).split(":")
        try:
            page, target, guild_id = int(parts[2]), int(parts[3]), int(data["guild_id"])
        except (IndexError, ValueError, KeyError, TypeError):
            return
        embeds = (data.get("message") or {}).get("embeds") or [{}]
        avatar = (embeds[0].get("thumbnail") or {}).get("url")      # the picture is already on the message: no need to ask Discord again
        await self._callback(data, DEFERRED_UPDATE)
        await self._edit(data, await asyncio.to_thread(self.service.card, guild_id, target, avatar, page))

    async def _button(self, data: dict, user_id: int, text: dict) -> None:
        parts = str((data.get("data") or {}).get("custom_id", "")).split(":")
        if len(parts) != 3 or parts[0] != "dindon" or parts[2] != str(user_id):    # not ours, or not the person it was shown to
            return
        if parts[1] == "cancel":
            await self._callback(data, UPDATE_MESSAGE, text["cancelled"])
        elif parts[1] == "erase":
            await self._callback(data, UPDATE_MESSAGE, text["erasing"])            # the buttons are gone: it cannot be clicked twice
            await self._edit(data, await asyncio.to_thread(self.service.run, user_id, "effacer"))
