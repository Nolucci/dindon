"""The verdict of a debate: rating out of 10, the window, and the final score (50 % ratings, 50 % Dindon's analysis). Level of proof: SIMULATED (real PostgreSQL, invented people, a clock moved by hand)."""
from decimal import Decimal

import pytest

from dindon.debate import ratings, rules, store
from test_debate import ALICE, BOB, CAROL, DAN, EVE, T0, at, conn, opened, refused  # noqa: F401


def finished(conn, **positions):
    """A debate with the given positions, ended by its camps (Bob and Dan, the two only people of the smaller camp, ask to end)."""
    debate = opened(conn)
    for user, position in positions.items():
        store.set_position(conn, debate.id, {"alice": ALICE, "bob": BOB, "carol": CAROL, "dan": DAN, "eve": EVE}[user], position, at(minutes=1))
    return debate


def close(conn, debate, minutes=10):
    return store.end(conn, debate.id, rules.ENDED, at(minutes=minutes))


def test_a_score_is_a_number_from_0_to_10_with_two_decimals():
    assert ratings.parse_score("7,5") == Decimal("7.50") and ratings.parse_score(" 8.256 ") == Decimal("8.26") and ratings.parse_score("10") == Decimal("10.00")
    assert all(ratings.parse_score(x) is None for x in ("", "11", "10,01", "-1", "abc", "7,5,2", None))


def test_a_debate_where_nobody_took_part_or_that_failed_has_nothing_to_rate(conn):
    debate = opened(conn)
    assert close(conn, debate).rating_ends_at is None


def test_everybody_who_took_a_position_rates_the_participants_except_themselves_during_the_window(conn):
    debate = finished(conn, alice="for", bob="against", carol="witness")
    closed = close(conn, debate)
    assert closed.rating_ends_at == at(minutes=10, seconds=rules.RATING_SECONDS)
    assert ratings.rate(conn, debate.id, CAROL, ALICE, Decimal("7.5"), at(minutes=11)) == "recorded"          # a witness rates
    assert ratings.rate(conn, debate.id, CAROL, ALICE, Decimal("8"), at(minutes=12)) == "changed"
    refused(lambda: ratings.rate(conn, debate.id, ALICE, ALICE, Decimal("10"), at(minutes=11)), "self")
    refused(lambda: ratings.rate(conn, debate.id, DAN, ALICE, Decimal("5"), at(minutes=11)), "not_voter")        # never took a position
    refused(lambda: ratings.rate(conn, debate.id, ALICE, CAROL, Decimal("5"), at(minutes=11)), "not_target")     # a witness is not rated
    refused(lambda: ratings.rate(conn, debate.id, BOB, ALICE, Decimal("5"), at(minutes=10, seconds=rules.RATING_SECONDS)), "rating_over")
    assert ratings.given(conn, debate.id, CAROL) == {ALICE: Decimal("8.00")}


def test_nobody_rates_a_debate_that_is_still_open(conn):
    debate = finished(conn, alice="for", bob="against")
    refused(lambda: ratings.rate(conn, debate.id, ALICE, BOB, Decimal("5"), at(minutes=2)), "not_rating")


def test_the_final_score_is_half_the_average_of_the_ratings_and_half_dindons_analysis(conn):
    debate = finished(conn, alice="for", bob="against", carol="witness")
    close(conn, debate)
    ratings.rate(conn, debate.id, BOB, ALICE, Decimal("4"), at(minutes=11))
    ratings.rate(conn, debate.id, CAROL, ALICE, Decimal("9"), at(minutes=11))
    ratings.rate(conn, debate.id, ALICE, BOB, Decimal("10"), at(minutes=11))
    assert ratings.due(conn, at(minutes=12)) == []
    assert ratings.due(conn, at(minutes=10, seconds=rules.RATING_SECONDS)) == [debate.id]
    found = {r["user_id"]: r for r in ratings.finalize(conn, debate.id)}
    # nothing was checked and nobody has roles: the three parts are neutral, the analysis is 5
    assert found[ALICE]["ai"] == Decimal("5.00") and found[ALICE]["vote"] == Decimal("6.50") and found[ALICE]["votes"] == 2
    assert found[ALICE]["final"] == Decimal("5.75") and found[BOB]["final"] == Decimal("7.50")
    assert [r["user_id"] for r in ratings.finalize(conn, debate.id)] == [BOB, ALICE]                         # asking again changes nothing
    assert found[BOB]["winner"] and not found[ALICE]["winner"]


def test_without_any_rating_the_analysis_counts_alone(conn):
    debate = finished(conn, alice="for", bob="against")
    close(conn, debate)
    found = ratings.finalize(conn, debate.id)
    assert all(r["vote"] is None and r["final"] == r["ai"] == Decimal("5.00") and r["winner"] for r in found)    # a tie is shared


def test_the_analysis_rewards_sourced_claims_and_claims_that_held(conn):
    debate = finished(conn, alice="for", bob="against")
    for author, verdict, sourced in ((ALICE, "confirmed", True), (ALICE, "confirmed", True), (BOB, "confirmed", True), (BOB, "contradicted", False)):
        claim = conn.execute("INSERT INTO debate_claims (debate_id, message_id, author_id, claim, said, verdict) VALUES (%s, 1, %s, 'une affirmation', 'une affirmation', %s) RETURNING id",
                             (debate.id, author, verdict)).fetchone()[0]
        if sourced:
            conn.execute("INSERT INTO debate_sources (claim_id, url, tier, stance, quote, sha256) VALUES (%s, 'https://insee.fr/x', 'official', 'supports', %s, 'abc')",
                         (claim, "une citation exacte de la page qui fait plus de vingt-cinq caractères"))
    close(conn, debate)
    found = ratings.analysis(conn, debate.id, [ALICE, BOB])
    assert (found[ALICE]["sources"], found[BOB]["sources"]) == (Decimal("10.00"), Decimal("5.00"))
    assert (found[ALICE]["logic"], found[BOB]["logic"]) == (Decimal("10.00"), Decimal("5.00"))
    assert found[ALICE]["score"] > found[BOB]["score"]
