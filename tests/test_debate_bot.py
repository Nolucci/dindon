"""The debates on Discord (docs/regles-du-bot.md, step D2): the command and its popup, the place of the debate (a thread, or the channel itself), the buttons, the end (button or silence, never a
timer), the closing, and what happens after a stop.

Level of proof: SIMULATED. Real PostgreSQL, the real engine and the real command handlers, but Discord is a fake kept in memory (`FakeDiscord`: threads, messages, edits,
errors on demand) and the clock is moved by hand. Only the HTTP client has its own test against a local server. Nothing here has talked to the real Discord, and the
assumptions about it (the popup's fields, the permissions sent with a button) are listed in docs/regles-du-bot.md (« à vérifier sur un vrai Discord »).
"""
import asyncio
import itertools
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dindon import privacy
from dindon.bot import runner as runner_module
from dindon.bot.debate_commands import Debates
from dindon.bot.privacy_commands import COMMAND, EPHEMERAL, MODAL, Interactions, PrivacyService
from dindon.bot.rest import DiscordREST, Response
from dindon.bot.runner import BotRunner, Writer
from dindon.debate import rules, stats, store, texts
from dindon.debate.checker import notice_mode
from gateway_fixtures import ALICE, BOB, CAROL, GENERAL, GUILD, THREAD, guild_create, message_create
from test_bot import create, event

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
ALICE_ID, BOB_ID, CAROL_ID = int(ALICE["id"]), int(BOB["id"]), int(CAROL["id"])
TOPIC = "Faut-il réduire le temps de travail ?"
BOT_USER = {"id": "1000000000000000009", "username": "dindon", "bot": True}
MANAGE_MESSAGES, SEND_MESSAGES, ADMINISTRATOR = 1 << 13, 1 << 11, 1 << 3        # Discord's permission bits


def run(coroutine):
    return asyncio.run(coroutine)


class Time:
    """One clock for the whole test: wall time (what the silence of a debate is measured by) and the monotonic time (clicks, refreshes, retries) move together."""

    def __init__(self):
        self.wall, self.mono = T0, 1000.0

    def now(self) -> datetime:
        return self.wall

    def tick(self) -> float:
        return self.mono

    def advance(self, **delta) -> None:
        self.wall += timedelta(**delta)
        self.mono += timedelta(**delta).total_seconds()


class FakeDiscord:
    """The few endpoints that the debates use, with the state that Discord would keep. Failures on demand: `fail`, `delete_thread` (a thread or a channel)."""

    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.threads: dict[int, dict] = {}
        self.messages: dict[tuple[int, int], dict] = {}
        self._thread_ids, self._message_ids = itertools.count(int(THREAD)), itertools.count(9000)
        self._failures: list[list] = []
        self._deleted: set[int] = set()
        self.history: dict[int, list[dict]] = {}                                  # place -> its messages as Discord returns them (people's and the bot's)
        self.forums: dict[int, dict] = {}                                         # forum channels: id -> the channel as Discord gives it (type 15, flags, available_tags)
        self._lock = threading.Lock()

    def fail(self, method: str, pattern: str, status: int, *, times: int = 1, code: int | None = None) -> None:
        self._failures.append([method, re.compile(pattern), status, times, code])

    def delete_thread(self, place_id: int) -> None:
        self._deleted.add(int(place_id))

    def say(self, place_id: int, author: dict, content: str = "Un message", *, type: int = 0, when: datetime | None = None) -> int:
        """Somebody writes in a thread or a channel (without the bot's engine hearing of it: what a gap is made of). Returns the message's number."""
        message_id = next(self._message_ids)
        self.history.setdefault(int(place_id), []).append({"id": str(message_id), "channel_id": str(place_id), "author": author, "type": type, "content": content,
                                                           "timestamp": (when or T0).isoformat()})
        return message_id

    def posted(self, place_id: int, kind: str | None = None) -> list[dict]:
        """The messages of a place in the order they were posted (optionally only those whose embed title contains `kind`)."""
        found = [m for (t, _), m in sorted(self.messages.items(), key=lambda item: item[0][1]) if t == int(place_id)]
        return [m for m in found if kind is None or any(kind in (e.get("title") or "") for e in m.get("embeds", [])) or kind in m.get("content", "")]

    def call(self, method, path, body=None, *, authorized=True) -> Response:
        with self._lock:
            self.calls.append((method, path, body))
            for failure in self._failures:
                if failure[0] == method and failure[1].fullmatch(path) and failure[3] > 0:
                    failure[3] -= 1
                    return Response(failure[2], {"code": failure[4], "message": "refused"} if failure[4] else None)
            path, _, query = path.partition("?")
            match = re.fullmatch(r"/channels/(\d+)(?:/(threads|messages|thread-members/@me)(?:/(\d+))?)?", path)
            if match is None:
                return Response(404)
            channel, part, message = int(match[1]), match[2], match[3]
            if channel in self._deleted:
                return Response(404, {"code": 10003, "message": "Unknown Channel"})
            if method == "GET" and part is None:
                return Response(200, self.forums[channel]) if channel in self.forums else Response(200, {"id": str(channel), "type": 0, "guild_id": GUILD})
            if method == "POST" and part == "threads" and channel in self.forums:        # a post of a forum: the thread and its first message are made together
                forum = self.forums[channel]
                tags = list(body.get("applied_tags") or [])
                if not set(tags) <= {t["id"] for t in forum["available_tags"]} or len(tags) > 5 or (int(forum.get("flags", 0)) & 16 and not tags) or "message" not in body:
                    return Response(400, {"code": 40067 if not tags else 50035, "message": "refused"})
                thread_id = next(self._thread_ids)
                self.threads[thread_id] = {"parent": channel, "archived": False, **{k: v for k, v in body.items() if k != "message"}}
                self.messages[(thread_id, thread_id)] = dict(body["message"])             # (the first message of a post has the number of the post)
                self.history.setdefault(thread_id, []).append({"id": str(thread_id), "channel_id": str(thread_id), "author": {"id": "42", "bot": True}, "type": 0,
                                                               "content": "", "timestamp": T0.isoformat()})
                return Response(201, {"id": str(thread_id), "message": {"id": str(thread_id)}})
            if method == "POST" and part == "threads":
                thread_id = next(self._thread_ids)
                self.threads[thread_id] = {"parent": channel, "archived": False, **body}
                return Response(201, {"id": str(thread_id)})
            if method == "PUT" and part == "thread-members/@me":
                return Response(204)
            if method == "GET" and part == "messages":                               # a page: the oldest messages after a cursor, newest first (as Discord does)
                options = dict(item.split("=") for item in query.split("&") if item)
                after, limit = int(options.get("after", 0)), int(options.get("limit", 50))
                page = sorted((m for m in self.history.get(channel, []) if int(m["id"]) > after), key=lambda m: int(m["id"]))[:limit]
                return Response(200, list(reversed(page)))
            if method == "POST" and part == "messages":
                message_id = next(self._message_ids)
                self.messages[(channel, message_id)] = dict(body)
                self.history.setdefault(channel, []).append({"id": str(message_id), "channel_id": str(channel), "author": {"id": "42", "bot": True}, "type": 0,
                                                             "content": body.get("content", ""), "timestamp": T0.isoformat()})
                return Response(200, {"id": str(message_id)})
            if method == "DELETE" and part == "messages":
                gone = self.messages.pop((channel, int(message)), None)
                self.history[channel] = [m for m in self.history.get(channel, []) if m["id"] != message]
                return Response(204) if gone is not None else Response(404, {"code": 10008})
            if method == "PATCH" and part == "messages":
                if (channel, int(message)) not in self.messages:
                    return Response(404, {"code": 10008})
                self.messages[(channel, int(message))].update(body)
                return Response(200, {"id": message})
            if method == "PATCH" and part is None and channel in self.threads:
                self.threads[channel].update(body)
                return Response(200, {"id": str(channel)})
            return Response(404)

    def of(self, method: str, suffix: str) -> list:
        return [c for c in self.calls if c[0] == method and c[1].endswith(suffix)]


class Sent:
    """Stands for the HTTP calls that answer an interaction (like tests/test_privacy.py). `refuse_popups(n)`: Discord refuses the next n popups (HTTP 400)."""

    def __init__(self):
        self.calls = []
        self.shown: list[dict] = []                                                   # the popups that Discord accepted
        self.refused = 0                                                              # and those it did not
        self._popups_to_refuse = 0

    def refuse_popups(self, times: int) -> None:
        self._popups_to_refuse = times

    def __call__(self, method, path, body, authorized, attachment=None):
        self.calls.append((method, path, body, authorized, attachment))
        if method == "POST" and body.get("type") == MODAL:
            if self._popups_to_refuse > 0:
                self._popups_to_refuse -= 1
                self.refused += 1
                return 400
            self.shown.append(body["data"])
        return 200 if method in ("PUT", "PATCH") else 204

    def texts(self) -> list[str]:
        """Everything said to people, in order (the deferral and the popups say nothing)."""
        return [(c[2].get("data") or {}).get("content") if c[0] == "POST" else c[2].get("content") for c in self.calls if (c[2].get("data") or {}).get("content") or c[2].get("content")]

    def last(self) -> str:
        return self.texts()[-1]

    def popups(self) -> list[dict]:
        return list(self.shown)


class QuietChecker:
    """A checker that reads nothing: it only says that the checks of the claims are on (the popup then offers to switch them off for one debate)."""

    mode = "observe"

    def check(self, text):
        return []


class World:
    def __init__(self, url, tmp_path, checker=None):
        self.time, self.discord, self.sent = Time(), FakeDiscord(), Sent()
        self.url, self.checker = url, checker                                       # the checker: what reads the claims of the messages (None: the checks are off)
        self.service = PrivacyService(url, (tmp_path,))
        self.interactions = Interactions("tok", "http://api", self.service)
        self.interactions._request = self.sent
        self.debates = self.make_debates()
        self.runner = BotRunner([GUILD], Writer(url), batch_seconds=0, interactions=self.interactions, debates=self.debates)
        self.runner.handle(event("GUILD_CREATE", guild_create()))
        self._ids = itertools.count(500)

    def make_debates(self) -> Debates:
        """A fresh engine on the same database and the same fake Discord: what a restarted bot is."""
        debates = Debates(self.url, self.discord, clock=self.time.now, mono=self.time.tick, checker=self.checker)
        debates.interactions = self.interactions
        self.interactions.debates = debates
        self.interactions.verification = self.checker is not None
        self.interactions.live = notice_mode(self.checker) if self.checker is not None else False
        return debates

    def restart(self) -> None:
        self.debates = self.make_debates()
        self.runner = BotRunner([GUILD], Writer(self.url), batch_seconds=0, interactions=self.interactions, debates=self.debates)
        self.runner.handle(event("GUILD_CREATE", guild_create()))

    # --- what people do -------------------------------------------------------------------------------------------

    def ask(self, user=ALICE_ID, topic=TOPIC, **options):
        """`/dindon debat sujet`: the popup that the person is shown (the last one, if Discord refused the first), or None when they were refused instead."""
        before = len(self.sent.popups())
        run(self.interactions.answer(debat(user, topic, **options)))
        return self.popup() if len(self.sent.popups()) > before else None

    def popup(self) -> dict | None:
        return self.sent.popups()[-1] if self.sent.popups() else None

    def submit(self, user, popup, **options):
        """The person fills the popup and sends it."""
        run(self.interactions.answer(submission(user, popup, **options)))

    def command(self, user=ALICE_ID, topic=TOPIC, *, channel=GENERAL, channel_type=0, guild=GUILD, **answers):
        """The whole thing, as a person does it: the command, the popup, the popup filled and sent. Nothing is sent when the command was refused (no popup). By default, in a thread."""
        popup = self.ask(user, topic, channel=channel, channel_type=channel_type, guild=guild)
        if popup is not None:
            self.submit(user, popup, channel=channel, channel_type=channel_type, guild=guild, **answers)
        return popup

    def add_forum(self, channel_id=300, *, name="Débats", tags=(), flags=0, guild=GUILD):
        """A forum channel on the fake Discord, with its labels (Discord's `available_tags`)."""
        self.discord.forums[channel_id] = {"id": str(channel_id), "type": 15, "guild_id": guild, "name": name, "flags": flags,
                                           "available_tags": [{"id": t[0], "name": t[1], "moderated": len(t) > 2 and t[2]} for t in tags]}
        return channel_id

    def forum(self, user=ALICE_ID, *, salon=None, etiquette=None, retirer=None, permissions=MANAGE_MESSAGES, guild=GUILD, id="781"):
        """`/dindon forum`: a moderator tells Dindon where the debates go (or looks at it, or takes it off)."""
        options = [{"type": kind, "name": name, "value": value} for name, kind, value in (("salon", 7, salon), ("etiquette", 3, etiquette), ("retirer", 5, retirer)) if value is not None]
        member = {"user": {"id": str(user)}, **({"permissions": str(permissions)} if permissions is not None else {})}
        run(self.interactions.answer({"id": id, "token": "tok", "type": 2, "application_id": "42", "guild_id": guild, "channel_id": GENERAL, "channel": {"id": GENERAL, "type": 0},
                                      "data": {"name": "dindon", "options": [{"type": 1, "name": "forum", "options": options}]}, "member": member}))

    def click(self, user, place, debate_id, kind, value, **member):
        self.time.advance(seconds=2)                                  # people do not click twice in a second
        run(self.interactions.answer(button(user, place, texts.custom_id(kind, debate_id, value), **member)))

    def write(self, place, author=BOB, content="Je pense que oui", **extra):
        extra.setdefault("timestamp", self.time.now().isoformat())
        self.runner.handle(create(message_create(next(self._ids), content, author, channel_id=str(place), **extra)))

    def tick(self, **delta):
        self.time.advance(**delta)
        run(self.debates.tick())


def debat(user, topic=TOPIC, *, channel_type=0, guild=GUILD, id="777", channel=GENERAL):
    """The slash command as Discord sends it."""
    options = [{"type": 3, "name": "sujet", "value": topic}] if topic else []                       # the subject is optional: without it, the person chooses an axis in the popup
    data = {"id": id, "token": "tok", "type": 2, "application_id": "42", "channel_id": channel, "channel": {"id": channel, "type": channel_type},
            "data": {"name": "dindon", "options": [{"type": 1, "name": "debat", "options": options}]}, "member": {"user": {"id": str(user)}}}
    if guild:
        data["guild_id"] = guild
    return data


def fields_of(popup: dict) -> dict[str, dict]:
    """The fields of a popup by identifier (each sits in a label)."""
    return {f["component"]["custom_id"]: f["component"] for f in popup["components"]}


def submission(user, popup, *, topic=None, context="", thread=True, verify=True, axis=None, quiet=rules.DEFAULT_QUIET, omit=(), channel=GENERAL, channel_type=0, guild=GUILD, id="779",
               custom_id=None) -> dict:
    """The popup as Discord sends it back when the person sends it: one answer for each field that the popup had. `topic` None: the subject as the popup showed it. `axis`: the code of the axis
    chosen in the list. The options (open a thread, check the claims) come back as a checkbox each, or as the values that stay ticked in a group of checkboxes or in a plain list."""
    answers = []
    for name, field in fields_of(popup).items():
        if name in omit:
            continue
        if name == "topic":
            answer = {"type": 4, "custom_id": "topic", "value": field.get("value", "") if topic is None else topic}
        elif name == "context":
            answer = {"type": 4, "custom_id": "context", "value": context}
        elif name == "axis":
            answer = {"type": 3, "custom_id": "axis", "values": [axis] if axis else []}
        elif name == "quiet":
            answer = {"type": 3, "custom_id": "quiet", "values": [str(quiet)]}
        elif name == "options":
            flags = {"thread": thread, "verify": verify}
            answer = {"type": field["type"], "custom_id": "options", "values": [o["value"] for o in field["options"] if flags[o["value"]]]}
        else:
            answer = {"type": 23, "custom_id": name, "value": thread if name == "thread" else verify}
        answers.append({"type": 18, "component": answer})
    data = {"id": id, "token": "tok3", "type": 5, "application_id": "42", "channel_id": channel, "channel": {"id": channel, "type": channel_type},
            "data": {"custom_id": popup["custom_id"] if custom_id is None else custom_id, "components": answers}, "member": {"user": {"id": str(user)}}}
    if guild:
        data["guild_id"] = guild
    return data


def button(user, place, custom_id, id="888", permissions=None):
    member = {"user": {"id": str(user)}, **({"permissions": str(permissions)} if permissions is not None else {})}
    return {"id": id, "token": "tok2", "type": 3, "application_id": "42", "guild_id": GUILD, "channel_id": str(place),
            "data": {"custom_id": custom_id, "component_type": 2}, "member": member}


@pytest.fixture
def world(ingest_url, tmp_path):
    return World(ingest_url, tmp_path)


@pytest.fixture
def checking_world(ingest_url, tmp_path):
    """The same, with the checks of the claims switched on (nothing is read: see QuietChecker)."""
    return World(ingest_url, tmp_path, checker=QuietChecker())


def the_debate(ingest_db, place):
    return store.by_thread(ingest_db, int(place))


def only_debate(db):
    """The one debate in the database. (Never assume its number: a sequence is not rolled back, so it depends on the tests that ran before.)"""
    [(debate_id,)] = db.execute("SELECT id FROM debates").fetchall()
    return store.get(db, debate_id)


def debates_written(db) -> int:
    return db.execute("SELECT count(*) FROM debates").fetchone()[0]


# --- the command and its popup ----------------------------------------------------------------------------------------------


def test_the_command_has_only_an_optional_subject_everything_else_is_chosen_in_the_popup():
    [debat_command] = [o for o in COMMAND["options"] if o["name"] == "debat"]
    [subject] = debat_command["options"]
    assert subject["required"] is False and subject["name"] == "sujet" and (subject["min_length"], subject["max_length"]) == (3, 200)    # (without it, the person picks an axis)
    assert all(len(o["description"]) <= 100 for o in [debat_command, subject])                                                       # Discord's limit


def test_the_command_shows_a_popup_and_creates_nothing_yet(world, ingest_db):
    popup = world.ask(ALICE_ID)
    assert (world.sent.calls[0][0], world.sent.calls[0][1], world.sent.calls[0][2]["type"]) == ("POST", "/interactions/777/tok/callback", MODAL)
    assert popup["custom_id"] == texts.setup_custom_id(ALICE_ID, int(GENERAL)) and popup["title"] == "Paramètres du débat"
    fields = fields_of(popup)
    assert list(fields) == ["topic", "context", "axis", "thread", "quiet"]                                                         # five fields at most, and no verification: the checks are off
    assert (fields["topic"]["type"], fields["topic"]["value"], fields["topic"]["required"]) == (4, TOPIC, False)                   # the subject as typed, which can be changed or emptied
    assert (fields["context"]["type"], fields["context"]["style"], fields["context"]["required"]) == (4, 2, False)
    assert (fields["thread"]["type"], fields["thread"]["default"], fields["thread"]["required"]) == (23, True, False)              # a thread unless the person unticks it (and unticked is a valid answer)
    assert [(o["value"], o["default"]) for o in fields["quiet"]["options"]] == [(str(s), s == 86_400) for s in rules.QUIET_CHOICES]
    assert [o["label"] for o in fields["quiet"]["options"]] == ["1 heure", "6 heures", "24 heures", "3 jours", "7 jours"]
    assert [f["type"] for f in popup["components"]] == [18] * 5 and all(len(f["label"]) <= 45 for f in popup["components"])        # Discord's limit on labels…
    assert all(len(f.get("description", "")) < 100 for f in popup["components"])                                                   # …and on descriptions (none is cut short)
    assert world.discord.calls == [] and debates_written(ingest_db) == 0 and world.debates._threads == {}


def test_the_popup_offers_the_verification_only_when_the_owner_switched_the_checks_on_as_one_group_with_the_thread(checking_world):
    fields = fields_of(checking_world.ask(ALICE_ID))
    assert list(fields) == ["topic", "context", "axis", "options", "quiet"]                                                        # still five: the two choices share one field
    group = fields["options"]
    assert (group["type"], group["required"], group["min_values"], group["max_values"]) == (22, False, 0, 2)                      # none ticked is a valid answer
    assert [(o["value"], o["default"]) for o in group["options"]] == [("thread", True), ("verify", True)]                          # both on unless the person switches them off


def test_in_a_thread_there_is_no_choice_of_thread_and_the_verification_stays_a_checkbox_of_its_own(world, checking_world):
    assert "thread" not in fields_of(world.ask(ALICE_ID, channel=THREAD, channel_type=11))
    assert "thread" in fields_of(world.ask(ALICE_ID, channel_type=5))                                                              # an announcement channel can hold threads
    fields = fields_of(checking_world.ask(ALICE_ID, channel=THREAD, channel_type=11))
    assert list(fields) == ["topic", "context", "axis", "verify", "quiet"] and (fields["verify"]["type"], fields["verify"]["default"], fields["verify"]["required"]) == (23, True, False)
    assert list(fields_of(world.ask(ALICE_ID, channel=THREAD, channel_type=11))) == ["topic", "context", "axis", "quiet"]


def test_a_popup_that_discord_does_not_accept_is_replaced_by_a_plainer_one(world, checking_world, ingest_db):
    world.sent.refuse_popups(1)
    popup = world.ask(ALICE_ID)
    assert (world.sent.refused, len(world.sent.popups())) == (1, 1)
    options = fields_of(popup)["options"]
    assert (options["type"], options["required"], options["min_values"], options["max_values"]) == (3, False, 0, 1)                 # a list in which each option is ticked or not
    assert [(o["value"], o["default"]) for o in options["options"]] == [("thread", True)]
    world.submit(ALICE_ID, popup, thread=True)
    assert the_debate(ingest_db, max(world.discord.threads)).in_thread is True                                                      # and what it answers is understood
    checking_world.sent.refuse_popups(1)
    both = fields_of(checking_world.ask(BOB_ID))["options"]
    assert (both["type"], both["max_values"]) == (3, 2) and [(o["value"], o["default"]) for o in both["options"]] == [("thread", True), ("verify", True)]


def test_when_no_popup_is_accepted_the_person_is_told_and_nothing_is_created(world, ingest_db):
    world.sent.refuse_popups(2)
    assert world.ask(ALICE_ID) is None and world.sent.refused == 2
    assert "Une erreur est survenue" in world.sent.last() and debates_written(ingest_db) == 0 and world.discord.calls == []


@pytest.mark.parametrize(("options", "expected"), [
    ({"guild": None}, "salon d'un serveur"),
    ({"guild": "999"}, "salon d'un serveur"),
    ({"channel_type": 2}, "salon texte ou un fil"),
    ({"topic": "ab"}, "entre 3 et 200"),
])
def test_what_cannot_be_a_debate_is_refused_privately_without_a_popup_and_without_touching_discord(world, ingest_db, options, expected):
    assert world.ask(ALICE_ID, **options) is None
    assert expected in world.sent.last() and world.sent.calls[0][2]["data"]["flags"] == EPHEMERAL and world.discord.calls == []
    assert debates_written(ingest_db) == 0


def test_the_limits_are_told_before_the_popup_is_shown(world, ingest_db):
    world.command(ALICE_ID)
    assert world.ask(ALICE_ID) is None and "déjà un débat ouvert" in world.sent.last()
    world.command(BOB_ID)
    world.command(CAROL_ID)
    assert world.ask(1005) is None and "trop de débats ouverts" in world.sent.last() and len(world.discord.threads) == 3


def test_someone_who_stopped_being_recorded_cannot_start_one(world, ingest_db):
    privacy.stop_recording(ingest_db, ALICE_ID)
    assert world.ask(ALICE_ID) is None
    assert "ne pas être enregistré" in world.sent.last() and world.discord.calls == []


# --- the popup sent: the place and the launch message -----------------------------------------------------------------------


def test_with_the_thread_box_ticked_a_public_thread_is_opened_with_the_launch_message_and_no_timer(world, ingest_db):
    world.command(ALICE_ID, thread=True)
    [thread] = world.discord.threads
    assert world.discord.threads[thread] == {"parent": int(GENERAL), "archived": False, "name": f"Débat · {TOPIC}", "type": 11, "auto_archive_duration": 1440}
    assert [c[:2] for c in world.discord.calls] == [("POST", f"/channels/{GENERAL}/threads"), ("PUT", f"/channels/{thread}/thread-members/@me"),
                                                    ("POST", f"/channels/{thread}/messages")]
    [question] = world.discord.posted(thread)
    description = question["embeds"][0]["description"]
    assert TOPIC in description and "<t:" not in description and "1 jour sans message" in description and "Terminer le débat" in description
    assert "tous les messages" not in description                                                                                   # (that warning is for a debate in the channel)
    assert question["allowed_mentions"] == {"parse": []}
    debate = the_debate(ingest_db, thread)
    positions, finish = question["components"][0]["components"], question["components"][1]["components"]
    assert [b["custom_id"] for b in positions] == [texts.custom_id("pos", debate.id, k) for k in ("for", "unsure", "against")]
    assert [b["emoji"]["name"] for b in positions] == ["✅", "❔", "❌"] and [b["label"] for b in positions] == ["Pour · 0", "Ne sait pas · 0", "Contre · 0"]
    assert [(b["custom_id"], b["label"]) for b in finish] == [(texts.custom_id("end", debate.id, "now"), "Terminer le débat")]
    assert (debate.status, debate.created_by, debate.topic, debate.in_thread, debate.channel_id, debate.quiet_seconds) == ("open", ALICE_ID, TOPIC, True, int(GENERAL), 86_400)
    assert debate.question_message_id == debate.start_message_id == max(m for _, m in world.discord.messages)
    popup, deferred, told = world.sent.calls[:3]
    assert popup[2]["type"] == MODAL
    assert deferred[2] == {"type": 5, "data": {"flags": EPHEMERAL}}                                                                  # answered privately, after the acknowledgement
    assert told[1] == "/webhooks/42/tok3/messages/@original" and f"<#{thread}>" in told[2]["content"]
    run(world.debates.tick())                                                                                                      # once the debates are loaded, the thread is one and the channel is not
    assert world.debates.is_debate_thread(thread) and not world.debates.is_debate_thread(GENERAL)


def test_with_the_box_unticked_the_debate_takes_place_in_the_channel_and_says_that_everything_is_read(world, ingest_db):
    world.command(ALICE_ID, thread=False)
    assert world.discord.threads == {} and [c[:2] for c in world.discord.calls] == [("POST", f"/channels/{GENERAL}/messages")]
    [question] = world.discord.posted(GENERAL)
    assert "Dans ce salon, Dindon lit tous les messages écrits tant que le débat est ouvert" in question["embeds"][0]["description"]
    debate = only_debate(ingest_db)
    assert (debate.status, debate.in_thread, debate.thread_id, debate.channel_id) == ("open", False, int(GENERAL), int(GENERAL))
    assert debate.question_message_id == max(m for _, m in world.discord.messages)
    assert f"<#{GENERAL}>" in world.sent.last()
    run(world.debates.tick())
    assert world.debates.is_debate_thread(GENERAL)


def test_asked_inside_a_thread_the_debate_takes_place_in_that_thread_without_a_new_one(world, ingest_db):
    world.command(ALICE_ID, channel=THREAD, channel_type=11)
    assert world.discord.threads == {} and [c[:2] for c in world.discord.calls] == [("POST", f"/channels/{THREAD}/messages")]
    debate = only_debate(ingest_db)
    assert (debate.in_thread, debate.thread_id, debate.channel_id) == (False, int(THREAD), int(THREAD))


def test_the_context_is_kept_and_shown_in_the_launch_message(world, ingest_db):
    world.command(ALICE_ID, context="  On parle du  temps de travail\n\nen France, pas ailleurs.  ")
    debate = only_debate(ingest_db)
    assert debate.context == "On parle du temps de travail\n\nen France, pas ailleurs."
    assert debate.context in world.discord.posted(debate.thread_id)[0]["embeds"][0]["description"]


def test_the_subject_can_be_changed_in_the_popup(world, ingest_db):
    world.command(ALICE_ID, topic="Un autre sujet, plus précis ?")
    assert only_debate(ingest_db).topic == "Un autre sujet, plus précis ?"


@pytest.mark.parametrize("seconds", rules.QUIET_CHOICES)
def test_each_silence_of_the_popup_is_the_one_kept(world, ingest_db, seconds):
    world.command(ALICE_ID, quiet=seconds)
    assert only_debate(ingest_db).quiet_seconds == seconds


def test_without_an_answer_for_the_silence_the_default_is_used(world, ingest_db):
    world.command(ALICE_ID, omit=("quiet",))
    assert only_debate(ingest_db).quiet_seconds == rules.DEFAULT_QUIET


@pytest.mark.parametrize(("answers", "expected"), [
    ({"quiet": 5}, "durée de silence"),
    ({"quiet": "banane"}, "durée de silence"),
    ({"context": "x" * 1001}, "1 000 caractères"),
    ({"topic": "ab"}, "entre 3 et 200"),
])
def test_what_the_popup_should_have_prevented_is_refused_again_and_nothing_is_created(world, ingest_db, answers, expected):
    world.command(ALICE_ID, **answers)
    assert expected in world.sent.last() and debates_written(ingest_db) == 0 and world.discord.calls == []


def test_the_checks_of_a_debate_follow_the_box_of_the_popup(checking_world, ingest_db):
    checking_world.command(ALICE_ID, verify=True)
    checking_world.command(BOB_ID, verify=False)
    assert [d.verify for d in sorted(store.active(ingest_db), key=lambda d: d.id)] == [True, False]


def test_a_debate_is_never_checked_when_the_owner_left_the_checks_off_whatever_the_answer_says(world, ingest_db):
    answer = submission(ALICE_ID, world.ask(ALICE_ID))
    answer["data"]["components"].append({"type": 18, "component": {"type": 23, "custom_id": "verify", "value": True}})        # a field that the popup did not have
    run(world.interactions.answer(answer))
    assert only_debate(ingest_db).verify is False


def test_the_launch_message_of_a_checked_debate_carries_the_notice_and_that_of_an_unchecked_one_does_not(checking_world, ingest_db):
    checking_world.command(ALICE_ID, verify=True)
    checking_world.command(BOB_ID, verify=False)
    first, second = sorted(store.active(ingest_db), key=lambda d: d.id)

    def description(debate):
        return checking_world.discord.posted(debate.thread_id)[0]["embeds"][0]["description"]

    assert texts.notice_short("observe") in description(first) and "🔎" not in description(second)


@pytest.mark.parametrize("forged", ["dindon:debat:setup:x:y", "dindon:debat:setup:1", "dindon:debat:setup", "dindon:card:1:2", ""])
def test_a_popup_that_is_not_ours_or_was_not_shown_to_this_person_here_is_ignored_without_a_word(world, ingest_db, forged):
    popup = world.ask(ALICE_ID)
    calls = len(world.sent.calls)
    world.submit(ALICE_ID, popup, custom_id=forged)
    world.submit(BOB_ID, popup)                                                                                                    # the popup of somebody else
    world.submit(ALICE_ID, popup, channel=THREAD, channel_type=11)                                                                # the popup of another channel
    assert len(world.sent.calls) == calls and debates_written(ingest_db) == 0 and world.discord.calls == []


def test_a_server_that_is_not_followed_gets_no_debate_even_with_a_popup_in_hand(world, ingest_db):
    popup = world.ask(ALICE_ID)
    world.submit(ALICE_ID, popup, guild="999")
    assert "salon d'un serveur" in world.sent.last() and debates_written(ingest_db) == 0 and world.discord.calls == []


def test_the_limit_is_checked_again_when_the_popup_is_sent_for_it_may_have_changed_meanwhile(world, ingest_db):
    popup = world.ask(ALICE_ID)
    store.start(ingest_db, guild_id=int(GUILD), channel_id=1, topic="Un autre débat", created_by=ALICE_ID, now=T0)                  # opened from somewhere else in the meantime
    world.submit(ALICE_ID, popup)
    assert "déjà un débat ouvert" in world.sent.last() and debates_written(ingest_db) == 1 and world.discord.calls == []


def test_a_second_debate_in_the_same_channel_is_refused_but_a_thread_in_it_is_fine(world, ingest_db):
    world.command(ALICE_ID, thread=False)
    world.command(BOB_ID, thread=False)
    assert "Un débat est déjà ouvert dans ce salon" in world.sent.last() and debates_written(ingest_db) == 1
    world.command(BOB_ID, thread=True)
    assert "Le débat est ouvert" in world.sent.last() and debates_written(ingest_db) == 2


def test_two_popups_of_the_same_channel_sent_one_after_the_other_open_only_one(world, ingest_db):
    first, second = world.ask(ALICE_ID), world.ask(BOB_ID)
    world.submit(ALICE_ID, first, thread=False)
    world.submit(BOB_ID, second, thread=False)
    assert "Un débat est déjà ouvert dans ce salon" in world.sent.last() and debates_written(ingest_db) == 1
    assert len(world.discord.posted(GENERAL)) == 1


def test_without_the_right_to_make_threads_the_author_is_told_how_to_fix_it_and_may_try_again(world, ingest_db):
    world.discord.fail("POST", r"/channels/\d+/threads", 403, code=50013)
    world.command(ALICE_ID)
    assert "Inviter le bot" in world.sent.last() and "fils publics" in world.sent.last()
    assert only_debate(ingest_db).close_reason == "failed" and store.active(ingest_db) == []
    world.command(ALICE_ID)                                                                                                        # the failed one holds nobody's place
    assert "Le débat est ouvert" in world.sent.last()


def test_without_the_right_to_write_in_the_channel_the_author_is_told_and_nothing_stays_open(world, ingest_db):
    world.discord.fail("POST", rf"/channels/{GENERAL}/messages", 403, code=50013)
    world.command(ALICE_ID, thread=False)
    assert "Inviter le bot" in world.sent.last() and store.active(ingest_db) == [] and world.debates._threads == {}
    world.command(ALICE_ID, thread=False)
    assert "Le débat est ouvert" in world.sent.last() and world.debates.has_work()


def test_a_launch_message_that_could_not_be_posted_leaves_no_running_debate(world, ingest_db):
    world.discord.fail("POST", r"/channels/\d+/messages", 500)
    world.command(ALICE_ID)
    assert "n'a pas pu être ouvert" in world.sent.last() and store.active(ingest_db) == []
    assert only_debate(ingest_db).close_reason == "failed" and world.debates._threads == {}


def test_a_database_that_fails_while_writing_the_debate_is_told_and_nothing_is_done_on_discord(world, ingest_db, monkeypatch):
    popup = world.ask(ALICE_ID)

    def away(action):
        raise OSError("database away")

    monkeypatch.setattr(world.debates, "_db", away)
    world.submit(ALICE_ID, popup)
    assert "Une erreur est survenue" in world.sent.last() and world.discord.calls == []


# --- an axis instead of a subject: Dindon asks the question --------------------------------------------------------------------


def axis_row(db, code="structure"):
    """What the database says of an axis: (name, question, negative pole, positive pole). The tests read it instead of repeating it: the axes are the owner's to edit."""
    return db.execute("SELECT name, question, negative_pole, positive_pole FROM axes WHERE code = %s", (code,)).fetchone()


def an_axis_debate(world, db, code="structure", **answers):
    world.command(ALICE_ID, topic="", axis=code, **answers)
    return only_debate(db)


def test_the_popup_lists_the_axes_of_dindon_in_their_order_with_their_two_poles(world, ingest_db):
    rows = ingest_db.execute("SELECT code, name, negative_pole, positive_pole FROM axes WHERE is_active ORDER BY position, id").fetchall()
    field = fields_of(world.ask(ALICE_ID))["axis"]
    assert len(rows) == 21 and (field["type"], field["required"], field["min_values"], field["max_values"]) == (3, False, 0, 1)    # nothing is chosen unless the person chooses
    assert [(o["value"], o["label"], o["description"]) for o in field["options"]] == [(code, name, f"{neg} ↔ {pos}") for code, name, neg, pos in rows]
    assert not any(o.get("default") for o in field["options"]) and len(field["placeholder"]) <= 150


def test_without_a_subject_the_popup_shows_an_empty_subject_and_a_command_without_one_is_fine(world, ingest_db):
    popup = world.ask(ALICE_ID, "")
    assert "value" not in fields_of(popup)["topic"] and fields_of(popup)["topic"]["required"] is False
    assert "axe" in [f for f in popup["components"] if f["component"]["custom_id"] == "topic"][0]["description"]
    assert debates_written(ingest_db) == 0


def test_when_no_axis_is_active_there_is_no_list_and_the_subject_is_required_again(world, ingest_db):
    ingest_db.execute("UPDATE axes SET is_active = false")
    popup = world.ask(ALICE_ID, "")
    fields = fields_of(popup)
    assert list(fields) == ["topic", "context", "thread", "quiet"] and fields["topic"]["required"] is True
    assert "description" not in popup["components"][0]
    world.submit(ALICE_ID, popup, topic="")
    assert "Écrivez un sujet" in world.sent.last() and debates_written(ingest_db) == 0


def test_an_axis_whose_question_cannot_be_a_subject_is_not_offered_and_at_most_twenty_five_are(world, ingest_db):
    ingest_db.execute("UPDATE axes SET question = 'ab' WHERE code = 'structure'")
    for n in range(6):
        ingest_db.execute("INSERT INTO axes (code, name, question, negative_pole, positive_pole, definition, position, is_active) VALUES (%s, %s, %s, 'A', 'B', 'x', %s, true)",
                          (f"extra{n}", f"Axe {n}", f"Une question de l'axe numéro {n} ?", 100 + n))
    offered = [o["value"] for o in fields_of(world.ask(ALICE_ID))["axis"]["options"]]
    assert len(offered) == 25 and "structure" not in offered and offered[-1] == "extra4"                                            # (20 usable ones + 6 new = 26, cut at 25 in their order)


def test_every_axis_of_dindon_makes_a_question_that_fits_on_discord(ingest_db):
    axes = store.offered_axes(ingest_db)
    assert len(axes) == 21
    for axis in axes:
        debate = store.start(ingest_db, guild_id=1, channel_id=2, topic=axis.question, created_by=ALICE_ID, axis=axis, now=T0)
        message = texts.question(debate, {"for": 12, "unsure": 3, "against": 100})
        labels = [b["label"] for b in message["components"][0]["components"]]
        assert axis.question in message["embeds"][0]["description"] and len(message["embeds"][0]["description"]) < 4000
        assert labels == [f"{axis.negative_pole} · 12", "Ne sait pas · 3", f"{axis.positive_pole} · 100"] and all(len(label) <= 80 for label in labels)
        assert debate.axis == axis.snapshot()
        store.fail(ingest_db, debate.id, T0)


def test_without_a_subject_the_axis_chosen_gives_the_question_and_its_two_poles_as_the_answers(world, ingest_db):
    name, question, negative, positive = axis_row(ingest_db)
    debate = an_axis_debate(world, ingest_db)
    assert debate.topic == question and debate.axis == {"code": "structure", "name": name, "for": negative, "against": positive}
    [launch] = world.discord.posted(debate.thread_id)
    description = launch["embeds"][0]["description"]
    assert question in description and f"Question posée par Dindon · axe « {name} »" in description and "Répondez avec les boutons" in description and "Prenez position" not in description
    buttons = launch["components"][0]["components"]
    assert [b["label"] for b in buttons] == [f"{negative} · 0", "Ne sait pas · 0", f"{positive} · 0"] and [b["emoji"]["name"] for b in buttons] == ["🔵", "❔", "🟠"]
    assert [b["custom_id"] for b in buttons] == [texts.custom_id("pos", debate.id, k) for k in ("for", "unsure", "against")]       # (the same buttons underneath: only the words change)
    assert "✅" not in str(launch) and "❌" not in str(launch)                                                                       # neither pole is shown as the right one


def test_the_answers_name_the_pole_that_was_chosen_and_the_counters_use_the_poles(world, ingest_db):
    _, _, negative, positive = axis_row(ingest_db)
    debate = an_axis_debate(world, ingest_db)
    place = debate.thread_id
    world.click(BOB_ID, place, debate.id, "pos", "for")
    assert f"Position enregistrée : 🔵 {negative}" in world.sent.last()
    world.click(CAROL_ID, place, debate.id, "pos", "against")
    world.click(BOB_ID, place, debate.id, "pos", "against")
    assert f"Position changée : 🟠 {positive}" in world.sent.last()
    world.click(CAROL_ID, place, debate.id, "pos", "against")
    assert f"Vous aviez déjà choisi 🟠 {positive}" in world.sent.last()
    world.click(CAROL_ID, place, debate.id, "pos", "unsure")
    assert "Position changée : ❔ Ne sait pas" in world.sent.last()
    world.tick(seconds=6)
    labels = [b["label"] for b in world.discord.of("PATCH", f"/messages/{debate.question_message_id}")[-1][2]["components"][0]["components"]]
    assert labels == [f"{negative} · 0", "Ne sait pas · 1", f"{positive} · 1"]


def test_the_statistics_say_the_poles_and_never_pour_or_contre(world, ingest_db):
    _, _, negative, positive = axis_row(ingest_db)
    debate = an_axis_debate(world, ingest_db)
    place = debate.thread_id
    run(world.debates.tick())
    world.write(place, BOB)
    world.click(BOB_ID, place, debate.id, "pos", "for")
    world.click(CAROL_ID, place, debate.id, "pos", "against")
    world.click(BOB_ID, place, debate.id, "pos", "against")
    world.click(ALICE_ID, place, debate.id, "end", "now")
    world.tick(seconds=1)
    [closing] = world.discord.posted(place, "Débat terminé")
    text = closing["embeds"][0]["description"]
    assert f"🔵 {negative} **0** · ❔ Ne sait pas **0** · 🟠 {positive} **2**" in text and "Pour" not in text and "Contre" not in text
    people = texts.stats_page(stats.collect(ingest_db, debate.id), 1)["embeds"][0]["description"]
    assert f"— 🟠 {positive} (avant : 🔵 {negative})" in people and "✅" not in people and "❌" not in people


def test_a_subject_that_was_written_always_wins_over_an_axis(world, ingest_db):
    world.command(ALICE_ID, topic=TOPIC, axis="structure")
    debate = only_debate(ingest_db)
    assert debate.topic == TOPIC and debate.axis is None
    assert [b["label"] for b in world.discord.posted(debate.thread_id)[0]["components"][0]["components"]] == ["Pour · 0", "Ne sait pas · 0", "Contre · 0"]


def test_the_subject_written_in_the_popup_wins_too_and_spaces_alone_are_no_subject(world, ingest_db):
    world.submit(ALICE_ID, world.ask(ALICE_ID, ""), topic="Un sujet écrit dans la fenêtre", axis="structure")
    assert only_debate(ingest_db).topic == "Un sujet écrit dans la fenêtre" and only_debate(ingest_db).axis is None
    ingest_db.execute("DELETE FROM debates")
    world.submit(ALICE_ID, world.ask(ALICE_ID, ""), topic="    ", axis="structure")
    assert only_debate(ingest_db).axis["code"] == "structure"


def test_neither_a_subject_nor_an_axis_is_told_and_creates_nothing(world, ingest_db):
    world.command(ALICE_ID, topic="")
    assert "Écrivez un sujet, ou choisissez un axe" in world.sent.last() and debates_written(ingest_db) == 0 and world.discord.calls == []


@pytest.mark.parametrize("switch_off", [False, True])
def test_an_axis_that_does_not_exist_or_was_switched_off_since_is_told_and_creates_nothing(world, ingest_db, switch_off):
    popup = world.ask(ALICE_ID, "")
    if switch_off:
        ingest_db.execute("UPDATE axes SET is_active = false WHERE code = 'structure'")
    world.submit(ALICE_ID, popup, topic="", axis="structure" if switch_off else "n-existe-pas")
    assert "Cet axe n'est plus proposé" in world.sent.last() and debates_written(ingest_db) == 0 and world.discord.calls == []


def test_a_debate_keeps_the_words_it_opened_with_whatever_happens_to_the_axis_afterwards(world, ingest_db):
    _, _, negative, positive = axis_row(ingest_db)
    debate = an_axis_debate(world, ingest_db)
    ingest_db.execute("UPDATE axes SET name = 'Renommé', negative_pole = 'Autre', positive_pole = 'Encore', is_active = false WHERE code = 'structure'")
    world.click(BOB_ID, debate.thread_id, debate.id, "pos", "for")
    assert f"🔵 {negative}" in world.sent.last()
    world.tick(seconds=6)
    labels = [b["label"] for b in world.discord.of("PATCH", f"/messages/{debate.question_message_id}")[-1][2]["components"][0]["components"]]
    assert labels == [f"{negative} · 1", "Ne sait pas · 0", f"{positive} · 0"] and store.get(ingest_db, debate.id).axis["for"] == negative


def test_an_axis_debate_can_take_place_in_the_channel_and_be_checked_like_any_other(checking_world, ingest_db):
    checking_world.command(ALICE_ID, topic="", axis="religion", thread=False, verify=True)
    debate = only_debate(ingest_db)
    assert (debate.axis["code"], debate.in_thread, debate.verify, debate.thread_id) == ("religion", False, True, int(GENERAL))
    assert texts.notice_short("observe") in checking_world.discord.posted(GENERAL)[0]["embeds"][0]["description"]


# --- the buttons ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("in_thread", [True, False])
def test_a_position_is_taken_changed_and_shown_on_the_launch_message_at_most_every_few_seconds(world, ingest_db, in_thread):
    world.command(ALICE_ID, thread=in_thread)
    debate = only_debate(ingest_db)
    place = debate.thread_id
    world.click(BOB_ID, place, debate.id, "pos", "for")
    assert "Position enregistrée : ✅ Pour" in world.sent.last() and world.sent.calls[-1][2]["data"]["flags"] == EPHEMERAL
    world.click(CAROL_ID, place, debate.id, "pos", "against")
    world.click(BOB_ID, place, debate.id, "pos", "against")
    assert "Position changée : ❌ Contre" in world.sent.last()
    run(world.debates.tick())
    edits = world.discord.of("PATCH", f"/messages/{debate.question_message_id}")
    assert len(edits) == 1                                                                                                         # three clicks, one edit
    assert [b["label"] for b in edits[0][2]["components"][0]["components"]] == ["Pour · 0", "Ne sait pas · 0", "Contre · 2"]
    assert edits[0][2]["components"][1]["components"][0]["custom_id"] == texts.custom_id("end", debate.id, "now")                   # the end button stays
    world.click(CAROL_ID, place, debate.id, "pos", "unsure")
    run(world.debates.tick())
    assert len(world.discord.of("PATCH", f"/messages/{debate.question_message_id}")) == 1                                           # too soon after the last edit: it waits
    world.tick(seconds=6)
    assert [b["label"] for b in world.discord.of("PATCH", f"/messages/{debate.question_message_id}")[-1][2]["components"][0]["components"]] == ["Pour · 0", "Ne sait pas · 1", "Contre · 1"]


def test_a_double_click_is_not_handled_twice(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    custom_id = texts.custom_id("pos", debate.id, "for")
    run(world.interactions.answer(button(BOB_ID, debate.thread_id, custom_id)))
    run(world.interactions.answer(button(BOB_ID, debate.thread_id, custom_id)))
    assert "Un instant" in world.sent.last() and ingest_db.execute("SELECT count(*) FROM debate_positions").fetchone()[0] == 1


def test_a_person_who_stopped_cannot_take_a_position_and_other_buttons_are_ignored(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    privacy.stop_recording(ingest_db, BOB_ID)
    world.click(BOB_ID, debate.thread_id, debate.id, "pos", "for")
    assert "ne pas être enregistré" in world.sent.last() and ingest_db.execute("SELECT count(*) FROM debate_positions").fetchone()[0] == 0
    count = len(world.sent.calls)
    for foreign in ("dindon:debat:pos:1:maybe", "dindon:debat:other:1:for", "dindon:debat:pos:x:for", "dindon:debat:pos", "dindon:debat:vote:1:stop", "dindon:debat:end:1:later"):
        run(world.interactions.answer(button(CAROL_ID, debate.thread_id, foreign)))
    assert len(world.sent.calls) == count                                                                                          # malformed buttons get no answer
    assert ingest_db.execute("SELECT count(*) FROM debate_positions").fetchone()[0] == 0


# --- the end of a debate: the button -----------------------------------------------------------------------------------------


def test_the_person_who_opened_the_debate_ends_it_and_the_statistics_follow(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    thread = debate.thread_id
    run(world.debates.tick())                                                                                                      # (the engine has loaded the running debates, as it does in its first seconds)
    world.write(thread, BOB)                                                                                                       # written a moment ago: not yet written to the database…
    world.click(BOB_ID, thread, debate.id, "pos", "for")
    world.click(ALICE_ID, thread, debate.id, "end", "now")                                                                         # …and still counted: ending first brings it in
    assert "le débat est terminé" in world.sent.last() and world.sent.calls[-1][2]["data"]["flags"] == EPHEMERAL
    over = store.get(ingest_db, debate.id)
    assert (over.status, over.close_reason) == ("closed", "ended") and str(thread) not in world.debates._threads             # no longer read from here on
    assert world.discord.posted(thread, "Débat terminé") == []                                                                      # (the statistics come with the next look)
    world.tick(seconds=1)
    [closing] = world.discord.posted(thread, "Débat terminé")
    description = closing["embeds"][0]["description"]
    assert "terminé à la demande" in description and "**1** participant(s) · **1** message(s)" in description and "✅ Pour **1**" in description
    assert closing["allowed_mentions"] == {"parse": []}
    question = world.discord.messages[(thread, debate.question_message_id)]
    assert question["components"] == [] and "Ce débat est terminé" in question["embeds"][0]["description"]                          # the buttons are gone
    assert world.discord.threads[thread]["archived"] is True                                                                       # the thread that Dindon made is put away
    assert store.get(ingest_db, debate.id).final_message_id == max(m for _, m in world.discord.messages)
    world.tick(minutes=5)
    assert len(world.discord.posted(thread, "Débat terminé")) == 1                                                                  # and it is said once


def test_a_debate_in_the_channel_ends_the_same_way_and_the_channel_is_never_archived(world, ingest_db):
    world.command(ALICE_ID, thread=False)
    debate = only_debate(ingest_db)
    world.write(GENERAL, BOB)
    world.click(ALICE_ID, GENERAL, debate.id, "end", "now")
    world.tick(seconds=1)
    assert len(world.discord.posted(GENERAL, "Débat terminé")) == 1 and store.get(ingest_db, debate.id).status == "closed"
    assert [c for c in world.discord.calls if c[0] == "PATCH" and c[1] == f"/channels/{GENERAL}"] == []
    assert not world.debates.is_debate_thread(GENERAL)


def test_a_debate_in_an_existing_thread_leaves_that_thread_as_it_was(world, ingest_db):
    world.command(ALICE_ID, channel=THREAD, channel_type=11)
    debate = only_debate(ingest_db)
    world.write(THREAD, BOB)
    world.click(ALICE_ID, THREAD, debate.id, "end", "now")
    world.tick(seconds=1)
    assert len(world.discord.posted(THREAD, "Débat terminé")) == 1
    assert [c for c in world.discord.calls if c[0] == "PATCH" and c[1] == f"/channels/{THREAD}"] == []                             # it was not made by Dindon: not archived


@pytest.mark.parametrize(("user", "permissions", "allowed"), [
    (ALICE_ID, None, True),                                                                                                       # the person who opened it
    (BOB_ID, MANAGE_MESSAGES, True),                                                                                              # a moderator
    (BOB_ID, ADMINISTRATOR, True),
    (BOB_ID, MANAGE_MESSAGES | SEND_MESSAGES, True),
    (BOB_ID, None, False),                                                                                                        # anybody else
    (BOB_ID, SEND_MESSAGES, False),
    (BOB_ID, 0, False),
])
def test_only_the_person_who_opened_the_debate_or_a_moderator_can_end_it(world, ingest_db, user, permissions, allowed):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    world.click(user, debate.thread_id, debate.id, "end", "now", permissions=permissions)
    over = store.get(ingest_db, debate.id)
    if allowed:
        assert over.status == "closed" and "le débat est terminé" in world.sent.last()
    else:
        assert over.status == "open" and "Seuls la personne qui a lancé le débat et les modérateurs" in world.sent.last() and world.debates.is_debate_thread(debate.thread_id)


def test_garbled_permissions_do_not_make_somebody_a_moderator(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    for garbage in ("banane", "", "-1x", "-1", "-9223372036854775808", None):
        world.click(BOB_ID, debate.thread_id, debate.id, "end", "now", permissions=garbage)
        assert store.get(ingest_db, debate.id).status == "open"
    assert store.get(ingest_db, debate.id).created_by == ALICE_ID


def test_ending_twice_or_ending_a_debate_that_does_not_exist_is_answered_and_changes_nothing(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    world.click(ALICE_ID, debate.thread_id, debate.id, "end", "now")
    world.click(ALICE_ID, debate.thread_id, debate.id, "end", "now")
    assert "Ce débat est terminé" in world.sent.last()
    world.click(ALICE_ID, debate.thread_id, debate.id + 12345, "end", "now")
    assert "n'existe plus" in world.sent.last()
    world.click(BOB_ID, debate.thread_id, debate.id, "pos", "for")                                                                 # and a closed debate takes no more positions
    assert "Ce débat est terminé" in world.sent.last() and ingest_db.execute("SELECT count(*) FROM debate_positions").fetchone()[0] == 0


def test_a_debate_where_nobody_took_part_is_closed_with_that_said(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    world.click(ALICE_ID, debate.thread_id, debate.id, "end", "now")                                                               # (the one who ends it has not taken part either)
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).close_reason == "no_participants"
    assert "Personne n'a pris part" in world.discord.posted(debate.thread_id, "Débat terminé")[0]["embeds"][0]["description"]


# --- the end of a debate: the silence, and no timer --------------------------------------------------------------------------


def test_the_passing_of_time_posts_nothing_and_closes_nothing_while_somebody_still_writes(world, ingest_db):
    world.command(ALICE_ID, quiet=3_600)
    debate = only_debate(ingest_db)
    posts = len(world.discord.of("POST", f"/channels/{debate.thread_id}/messages"))
    for _ in range(30):                                                                                                            # thirty hours, a message every half hour
        world.tick(minutes=30)
        world.write(debate.thread_id, BOB)
        world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).status == "open" and len(world.discord.of("POST", f"/channels/{debate.thread_id}/messages")) == posts
    assert store.summary(ingest_db, debate.id)["messages"] == 30


def test_the_debate_ends_by_itself_after_the_silence_that_was_chosen(world, ingest_db):
    world.command(ALICE_ID, quiet=21_600)
    debate = only_debate(ingest_db)
    world.write(debate.thread_id, BOB)
    run(world.debates.tick())
    world.tick(hours=5, minutes=59)
    assert store.get(ingest_db, debate.id).status == "open" and world.discord.posted(debate.thread_id, "Débat terminé") == []
    world.tick(minutes=1)
    over = store.get(ingest_db, debate.id)
    assert (over.status, over.close_reason) == ("closed", "silence") and not world.debates.is_debate_thread(debate.thread_id)
    [closing] = world.discord.posted(debate.thread_id, "Débat terminé")
    assert "Plus personne n'a écrit depuis un moment" in closing["embeds"][0]["description"]
    assert world.discord.threads[debate.thread_id]["archived"] is True


def test_a_message_or_a_position_starts_the_silence_again(world, ingest_db):
    world.command(ALICE_ID, quiet=3_600)
    debate = only_debate(ingest_db)
    run(world.debates.tick())
    world.tick(minutes=50)
    world.write(debate.thread_id, BOB)
    world.tick(seconds=1)
    world.tick(minutes=50)                                                                                                         # 1h40 after the opening, 50 minutes after the message
    assert store.get(ingest_db, debate.id).status == "open"
    world.click(CAROL_ID, debate.thread_id, debate.id, "pos", "for")
    world.tick(minutes=50)                                                                                                         # 50 minutes after the position
    assert store.get(ingest_db, debate.id).status == "open"
    world.tick(minutes=11)
    assert store.get(ingest_db, debate.id).close_reason == "silence"


def test_a_message_written_by_a_bot_or_by_someone_who_stopped_is_no_activity(world, ingest_db):
    world.command(ALICE_ID, quiet=3_600)
    debate = only_debate(ingest_db)
    privacy.stop_recording(ingest_db, CAROL_ID)
    run(world.debates.tick())
    world.tick(minutes=40)
    world.write(debate.thread_id, BOT_USER)
    world.write(debate.thread_id, CAROL)
    world.tick(minutes=21)
    assert store.get(ingest_db, debate.id).close_reason == "no_participants"                                                       # silent for an hour, and nobody had taken part


# --- the messages of the place ----------------------------------------------------------------------------------------------


def test_the_messages_of_the_thread_are_counted_and_still_go_to_the_map(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    thread = debate.thread_id
    world.write(thread, BOB)
    world.write(thread, BOB, "Un deuxième message")
    world.write(thread, CAROL)
    world.write(thread, BOT_USER)                                                                                                  # a bot is not a participant
    world.write(thread, BOB, "(le fil a été renommé)", type=4)                                                                     # a system message either
    world.write(GENERAL, BOB, "Dans un autre salon")                                                                               # nor a message elsewhere
    assert world.runner.stats["received"] == 6                                                                                     # every one of them goes on to the map as before
    run(world.debates.tick())
    assert store.summary(ingest_db, debate.id)["messages"] == 3 and store.participants(ingest_db, debate.id) == {BOB_ID, CAROL_ID}
    world.write(thread, BOB)
    run(world.debates.tick())
    assert store.summary(ingest_db, debate.id)["messages"] == 4


def test_in_the_channel_every_message_written_while_the_debate_is_open_is_counted_and_goes_to_the_map(world, ingest_db):
    world.command(ALICE_ID, thread=False)
    debate = only_debate(ingest_db)
    world.write(GENERAL, BOB, "Un message qui n'a rien à voir avec le sujet")                                                       # everything said in the channel is read: that is what the popup said
    world.write(GENERAL, CAROL)
    world.write(GENERAL, BOT_USER)
    world.write(THREAD, BOB, "Dans un fil du salon")                                                                               # another place: not the debate's
    assert world.runner.stats["received"] == 4
    run(world.debates.tick())
    assert store.summary(ingest_db, debate.id)["messages"] == 2 and store.participants(ingest_db, debate.id) == {BOB_ID, CAROL_ID}


def test_what_was_written_in_the_channel_before_the_launch_message_is_not_part_of_the_debate(world, ingest_db):
    world.discord.say(GENERAL, BOB, "Avant le débat")
    world.command(ALICE_ID, thread=False)
    debate = only_debate(ingest_db)
    world.restart()                                                                                                                # a restart reads the place again, from the launch message on
    world.discord.say(GENERAL, CAROL, "Après")
    world.tick(seconds=5)
    assert store.participants(ingest_db, debate.id) == {CAROL_ID} and store.summary(ingest_db, debate.id)["messages"] == 1


def test_a_message_announced_twice_counts_once_and_a_person_who_stopped_does_not_count(world, ingest_db):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    payload = message_create(4242, "Bonjour", BOB, channel_id=str(debate.thread_id))
    world.runner.handle(create(payload))
    world.runner.handle(create(payload))
    privacy.stop_recording(ingest_db, CAROL_ID)
    world.write(debate.thread_id, CAROL)
    run(world.debates.tick())
    summary = store.summary(ingest_db, debate.id)
    assert (summary["participants"], summary["messages"]) == (1, 1)


def test_messages_wait_for_a_database_that_is_away_and_are_counted_when_it_is_back(world, ingest_db, monkeypatch):
    world.command(ALICE_ID)
    debate = only_debate(ingest_db)
    run(world.debates.tick())                                                                                                      # the debates are loaded: the failure below is in the writing of messages
    world.write(debate.thread_id, BOB)
    real = world.debates._db

    def away(action):
        raise OSError("database away")

    monkeypatch.setattr(world.debates, "_db", away)
    with pytest.raises(OSError):
        run(world.debates.tick())
    monkeypatch.setattr(world.debates, "_db", real)
    run(world.debates.tick())
    assert store.summary(ingest_db, debate.id)["messages"] == 1


# --- after a stop, and when Discord goes wrong ------------------------------------------------------------------------------


def started(world, ingest_db, *, speakers=(BOB, CAROL), thread=True):
    """A debate with one message from each of the speakers, counted. Returns (its place, the debate)."""
    world.command(ALICE_ID, thread=thread)
    debate = only_debate(ingest_db)
    for author in speakers:
        world.write(debate.thread_id, author)
    run(world.debates.tick())
    return debate.thread_id, debate


def test_a_bot_that_starts_again_goes_on_with_the_debate_and_counts_the_messages(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.restart()
    world.write(thread, BOB, "avant le chargement")                                                                                # before the first tick nobody knows which places are debates: kept aside
    run(world.debates.tick())
    assert world.debates.is_debate_thread(thread) and not world.debates.is_debate_thread(GENERAL)
    world.write(thread, CAROL)
    world.tick(seconds=1)
    assert store.summary(ingest_db, debate.id)["messages"] == 4 and store.get(ingest_db, debate.id).status == "open"


def test_a_debate_in_the_channel_also_survives_a_restart(world, ingest_db):
    place, debate = started(world, ingest_db, thread=False)
    world.restart()
    run(world.debates.tick())
    assert world.debates.is_debate_thread(GENERAL)
    world.write(GENERAL, BOB)
    world.tick(seconds=1)
    assert store.summary(ingest_db, debate.id)["messages"] == 3 and place == int(GENERAL)


def test_the_silence_goes_on_being_counted_across_a_restart(world, ingest_db):
    world.command(ALICE_ID, quiet=3_600)
    debate = only_debate(ingest_db)
    world.tick(minutes=40)
    world.restart()
    world.tick(minutes=19)
    assert store.get(ingest_db, debate.id).status == "open"
    world.tick(minutes=1)
    assert store.get(ingest_db, debate.id).close_reason == "no_participants"


def test_a_closing_that_was_owed_at_the_stop_is_posted_by_the_next_start(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.discord.fail("POST", rf"/channels/{thread}/messages", 500, times=1)
    world.click(ALICE_ID, thread, debate.id, "end", "now")
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).status == "closed" and world.discord.posted(thread, "Débat terminé") == []
    world.restart()
    world.tick(seconds=3)
    assert len(world.discord.posted(thread, "Débat terminé")) == 1


def test_a_failed_post_is_tried_again_with_growing_waits_and_not_twice_when_it_works(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.discord.fail("POST", rf"/channels/{thread}/messages", 500, times=2)
    world.click(ALICE_ID, thread, debate.id, "end", "now")
    world.tick(seconds=1)                                                                                                          # fails (first wait: 2 s)
    world.tick(seconds=1)
    assert len(world.discord.of("POST", f"/channels/{thread}/messages")) == 2                                                      # the launch message, and the one failed try: nothing hammered
    world.tick(seconds=2)                                                                                                          # fails again (second wait: 5 s)
    world.tick(seconds=4)
    assert world.discord.posted(thread, "Débat terminé") == []
    world.tick(seconds=2)
    assert len(world.discord.posted(thread, "Débat terminé")) == 1
    world.tick(minutes=2)
    assert len(world.discord.posted(thread, "Débat terminé")) == 1


def test_a_closing_that_never_works_is_given_up_after_a_few_tries(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.discord.fail("POST", rf"/channels/{thread}/messages", 500, times=99)
    world.click(ALICE_ID, thread, debate.id, "end", "now")
    for _ in range(12):
        world.tick(seconds=61)
    assert len(world.discord.of("POST", f"/channels/{thread}/messages")) == 1 + 5                                                  # the launch message, five tries at the closing
    assert store.get(ingest_db, debate.id).final_message_id == 0 and store.unannounced(ingest_db) == []


def test_a_thread_deleted_on_discord_ends_its_debate_without_retrying_for_ever(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.discord.delete_thread(thread)
    world.click(ALICE_ID, thread, debate.id, "end", "now")                                                                         # the closing finds the thread gone
    world.tick(seconds=1)
    over = store.get(ingest_db, debate.id)
    assert over.status == "closed" and over.final_message_id == 0 and not world.debates.is_debate_thread(thread)
    calls = len(world.discord.calls)
    world.tick(minutes=5)
    assert len(world.discord.calls) == calls


def test_a_debate_left_half_made_by_a_crash_stops_holding_its_authors_place(world, ingest_db):
    left = store.start(ingest_db, guild_id=int(GUILD), channel_id=int(GENERAL), topic="Un sujet", created_by=ALICE_ID, now=T0)      # written, its place never made
    world.restart()
    world.tick(seconds=30)
    assert store.get(ingest_db, left.id).status == "preparing"                                                                     # recent: it may still be being opened
    world.tick(minutes=3)
    assert store.get(ingest_db, left.id).close_reason == "failed"
    world.command(ALICE_ID)
    assert "Le débat est ouvert" in world.sent.last()


# --- the engine's loop ------------------------------------------------------------------------------------------------------


def test_the_engine_ends_a_quiet_debate_by_itself_with_no_event_from_discord(world, ingest_db, monkeypatch):
    monkeypatch.setattr(runner_module, "DEBATE_TICK_SECONDS", 0.05)

    async def scenario():
        events, stop = asyncio.Queue(), asyncio.Event()
        engine = asyncio.create_task(world.runner.run(events, stop))
        await world.interactions.answer(debat(ALICE_ID))
        await world.interactions.answer(submission(ALICE_ID, world.popup(), thread=True, quiet=3_600))
        [thread] = world.discord.threads
        store.set_position(ingest_db, the_debate(ingest_db, thread).id, BOB_ID, "for", T0)
        world.time.advance(minutes=61)
        for _ in range(100):
            if world.discord.posted(thread, "Débat terminé"):
                break
            await asyncio.sleep(0.05)
        stop.set()
        await engine
        return thread

    thread = run(scenario())
    assert len(world.discord.posted(thread, "Débat terminé")) == 1 and the_debate(ingest_db, thread).close_reason == "silence"


def test_a_debate_that_cannot_be_looked_after_does_not_stop_the_engine_and_is_said_once(world, ingest_db, monkeypatch, caplog):
    async def broken():
        raise OSError("database away")

    monkeypatch.setattr(world.debates, "tick", broken)
    monkeypatch.setattr(world.debates, "has_work", lambda: True)

    async def scenario():
        for _ in range(3):
            world.runner._debate_tick_at = -1e9
            world.runner._debate_tick_due()
            await asyncio.gather(*list(world.runner._tasks))

    with caplog.at_level("WARNING", logger="dindon.bot"):
        run(scenario())
    assert len([r for r in caplog.records if "could not be looked after" in r.getMessage()]) == 1 and world.runner._debate_ticking is False


# --- the pieces: texts, HTTP ------------------------------------------------------------------------------------------------


def test_the_buttons_of_other_things_are_not_taken_for_ours():
    assert texts.parse_custom_id("dindon:debat:pos:12:for") == ("pos", 12, "for")
    assert texts.parse_custom_id("dindon:debat:end:12:now") == ("end", 12, "now")
    assert texts.parse_custom_id("dindon:debat:stats:12:2") == ("stats", 12, "2")
    for other in ("dindon:debat:pos:12:continue", "dindon:debat:vote:12:continue", "dindon:debat:end:12:later", "dindon:debat:pos:x:for", "dindon:debat:pos:12", "dindon:card:0:1",
                  "dindon:debat:setup:12:34", "", None):
        assert texts.parse_custom_id(other) is None


def test_the_popup_identifier_names_the_person_and_the_channel_and_nothing_else_is_taken_for_it():
    assert texts.parse_setup_id(texts.setup_custom_id(12, 34)) == (12, 34)
    for other in ("dindon:debat:setup:12", "dindon:debat:setup:x:34", "dindon:debat:pos:12:34", "dindon:debat:setup:12:34:5", "", None):
        assert texts.parse_setup_id(other) is None
    assert len(texts.setup_custom_id(2**63, 2**63)) <= 100                                                                         # Discord's limit on an identifier


def test_what_a_popup_answers_is_read_wherever_the_fields_sit():
    components = [{"type": 18, "component": {"type": 4, "custom_id": "topic", "value": "Un sujet"}},
                  {"type": 1, "components": [{"type": 4, "custom_id": "context", "value": ""}]},
                  {"type": 18, "component": {"type": 23, "custom_id": "thread", "value": True}},
                  {"type": 18, "component": {"type": 3, "custom_id": "quiet", "values": ["3600"]}}, "junk", {"type": 18}]
    assert texts.modal_values(components) == {"topic": "Un sujet", "context": "", "thread": True, "quiet": ["3600"]}
    assert texts.modal_values(None) == {} and texts.modal_values([None, 3]) == {}
    assert texts.ticked({"thread": True}, "thread") and not texts.ticked({"thread": False}, "thread")                              # a checkbox of its own
    assert texts.ticked({"options": ["verify"]}, "verify") and not texts.ticked({"options": ["verify"]}, "thread")                  # a group, or a list: what stays in it is ticked
    assert not texts.ticked({"options": []}, "verify") and not texts.ticked({}, "verify") and not texts.ticked({"verify": "yes"}, "verify")   # nothing, or something odd: not ticked


def test_every_message_forbids_mentions_and_a_long_subject_fits_a_thread_name(world, ingest_db):
    debate = store.start(ingest_db, guild_id=1, channel_id=2, topic="@everyone " + "x" * 190, created_by=ALICE_ID, context="@here " * 20, now=T0)
    assert texts.question(debate, {"for": 1, "unsure": 0, "against": 0})["allowed_mentions"] == {"parse": []}
    assert texts.question(debate, {"for": 1, "unsure": 0, "against": 0}, verifying=True)["allowed_mentions"] == {"parse": []}
    assert len(texts.thread_name(debate.topic)) == 100 and texts.thread_name("Court") == "Débat · Court"


class _Server:
    """A real HTTP server on this machine, to test the client itself: what it sends, and how it reads 429s and errors."""

    def __init__(self):
        self.requests, self.answers = [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_any(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, self.rfile.read(length)))
                status, body, headers = outer.answers.pop(0) if outer.answers else (200, {"id": "1"}, {})
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_PATCH = handle_any

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/v10"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


@pytest.fixture
def server():
    fake = _Server()
    yield fake
    fake.stop()


def test_the_client_sends_the_token_and_json_and_reads_the_answer(server):
    waited = []
    rest = DiscordREST("Bot secret-token", server.url, sleep=waited.append)
    server.answers = [(201, {"id": "123456789012345678"}, {})]
    answer = rest.call("POST", "/channels/5/threads", {"name": "x"})
    method, path, headers, body = server.requests[0]
    assert (answer.status, answer.ok, answer.id) == (201, True, 123456789012345678)
    assert (method, path, json.loads(body)) == ("POST", "/api/v10/channels/5/threads", {"name": "x"})
    assert headers["authorization"] == "Bot secret-token" and headers["content-type"] == "application/json" and waited == []


def test_a_put_without_data_still_says_that_it_has_none(server):
    DiscordREST("t", server.url).call("PUT", "/channels/5/thread-members/@me")
    assert server.requests[0][2]["content-length"] == "0"


def test_a_rate_limit_is_waited_out_and_retried_but_not_for_ever(server):
    waited = []
    rest = DiscordREST("t", server.url, sleep=waited.append)
    server.answers = [(429, {"retry_after": 1.5}, {}), (429, None, {"Retry-After": "2"}), (200, {"id": "7"}, {})]
    assert rest.call("POST", "/channels/5/messages", {}).id == 7 and waited == [1.5, 2.0]
    waited.clear()
    server.answers = [(429, {"retry_after": 0.1}, {})] * 10
    assert rest.call("POST", "/channels/5/messages", {}).status == 429 and len(waited) == 3          # three retries, then the 429 is handed back
    waited.clear()
    server.answers = [(429, {"retry_after": 60}, {})]
    assert rest.call("POST", "/channels/5/messages", {}).status == 429 and waited == []               # too long to sleep through


def test_an_error_is_returned_with_discords_code_and_an_unreachable_discord_is_status_zero(server):
    rest = DiscordREST("t", server.url)
    server.answers = [(403, {"code": 50013, "message": "Missing Permissions"}, {})]
    refused = rest.call("POST", "/channels/5/threads", {})
    assert (refused.status, refused.code, refused.ok, refused.id) == (403, 50013, False, None)
    assert DiscordREST("t", "http://127.0.0.1:9/api/v10", timeout=1).call("GET", "/users/@me").status == 0       # nothing listens on port 9
