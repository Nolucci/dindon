"""The debates (docs/regles-du-bot.md), step D1: the rules, the state kept in the database, the end (button or silence, never a timer), and what the privacy rights do to it.

Level of proof: SIMULATED. A real PostgreSQL, invented people, and a clock that the tests move by hand (a silence of a week lasts a millisecond).
Nothing here talks to Discord or to an AI: those come in the next steps.
"""
import itertools
import threading
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from dindon import privacy
from dindon.debate import rules, store
from dindon.debate.store import DebateRefused

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
GUILD, CHANNEL = 111, 222
ALICE, BOB, CAROL, DAN, EVE = 1001, 1002, 1003, 1004, 1005
_thread_ids = itertools.count(5000)
_message_ids = itertools.count(9000)
DAY = 86_400


@pytest.fixture
def conn(conn):
    """The `conn` of the other tests, with its transaction already open. The code under test opens transactions of its own: on a connection
    that has none yet, the first of them is a real one and commits, and the debates of a test would leak into the next. Inside an open one
    they are savepoints, and everything is rolled back at the end."""
    conn.execute("SELECT 1")
    return conn


def at(**delta) -> datetime:
    return T0 + timedelta(**delta)


def opened(conn, *, by=ALICE, guild=GUILD, channel=CHANNEL, now=T0, **options):
    """A debate that is running: written, then given its place (a thread by default)."""
    debate = store.start(conn, guild_id=guild, channel_id=channel, topic="Faut-il réduire le temps de travail ?", created_by=by, now=now, **options)
    place = next(_thread_ids) if options.get("in_thread", True) else channel                  # a debate in the channel takes place in the channel itself
    return store.attach_thread(conn, debate.id, thread_id=place, question_message_id=next(_message_ids), now=now)


def speak(conn, debate, user, when=T0):
    assert store.record_message(conn, debate.id, message_id=next(_message_ids), author_id=user, sent_at=when)


def refused(call, code):
    with pytest.raises(DebateRefused) as error:
        call()
    assert error.value.code == code


# --- the rules, with no database --------------------------------------------------------------------------------------------


def test_the_subject_is_tidied_and_must_be_a_real_one():
    assert rules.clean_topic("  Le   nucléaire,\n pour ou contre ? ") == "Le nucléaire, pour ou contre ?"
    assert rules.clean_topic("ab") is None and rules.clean_topic("   ") is None
    assert rules.clean_topic("x" * 201) is None and rules.clean_topic("x" * 200) is not None


def test_the_context_is_tidied_line_by_line_and_may_be_absent():
    assert rules.clean_context("  Le   cadre\n\n  du  débat  ") == "Le cadre\n\ndu débat"
    assert rules.clean_context("") is None and rules.clean_context(None) is None and rules.clean_context("  \n ") is None
    assert rules.clean_context("x" * 1000) is not None and rules.clean_context("x" * 1001) is None


def test_the_silences_offered_are_in_words_and_the_default_is_one_of_them():
    assert rules.DEFAULT_QUIET in rules.QUIET_CHOICES == tuple(sorted(rules.QUIET_CHOICES))
    assert [rules.quiet_label(s) for s in rules.QUIET_CHOICES] == ["1 heure", "6 heures", "1 jour", "3 jours", "7 jours"]
    assert rules.quiet_label(5_400) == "90 minutes"
    assert not hasattr(rules, "DURATIONS") and not hasattr(rules, "decide") and not hasattr(rules, "VOTE_WINDOW_SECONDS")      # no timer, no vote any more


# --- opening ----------------------------------------------------------------------------------------------------------------


def test_a_debate_is_written_first_and_opens_when_its_place_exists(conn):
    debate = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="  Le  nucléaire ?  ", created_by=ALICE, now=T0)
    assert (debate.status, debate.topic, debate.thread_id, debate.started_at, debate.last_activity_at) == ("preparing", "Le nucléaire ?", None, None, None)
    assert (debate.in_thread, debate.verify, debate.quiet_seconds, debate.context) == (True, True, rules.DEFAULT_QUIET, None)
    assert store.quiet(conn, at(days=400)) == []                                        # not open: nothing can end it
    running = store.attach_thread(conn, debate.id, thread_id=77, question_message_id=88, now=at(seconds=5))
    assert (running.status, running.thread_id, running.question_message_id, running.start_message_id) == ("open", 77, 88, 88)
    assert running.started_at == at(seconds=5) and running.last_activity_at == at(seconds=5)
    assert store.by_thread(conn, 77) == running and store.by_thread(conn, 78) is None
    refused(lambda: store.attach_thread(conn, debate.id, thread_id=79, question_message_id=1, now=T0), "not_preparing")


def test_the_parameters_of_the_popup_are_kept(conn):
    debate = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, context="  Parlons\n  du  fond. ", in_thread=False, verify=False,
                         quiet_seconds=3_600, now=T0)
    assert (debate.context, debate.in_thread, debate.verify, debate.quiet_seconds) == ("Parlons\ndu fond.", False, False, 3_600)
    assert store.get(conn, debate.id) == debate


def test_a_debate_opened_from_an_axis_keeps_a_copy_of_its_words_and_a_free_one_has_none(conn):
    axis = store.Axis("structure", "Structure de l'État", "Le pouvoir doit-il être réparti ou concentré ?", "Fédéral", "Unitaire")
    debate = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic=axis.question, created_by=ALICE, axis=axis, now=T0)
    assert debate.axis == {"code": "structure", "name": "Structure de l'État", "for": "Fédéral", "against": "Unitaire"} and store.get(conn, debate.id) == debate
    conn.execute("UPDATE axes SET name = 'Autre', negative_pole = 'X' WHERE code = 'structure'")                       # the axis changes later: the debate does not
    assert store.get(conn, debate.id).axis["for"] == "Fédéral"
    free = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet libre", created_by=BOB, now=T0)
    assert free.axis is None and store.get(conn, free.id).axis is None


def test_the_axes_that_are_offered_are_the_active_ones_in_their_order_with_a_question_that_can_be_a_subject(conn):
    offered = store.offered_axes(conn)
    assert len(offered) == 21 and offered[0].code == "structure" and [a.code for a in offered] == [r[0] for r in conn.execute("SELECT code FROM axes WHERE is_active ORDER BY position, id")]
    conn.execute("UPDATE axes SET is_active = false WHERE code = 'pouvoir'")
    conn.execute("UPDATE axes SET question = 'ab' WHERE code = 'immigration'")
    conn.execute("UPDATE axes SET question = %s WHERE code = 'diplomatie'", ("x" * 201,))
    codes = [a.code for a in store.offered_axes(conn)]
    assert len(codes) == 18 and not {"pouvoir", "immigration", "diplomatie"} & set(codes)
    assert store.axis(conn, "structure").negative_pole and store.axis(conn, "pouvoir") is None and store.axis(conn, "n'importe quoi") is None


def test_at_most_twenty_five_axes_are_offered_whatever_the_popup_does_with_them(conn):
    for n in range(6):
        conn.execute("INSERT INTO axes (code, name, question, negative_pole, positive_pole, definition, position, is_active) VALUES (%s, %s, %s, 'A', 'B', 'x', %s, true)",
                     (f"extra{n}", f"Axe {n}", f"Une question de l'axe numéro {n} ?", 100 + n))
    codes = [a.code for a in store.offered_axes(conn)]
    assert len(codes) == store.MAX_AXES_OFFERED == 25 and codes[-1] == "extra3"                  # 21 + 6 = 27, cut at 25, in their order


def test_a_debate_that_cannot_be_set_up_on_discord_is_closed_and_owes_nothing(conn):
    debate = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, now=T0)
    closed = store.fail(conn, debate.id, at(seconds=3))
    assert (closed.status, closed.close_reason, closed.closed_at) == ("closed", "failed", at(seconds=3))
    assert store.unannounced(conn) == [] and store.active(conn) == []
    store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un autre sujet", created_by=ALICE, now=at(seconds=4))   # and the person may try again


def test_the_subject_the_context_and_the_silence_are_checked_and_nothing_is_written_by_a_refusal(conn):
    refused(lambda: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="ab", created_by=ALICE), "topic")
    refused(lambda: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, context="x" * 1001), "context")
    for silence in (0, 59, 100, 86_401, -DAY, 2_592_000):
        refused(lambda silence=silence: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, quiet_seconds=silence), "quiet")
    assert conn.execute("SELECT count(*) FROM debates").fetchone()[0] == 0


def test_every_silence_that_the_popup_offers_is_accepted(conn):
    for index, silence in enumerate(rules.QUIET_CHOICES):
        store.fail(conn, store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic=f"Sujet {index}", created_by=ALICE, quiet_seconds=silence).id)


def test_one_open_debate_per_person_and_three_per_server(conn):
    first = opened(conn, by=ALICE)
    refused(lambda: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Encore un sujet", created_by=ALICE), "person_limit")
    store.start(conn, guild_id=999, channel_id=CHANNEL, topic="Ailleurs", created_by=EVE)   # another server does not count in this one's limit…
    opened(conn, by=BOB)
    opened(conn, by=CAROL)
    refused(lambda: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Le quatrième", created_by=DAN), "server_limit")
    store.fail(conn, first.id, T0)                                                      # …and a debate that is closed frees its place
    store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Le quatrième", created_by=DAN)


def test_someone_who_asked_not_to_be_recorded_cannot_start_a_debate(conn):
    privacy.stop_recording(conn, ALICE)
    refused(lambda: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE), "blocked")
    refused(lambda: store.check_can_start(conn, guild_id=GUILD, created_by=ALICE), "blocked")


def test_what_is_known_before_the_popup_is_checked_without_writing_anything(conn):
    store.check_can_start(conn, guild_id=GUILD, created_by=ALICE)
    opened(conn, by=ALICE)
    refused(lambda: store.check_can_start(conn, guild_id=GUILD, created_by=ALICE), "person_limit")
    opened(conn, by=BOB)
    opened(conn, by=CAROL)
    refused(lambda: store.check_can_start(conn, guild_id=GUILD, created_by=DAN), "server_limit")
    store.check_can_start(conn, guild_id=999, created_by=DAN)
    assert conn.execute("SELECT count(*) FROM debates").fetchone()[0] == 3


def test_a_debate_in_the_channel_is_alone_there_while_threads_are_not(conn):
    """The channel itself is the place: two debates there would count the same messages twice. Threads each have their own."""
    in_channel = opened(conn, by=ALICE, in_thread=False)
    refused(lambda: store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un autre", created_by=BOB, in_thread=False), "channel_busy")
    opened(conn, by=BOB, in_thread=True)                                                # a thread in the same channel: no conflict
    opened(conn, by=CAROL, in_thread=False, channel=CHANNEL + 1)                        # another channel: no conflict
    assert in_channel.thread_id == CHANNEL


def test_a_closed_debate_frees_its_channel_for_the_next_one_which_is_then_the_one_found_there(conn):
    """The place of a debate in a channel is the channel: the second debate has the same one as the first, which is over."""
    first = opened(conn, by=ALICE, in_thread=False)
    store.end(conn, first.id, rules.ENDED, at(minutes=1))
    second = opened(conn, by=BOB, in_thread=False, now=at(minutes=2))
    assert second.thread_id == first.thread_id == CHANNEL and second.status == "open"
    assert store.by_thread(conn, CHANNEL) == second and [d.id for d in store.active(conn)] == [second.id]


def test_two_open_debates_can_never_share_a_place(conn):
    first = opened(conn, by=ALICE, in_thread=False)
    other = store.start(conn, guild_id=GUILD, channel_id=CHANNEL + 1, topic="Un sujet", created_by=BOB, in_thread=False, now=T0)
    with pytest.raises(psycopg.errors.UniqueViolation):                     # the database itself refuses, whatever the code above it does
        store.attach_thread(conn, other.id, thread_id=first.thread_id, question_message_id=1, now=T0)


def test_two_commands_at_the_same_moment_cannot_both_pass_the_limit(ingest_url):
    results, barrier = [], threading.Barrier(2)

    def go():
        with psycopg.connect(ingest_url, autocommit=True) as other:
            barrier.wait()
            try:
                store.start(other, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, now=T0)
                results.append("ok")
            except DebateRefused as error:
                results.append(error.code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert sorted(results) == ["ok", "person_limit"]


def test_two_debates_in_the_same_channel_at_the_same_moment_cannot_both_open(ingest_url):
    results, barrier = [], threading.Barrier(2)

    def go(person):
        with psycopg.connect(ingest_url, autocommit=True) as other:
            barrier.wait()
            try:
                store.start(other, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=person, in_thread=False, now=T0)
                results.append("ok")
            except DebateRefused as error:
                results.append(error.code)

    threads = [threading.Thread(target=go, args=(person,)) for person in (ALICE, BOB)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert sorted(results) == ["channel_busy", "ok"]


# --- what happens while it is open ------------------------------------------------------------------------------------------


def test_a_person_takes_a_position_and_may_change_it_and_the_history_is_kept(conn):
    debate = opened(conn)
    assert store.set_position(conn, debate.id, BOB, "for", at(minutes=1)) == "recorded"
    assert store.set_position(conn, debate.id, BOB, "for", at(minutes=2)) == "unchanged"
    assert store.set_position(conn, debate.id, BOB, "against", at(minutes=3)) == "changed"
    store.set_position(conn, debate.id, CAROL, "unsure", at(minutes=3))
    assert store.positions(conn, debate.id) == {BOB: "against", CAROL: "unsure"}
    assert store.position_counts(conn, debate.id) == {"for": 0, "unsure": 1, "against": 1}
    assert conn.execute("SELECT position FROM debate_positions WHERE user_id = %s ORDER BY id", (BOB,)).fetchall() == [("for",), ("against",)]
    refused(lambda: store.set_position(conn, debate.id, BOB, "maybe"), "position")
    refused(lambda: store.set_position(conn, 424242, BOB, "for"), "unknown")


def test_positions_are_refused_to_people_who_stopped_and_once_the_debate_is_closed(conn):
    debate = opened(conn)
    store.set_position(conn, debate.id, BOB, "for", at(minutes=1))
    privacy.stop_recording(conn, BOB)
    refused(lambda: store.set_position(conn, debate.id, BOB, "against"), "blocked")
    assert store.positions(conn, debate.id) == {}                                       # and what they said before no longer counts in the totals
    store.fail(conn, debate.id, at(minutes=2))
    refused(lambda: store.set_position(conn, debate.id, CAROL, "for"), "not_open")


def test_a_message_counts_once_and_only_for_a_running_debate_and_a_person_who_is_recorded(conn):
    debate = opened(conn)
    assert store.record_message(conn, debate.id, message_id=1, author_id=BOB, sent_at=T0)
    assert not store.record_message(conn, debate.id, message_id=1, author_id=BOB, sent_at=T0)      # the Gateway may announce a message twice
    privacy.stop_recording(conn, CAROL)
    assert not store.record_message(conn, debate.id, message_id=2, author_id=CAROL, sent_at=T0)
    assert conn.execute("SELECT count(*) FROM debate_messages WHERE debate_id = %s", (debate.id,)).fetchone()[0] == 1
    store.fail(conn, debate.id, at(minutes=1))
    assert not store.record_message(conn, debate.id, message_id=3, author_id=BOB, sent_at=at(minutes=2))


def test_a_message_waits_to_be_read_only_if_the_debate_checks_its_claims_and_the_engine_asks_for_it(conn):
    checked, unchecked = opened(conn, by=ALICE, verify=True), opened(conn, by=BOB, verify=False)

    def waiting(debate_id, message):
        return conn.execute("SELECT read_at IS NULL FROM debate_messages WHERE debate_id = %s AND message_id = %s", (debate_id, message)).fetchone()[0]

    store.record_message(conn, checked.id, message_id=1, author_id=CAROL, sent_at=T0, to_read=True)
    store.record_message(conn, checked.id, message_id=2, author_id=CAROL, sent_at=T0, to_read=False)
    store.record_message(conn, unchecked.id, message_id=3, author_id=CAROL, sent_at=T0, to_read=True)       # this debate was opened without verification: never queued
    assert (waiting(checked.id, 1), waiting(checked.id, 2), waiting(unchecked.id, 3)) == (True, False, False)


def test_the_participants_are_those_who_wrote_or_took_a_position_and_never_those_who_stopped(conn):
    debate = opened(conn)
    speak(conn, debate, BOB)
    store.set_position(conn, debate.id, CAROL, "for", T0)
    speak(conn, debate, DAN)
    store.set_position(conn, debate.id, DAN, "against", T0)                             # both: counted once
    assert store.participants(conn, debate.id) == {BOB, CAROL, DAN}
    privacy.stop_recording(conn, DAN)                                                   # they stop in the middle of it
    assert store.participants(conn, debate.id) == {BOB, CAROL}


def test_the_summary_gives_the_people_the_messages_and_the_positions(conn):
    debate = opened(conn)
    speak(conn, debate, BOB)
    speak(conn, debate, BOB)
    store.set_position(conn, debate.id, CAROL, "against", T0)
    assert store.summary(conn, debate.id) == {"participants": 2, "messages": 2, "positions": {"for": 0, "unsure": 0, "against": 1}}


# --- the end: the button, the silence, and no timer -------------------------------------------------------------------------


def test_a_debate_has_no_time_limit_however_long_it_lasts(conn):
    debate = opened(conn, quiet_seconds=7 * DAY)
    speak(conn, debate, BOB, at(days=3))
    assert store.quiet(conn, at(days=9)) == [] and store.get(conn, debate.id).status == "open"
    assert not {"duration_seconds", "ends_at", "voting_ends_at", "round", "max_rounds", "vote_message_id"} & {f for f in store.Debate.__dataclass_fields__}
    assert conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'debate_votes'").fetchone()[0] == 0


def test_ending_closes_the_debate_once_and_says_why(conn):
    debate = opened(conn)
    speak(conn, debate, BOB)
    ended = store.end(conn, debate.id, rules.ENDED, at(hours=5))
    assert (ended.status, ended.close_reason, ended.closed_at) == ("closed", "ended", at(hours=5))
    assert store.end(conn, debate.id, rules.ENDED, at(hours=6)) is None                 # a second click, or the silence arriving at the same moment: nothing more happens
    assert store.get(conn, debate.id).closed_at == at(hours=5) and store.active(conn) == []


def test_a_debate_where_nobody_took_part_is_closed_as_such_whatever_the_reason(conn):
    for index, reason in enumerate((rules.ENDED, rules.SILENCE)):
        debate = opened(conn, by=ALICE + index)
        assert store.end(conn, debate.id, reason, at(hours=1)).close_reason == "no_participants"


def test_the_silence_ends_it_with_its_own_reason(conn):
    debate = opened(conn, quiet_seconds=3_600)
    speak(conn, debate, BOB, at(minutes=10))
    assert store.end(conn, debate.id, rules.SILENCE, at(hours=2)).close_reason == "silence"


def test_the_end_of_a_debate_that_is_not_open_does_nothing(conn):
    preparing = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, now=T0)
    assert store.end(conn, preparing.id, rules.ENDED, T0) is None and store.get(conn, preparing.id).status == "preparing"
    refused(lambda: store.end(conn, 424242, rules.ENDED, T0), "unknown")


def test_the_silence_is_counted_from_the_last_message_or_position_and_each_debate_has_its_own(conn):
    short, long = opened(conn, by=ALICE, quiet_seconds=3_600), opened(conn, by=BOB, quiet_seconds=DAY)
    assert store.quiet(conn, at(minutes=59, seconds=59)) == []
    assert store.quiet(conn, at(hours=1)) == [short.id]                                 # on the dot
    assert store.quiet(conn, at(hours=23)) == [short.id]
    assert store.quiet(conn, at(days=1)) == [short.id, long.id]
    speak(conn, short, CAROL, at(minutes=50))                                           # a message starts the silence again…
    store.set_position(conn, long.id, DAN, "for", at(hours=23))                         # …and so does a position
    assert store.quiet(conn, at(hours=1, minutes=49)) == []
    assert store.quiet(conn, at(hours=1, minutes=50)) == [short.id]
    assert store.quiet(conn, at(days=1, hours=22)) == [short.id]
    assert store.quiet(conn, at(days=1, hours=23)) == [short.id, long.id]


def test_an_old_message_read_back_after_a_gap_never_brings_the_silence_back_in_time(conn):
    debate = opened(conn, quiet_seconds=3_600)
    speak(conn, debate, BOB, at(minutes=40))
    store.record_message(conn, debate.id, message_id=1, author_id=CAROL, sent_at=at(minutes=5))      # read late, written early
    assert store.get(conn, debate.id).last_activity_at == at(minutes=40)
    assert store.quiet(conn, at(minutes=99)) == [] and store.quiet(conn, at(minutes=100)) == [debate.id]


def test_a_debate_that_is_not_open_or_has_no_silence_is_never_ended_by_it(conn):
    preparing = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, now=T0)
    closed = opened(conn, by=BOB)
    store.end(conn, closed.id, rules.ENDED, at(minutes=1))
    open_one = opened(conn, by=CAROL)
    conn.execute("UPDATE debates SET quiet_seconds = NULL WHERE id = %s", (open_one.id,))              # (a debate of the first design)
    assert preparing.status == "preparing" and store.quiet(conn, at(days=400)) == []


def test_the_end_happens_once_even_if_the_button_and_the_silence_come_together(ingest_url):
    with psycopg.connect(ingest_url, autocommit=True) as setup:
        debate = opened(setup)
        speak(setup, debate, BOB)
    results, barrier = [], threading.Barrier(2)

    def go(reason):
        with psycopg.connect(ingest_url, autocommit=True) as other:
            barrier.wait()
            closed = store.end(other, debate.id, reason, at(days=2))
            results.append(None if closed is None else closed.close_reason)

    threads = [threading.Thread(target=go, args=(reason,)) for reason in (rules.ENDED, rules.SILENCE)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert len([r for r in results if r]) == 1 and results.count(None) == 1


# --- the place of the debate, and what happens when it disappears -----------------------------------------------------------


def test_the_place_is_the_thread_or_the_channel_itself(conn):
    in_thread, in_channel = opened(conn, by=ALICE, in_thread=True), opened(conn, by=BOB, in_thread=False)
    assert in_thread.thread_id != in_thread.channel_id and in_thread.in_thread
    assert not in_channel.in_thread and in_channel.thread_id == in_channel.channel_id == CHANNEL


def test_where_to_go_on_reading_after_a_gap_starts_after_the_launch_message_never_at_the_beginning_of_the_channel(conn):
    debate = opened(conn)
    assert store.last_seen_message(conn, debate.id) == debate.question_message_id != 0
    store.record_message(conn, debate.id, message_id=debate.question_message_id + 10, author_id=BOB, sent_at=T0)
    store.record_message(conn, debate.id, message_id=debate.question_message_id + 4, author_id=CAROL, sent_at=T0)
    assert store.last_seen_message(conn, debate.id) == debate.question_message_id + 10
    preparing = store.start(conn, guild_id=GUILD, channel_id=CHANNEL + 5, topic="Un sujet", created_by=EVE, now=T0)
    assert store.last_seen_message(conn, preparing.id) == 0 and store.last_seen_message(conn, 424242) == 0


def test_a_deleted_thread_or_channel_closes_its_debates_without_anything_owed(conn):
    a, b, c = opened(conn, by=ALICE), opened(conn, by=BOB, in_thread=False, channel=300), opened(conn, by=CAROL, channel=400)
    assert store.close_gone(conn, thread_ids=(a.thread_id,), now=at(minutes=1)) == [a.thread_id]
    assert store.close_gone(conn, channel_ids=(300,), now=at(minutes=2)) == [b.thread_id]          # a debate in a channel: the channel is its place
    assert store.get(conn, a.id).close_reason == "failed" and store.get(conn, b.id).status == "closed" and store.get(conn, c.id).status == "open"
    assert store.close_gone(conn, channel_ids=(400,), now=at(minutes=3)) == [c.thread_id]          # the parent of a thread takes the thread with it
    assert store.close_gone(conn, thread_ids=(a.thread_id,), channel_ids=(300, 400), now=at(minutes=4)) == []     # what is closed is left alone
    assert store.unannounced(conn) == [] and store.get(conn, a.id).closed_at == at(minutes=1)


def test_a_debate_left_half_made_by_a_crash_is_closed_after_a_while_and_only_then(conn):
    old = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un sujet", created_by=ALICE, now=T0)
    recent = store.start(conn, guild_id=GUILD, channel_id=CHANNEL, topic="Un autre", created_by=BOB, now=at(minutes=1, seconds=30))
    running = opened(conn, by=CAROL)
    assert store.close_stale(conn, at(minutes=2), timedelta(minutes=2)) == 0
    assert store.close_stale(conn, at(minutes=3), timedelta(minutes=2)) == 1
    assert store.get(conn, old.id).close_reason == "failed" and store.get(conn, recent.id).status == "preparing" and store.get(conn, running.id).status == "open"


# --- after a stop of the bot ------------------------------------------------------------------------------------------------


def test_what_is_left_to_announce_is_known_after_a_stop(conn):
    debate = opened(conn)
    speak(conn, debate, BOB)
    assert [d.id for d in store.active(conn)] == [debate.id] and store.unannounced(conn) == []
    assert store.bot_messages_deleted(conn, debate.id, [debate.question_message_id]) == ["question"]    # a moderator deleted the launch message
    assert [d.id for d in store.unannounced(conn)] == [debate.id]
    assert store.bot_messages_deleted(conn, debate.id, [123]) == []                                    # the message of somebody else: nothing to do
    assert store.set_question_message(conn, debate.id, 555) and not store.set_question_message(conn, debate.id, 556)
    assert store.unannounced(conn) == [] and store.get(conn, debate.id).question_message_id == 555
    store.end(conn, debate.id, rules.ENDED, at(hours=1))
    assert [d.id for d in store.unannounced(conn)] == [debate.id]                       # closed, the statistics are still owed
    assert store.set_final_message(conn, debate.id, 777) and not store.set_final_message(conn, debate.id, 778)
    assert store.unannounced(conn) == [] and store.active(conn) == []


def test_the_state_can_be_read_back_with_a_new_connection_so_a_debate_survives_a_restart(ingest_url):
    with psycopg.connect(ingest_url, autocommit=True) as before:
        debate = opened(before, quiet_seconds=3_600, in_thread=False, verify=False, context="Le cadre")
    with psycopg.connect(ingest_url, autocommit=True) as after:                         # the bot was restarted
        [reloaded] = store.active(after)
        assert reloaded == debate and (reloaded.in_thread, reloaded.verify, reloaded.context) == (False, False, "Le cadre")
        assert store.quiet(after, at(minutes=59)) == [] and store.quiet(after, at(hours=2)) == [debate.id]


# --- the rights of the people -----------------------------------------------------------------------------------------------


def _busy_debate(conn, *, by=ALICE):
    debate = opened(conn, by=by)
    speak(conn, debate, BOB)
    speak(conn, debate, CAROL)
    store.set_position(conn, debate.id, BOB, "for", T0)
    store.set_position(conn, debate.id, BOB, "against", at(minutes=1))
    store.set_position(conn, debate.id, CAROL, "unsure", T0)
    return debate


def rows(conn, table, column, user):
    return conn.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (user,)).fetchone()[0]


def test_erasing_a_person_removes_their_part_in_debates_and_keeps_the_others(conn):
    debate = _busy_debate(conn)
    counts = privacy.erase_person(conn, BOB, source="test")
    assert counts["debate_traces"] == 1 + 2                                             # 1 message, 2 positions
    assert [rows(conn, t, c, BOB) for t, c in privacy.DEBATE_PERSON_COLUMNS] == [0] * len(privacy.DEBATE_PERSON_COLUMNS)
    assert rows(conn, "debate_messages", "author_id", CAROL) == 1 and store.positions(conn, debate.id) == {CAROL: "unsure"}
    privacy.erase_person(conn, ALICE, source="test")                                    # the one who started it
    assert store.get(conn, debate.id).created_by is None and store.get(conn, debate.id).topic                # the debate itself stays


def test_every_table_of_the_debates_that_holds_a_person_is_cleaned_by_the_erasure(conn):
    """A new migration that adds a column with a person's id to a debate table must say so in privacy.py: this fails until it does."""
    found = {(t, c) for t, c in conn.execute(
        """SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name LIKE 'debate%'
           AND column_name IN ('user_id', 'author_id', 'created_by', 'voter_id', 'member_id')""").fetchall()}
    assert found == set(privacy.DEBATE_PERSON_COLUMNS) | {("debates", "created_by")}


def test_the_export_of_a_person_lists_what_they_did_in_debates_and_nothing_of_others(conn):
    _busy_debate(conn)
    mine = privacy.export_person(conn, BOB)["debates"]
    assert len(mine) == 1 and mine[0]["messages_counted"] == 1 and mine[0]["started_by_them"] is False
    assert [p["position"] for p in mine[0]["positions"]] == ["for", "against"] and "votes" not in mine[0]
    assert "unsure" not in str(mine)                                                    # Carol's position is not Bob's
    assert privacy.export_person(conn, ALICE)["debates"][0]["started_by_them"] is True
    assert privacy.export_person(conn, DAN)["debates"] == []


def test_removing_a_server_removes_its_debates_and_only_its_debates(conn):
    mine, other = _busy_debate(conn), opened(conn, by=DAN, guild=999)
    counts = privacy.erase_server(conn, GUILD, source="test")
    assert counts["debates"] == 1 and store.get(conn, mine.id) is None and store.get(conn, other.id) is not None
    assert conn.execute("SELECT count(*) FROM debate_messages").fetchone()[0] == 0


def test_the_retention_deletes_old_closed_debates_and_never_a_running_one(conn):
    old, recent, running = opened(conn, by=ALICE), opened(conn, by=BOB), opened(conn, by=CAROL)
    store.fail(conn, old.id, datetime.now(UTC) - timedelta(days=100))
    store.fail(conn, recent.id, datetime.now(UTC) - timedelta(days=2))
    assert privacy.purge_older_than(conn, 0)["debates"] == 0                            # no retention set: nothing is deleted
    assert privacy.purge_older_than(conn, 30)["debates"] == 1
    assert store.get(conn, old.id) is None and store.get(conn, recent.id) and store.get(conn, running.id)
