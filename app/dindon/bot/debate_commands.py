"""The debates on Discord: `/dindon debat sujet`, its popup, the buttons, the end. The rules and the state are in `dindon/debate/`; this module does what they decide, on Discord. See docs/regles-du-bot.md.

* `/dindon debat sujet` creates **nothing**: the person gets a popup (a Discord modal) where they choose the parameters: the subject and its context, a thread or the channel itself, whether the
  claims are checked, and the silence after which the debate ends by itself. When they send it the debate is written (refused here if a limit says so), its place is made (a **public thread**
  under the channel, or the channel itself), the **launch message** with the three position buttons and the end button is posted, and only then does the debate open (`attach_thread`).
* There is **no time limit and no vote**. A debate ends when the person who opened it, or a moderator, presses « Terminer le débat », or after the silence chosen in the popup.
* Every message written in the place of a running debate is handed over by the engine (`on_message`) and counted in batches. Bots are not participants. In the channel itself that is every message of
  the channel, while the debate is open: the launch message says so.
* A **tick** (every couple of seconds while a debate runs) writes the counted messages, ends the debates whose silence is over (`store.quiet`), posts what is owed to Discord (the closing
  statistics), and refreshes the counters of the launch message, at most every few seconds (Discord limits how often a message is edited).
* Everything that is owed is derived from the database (`store.unannounced`), not from memory: a bot that stops and starts again posts the closing it owed.
* A thread (or channel) that was deleted on Discord ends its debate (the event, or a 404 as the first sign). A post that fails is tried again with growing waits, and given up after a few attempts.
* **After a gap** (the bot was stopped, or Discord started a new Gateway session: what was written meanwhile never reached it) the place of each running debate is read again from Discord, from the
  last message counted (or the launch message), before anything else is looked at.
* A message of a person that is deleted stops counting (the ingestion forgets it, see ingest/loader.py). The bot's own launch message, if a moderator deletes it, is posted again. An edit changes nothing
  here: the message was written, and counts.
* The answers to a person are private (only they see them). Nothing here logs a subject, a message or a name: counts and kinds of errors only.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import psycopg

from dindon.bot.privacy_commands import Reply
from dindon.bot.rest import DiscordREST, Response
from dindon.clock import utc_now
from dindon.db import connect
from dindon.debate import answers, claims, forum, rules, stats, store, texts
from dindon.debate.checker import notice_mode
from dindon.debate.reading import Reading
from dindon.debate.store import Debate, DebateRefused

log = logging.getLogger("dindon.bot.debate")

TEXT_CHANNEL_TYPES = (0, 5)               # a text channel or an announcement channel: where a thread can be opened
PLACE_TYPES = (0, 5, 10, 11, 12)          # where a debate can be asked for: those, or a thread (it then takes place in it)
MODERATOR_RIGHTS = (1 << 3) | (1 << 4) | (1 << 5) | (1 << 13) | (1 << 34)   # administrator, manage channels, manage the server, manage messages, manage threads
THREAD_TYPE_PUBLIC = 11
AUTO_ARCHIVE_MINUTES = 1440               # a day of silence in the thread before Discord archives it: the buttons keep working in the meantime
MAX_INBOX = 5000                          # counted messages waiting for a database that is away; beyond, the oldest are dropped (a message is only a count)
GIVE_UP_AFTER = 5                         # attempts to post the closing message
PAGE = 100                                # messages asked of Discord at a time
MAX_CATCH_UP_PAGES = 50                   # a thread is read back 5000 messages at a time at most; the rest waits for the next try
CATCH_UP_RETRY_SECONDS = 30
STALE_PREPARING = timedelta(minutes=2)    # a debate still being prepared this long was left by a crash
RETRY_SECONDS = (2, 5, 15, 30, 60)

TEXT = {
    "elsewhere": "Les débats se lancent dans un salon d'un serveur que Dindon suit.",
    "not_a_channel": "Lancez le débat depuis un salon texte ou un fil, pas depuis un message privé.",
    "opened": "Le débat est ouvert : {place}. Vous pouvez y prendre position tout de suite.",
    "ended": "C'est fait : le débat est terminé, les statistiques arrivent.",
    "no_permission": ("Dindon n'a pas la permission d'ouvrir un fil ici. Il faut inviter le bot de nouveau avec le lien de l'interface (« Inviter le bot »), "
                      "qui demande maintenant : créer des fils publics, envoyer des messages (dans les salons et dans les fils) et intégrer des liens."),
    "open_failed": "Le débat n'a pas pu être ouvert. Réessayez dans un instant.",
    "failed": "Une erreur est survenue, rien n'a été modifié. Réessayez dans un instant.",
    "forum_fallback": " (Le forum des débats n'a pas répondu : le débat est dans un fil de ce salon.)",
    "forum_denied": "Seuls les modérateurs peuvent régler le forum des débats (droit de gérer le salon, le serveur, les messages ou les fils).",
    "forum_none": "Aucun forum n'est réglé : un débat a lieu dans un fil sous le salon (ou dans le salon). `/dindon forum salon:` en choisit un.",
    "forum_current": "Les débats sont créés dans le forum {forum}{tag}. `/dindon forum retirer:Oui` les remet dans des fils sous le salon.",
    "forum_set": "C'est noté : les débats de ce serveur seront créés dans le forum {forum}{tag}, un post chacun.",
    "forum_removed": "C'est fait : les débats reviennent dans des fils sous le salon.",
    "forum_not_forum": "Ce salon n'est pas un forum de ce serveur : choisissez un salon de type forum.",
    "forum_unreachable": "Dindon ne peut pas lire ce forum. Donnez-lui l'accès : voir le salon, envoyer des messages, envoyer des messages dans les posts.",
    "forum_tag_unknown": "Je ne connais pas l'étiquette « {tag} » dans ce forum. Étiquettes : {tags}.",
    "forum_tag_required": "Ce forum exige une étiquette. Ajoutez une étiquette générale non réservée aux modérateurs (Politique ou Philosophie), ou indiquez une étiquette de secours avec `etiquette:`. Étiquettes : {tags}.",
    "forum_tag_moderated": " Cette étiquette est réservée aux modérateurs : Dindon n'y arrivera que s'il peut gérer les fils.",
    "no_topic": "Écrivez un sujet, ou choisissez un axe : Dindon posera sa question.",
    "no_axis": "Cet axe n'est plus proposé : choisissez-en un autre, ou écrivez un sujet.",
    "wait": "Un instant : réessayez dans une seconde.",
    "recorded": "Position enregistrée : {choice}. Vous pouvez en changer quand vous voulez.",
    "changed": "Position changée : {choice}.",
    "unchanged": "Vous aviez déjà choisi {choice}.",
}


def _choice(value: str, axis: dict | None = None) -> str:
    emoji, label = texts.position_buttons(axis)[value]
    return f"{emoji} {label}"


class Debates:
    def __init__(self, database_url: str, rest: DiscordREST, *, clock: Callable[[], datetime] = utc_now, mono: Callable[[], float] = time.monotonic,
                 refresh_seconds: float = 5.0, click_seconds: float = 1.0, checker=None):
        self._url, self.rest, self.clock, self._mono = database_url, rest, clock, mono
        self.checker = checker                                    # reads the messages for claims and checks them (debate/checker.py), or None: nothing is read, nothing leaves
        self._check_retry_at = 0.0
        self._check_failing = False
        self._retracting = False                                  # corrections wait to be taken back from Discord
        self._refresh_seconds, self._click_seconds = refresh_seconds, click_seconds
        self.interactions = None                                  # the answerer of commands (privacy_commands.Interactions), set by whoever builds both
        self.allowed: Callable[[object], bool] = lambda guild_id: True   # does the bot follow this server? (the engine sets it)
        self._conn: psycopg.Connection | None = None
        self._lock = threading.Lock()
        self._threads: dict[str, int] = {}                        # thread id -> debate id, for the debates that run
        self._inbox: list[tuple[int, int, int, datetime]] = []    # (debate, message, author, when) counted messages waiting to be written
        self._early: list[dict] = []                              # the few fields of messages that came before the debates were loaded: looked at once they are
        self._deleted: list[tuple[int, list[int]]] = []           # (debate, ids) messages deleted in a debate thread, to see whether any was the bot's own
        self._gone_threads: set[int] = set()                      # threads (and channels) deleted on Discord, whose debates must be closed
        self._gone_channels: set[int] = set()
        self._gap = True                                          # messages may have been missed: the threads must be read again (true at the start)
        self._gap_retry_at = 0.0
        self._dirty: set[int] = set()                             # debates whose question message shows old counts
        self._refreshed: dict[int, float] = {}
        self._clicks: dict[tuple[int, bool, int], float] = {}
        self._answers_dirty: set[int] = set()                  # the answers whose Valide / Invalide counters are to be shown again
        self._answers_refreshed: dict[int, float] = {}
        self._attempts: dict[tuple[int, str], int] = {}
        self._retry_at: dict[tuple[int, str], float] = {}
        self._loaded = False
        self._owing = False
        self._swept = -1e9

    # --- the database ---------------------------------------------------------------------------------------------

    def _db(self, action):
        with self._lock:
            if self._conn is None or self._conn.closed:
                self._conn = connect(self._url)
                self._conn.autocommit = True
            try:
                return action(self._conn)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                try:
                    self._conn.close()
                finally:
                    self._conn = None
                raise

    async def db(self, action):
        return await asyncio.to_thread(self._db, action)

    async def _rest(self, method: str, path: str, body: dict | list | None = None) -> Response:
        return await asyncio.to_thread(self.rest.call, method, path, body)

    # --- what the engine asks -------------------------------------------------------------------------------------

    def is_debate_thread(self, channel_id: object) -> bool:
        """Whether a message of this channel is for a debate. Until the debates are loaded nobody knows, so every message is kept aside for a moment."""
        return not self._loaded or str(channel_id) in self._threads

    def has_work(self) -> bool:
        """Whether the engine should wake up often: a debate runs, or something is owed. Until the first tick, yes (the debates have not been loaded)."""
        return (not self._loaded or bool(self._threads) or bool(self._inbox) or bool(self._dirty) or self._owing or self._gap
                or bool(self._deleted) or bool(self._gone_threads) or bool(self._gone_channels) or self._retracting)

    @property
    def verifying(self) -> bool:
        return self.checker is not None

    @property
    def live(self) -> bool:
        """The corrections that trusted sources make by themselves are on: the owner asked for them AND gave a measured precision that reaches the threshold (debate/checker.resolve_mode)."""
        return self.checker is not None and getattr(self.checker, "mode", "observe") == "live"

    @property
    def answering(self) -> bool:
        """Dindon answers first, without the Internet, and the participants judge its answers (`answer` and `live`)."""
        return self.checker is not None and getattr(self.checker, "mode", "observe") in ("answer", "live")

    @property
    def notice_mode(self) -> str:
        """What the members are told Dindon does (texts.notice)."""
        return notice_mode(self.checker)

    def has_checks(self) -> bool:
        """Whether there is something to look for in the queue of messages to read: the checks are on and a debate runs."""
        return self.checker is not None and bool(self._threads)

    def status(self) -> dict:
        return {"running": len(self._threads), "waiting_messages": len(self._inbox)}

    def on_message(self, data: dict) -> None:
        """A message was written in a thread that is a running debate: it will be counted. Not the messages of bots, nor the system's (a thread's name changed…)."""
        if not self._loaded:
            if len(self._early) < MAX_INBOX:
                self._early.append({key: data.get(key) for key in ("channel_id", "id", "author", "type", "timestamp")})
            return
        debate_id = self._threads.get(str(data.get("channel_id")))
        counted = self._counted(data)
        if debate_id is None or counted is None:
            return
        if len(self._inbox) >= MAX_INBOX:
            del self._inbox[: len(self._inbox) - MAX_INBOX + 1]
        self._inbox.append((debate_id, *counted))

    def _counted(self, data: dict) -> tuple[int, int, datetime] | None:
        """(message, author, when) of a message that counts for a debate; None for a bot's, or a system message (a thread renamed…). One rule for the messages
        that arrive live and the ones read back after a gap."""
        author = data.get("author") or {}
        if author.get("bot") or data.get("type") not in (0, 19) or not str(author.get("id", "")).isdigit() or not str(data.get("id", "")).isdigit():
            return None
        try:
            sent_at = datetime.fromisoformat(data["timestamp"])
        except (KeyError, TypeError, ValueError):
            sent_at = self.clock()
        return int(data["id"]), int(author["id"]), sent_at

    def note_gap(self) -> None:
        """The Gateway started a new session: what was written since the last event never came. The places of the debates will be read again before their silence is looked at."""
        self._gap = True

    def on_delete(self, data: dict, ids: list) -> None:
        """Messages were deleted in a channel. Only those of a debate thread matter here, and only if one of them is the bot's own."""
        debate_id = self._threads.get(str(data.get("channel_id")))
        numbers = [int(i) for i in ids if str(i).isdigit()]
        if debate_id is not None and numbers:
            self._deleted.append((debate_id, numbers))

    def on_thread_gone(self, thread_id: object) -> None:
        if str(thread_id) in self._threads and str(thread_id).isdigit():
            self._gone_threads.add(int(thread_id))

    def on_channel_gone(self, channel_id: object) -> None:
        """A channel was deleted: the threads under it went with it, and Discord does not necessarily say so for each."""
        if self._threads and str(channel_id).isdigit():
            self._gone_channels.add(int(channel_id))

    async def load(self) -> None:
        """At the start: the debates that were running go on (they are in the database), and the ones that a crash left half made are closed."""
        await self.db(lambda c: store.close_stale(c, self.clock(), STALE_PREPARING))
        for debate in await self.db(store.active):
            if debate.thread_id is not None:
                self._threads[str(debate.thread_id)] = debate.id
        self._loaded = True
        self._swept = self._mono()
        early, self._early = self._early, []
        for data in early:
            self.on_message(data)
        if self._threads:
            log.info("%d debate(s) go on after the start", len(self._threads))

    # --- the command ----------------------------------------------------------------------------------------------

    async def command(self, data: dict, user_id: int, option: dict) -> None:
        """`/dindon debat sujet`: nothing is created yet. The person gets a popup in which they choose the parameters of the debate; the debate opens when they send it (`modal_submit`)."""
        say = self.interactions.say
        values = {o.get("name"): o.get("value") for o in option.get("options") or []}
        guild_id, channel_id = data.get("guild_id"), data.get("channel_id")
        if not guild_id or not channel_id or not self.allowed(guild_id):
            await say(data, TEXT["elsewhere"])
            return
        place = (data.get("channel") or {}).get("type")
        if place not in PLACE_TYPES:
            await say(data, TEXT["not_a_channel"])
            return
        asked = " ".join(str(values.get("sujet") or "").split())
        topic = rules.clean_topic(asked) if asked else ""              # no subject is fine: the person may choose an axis in the popup
        if topic is None:
            await say(data, texts.REFUSALS["topic"])
            return

        def checks(conn):
            store.check_can_start(conn, guild_id=int(guild_id), created_by=user_id)
            return store.offered_axes(conn), forum.get(conn, int(guild_id))

        try:                                                           # what is already known to be refused: not worth a popup
            axes, where = await self.db(checks)
        except DebateRefused as refusal:
            await say(data, self._refusal(refusal.code))
            return
        except Exception as error:
            log.error("a debate could not be checked (%s)", type(error).__name__)
            await say(data, TEXT["failed"])
            return
        can_thread = place in TEXT_CHANNEL_TYPES                       # a thread cannot hold a thread: a debate asked for there takes place in it
        popup = texts.setup_modal(user_id, int(channel_id), topic, can_thread=can_thread, can_verify=self.verifying, axes=axes, forum=where.name if where else None)
        plain = texts.setup_modal(user_id, int(channel_id), topic, can_thread=can_thread, can_verify=self.verifying, axes=axes, forum=where.name if where else None, style="select")
        if not await self.interactions.modal(data, popup, plain):
            await say(data, TEXT["failed"])

    async def modal_submit(self, data: dict, user_id: int) -> None:
        """The person filled the popup and sent it: the debate is written, its place (a thread, or the channel) and its launch message are made, and it opens."""
        say = self.interactions.say
        parsed = texts.parse_setup_id((data.get("data") or {}).get("custom_id"))
        if parsed is None or parsed[0] != user_id or str(parsed[1]) != str(data.get("channel_id")):
            return                                                     # not the popup that was shown to this person here
        guild_id = data.get("guild_id")
        if not guild_id or not self.allowed(guild_id):
            await say(data, TEXT["elsewhere"])
            return
        values = texts.modal_values((data.get("data") or {}).get("components"))
        in_thread = (data.get("channel") or {}).get("type") in TEXT_CHANNEL_TYPES and texts.ticked(values, "thread")
        verify = self.verifying and texts.ticked(values, "verify")
        typed = " ".join(str(values.get("topic") or "").split())
        wanted = values.get("axis")
        wanted = wanted[0] if isinstance(wanted, list) and wanted else ""
        try:
            quiet = int((values.get("quiet") or [rules.DEFAULT_QUIET])[0])
        except (TypeError, ValueError, IndexError):
            quiet = 0
        axis = None
        if not typed:                                                  # no subject written: the question is the axis's, if one was chosen (a subject that was written always wins)
            if not wanted:
                await say(data, TEXT["no_topic"])
                return
            try:
                axis = await self.db(lambda c: store.axis(c, wanted))
            except Exception as error:
                log.error("an axis could not be read (%s)", type(error).__name__)
                await say(data, TEXT["failed"])
                return
            if axis is None:
                await say(data, TEXT["no_axis"])
                return
        started = self.clock()
        try:
            debate = await self.db(lambda c: store.start(c, guild_id=int(guild_id), channel_id=parsed[1], topic=typed or axis.question, context=str(values.get("context") or "") or None,
                                                         created_by=user_id, in_thread=in_thread, verify=verify, axis=None if typed else axis, quiet_seconds=quiet, now=started))
        except DebateRefused as refusal:
            await say(data, self._refusal(refusal.code))
            return
        except Exception as error:
            log.error("a debate could not be written (%s)", type(error).__name__)
            await say(data, TEXT["failed"])
            return
        await self.interactions.defer(data)                           # Discord gives 3 seconds; the thread takes longer
        await self.interactions.finish(data, Reply(await self._open(debate, started)))

    @staticmethod
    def _refusal(code: str) -> str:
        return texts.REFUSALS.get(code, TEXT["failed"]).format(n=rules.MAX_OPEN_PER_SERVER)

    async def _open(self, debate: Debate, started: datetime) -> str:
        """Makes the place of the debate (a post of the server's forum, a thread, or the channel itself) and posts the message that launches it, then opens the debate. Returns what the author is told."""
        place, note, starter = debate.channel_id, "", None
        if debate.in_thread:
            made = await self._forum_post(debate)
            if isinstance(made, tuple):                            # a post of the forum: its first message IS the launch message, made with it
                place, starter = made
            else:
                note = TEXT["forum_fallback"] if made == "failed" else ""
                thread = await self._rest("POST", f"/channels/{debate.channel_id}/threads",
                                          {"name": texts.thread_name(debate.topic), "type": THREAD_TYPE_PUBLIC, "auto_archive_duration": AUTO_ARCHIVE_MINUTES})
                if not thread.ok or thread.id is None:
                    return await self._not_opened(debate, thread)
                place = thread.id
            await self._rest("PUT", f"/channels/{place}/thread-members/@me")     # the bot is in its thread (it receives the messages of the threads it is in)
        if starter is None:
            counts = dict.fromkeys(rules.POSITIONS, 0)
            posted = await self._rest("POST", f"/channels/{place}/messages", texts.question(debate, counts, verifying=self.verifying, live=self.notice_mode))
            if not posted.ok or posted.id is None:
                return await self._not_opened(debate, posted)
            starter = posted.id
        try:
            await self.db(lambda c: store.attach_thread(c, debate.id, thread_id=place, question_message_id=starter, now=started))
        except Exception as error:
            log.error("a debate could not be opened (%s)", type(error).__name__)
            await self._close_failed(debate.id)
            return TEXT["open_failed"]
        self._threads[str(place)] = debate.id
        return TEXT["opened"].format(place=f"<#{place}>") + note

    async def _forum_post(self, debate: Debate) -> tuple[int, int] | str | None:
        """The debate as a post of the server's forum, if a moderator chose one (`/dindon forum`): (the post, its first message). None: there is no forum. 'failed': there is one and it did not
        work (deleted, no access, a label that is required…): the debate then goes in a thread under the channel, and the author is told. The labels are read from the forum now, not from
        memory: a label that was renamed or removed would make Discord refuse the post."""
        try:
            where = await self.db(lambda c: forum.get(c, debate.guild_id))
        except Exception as error:
            log.error("the forum of the debates could not be read (%s)", type(error).__name__)
            return "failed"
        if where is None:
            return None
        channel = await self._rest("GET", f"/channels/{where.channel_id}")
        if not channel.ok or not isinstance(channel.data, dict) or channel.data.get("type") != forum.FORUM_CHANNEL:
            log.warning("the forum of the debates could not be read (HTTP %s): the debate goes in a thread", channel.status)
            return "failed"
        tags = forum.pick_tags(channel.data.get("available_tags") or [], where.tag_id, (debate.axis or {}).get("name"), debate.topic,
                               required=bool(int(channel.data.get("flags") or 0) & forum.REQUIRE_TAG))
        if not tags and int(channel.data.get("flags") or 0) & forum.REQUIRE_TAG:
            return "failed"
        body = {"name": texts.thread_name(debate.topic), "auto_archive_duration": AUTO_ARCHIVE_MINUTES, "applied_tags": tags,
                "message": texts.question(debate, dict.fromkeys(rules.POSITIONS, 0), verifying=self.verifying, live=self.notice_mode)}
        made = await self._rest("POST", f"/channels/{where.channel_id}/threads", body)
        if not made.ok or made.id is None:
            log.warning("a debate could not be created in the forum (HTTP %s, code %s): it goes in a thread", made.status, made.code)
            return "failed"
        starter = (made.data.get("message") or {}).get("id") if isinstance(made.data, dict) else None
        return made.id, int(starter) if str(starter or "").isdigit() else made.id    # (the first message of a forum post has the number of the post)

    async def forum_command(self, data: dict, user_id: int, option: dict) -> None:
        """`/dindon forum`: tells Dindon in which forum of the server the debates are created (a post each, with labels), or shows it, or takes it off. Moderators only. Answered privately."""
        say = self.interactions.say
        values = {o.get("name"): o.get("value") for o in option.get("options") or []}
        guild_id = data.get("guild_id")
        if not guild_id or not self.allowed(guild_id):
            await say(data, TEXT["elsewhere"])
            return
        current = await self.db(lambda c: forum.get(c, int(guild_id)))
        if not values.get("salon") and not values.get("retirer"):
            await say(data, TEXT["forum_current"].format(forum=f"<#{current.channel_id}>", tag=f" (étiquette « {current.tag_name} »)" if current.tag_name else "") if current else TEXT["forum_none"])
            return
        if not self._moderator(data):
            await say(data, TEXT["forum_denied"])
            return
        if values.get("retirer"):
            await self.db(lambda c: forum.clear(c, int(guild_id)))
            await say(data, TEXT["forum_removed"])
            return
        channel_id = str(values["salon"])
        found = await self._rest("GET", f"/channels/{channel_id}")
        if not found.ok or not isinstance(found.data, dict):
            await say(data, TEXT["forum_unreachable"])
            return
        if found.data.get("type") != forum.FORUM_CHANNEL or str(found.data.get("guild_id")) != str(guild_id):
            await say(data, TEXT["forum_not_forum"])
            return
        available = found.data.get("available_tags") or []
        chosen = None
        wanted = " ".join(str(values.get("etiquette") or "").split())
        if wanted:
            chosen = forum.find_tag(available, wanted)
            if chosen is None:
                await say(data, TEXT["forum_tag_unknown"].format(tag=wanted, tags=forum.tag_names(available) or "aucune"))
                return
        elif int(found.data.get("flags") or 0) & forum.REQUIRE_TAG and forum.general_tag(available) is None:
            await say(data, TEXT["forum_tag_required"].format(tags=forum.tag_names(available) or "aucune"))
            return
        saved = forum.Forum(int(channel_id), str(found.data.get("name") or ""), str(chosen["id"]) if chosen else None, str(chosen["name"]) if chosen else None)
        await self.db(lambda c: forum.save(c, int(guild_id), saved))
        await say(data, TEXT["forum_set"].format(forum=f"<#{saved.channel_id}>", tag=f" (étiquette « {saved.tag_name} »)" if saved.tag_name else "")
                  + (TEXT["forum_tag_moderated"] if chosen and chosen.get("moderated") else ""))

    async def _not_opened(self, debate: Debate, response: Response) -> str:
        log.warning("a debate could not be opened on Discord (HTTP %s, code %s)", response.status, response.code)
        await self._close_failed(debate.id)
        return TEXT["no_permission"] if response.status == 403 or response.code == 50013 else TEXT["open_failed"]

    async def _close_failed(self, debate_id: int) -> None:
        try:
            await self.db(lambda c: store.fail(c, debate_id, self.clock()))
        except Exception as error:      # the stale ones are closed by the next sweep
            log.error("a debate that failed to open could not be closed (%s)", type(error).__name__)

    # --- the buttons ----------------------------------------------------------------------------------------------

    async def button(self, data: dict, user_id: int) -> None:
        """A position, the end of the debate, or a page of the statistics. Answered privately, at once."""
        parsed = texts.parse_custom_id((data.get("data") or {}).get("custom_id"))
        if parsed is None:
            return
        kind, debate_id, value = parsed
        say = self.interactions.say
        now = self._mono()
        key = (user_id, kind == "val", debate_id)              # (the number of a Valide / Invalide button is an answer's, not a debate's)
        if now - self._clicks.get(key, -1e9) < self._click_seconds:
            if kind != "stats":                                     # (turning a page of the statistics twice in a second is only a double click: ignored without a word)
                await say(data, TEXT["wait"])
            return
        self._clicks = {k: t for k, t in self._clicks.items() if now - t < 60}
        self._clicks[key] = now
        if kind == "val":
            await self._judge(data, debate_id, user_id, value)
            return
        if kind == "stats":
            await self._show_stats(data, debate_id, int(value))
            return
        if kind == "end":
            await self._end_by_button(data, debate_id, user_id)
            return
        when = self.clock()
        try:
            result = await self.db(lambda c: store.set_position(c, debate_id, user_id, value, when))
            debate = await self.db(lambda c: store.get(c, debate_id))
            text = TEXT[result].format(choice=_choice(value, debate.axis if debate else None))
            self._dirty.add(debate_id)
        except DebateRefused as refusal:
            text = self._refusal(refusal.code)
        except Exception as error:
            log.error("a button of a debate could not be handled (%s)", type(error).__name__)
            text = TEXT["failed"]
        await say(data, text)

    async def _judge(self, data: dict, answer_id: int, user_id: int, choice: str) -> None:
        """Valide or Invalide under one of Dindon's answers. Answered privately. What it leads to (a search, if there is more Invalide) is decided by the engine, from the database."""
        await self.interactions.defer(data)                    # acknowledge the click before a database lock can exhaust Discord's three seconds
        try:
            result = await self.db(lambda c: answers.vote(c, answer_id, user_id, choice, self.clock()))
            self._answers_dirty.add(answer_id)
            text = {"recorded": "Vote enregistré : {c}. Merci.", "changed": "Vote changé : {c}.", "unchanged": "Vous aviez déjà voté {c}."}[result].format(c="✅ Valide" if choice == "valid" else "❌ Invalide")
        except answers.VoteRefused as refusal:
            text = {"unknown": texts.REFUSALS["answer_gone"], "not_open": texts.REFUSALS["not_open"], "searched": texts.REFUSALS["searched"],
                    "blocked": texts.REFUSALS["blocked"]}.get(refusal.code, TEXT["failed"])
        except Exception as error:
            log.error("a vote on an answer could not be handled (%s)", type(error).__name__)
            text = TEXT["failed"]
        await self.interactions.finish(data, Reply(text))

    @staticmethod
    def _moderator(data: dict) -> bool:
        """Administrator, or the right to manage the channel, the server, the messages or the threads where the command was used or the button pressed."""
        try:
            rights = max(int((data.get("member") or {}).get("permissions") or 0), 0)       # (a bit field is never negative: whatever else it is, it gives no right)
        except (TypeError, ValueError):
            rights = 0
        return bool(rights & MODERATOR_RIGHTS)

    @classmethod
    def _may_end(cls, data: dict, debate: Debate, user_id: int) -> bool:
        """The person who opened the debate, or a moderator."""
        return debate.created_by == user_id or cls._moderator(data)

    async def _end_by_button(self, data: dict, debate_id: int, user_id: int) -> None:
        say = self.interactions.say
        try:
            debate = await self.db(lambda c: store.get(c, debate_id))
            if debate is None or debate.status != "open":
                await say(data, texts.REFUSALS["unknown" if debate is None else "not_open"])
                return
            if not self._may_end(data, debate, user_id):
                await say(data, texts.REFUSALS["not_allowed"])
                return
            await self._flush_messages()                               # what was written in the last seconds still counts: the debate is closed to messages once it ends
            closed = await self.db(lambda c: store.end(c, debate_id, rules.ENDED, self.clock()))
        except Exception as error:
            log.error("a debate could not be ended (%s)", type(error).__name__)
            await say(data, TEXT["failed"])
            return
        if closed is not None and closed.thread_id is not None:
            self._threads.pop(str(closed.thread_id), None)             # (the statistics are posted by the next tick: `_owed` finds the debate closed without them)
            self._owing = True
        await say(data, TEXT["ended"])

    async def _show_stats(self, data: dict, debate_id: int, page: int) -> None:
        """A click on a page button of the statistics: the page is made again from the database (what was deleted or erased since is gone)."""
        try:
            found = await self.db(lambda c: stats.collect(c, debate_id, self.clock()))
        except Exception as error:
            log.error("the statistics of a debate could not be read (%s)", type(error).__name__)
            await self.interactions.say(data, TEXT["failed"])
            return
        if found is None:
            await self.interactions.say(data, texts.REFUSALS["unknown"])
            return
        await self.interactions.show(data, texts.stats_page(found, page, checks_on=self.verifying))

    # --- the tick -------------------------------------------------------------------------------------------------

    async def tick(self) -> None:
        if not self._loaded:
            await self.load()
        await self._close_gone()
        if self._gap and self._mono() >= self._gap_retry_at:
            await self._catch_up()
        await self._flush_messages()
        await self._bot_messages_deleted()
        now = self.clock()
        for debate_id in await self.db(lambda c: store.quiet(c, now)):          # nobody wrote for as long as the person allowed: the debate ends by itself
            closed = await self.db(lambda c, i=debate_id: store.end(c, i, rules.SILENCE, now))
            if closed is not None and closed.thread_id is not None:
                self._threads.pop(str(closed.thread_id), None)
        await self._owed()
        await self._corrections()
        await self._answers()
        await self._refresh()
        if self._mono() - self._swept > 60:
            self._swept = self._mono()
            await self.db(lambda c: store.close_stale(c, self.clock(), STALE_PREPARING))

    async def _flush_messages(self) -> None:
        batch, self._inbox = self._inbox, []
        if not batch:
            return

        to_read = self.verifying

        def write(conn):
            for debate_id, message_id, author_id, sent_at in batch:
                store.record_message(conn, debate_id, message_id=message_id, author_id=author_id, sent_at=sent_at, to_read=to_read)

        try:
            await self.db(write)
        except Exception:
            self._inbox = batch + self._inbox            # writing a message twice counts it once: try again
            raise

    async def check_next(self) -> bool:
        """Reads one message of a running debate for claims and checks them (in observation: the result is only written to the database, nothing is published). True if a message was dealt with.
        The queue is the database (debate/claims.py), taken oldest first. A debate that already had `MAX_CHECKS_PER_HOUR` claims checked this hour waits for the next hour: however chatty it is,
        it asks no more than that of the Internet and of the local model. If the model or the database cannot answer, it is tried again later, with growing waits."""
        if self.checker is None or self._mono() < self._check_retry_at:
            return False
        try:
            await self.db(lambda c: claims.expire_unread(c, self.clock()))
            if self.answering and await self._search_asked():             # the participants rejected an answer of Dindon: it looks on the Internet, before reading anything new
                self._check_failing = False
                return True
            for item in await self.db(lambda c: claims.next_unread(c, 30, self.clock())):
                if await self.db(lambda c, d=item.debate_id: claims.checks_last_hour(c, d, self.clock())) >= claims.MAX_CHECKS_PER_HOUR:
                    continue
                if self.answering:
                    considered = await asyncio.to_thread(self.checker.consider, item.text)
                    await self.db(lambda c, i=item, k=considered: claims.finish_reading(c, i, list(k.results), self.clock(), answers=k.answers))
                else:
                    results = await asyncio.to_thread(self.checker.check, item.text)
                    await self.db(lambda c, i=item, r=results: claims.finish_reading(c, i, r, self.clock()))
                self._check_failing = False
                return True
        except Exception as error:                                # the local model is away, the database is: said once, tried again in a while
            if not self._check_failing:
                log.warning("the claims of the debates could not be checked (%s): trying again later", type(error).__name__)
            self._check_failing = True
            self._check_retry_at = self._mono() + 30
        return False

    async def _search_asked(self) -> bool:
        """Looks on the Internet for ONE answer of Dindon that the participants rejected (more Invalide than Valide), with the budget of every check; or says that it cannot (no search service).
        True if something was done. Each answer is searched once."""
        for due in await self.db(lambda c: answers.searches_due(c, 3)):
            if await self.db(lambda c, d=due.debate_id: claims.checks_last_hour(c, d, self.clock())) >= claims.MAX_CHECKS_PER_HOUR:
                continue
            result = None
            if getattr(self.checker, "can_search", True):
                result = await asyncio.to_thread(self.checker.search, Reading(due.claim, due.said, due.query))
            await self.db(lambda c, d=due, r=result: answers.finish_search(c, d, r, self.clock()))
            self._owing = True
            return True
        return False

    async def _catch_up(self) -> None:
        """Reads the thread of each running debate again from Discord, from the last message counted, and counts what was missed (writing a message twice counts it once).
        Done before the silences are looked at. If Discord cannot be reached the gap stays and it is tried again in a while."""
        complete = True
        for debate in await self.db(store.active):
            if debate.thread_id is None or debate.status not in store.OPEN:
                continue
            cursor = await self.db(lambda c, i=debate.id: store.last_seen_message(c, i))
            for _ in range(MAX_CATCH_UP_PAGES):
                page = await self._rest("GET", f"/channels/{debate.thread_id}/messages?limit={PAGE}&after={cursor}")
                if page.status == 404:
                    await self._gone(debate)
                    break
                if not page.ok or not isinstance(page.data, list):
                    complete = False
                    break
                found = sorted((m for m in page.data if isinstance(m, dict) and str(m.get("id", "")).isdigit()), key=lambda m: int(m["id"]))
                counted = [c for c in (self._counted(m) for m in found) if c is not None]
                if counted:
                    def write(conn, debate_id=debate.id, counted=counted, to_read=self.verifying):
                        for message_id, author_id, sent_at in counted:
                            store.record_message(conn, debate_id, message_id=message_id, author_id=author_id, sent_at=sent_at, to_read=to_read)
                    await self.db(write)
                if len(page.data) < PAGE or not found:
                    break
                cursor = int(found[-1]["id"])
            else:
                complete = False                                          # a very long thread: the rest is read at the next try
        self._gap = not complete
        if not complete:
            self._gap_retry_at = self._mono() + CATCH_UP_RETRY_SECONDS
            log.warning("the threads of the debates could not all be read again, trying later")

    async def _gone(self, debate: Debate) -> None:
        """The thread of this debate is gone from Discord: the debate is closed, with nothing owed."""
        if debate.thread_id is not None:
            self._threads.pop(str(debate.thread_id), None)
        await self.db(lambda c: store.fail(c, debate.id, self.clock()))

    async def _close_gone(self) -> None:
        threads, channels = self._gone_threads, self._gone_channels
        self._gone_threads, self._gone_channels = set(), set()
        if not threads and not channels:
            return
        try:
            closed = await self.db(lambda c: store.close_gone(c, thread_ids=tuple(threads), channel_ids=tuple(channels), now=self.clock()))
        except Exception:
            self._gone_threads |= threads
            self._gone_channels |= channels
            raise
        for thread_id in closed:
            self._threads.pop(str(thread_id), None)
        if closed:
            log.info("%d debate(s) closed: their thread was deleted on Discord", len(closed))

    async def _bot_messages_deleted(self) -> None:
        batch, self._deleted = self._deleted, []
        for index, (debate_id, ids) in enumerate(batch):
            try:
                gone = await self.db(lambda c, d=debate_id, i=ids: store.bot_messages_deleted(c, d, i))
            except Exception:
                self._deleted = batch[index:] + self._deleted
                raise
            if gone:
                log.info("a message of the bot in a debate was deleted on Discord (%s): it is posted again", ", ".join(gone))
                self._owing = True

    async def _owed(self) -> None:
        owed = await self.db(store.unannounced)
        self._owing = bool(owed)
        for debate in owed:
            if debate.status in store.OPEN and debate.question_message_id is None and self._may_try((debate.id, "question")):
                await self._post_question(debate)
            if debate.status == "closed" and self._may_try((debate.id, "closed")):
                await self._post_closing(debate)

    def _may_try(self, key: tuple[int, str]) -> bool:
        return self._mono() >= self._retry_at.get(key, 0.0)

    def _succeeded(self, key: tuple[int, str]) -> None:
        self._attempts.pop(key, None)
        self._retry_at.pop(key, None)

    def _failed_post(self, key: tuple[int, str], response: Response) -> int:
        """Notes that a post failed and when to try again; returns how many attempts there have been."""
        attempts = self._attempts[key] = self._attempts.get(key, 0) + 1
        self._retry_at[key] = self._mono() + RETRY_SECONDS[min(attempts - 1, len(RETRY_SECONDS) - 1)]
        log.warning("a message of a debate could not be posted (HTTP %s, code %s), attempt %d", response.status, response.code, attempts)
        return attempts

    async def _corrections(self) -> None:
        """Takes back the corrections whose claim is gone, and, only in `live` mode, posts the corrections that are due: one per tick, spaced, and capped per hour for each debate."""
        await self._retract()
        if not self.live:
            return
        now = self.clock()
        for due in await self.db(lambda c: claims.corrections_due(c, now)):
            key = (due.claim_id, "correction")
            recent, last = await self.db(lambda c, d=due.debate_id: claims.corrections_recent(c, d, now))
            if (recent >= claims.CORRECTIONS_PER_HOUR or (last is not None and (now - last).total_seconds() < claims.CORRECTION_SPACING_SECONDS)
                    or not self._may_try(key)):
                continue
            await self._post_correction(due, key)
            return

    async def _answers(self) -> None:
        """What Dindon owes about its own answers: post the ones that are due (one per tick, spaced and capped like the corrections), write into its message the result of a search, and show the
        new Valide / Invalide counters (at most every few seconds). Only when Dindon answers first (`answer`, `live`)."""
        if not self.answering:
            return
        await self._show_searches()
        now = self.clock()
        for due in await self.db(lambda c: answers.posts_due(c, now)):
            key = (due.answer_id, "answer")
            recent, last = await self.db(lambda c, d=due.debate_id: claims.corrections_recent(c, d, now))
            if (recent >= claims.CORRECTIONS_PER_HOUR or (last is not None and (now - last).total_seconds() < claims.CORRECTION_SPACING_SECONDS) or not self._may_try(key)):
                continue
            await self._post_answer(due, key)
            break
        for answer_id in sorted(self._answers_dirty):
            if self._mono() - self._answers_refreshed.get(answer_id, -1e9) < self._refresh_seconds:
                continue
            self._answers_refreshed[answer_id] = self._mono()
            shown = await self.db(lambda c, i=answer_id: answers.view(c, i))
            if shown is None or shown.searched:
                self._answers_dirty.discard(answer_id)
                continue
            result = await self._rest("PATCH", f"/channels/{shown.thread_id}/messages/{shown.posted_message_id}",
                                      texts.local_answer(shown.claim, shown.answer, shown.answer_id, shown.message_id, shown.valid, shown.invalid))
            if result.ok or result.status == 404:                      # (a message that was deleted on Discord is not shown again)
                self._answers_dirty.discard(answer_id)

    async def _post_answer(self, due: answers.DueAnswer, key: tuple[int, str]) -> None:
        reserved = await self.db(lambda c: answers.reserve_post(c, due, self.clock()))
        posted = await self._rest("POST", f"/channels/{due.thread_id}/messages", texts.local_answer(due.claim, due.answer, due.answer_id, due.message_id))
        if posted.ok and posted.id is not None:
            await self.db(lambda c: claims.set_correction_posted(c, reserved, posted.id, self.clock()))
            self._succeeded(key)
            return
        attempts = self._failed_post(key, posted)
        if posted.status == 404 and posted.code == 10003:
            await self._gone(await self.db(lambda c: store.get(c, due.debate_id)))
        elif attempts >= answers.ANSWER_ATTEMPTS:
            log.error("an answer could not be posted and is given up")
            await self.db(lambda c: claims.give_up_correction(c, reserved, self.clock()))

    async def _show_searches(self) -> None:
        """Writes into Dindon's message what the search found, once, whatever it is: that its answer was right, or wrong, or that nothing settles it, with the sources to click."""
        pending = await self.db(lambda c: answers.to_show(c, 3))
        self._owing = self._owing or bool(pending)
        for item in pending:
            key = (item.answer_id, "shown")
            if not self._may_try(key):
                continue
            evidence = []
            if item.claim_id is not None:
                evidence = [e for stance in ("contradicts", "supports", "partly") for e in await self.db(lambda c, i=item.claim_id, st=stance: claims.claim_evidence(c, i, st))]
            result = await self._rest("PATCH", f"/channels/{item.thread_id}/messages/{item.posted_message_id}", texts.after_search(item.claim, item.answer, item.verdict, item.period, evidence))
            if result.ok or result.status == 404:
                await self.db(lambda c, i=item.answer_id: answers.mark_shown(c, i, self.clock()))
                self._succeeded(key)
            else:
                self._failed_post(key, result)

    async def _post_correction(self, due: claims.DueCorrection, key: tuple[int, str]) -> None:
        evidence = await self.db(lambda c: claims.claim_evidence(c, due.claim_id))
        correction_id = await self.db(lambda c: claims.reserve_correction(c, due, self.clock()))
        if not evidence:                                          # « contredit » always rests on a source (verify.decide): without one, nothing is said
            await self.db(lambda c: claims.give_up_correction(c, correction_id, self.clock()))
            return
        posted = await self._rest("POST", f"/channels/{due.thread_id}/messages", texts.correction(due.claim, due.period, evidence, due.message_id))
        if posted.ok and posted.id is not None:
            await self.db(lambda c: claims.set_correction_posted(c, correction_id, posted.id, self.clock()))
            self._succeeded(key)
            return
        attempts = self._failed_post(key, posted)
        if posted.status == 404 and posted.code == 10003:
            await self._gone(await self.db(lambda c: store.get(c, due.debate_id)))
        elif attempts >= claims.CORRECTION_ATTEMPTS:
            log.error("a correction could not be posted and is given up")
            await self.db(lambda c: claims.give_up_correction(c, correction_id, self.clock()))

    async def _retract(self) -> None:
        """A correction rests on a claim that is gone (its message was edited or deleted, its author erased): the correction is deleted from Discord, so that nothing quotes what no longer exists."""
        pending = await self.db(claims.corrections_to_retract)
        self._retracting = bool(pending)
        for correction_id, thread_id, message_id in pending:
            key = (correction_id, "retract")
            if not self._may_try(key):
                continue
            answer = await self._rest("DELETE", f"/channels/{thread_id}/messages/{message_id}")
            if answer.ok or answer.status == 404:                 # deleted, or already gone
                await self.db(lambda c, i=correction_id: claims.mark_retracted(c, i, self.clock()))
                self._succeeded(key)
            elif self._failed_post(key, answer) >= claims.CORRECTION_ATTEMPTS:
                await self.db(lambda c, i=correction_id: claims.mark_retracted(c, i, self.clock()))

    async def _post_question(self, debate: Debate) -> None:
        """The question was deleted on Discord: it is posted again, with the counts as they are now."""
        counts = await self.db(lambda c: store.position_counts(c, debate.id))
        posted = await self._rest("POST", f"/channels/{debate.thread_id}/messages", texts.question(debate, counts, verifying=self.verifying, live=self.notice_mode))
        if posted.ok and posted.id is not None:
            await self.db(lambda c: store.set_question_message(c, debate.id, posted.id))
            self._succeeded((debate.id, "question"))
            return
        self._failed_post((debate.id, "question"), posted)
        if posted.status == 404:
            await self._gone(debate)

    async def _post_closing(self, debate: Debate) -> None:
        key = (debate.id, "closed")
        if self.verifying and debate.closed_at is not None and (self.clock() - debate.closed_at).total_seconds() < claims.GRACE_MINUTES * 60 \
                and await self.db(lambda c: claims.unread_for(c, debate.id)) > 0:
            return                                                    # the messages that are left are being read: the statistics wait for them, five minutes at most
        summary = await self.db(lambda c: store.summary(c, debate.id))
        full = await self.db(lambda c: stats.collect(c, debate.id, self.clock()))
        posted = await self._rest("POST", f"/channels/{debate.thread_id}/messages", texts.stats_page(full, 0, checks_on=self.verifying))
        if posted.ok and posted.id is not None:
            await self.db(lambda c: store.set_final_message(c, debate.id, posted.id))
            self._succeeded(key)
            await self._rest("PATCH", f"/channels/{debate.thread_id}/messages/{debate.question_message_id}", texts.question(debate, summary["positions"], verifying=self.verifying, live=self.notice_mode))
            if debate.in_thread:
                await self._rest("PATCH", f"/channels/{debate.thread_id}", {"archived": True})     # best effort: it is archived by itself after a day anyway (never done to a channel)
            return
        if self._failed_post(key, posted) >= GIVE_UP_AFTER or posted.status == 404:
            log.error("the closing message of a debate could not be posted, it is given up")
            await self.db(lambda c: store.set_final_message(c, debate.id, 0))      # 0: nothing was posted, and nothing more will be tried

    async def _refresh(self) -> None:
        """Shows the new counts on the question message, each debate at most every few seconds."""
        for debate_id in sorted(self._dirty):
            if self._mono() - self._refreshed.get(debate_id, -1e9) < self._refresh_seconds:
                continue
            self._refreshed[debate_id] = self._mono()
            debate = await self.db(lambda c, i=debate_id: store.get(c, i))
            if debate is None or debate.status == "closed" or debate.question_message_id is None:
                self._dirty.discard(debate_id)
                continue
            counts = await self.db(lambda c, i=debate_id: store.position_counts(c, i))
            answer = await self._rest("PATCH", f"/channels/{debate.thread_id}/messages/{debate.question_message_id}", texts.question(debate, counts, verifying=self.verifying, live=self.notice_mode))
            if answer.ok:
                self._dirty.discard(debate_id)
            elif answer.status == 404 and answer.code == 10003:       # the thread is gone
                self._dirty.discard(debate_id)
                await self._gone(debate)
            elif answer.status == 404:                                # the question is gone: `unannounced` now says that it is owed
                self._dirty.discard(debate_id)
                await self.db(lambda c, d=debate: store.bot_messages_deleted(c, d.id, [d.question_message_id]))
                self._owing = True
