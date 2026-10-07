"""Witnesses and the end of a debate by its camps (docs/regles-du-bot.md). Level of proof: SIMULATED (a real PostgreSQL, invented people, a clock moved by hand)."""
import pytest

from dindon.debate import rules, store
from test_debate import ALICE, BOB, CAROL, DAN, EVE, at, conn, opened, refused, speak  # noqa: F401


def take(conn, debate, user, position, minutes=1):
    return store.set_position(conn, debate.id, user, position, at(minutes=minutes))


def test_only_those_who_took_a_position_take_part_and_a_witness_does_not(conn):
    debate = opened(conn)
    take(conn, debate, ALICE, "for")
    take(conn, debate, BOB, "unsure")
    take(conn, debate, CAROL, "witness")
    speak(conn, debate, DAN, witness=True)                       # wrote without a position: not a participant either
    assert store.participants(conn, debate.id) == {ALICE, BOB}
    assert store.witnesses(conn, debate.id) == {CAROL}
    assert store.position_counts(conn, debate.id) == {"for": 1, "unsure": 1, "against": 0, "witness": 1}


def test_the_messages_of_a_witness_are_kept_marked_and_never_read_for_the_debate(conn):
    debate = opened(conn, verify=True)
    take(conn, debate, ALICE, "for")
    take(conn, debate, CAROL, "witness")
    assert store.record_message(conn, debate.id, message_id=1, author_id=ALICE, sent_at=at(minutes=2), to_read=True)
    assert store.record_message(conn, debate.id, message_id=2, author_id=CAROL, sent_at=at(minutes=2), to_read=True)
    rows = dict(conn.execute("SELECT author_id, witness FROM debate_messages WHERE debate_id = %s", (debate.id,)).fetchall())
    assert rows == {ALICE: False, CAROL: True}
    unread = {r[0] for r in conn.execute("SELECT author_id FROM debate_messages WHERE debate_id = %s AND read_at IS NULL", (debate.id,)).fetchall()}
    assert unread == {ALICE}


def test_a_witness_cannot_end_the_debate_nor_somebody_without_a_position(conn):
    debate = opened(conn)
    take(conn, debate, ALICE, "for")
    take(conn, debate, CAROL, "witness")
    refused(lambda: store.request_end(conn, debate.id, CAROL, at(minutes=3)), "not_participant")
    refused(lambda: store.request_end(conn, debate.id, DAN, at(minutes=3)), "not_participant")


def test_the_debate_ends_when_most_of_the_smallest_camp_asks(conn):
    debate = opened(conn)
    for user, position in ((ALICE, "for"), (BOB, "for"), (CAROL, "for"), (DAN, "against"), (EVE, "against")):
        take(conn, debate, user, position)
    assert store.request_end(conn, debate.id, CAROL, at(minutes=5)) == ("recorded", None)           # the big camp does not decide
    assert store.request_end(conn, debate.id, DAN, at(minutes=6)) == ("recorded", None)             # 1 of 2: not a majority yet
    assert store.end_votes(conn, debate.id) == (1, 2)
    assert store.request_end(conn, debate.id, DAN, at(minutes=7)) == ("unchanged", None)
    result, closed = store.request_end(conn, debate.id, EVE, at(minutes=8))
    assert result == "recorded" and closed.status == "closed" and closed.close_reason == rules.AGREED


def test_a_camp_that_empties_after_both_existed_ends_the_debate(conn):
    debate = opened(conn)
    take(conn, debate, ALICE, "for")
    take(conn, debate, BOB, "against")
    take(conn, debate, CAROL, "against")
    take(conn, debate, ALICE, "witness", 5)                       # the only « pour » leaves: 0 against 2
    assert store.get(conn, debate.id).close_reason == rules.ONE_SIDED


def test_one_person_changing_sides_alone_does_not_end_a_debate_that_never_had_two_camps(conn):
    debate = opened(conn)
    take(conn, debate, ALICE, "for")
    take(conn, debate, ALICE, "against", 2)
    assert store.get(conn, debate.id).status == "open"


def test_a_vote_to_end_is_taken_back_when_the_person_changes_camp(conn):
    debate = opened(conn)
    for user, position in ((ALICE, "for"), (BOB, "for"), (CAROL, "against"), (DAN, "against")):
        take(conn, debate, user, position)
    store.request_end(conn, debate.id, CAROL, at(minutes=5))
    take(conn, debate, CAROL, "for", 6)
    assert conn.execute("SELECT count(*) FROM debate_end_votes WHERE debate_id = %s", (debate.id,)).fetchone()[0] == 0
