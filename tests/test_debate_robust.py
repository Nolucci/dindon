"""The debates when things change under them (docs/regles-du-bot.md, step D3): messages deleted or edited, the bot's own messages deleted by a moderator, a thread or a channel deleted,
and what was written while the bot could not hear (it was stopped, or Discord started a new Gateway session).

Level of proof: SIMULATED, like test_debate_bot.py (real PostgreSQL and engine, a fake Discord in memory, a clock moved by hand). The events are shaped like Discord's
(https://discord.com/developers/docs/events/gateway-events) but never came from it.
"""
from datetime import timedelta

import pytest

from dindon import privacy
from dindon.bot.events import GatewayEvent
from dindon.debate import store
from gateway_fixtures import BOB, CAROL, GENERAL, GUILD, message_create
from test_bot import event, flush
from test_debate_bot import ALICE_ID, BOB_ID, BOT_USER, CAROL_ID, T0, only_debate, run, started, world  # noqa: F401 (the fixture)

DAN = {"id": "1000000000000000005", "username": "dan", "discriminator": "0", "global_name": None, "avatar": None}
EVE = {"id": "1000000000000000006", "username": "eve", "discriminator": "0", "global_name": None, "avatar": None}
DAN_ID, EVE_ID = int(DAN["id"]), int(EVE["id"])


def deleted(world, thread, *ids):
    kind, data = ("MESSAGE_DELETE", {"id": str(ids[0])}) if len(ids) == 1 else ("MESSAGE_DELETE_BULK", {"ids": [str(i) for i in ids]})
    world.runner.handle(event(kind, {**data, "channel_id": str(thread), "guild_id": GUILD}))


def reads(world, since: int = 0) -> list[str]:
    """The reads of a thread's history asked of Discord, from the `since`-th on (the first engine of a test also reads its new thread once, as any start does)."""
    return [c[1] for c in world.discord.of("GET", "")[since:]]


def people(db, debate) -> set[int]:
    """Whoever wrote a counted message or holds a position (a witness who wrote is not a participant, but still has messages)."""
    return store.participants(db, debate.id) | {r[0] for r in db.execute("SELECT author_id FROM debate_messages WHERE debate_id = %s", (debate.id,)).fetchall()}


def figures(db, debate):
    return len(people(db, debate)), store.summary(db, debate.id)["messages"]


# --- messages deleted or edited -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("already_on_the_map", [False, True])
def test_a_deleted_message_stops_counting_and_so_does_a_person_whose_only_message_it_was(world, ingest_db, already_on_the_map):
    thread, debate = started(world, ingest_db)                                                       # Bob (message 500) and Carol (501) have written one message each
    assert figures(ingest_db, debate) == (2, 2)
    if already_on_the_map:
        flush(world.runner)                                                                          # the map stored them before they were deleted
    deleted(world, thread, 500)
    flush(world.runner)
    assert figures(ingest_db, debate) == (1, 1) and people(ingest_db, debate) == {CAROL_ID}
    deleted(world, thread, 501, 99999)                                                               # a bulk deletion, one of them never counted
    flush(world.runner)
    assert figures(ingest_db, debate) == (0, 0)


def test_a_deleted_message_does_not_take_back_a_position(world, ingest_db):
    thread, debate = started(world, ingest_db)
    store.set_position(ingest_db, debate.id, BOB_ID, "for", T0)
    deleted(world, thread, 500)
    flush(world.runner)
    assert figures(ingest_db, debate) == (2, 1)                                                      # Bob is still in: he took a position
    assert store.positions(ingest_db, debate.id) == {BOB_ID: "for"}


def test_a_message_deleted_after_the_debate_is_over_is_forgotten_too(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.click(ALICE_ID, thread, debate.id, "end", "now", permissions=8)
    assert store.get(ingest_db, debate.id).status == "closed"
    deleted(world, thread, 500)
    flush(world.runner)
    assert ingest_db.execute("SELECT count(*) FROM debate_messages WHERE debate_id = %s", (debate.id,)).fetchone()[0] == 1


def test_an_edit_changes_nothing_in_a_debate(world, ingest_db):
    thread, debate = started(world, ingest_db)
    calls = len(world.discord.calls)
    edited = message_create(500, "Finalement, non", BOB, channel_id=str(thread), edited_timestamp="2026-10-05T12:01:00.000000+00:00")
    world.runner.handle(event("MESSAGE_UPDATE", edited))
    flush(world.runner)
    run(world.debates.tick())
    assert figures(ingest_db, debate) == (2, 2) and len(world.discord.calls) == calls


# --- the bot's own messages -----------------------------------------------------------------------------------------------------


def test_a_question_deleted_by_a_moderator_is_posted_again_with_the_counts_as_they_are(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.click(BOB_ID, thread, debate.id, "pos", "for")
    old = debate.question_message_id
    posts = len(world.discord.of("POST", f"/channels/{thread}/messages"))
    del world.discord.messages[(thread, old)]                                                         # a moderator deletes it: Discord forgets it and tells the bot
    deleted(world, thread, old)
    world.tick(seconds=1)
    new = store.get(ingest_db, debate.id).question_message_id
    assert new not in (None, old) and len(world.discord.of("POST", f"/channels/{thread}/messages")) == posts + 1
    labels = [b["label"] for b in world.discord.messages[(thread, new)]["components"][0]["components"]]
    assert labels == ["Pour · 1", "Ne sait pas · 0", "Contre · 0", "Témoin · 0"]                                   # not a blank question: Bob's position is shown
    world.click(CAROL_ID, thread, debate.id, "pos", "against")                                       # and the buttons of the new message work
    world.tick(seconds=6)
    assert [b["label"] for b in world.discord.messages[(thread, new)]["components"][0]["components"]] == ["Pour · 1", "Ne sait pas · 0", "Contre · 1", "Témoin · 0"]
    world.tick(seconds=3)
    assert len(world.discord.of("POST", f"/channels/{thread}/messages")) == posts + 1                # posted once


def test_a_question_deleted_without_the_bot_hearing_of_it_is_found_when_the_counts_are_shown(world, ingest_db):
    thread, debate = started(world, ingest_db)
    del world.discord.messages[(thread, debate.question_message_id)]                                 # gone on Discord; no event came
    world.click(BOB_ID, thread, debate.id, "pos", "for")
    world.tick(seconds=1)                                                                            # the edit finds it gone (404)…
    world.tick(seconds=1)                                                                            # …and the next look posts it again
    new = store.get(ingest_db, debate.id).question_message_id
    assert new not in (None, debate.question_message_id)
    assert world.discord.messages[(thread, new)]["components"][0]["components"][0]["label"] == "Pour · 1"


def test_a_launch_message_deleted_in_the_channel_is_posted_again_with_its_buttons_and_the_debate_goes_on(world, ingest_db):
    place, debate = started(world, ingest_db, thread=False)
    world.click(BOB_ID, place, debate.id, "pos", "for")
    old = debate.question_message_id
    del world.discord.messages[(place, old)]
    deleted(world, place, old)
    world.tick(seconds=1)
    new = store.get(ingest_db, debate.id).question_message_id
    assert new not in (None, old) and len(world.discord.posted(place, "Débat")) == 1
    [message] = [m for (p, _), m in world.discord.messages.items() if p == place]
    assert [b["custom_id"] for row in message["components"] for b in row["components"]][-1] == f"dindon:debat:end:{debate.id}:now"        # the end button is back too
    assert store.get(ingest_db, debate.id).status == "open" and world.debates.is_debate_thread(place)


def test_other_messages_deleted_in_the_thread_make_the_bot_post_nothing(world, ingest_db):
    thread, debate = started(world, ingest_db)
    posts = len(world.discord.calls)
    deleted(world, thread, 500)
    deleted(world, GENERAL, debate.question_message_id)                                              # the same number, but in another channel: not ours
    world.tick(seconds=1)
    assert len(world.discord.calls) == posts


# --- a thread deleted -----------------------------------------------------------------------------------------------------------


def test_a_deleted_thread_ends_its_debate_at_once_and_nothing_more_is_asked_of_discord(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.runner.handle(event("THREAD_DELETE", {"id": str(thread), "guild_id": GUILD, "parent_id": GENERAL, "type": 11}))
    world.tick(seconds=1)
    over = store.get(ingest_db, debate.id)
    assert (over.status, over.close_reason) == ("closed", "failed") and not world.debates.is_debate_thread(thread)
    calls = len(world.discord.calls)
    world.tick(minutes=45)
    assert len(world.discord.calls) == calls


def test_a_deleted_channel_ends_the_debates_that_were_under_it_but_not_other_threads(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.runner.handle(event("THREAD_DELETE", {"id": "123", "guild_id": GUILD, "parent_id": GENERAL, "type": 11}))      # not a debate
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).status == "open"
    world.runner.handle(event("CHANNEL_DELETE", {"id": GENERAL, "guild_id": GUILD, "type": 0}))
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).close_reason == "failed"


def test_a_deleted_channel_ends_a_debate_that_took_place_in_it(world, ingest_db):
    place, debate = started(world, ingest_db, thread=False)
    world.runner.handle(event("CHANNEL_DELETE", {"id": GENERAL, "guild_id": GUILD, "type": 0}))
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).close_reason == "failed" and not world.debates.is_debate_thread(place)
    calls = len(world.discord.calls)
    world.tick(minutes=45)
    assert len(world.discord.calls) == calls


def test_a_debate_in_an_existing_thread_ends_with_that_thread_and_a_channel_deleted_elsewhere_changes_nothing(world, ingest_db):
    world.command(ALICE_ID, channel="210", channel_type=11)
    debate = only_debate(ingest_db)
    world.runner.handle(event("CHANNEL_DELETE", {"id": "999", "guild_id": GUILD, "type": 0}))
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).status == "open"
    world.runner.handle(event("THREAD_DELETE", {"id": "210", "guild_id": GUILD, "parent_id": GENERAL, "type": 11}))
    world.tick(seconds=1)
    assert store.get(ingest_db, debate.id).close_reason == "failed"


# --- what was written while the bot could not hear ------------------------------------------------------------------------------


def test_what_was_written_while_the_bot_was_stopped_is_counted_when_it_starts_again(world, ingest_db):
    thread, debate = started(world, ingest_db)                                                       # two messages are counted
    world.restart()
    mark = len(reads(world))
    world.discord.say(thread, BOB)
    world.discord.say(thread, DAN, "Je ne suis pas d'accord")
    world.discord.say(thread, BOT_USER, "Un autre bot")                                              # not a person
    world.discord.say(thread, EVE, "Fil renommé", type=4)                                            # not a message
    world.tick(seconds=5)
    assert figures(ingest_db, debate) == (3, 4) and people(ingest_db, debate) == {BOB_ID, CAROL_ID, DAN_ID}
    assert reads(world, mark) == [f"/channels/{thread}/messages?limit=100&after=501"]                # from the last message counted, not from the start


def test_a_long_thread_is_read_back_page_after_page_and_never_counted_twice(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.restart()
    mark = len(reads(world))
    for number in range(230):
        world.discord.say(thread, DAN if number % 2 else EVE)
    world.tick(seconds=5)
    assert figures(ingest_db, debate) == (4, 232) and len(reads(world, mark)) == 3                   # 100 + 100 + 31 (the bot's own question is among them)
    world.debates.note_gap()
    world.tick(seconds=1)
    assert figures(ingest_db, debate) == (4, 232)                                                    # read again: nothing is counted twice
    assert world.discord.of("GET", "")[-1][1].endswith("&after=" + str(max(int(m["id"]) for m in world.discord.history[thread] if not m["author"].get("bot"))))


def test_the_messages_of_a_person_who_stopped_are_not_counted_when_they_are_read_back(world, ingest_db):
    thread, debate = started(world, ingest_db)
    privacy.stop_recording(ingest_db, DAN_ID)
    world.restart()
    world.discord.say(thread, DAN)
    world.discord.say(thread, EVE)
    world.tick(seconds=5)
    assert people(ingest_db, debate) == {BOB_ID, CAROL_ID, EVE_ID}


def test_a_silence_that_seems_over_after_a_stop_counts_what_was_written_meanwhile_before_it_decides(world, ingest_db):
    world.command(ALICE_ID, quiet=3_600)
    debate = only_debate(ingest_db)
    store.set_position(ingest_db, debate.id, ALICE_ID, "for", T0)                                    # (somebody has to take part for the debate to be more than empty)
    world.restart()                                                                                  # the bot is away…
    world.discord.say(debate.thread_id, BOB, when=T0 + timedelta(minutes=50))                        # …somebody writes at 50 minutes…
    world.time.advance(minutes=61)                                                                   # …and the bot is back after 61: not an hour of silence, only 11 minutes
    run(world.debates.tick())
    over = store.get(ingest_db, debate.id)
    assert over.status == "open" and people(ingest_db, debate) == {ALICE_ID, BOB_ID}            # (and not « nobody took part »)
    world.tick(minutes=48)                                                                           # 109 minutes: an hour after the message, less one
    assert store.get(ingest_db, debate.id).status == "open"
    world.tick(minutes=1)
    assert store.get(ingest_db, debate.id).close_reason == "silence"


def test_a_debate_in_the_channel_is_read_back_from_the_last_message_counted(world, ingest_db):
    place, debate = started(world, ingest_db, thread=False)
    world.restart()
    mark = len(reads(world))
    world.discord.say(place, DAN, "Écrit pendant l'arrêt")
    world.tick(seconds=5)
    assert figures(ingest_db, debate) == (3, 3) and reads(world, mark) == [f"/channels/{GENERAL}/messages?limit=100&after=501"]


def test_a_new_gateway_session_makes_the_bot_read_the_threads_again_and_a_resumed_one_does_not(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.runner.handle(GatewayEvent("connected"))                                                   # the first session of this run
    world.tick(seconds=1)
    world.discord.say(thread, DAN)
    world.runner.handle(GatewayEvent("disconnected"))
    world.runner.handle(GatewayEvent("resumed"))                                                     # same session: nothing was missed
    world.tick(seconds=1)
    assert figures(ingest_db, debate) == (2, 2)
    world.runner.handle(GatewayEvent("connected"))                                                   # a new session: a gap
    world.tick(seconds=1)
    assert figures(ingest_db, debate) == (3, 3)


def test_when_discord_cannot_be_read_the_gap_stays_and_is_tried_again_later(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.restart()
    mark = len(reads(world))
    world.discord.say(thread, DAN)
    world.discord.fail("GET", rf"/channels/{thread}/messages.*", 500, times=1)
    world.tick(seconds=1)
    assert figures(ingest_db, debate) == (2, 2) and world.debates._gap is True
    world.tick(seconds=10)
    assert len(reads(world, mark)) == 1                                                              # not hammered
    world.tick(seconds=30)
    assert figures(ingest_db, debate) == (3, 3) and world.debates._gap is False


def test_a_thread_that_is_gone_when_the_bot_reads_it_ends_the_debate(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.restart()
    world.discord.delete_thread(thread)
    world.tick(seconds=5)
    assert store.get(ingest_db, debate.id).close_reason == "failed" and not world.debates.is_debate_thread(thread)


def test_nothing_is_read_back_for_a_debate_that_is_over(world, ingest_db):
    thread, debate = started(world, ingest_db)
    world.click(ALICE_ID, thread, debate.id, "end", "now", permissions=8)
    world.tick(seconds=1)
    world.restart()
    mark = len(reads(world))
    world.discord.say(thread, DAN)
    world.tick(seconds=5)
    assert reads(world, mark) == [] and figures(ingest_db, debate) == (2, 2)
