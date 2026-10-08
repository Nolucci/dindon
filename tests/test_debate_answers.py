"""Dindon answers first, without the Internet, and the participants judge its answer (docs/regles-du-bot.md, « Répondre d'abord, chercher ensuite »): the answer under the message, Valide and Invalide,
the search on the Internet only where there is more Invalide, and the message corrected with what was found.

Level of proof: SIMULATED. Real PostgreSQL and engine, a fake Discord, and a script for the checker (what the local model answers, what the search finds). Nothing here shows that a real model
knows what it says: that is measured (docs/regles-du-bot.md « Mesure »). Nothing has been posted on a real Discord.
"""
import dataclasses
import json

import pytest

from dindon import privacy
from dindon.debate import answers, claims, stats, store, texts
from dindon.debate.claims import AnswerFound
from gateway_fixtures import BOB, CAROL, GENERAL, GUILD, message_create
from test_bot import event, flush
from test_debate_bot import ALICE_ID, BOB_ID, CAROL_ID, World, button, only_debate, run
from test_debate_checks import EVIDENCE, QUOTE, RESULT, SAYS, FakeChecker, check, info, opened, said

CLAIM = "Le taux de chômage en France est de 12 %"
WRONG = AnswerFound(CLAIM, "le chômage est à 12 %", "taux de chômage France", "false", "Le taux de chômage en France est d'environ 7 %.", "qwen3:14b")
RIGHT = AnswerFound("La Terre tourne autour du Soleil", "la Terre tourne autour du Soleil", "Terre Soleil", "true", None, "qwen3:14b")
UNSURE_SAYS = "La dette publique dépasse 110 % du PIB en France, c'est un fait."
DAN_ID, EVE_ID = 1005, 1006
SUPPORTS = dataclasses.replace(EVIDENCE, stance="supports", quote="le taux de chômage s'établit à 12 % de la population active en 2026")


def local(text):
    """What Dindon is certain of, by what is said: the unemployment claim is false, the Earth claim is true, anything else it is not sure of."""
    return [WRONG] if "chômage" in text else [RIGHT] if "Terre" in text else []


def make(ingest_url, tmp_path, mode="answer", **options):
    checker = FakeChecker(local=local, **options)
    checker.mode = mode
    return World(ingest_url, tmp_path, checker=checker)


@pytest.fixture
def answering(ingest_url, tmp_path):
    return make(ingest_url, tmp_path)


@pytest.fixture
def live(ingest_url, tmp_path):
    return make(ingest_url, tmp_path, "live")


@pytest.fixture
def blind(ingest_url, tmp_path):
    """Dindon answers, but there is no search service."""
    return make(ingest_url, tmp_path, can_search=False)


def title(message):
    return message["embeds"][0]["title"] if message.get("embeds") else ""


def dindon_messages(world, place):
    """(number, message) of what Dindon wrote about its own answers, in the order it was posted: the answer, or what it became after the search."""
    return [(mid, m) for (t, mid), m in sorted(world.discord.messages.items(), key=lambda item: item[0][1]) if t == place and ("Information non fiable" in title(m) or "Dindon a cherché" in title(m) or "Recherche impossible" in title(m))]


def wrong(world, db, content=SAYS, author=BOB):
    """A debate in which somebody says what Dindon is certain is false: it is read, answered and the answer posted. Returns (place, debate, number of the message, number of the answer)."""
    place, debate = opened(world, db)
    message_id = said(world, place, db, author, content)
    assert check(world) is True
    world.tick(seconds=1)
    return place, debate, message_id, db.execute("SELECT max(id) FROM debate_answers").fetchone()[0]


def judge(world, user, place, answer_id, choice):
    world.click(user, place, answer_id, "val", choice)


def row(db, answer_id):
    return db.execute("SELECT verdict, answer, searched_at IS NOT NULL, claim_id IS NOT NULL, shown_at IS NOT NULL FROM debate_answers WHERE id = %s", (answer_id,)).fetchone()


# --- the answer, under the message -----------------------------------------------------------------------------------------


def test_a_claim_that_dindon_is_certain_is_false_is_answered_under_the_message_as_not_reliable_with_one_button_to_verify(answering, ingest_db):
    place, debate, message_id, answer_id = wrong(answering, ingest_db)
    assert row(ingest_db, answer_id) == ("false", WRONG.answer, False, False, False) and answering.checker.searched == [] and claims.unread_count(ingest_db) == 0
    assert ingest_db.execute("SELECT count(*) FROM debate_claims").fetchone()[0] == 0                              # nothing was checked, so nothing is claimed
    [(_, message)] = dindon_messages(answering, place)
    embed = message["embeds"][0]
    assert embed["title"] == "⚠️ Information non fiable" and f"L'affirmation « {CLAIM} » est fausse." in embed["description"] and f"Correction : {WRONG.answer}" in embed["description"]
    assert "**" not in embed["description"] and "sans source" in embed["footer"]["text"] and "elle peut se tromper" in embed["footer"]["text"] and "appuyer sur Vérifier" in embed["footer"]["text"]
    assert message["message_reference"] == {"message_id": str(message_id), "fail_if_not_exists": False} and message["allowed_mentions"] == {"parse": [], "replied_user": False}
    [check_button] = message["components"][0]["components"]
    assert len(message["components"]) == 1 and (check_button["label"], check_button["emoji"]["name"], check_button["custom_id"]) == ("Vérifier", "🔎", f"dindon:debat:val:{answer_id}:check")
    everything = json.dumps(message, ensure_ascii=False).lower()
    for who in ("bobby", "bob", str(BOB_ID), "alice"):
        assert who not in everything, who                                                                         # it names nobody
    answering.tick(seconds=2)
    answering.tick(minutes=5)
    assert len(dindon_messages(answering, place)) == 1                                                              # posted once
    assert ingest_db.execute("SELECT answer_id, posted_message_id IS NOT NULL FROM debate_corrections").fetchone() == (answer_id, True)


def test_a_claim_that_it_is_certain_is_true_is_noted_and_nothing_is_said(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, "La Terre tourne autour du Soleil, c'est établi depuis longtemps.")
    assert check(answering) is True
    answering.tick(seconds=30)
    assert ingest_db.execute("SELECT verdict, answer FROM debate_answers").fetchall() == [("true", None)] and dindon_messages(answering, place) == [] and answering.checker.searched == []


def test_a_claim_that_a_trusted_source_contradicts_is_corrected_as_certain_with_its_quotation_in_answer_mode_too(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, UNSURE_SAYS)
    assert check(answering) is True
    answering.tick(seconds=30)
    assert ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 0 and ingest_db.execute("SELECT verdict FROM debate_claims").fetchall() == [("contradicted",)]
    [message] = answering.discord.posted(place, "Vérification")
    assert dindon_messages(answering, place) == [] and "Sûr" in message["embeds"][0]["footer"]["text"] and "est fausse." in message["embeds"][0]["description"] and "**" not in message["embeds"][0]["description"] and QUOTE in message["embeds"][0]["description"] and "insee.fr" in message["embeds"][0]["description"]


def test_in_observation_dindon_never_answers_it_only_notes_what_the_internet_says(ingest_url, tmp_path, ingest_db):
    observing = make(ingest_url, tmp_path, "observe")
    place, debate = opened(observing, ingest_db)
    said(observing, place, ingest_db, BOB, SAYS)
    assert check(observing) is True
    observing.tick(seconds=30)
    assert ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 0 and dindon_messages(observing, place) == [] and ingest_db.execute("SELECT count(*) FROM debate_claims").fetchone()[0] == 1


def test_a_debate_opened_without_verification_answers_nothing(answering, ingest_db):
    answering.command(ALICE_ID, verify=False)
    place = only_debate(ingest_db).thread_id
    run(answering.debates.tick())
    said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is False and ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 0 and dindon_messages(answering, place) == []


def test_in_a_debate_in_the_channel_the_answer_is_posted_in_the_channel(answering, ingest_db):
    place, debate = opened(answering, ingest_db, thread=False)
    message_id = said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is True
    answering.tick(seconds=1)
    [(_, message)] = dindon_messages(answering, int(GENERAL))
    assert message["message_reference"]["message_id"] == str(message_id) and place == int(GENERAL)


# --- not for everybody, not at any price ---------------------------------------------------------------------------------------


def test_nothing_is_answered_to_somebody_who_stopped_being_recorded_before_it_was_posted(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is True
    privacy.stop_recording(ingest_db, BOB_ID)
    answering.tick(seconds=1)
    assert dindon_messages(answering, place) == []


def test_an_answer_that_waited_more_than_half_an_hour_is_not_posted_any_more(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is True
    answering.tick(minutes=31)
    assert dindon_messages(answering, place) == []


def test_answers_are_spaced_and_a_debate_gets_ten_an_hour_at_most_like_the_corrections(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    for n in range(11):
        said(answering, place, ingest_db, BOB, f"{SAYS} ({n})")
        assert check(answering) is True
    answering.tick(seconds=1)
    assert len(dindon_messages(answering, place)) == 1
    answering.tick(seconds=5)
    assert len(dindon_messages(answering, place)) == 1                                                              # one per tick, and twenty seconds apart
    for _ in range(14):
        answering.tick(seconds=21)
    assert len(dindon_messages(answering, place)) == 10
    answering.tick(minutes=61)
    assert len(dindon_messages(answering, place)) == 10                                                             # the eleventh waited too long: it is not posted late


def test_a_failed_post_is_tried_again_with_growing_waits_posted_once_and_given_up_after_five(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is True
    answering.discord.fail("POST", rf"/channels/{place}/messages", 500, times=2)
    answering.tick(seconds=1)
    answering.tick(seconds=1)
    assert dindon_messages(answering, place) == [] and len(answering.discord.of("POST", f"/channels/{place}/messages")) == 2          # the launch message, and one failed try
    answering.tick(seconds=2)
    answering.tick(seconds=6)
    answering.tick(seconds=2)
    assert len(dindon_messages(answering, place)) == 1
    answering.tick(minutes=2)
    assert len(dindon_messages(answering, place)) == 1


def test_an_answer_that_never_gets_posted_is_given_up(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is True
    answering.discord.fail("POST", rf"/channels/{place}/messages", 500, times=99)
    for _ in range(8):
        answering.tick(seconds=61)
    assert ingest_db.execute("SELECT attempts, retracted_at IS NOT NULL FROM debate_corrections").fetchone() == (5, True)


def test_an_answer_survives_a_restart_and_is_posted_once(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, SAYS)
    assert check(answering) is True
    answering.restart()
    answering.tick(seconds=1)
    answering.restart()
    answering.tick(seconds=30)
    assert len(dindon_messages(answering, place)) == 1


# --- Valide and Invalide ------------------------------------------------------------------------------------------------------------


def test_a_vote_of_the_older_messages_is_recorded_changed_and_counted_and_the_message_takes_the_new_form(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "valid")
    assert "Vote enregistré : ✅ Valide" in answering.sent.last()
    assert answering.sent.calls[-2][2] == {"type": 5, "data": {"flags": 64}}
    assert answering.sent.calls[-1][0] == "PATCH"
    judge(answering, CAROL_ID, place, answer_id, "valid")
    assert "Vous aviez déjà voté ✅ Valide" in answering.sent.last()
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    assert "Vote changé : ❌ Invalide" in answering.sent.last() and answers.counts(ingest_db, answer_id) == (0, 1)
    judge(answering, DAN_ID, place, answer_id, "valid")
    answering.tick(seconds=6)
    [(_, message)] = dindon_messages(answering, place)
    assert [b["label"] for b in message["components"][0]["components"]] == ["Vérifier"]                                # the votes of the older messages still count; the message no longer shows them
    assert ingest_db.execute("SELECT count(*) FROM debate_answer_votes").fetchone()[0] == 2                          # one vote each, the last one


def test_a_double_click_a_malformed_button_and_an_answer_that_does_not_exist_are_dealt_with(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    custom_id = texts.custom_id("val", answer_id, "valid")
    run(answering.interactions.answer(button(CAROL_ID, place, custom_id)))
    run(answering.interactions.answer(button(CAROL_ID, place, custom_id)))
    assert "Un instant" in answering.sent.last() and ingest_db.execute("SELECT count(*) FROM debate_answer_votes").fetchone()[0] == 1
    count = len(answering.sent.calls)
    for malformed in ("dindon:debat:val:x:valid", "dindon:debat:val:1:maybe", "dindon:debat:val:1", "dindon:debat:val::valid"):
        run(answering.interactions.answer(button(DAN_ID, place, malformed)))
    assert len(answering.sent.calls) == count
    judge(answering, DAN_ID, place, answer_id + 999, "invalid")
    assert "n'existe plus" in answering.sent.last()


def test_somebody_who_stopped_being_recorded_cannot_vote_and_their_earlier_vote_no_longer_counts(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    privacy.stop_recording(ingest_db, CAROL_ID)
    assert answers.counts(ingest_db, answer_id) == (0, 0)
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    assert "ne pas être enregistré" in answering.sent.last()
    assert check(answering) is False and answering.checker.searched == []


def test_nobody_can_vote_once_the_debate_is_over(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    answering.click(ALICE_ID, place, debate.id, "end", "now", permissions=8)
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    assert "Ce débat est terminé" in answering.sent.last() and ingest_db.execute("SELECT count(*) FROM debate_answer_votes").fetchone()[0] == 0


# --- more Valide: nothing more; more Invalide: the Internet -------------------------------------------------------------------------


def test_with_more_valide_than_invalide_dindon_goes_no_further(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "valid")
    assert check(answering) is False and answering.checker.searched == []
    judge(answering, DAN_ID, place, answer_id, "invalid")
    judge(answering, EVE_ID, place, answer_id, "valid")
    assert check(answering) is False and answering.checker.searched == [] and row(ingest_db, answer_id)[2] is False


def test_with_as_many_valide_as_invalide_dindon_does_not_search_either(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "valid")
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is False and answering.checker.searched == [] and answers.searches_due(ingest_db) == []


def test_with_more_invalide_than_valide_dindon_looks_on_the_internet_once_and_corrects_its_own_message(answering, ingest_db):
    place, debate, message_id, answer_id = wrong(answering, ingest_db)
    answering.discord.calls.clear()
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is True
    [asked] = answering.checker.searched
    assert (asked.claim, asked.said, asked.query) == (CLAIM, WRONG.said, WRONG.query)                                  # the neutral phrase stored with the answer: never the message
    assert row(ingest_db, answer_id) == ("false", WRONG.answer, True, True, False)
    assert ingest_db.execute("SELECT verdict FROM debate_claims").fetchall() == [("contradicted",)] and ingest_db.execute("SELECT count(*) FROM debate_sources").fetchone()[0] == 1
    answering.tick(seconds=1)
    [(posted, message)] = dindon_messages(answering, place)
    embed = message["embeds"][0]
    assert embed["title"] == "🔎 Dindon a cherché sur Internet" and "contredisent" in embed["description"] and "peut aussi contenir des erreurs" in embed["description"]
    assert QUOTE in embed["description"] and "insee.fr" in embed["description"] and f"*Ma première réponse, sans recherche : {WRONG.answer}*" in embed["description"]
    assert [b["url"] for b in message["components"][0]["components"]] == [EVIDENCE.url] and [b["style"] for b in message["components"][0]["components"]] == [5]      # links, no more votes
    assert row(ingest_db, answer_id)[4] is True and [c[0] for c in answering.discord.calls if c[0] == "POST"] == []   # the same message was written again, no new one
    assert message["allowed_mentions"] == {"parse": [], "replied_user": False} and (place, posted) in answering.discord.messages
    answering.tick(minutes=5)
    assert check(answering) is False and len(answering.checker.searched) == 1                                         # searched once, shown once


def test_a_vote_that_goes_from_valide_to_invalide_makes_dindon_search_at_that_moment_and_not_before(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "valid")
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is False
    judge(answering, EVE_ID, place, answer_id, "invalid")
    assert check(answering) is True and len(answering.checker.searched) == 1


def test_the_author_may_judge_dindon_s_answer_like_anybody_else(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, BOB_ID, place, answer_id, "invalid")
    assert check(answering) is True and len(answering.checker.searched) == 1


def test_a_vote_after_the_search_is_told_that_dindon_already_looked(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is True
    answering.tick(seconds=1)
    judge(answering, EVE_ID, place, answer_id, "valid")
    assert "a déjà cherché sur Internet" in answering.sent.last() and ingest_db.execute("SELECT count(*) FROM debate_answer_votes").fetchone()[0] == 1


def test_a_search_that_the_participants_asked_for_survives_a_restart(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    answering.restart()
    run(answering.debates.tick())
    assert check(answering) is True and len(answering.checker.searched) == 1


def test_no_search_is_made_in_a_debate_that_is_over(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    answering.click(ALICE_ID, place, debate.id, "end", "now", permissions=8)
    assert check(answering) is False and answering.checker.searched == [] and row(ingest_db, answer_id)[2] is False


def test_the_searches_share_the_hourly_budget_of_the_debate(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    for n in range(claims.MAX_CHECKS_PER_HOUR):
        ingest_db.execute("INSERT INTO debate_claims (debate_id, message_id, author_id, claim, said, verdict, checked_at) VALUES (%s, %s, %s, 'Une affirmation', 'une affirmation', 'confirmed', %s)",
                          (debate.id, 10_000 + n, CAROL_ID, answering.time.now()))
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is False and answering.checker.searched == []
    answering.time.advance(minutes=61)
    assert check(answering) is True and len(answering.checker.searched) == 1


# --- « Vérifier »: one click, a deeper search, the message corrected --------------------------------------------------------------------


def test_the_button_verifier_makes_dindon_search_deeper_once_and_write_the_result_in_its_own_message(answering, ingest_db):
    place, debate, message_id, answer_id = wrong(answering, ingest_db)
    answering.discord.calls.clear()
    judge(answering, DAN_ID, place, answer_id, "check")
    assert "Vérification demandée" in answering.sent.last() and answering.sent.calls[-2][2] == {"type": 5, "data": {"flags": 64}}
    answering.tick(seconds=6)
    [(_, waiting)] = dindon_messages(answering, place)
    assert [(b["label"], b.get("disabled")) for b in waiting["components"][0]["components"]] == [("Vérification en cours…", True)]               # nobody can press it twice
    assert ingest_db.execute("SELECT search_requested_at IS NOT NULL, searched_at IS NOT NULL FROM debate_answers WHERE id = %s", (answer_id,)).fetchone() == (True, False)
    assert check(answering) is True
    [asked] = answering.checker.searched
    assert (asked.claim, asked.said, asked.query) == (CLAIM, WRONG.said, WRONG.query) and answering.checker.deep == [True]                            # the neutral phrase, and the deeper search
    answering.tick(seconds=1)
    [(posted, message)] = dindon_messages(answering, place)
    embed = message["embeds"][0]
    assert embed["title"] == "🔎 Dindon a cherché sur Internet" and "contredisent" in embed["description"] and QUOTE in embed["description"]
    assert [b["style"] for b in message["components"][0]["components"]] == [5] and row(ingest_db, answer_id)[2:] == (True, True, True)                  # links only: no button « Vérifier » any more
    assert [c[0] for c in answering.discord.calls if c[0] == "POST"] == []
    answering.tick(minutes=5)
    assert check(answering) is False and len(answering.checker.searched) == 1


def test_a_second_click_on_verifier_is_told_that_the_check_is_on_its_way_and_does_not_search_again(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "check")
    judge(answering, EVE_ID, place, answer_id, "check")
    assert "déjà en cours" in answering.sent.last()
    assert check(answering) is True and check(answering) is False and len(answering.checker.searched) == 1
    answering.tick(seconds=1)
    judge(answering, CAROL_ID, place, answer_id, "check")
    assert "a déjà cherché sur Internet" in answering.sent.last()


def test_verifier_is_refused_when_the_answer_is_gone_the_debate_is_over_or_the_person_asked_not_to_be_recorded(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id + 999, "check")
    assert "n'existe plus" in answering.sent.last()
    privacy.stop_recording(ingest_db, CAROL_ID)
    judge(answering, CAROL_ID, place, answer_id, "check")
    assert "ne pas être enregistré" in answering.sent.last() and check(answering) is False and answering.checker.searched == []
    answering.click(ALICE_ID, place, debate.id, "end", "now", permissions=8)
    judge(answering, EVE_ID, place, answer_id, "check")
    assert "Ce débat est terminé" in answering.sent.last() and answering.checker.searched == []


def test_a_check_that_somebody_asked_for_survives_a_restart(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "check")
    answering.restart()
    run(answering.debates.tick())
    assert check(answering) is True and len(answering.checker.searched) == 1


def test_an_answer_that_rests_on_pages_shows_them_as_not_official_and_says_that_it_is_a_first_opinion(answering, ingest_db):
    pages = dataclasses.replace(RESULT, verdict="likely_false", evidence=(dataclasses.replace(EVIDENCE, tier="other", url="https://blog.example/chomage"),))
    answering.checker.local = lambda text: [dataclasses.replace(WRONG, answer="D'après une page qui n'est pas une source de confiance : « 7,3 % »", basis="pages", result=pages)]
    place, debate, _, answer_id = wrong(answering, ingest_db)
    assert ingest_db.execute("SELECT basis, claim_id IS NOT NULL, searched_at IS NOT NULL FROM debate_answers WHERE id = %s", (answer_id,)).fetchone() == ("pages", True, False)
    assert ingest_db.execute("SELECT verdict FROM debate_claims").fetchall() == [("likely_false",)] and answering.discord.posted(place, "Vérification") == []   # provisional: never a correction
    [(_, message)] = dindon_messages(answering, place)
    description = message["embeds"][0]["description"]
    assert "probablement fausse" in description and "pas une source de confiance" in description and "Vérifier" in message["embeds"][0]["footer"]["text"]
    assert [b["label"] for b in message["components"][0]["components"]] == ["Vérifier"]


def test_an_answer_of_the_model_shows_the_pages_that_the_first_search_found_against_the_claim_marked_as_not_official(answering, ingest_db):
    pages = dataclasses.replace(RESULT, verdict="likely_false", evidence=(dataclasses.replace(EVIDENCE, tier="other", url="https://blog.example/chomage"),))
    answering.checker.local = lambda text: [dataclasses.replace(WRONG, result=pages)]
    place, debate, _, answer_id = wrong(answering, ingest_db)
    [(_, message)] = dindon_messages(answering, place)
    description = message["embeds"][0]["description"]
    assert WRONG.answer in description and "non officielles" in description and QUOTE in description and "blog.example" in description
    assert [b.get("url") for row_ in message["components"] for b in row_["components"]] == [None, "https://blog.example/chomage"]


# --- what the search found, whatever it is -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("found", "words", "source"), [
    (dataclasses.replace(RESULT, verdict="contradicted"), ["contredisent", "peut aussi contenir des erreurs"], QUOTE),
    (dataclasses.replace(RESULT, verdict="confirmed", evidence=(SUPPORTS,)), ["confirment", "ma réponse était fausse"], SUPPORTS.quote),
    (dataclasses.replace(RESULT, verdict="partly", evidence=(dataclasses.replace(EVIDENCE, stance="partly"),)), ["en partie", "trop catégorique"], QUOTE),
    (dataclasses.replace(RESULT, verdict="disputed", evidence=(EVIDENCE, SUPPORTS)), ["se contredisent", "ne peux pas trancher"], SUPPORTS.quote),
    (dataclasses.replace(RESULT, verdict="unverifiable", reason="no_source", evidence=()), ["pas trouvé de source de confiance", "non fiable"], None),
])
def test_whatever_the_search_finds_dindon_says_it_in_its_own_message_even_that_it_was_wrong(answering, ingest_db, found, words, source):
    answering.checker.search_result = found
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is True
    answering.tick(seconds=1)
    [(_, message)] = dindon_messages(answering, place)
    description = message["embeds"][0]["description"]
    assert all(w in description for w in words) and (source is None or source in description) and f"Ma première réponse, sans recherche : {WRONG.answer}" in description
    assert "Affirmation" in description and message["embeds"][0]["footer"]["text"].startswith("Dindon ne prend pas parti")


def test_without_a_search_service_dindon_says_that_it_cannot_look_and_that_its_answer_stays_without_a_source(blind, ingest_db):
    place, debate, _, answer_id = wrong(blind, ingest_db)
    judge(blind, DAN_ID, place, answer_id, "invalid")
    assert check(blind) is True
    blind.tick(seconds=1)
    [(_, message)] = dindon_messages(blind, place)
    assert "ne peux pas chercher sur Internet" in message["embeds"][0]["description"] and "sans source" in message["embeds"][0]["description"] and message["components"] == []
    assert message["embeds"][0]["title"] == "🔎 Recherche impossible"
    assert row(ingest_db, answer_id) == ("false", WRONG.answer, True, False, True) and blind.checker.searched == [] and ingest_db.execute("SELECT count(*) FROM debate_claims").fetchone()[0] == 0


def test_a_message_that_could_not_be_rewritten_is_tried_again_and_the_search_is_not_made_twice(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is True
    answering.discord.fail("PATCH", rf"/channels/{place}/messages/\d+", 500, times=1)
    answering.tick(seconds=1)
    assert row(ingest_db, answer_id)[4] is False
    answering.tick(seconds=3)
    assert row(ingest_db, answer_id)[4] is True and len(answering.checker.searched) == 1 and "Dindon a cherché" in title(dindon_messages(answering, place)[0][1])


# --- live: the corrections that sources make by themselves are not doubled ----------------------------------------------------


def test_in_live_mode_the_claim_that_the_participants_sent_to_the_internet_is_not_corrected_a_second_time(live, ingest_db):
    place, debate, _, answer_id = wrong(live, ingest_db)
    judge(live, DAN_ID, place, answer_id, "invalid")
    assert check(live) is True
    live.tick(seconds=1)
    live.tick(seconds=30)
    assert live.discord.posted(place, "Vérification") == [] and len(dindon_messages(live, place)) == 1               # one message: the answer, written again


def test_in_live_mode_what_dindon_cannot_answer_is_still_corrected_by_the_sources_by_themselves(live, ingest_db):
    place, debate = opened(live, ingest_db)
    said(live, place, ingest_db, BOB, UNSURE_SAYS)
    assert check(live) is True
    live.tick(seconds=1)
    assert len(live.discord.posted(place, "Vérification")) == 1 and dindon_messages(live, place) == []


# --- when the message goes -----------------------------------------------------------------------------------------------------------


def test_when_the_message_is_edited_dindon_s_answer_goes_and_the_message_is_read_again(answering, ingest_db):
    place, debate, message_id, answer_id = wrong(answering, ingest_db)
    [(old, _)] = dindon_messages(answering, place)
    edited = message_create(message_id, "Finalement le chômage est à 7,3 % en France, j'avais tort.", BOB, channel_id=str(place), edited_timestamp="2026-10-05T12:05:00.000000+00:00")
    answering.runner.handle(event("MESSAGE_UPDATE", edited))
    flush(answering.runner)
    answering.tick(seconds=1)
    assert ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 0 and (place, old) not in answering.discord.messages
    assert ingest_db.execute("SELECT answer_id IS NULL, retracted_at IS NOT NULL FROM debate_corrections").fetchone() == (True, True)


def test_when_the_message_is_deleted_dindon_s_answer_goes_with_it_even_after_a_search(answering, ingest_db):
    place, debate, message_id, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    assert check(answering) is True
    answering.tick(seconds=1)
    assert len(dindon_messages(answering, place)) == 1
    answering.runner.handle(event("MESSAGE_DELETE", {"id": str(message_id), "channel_id": str(place), "guild_id": GUILD}))
    flush(answering.runner)
    answering.tick(seconds=1)
    assert dindon_messages(answering, place) == [] and ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 0
    assert ingest_db.execute("SELECT count(*) FROM debate_claims").fetchone()[0] == 0 and ingest_db.execute("SELECT count(*) FROM debate_answer_votes").fetchone()[0] == 0


def test_when_the_author_is_erased_the_answer_about_their_claim_is_deleted_from_discord(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "valid")
    counts = privacy.erase_person(ingest_db, BOB_ID, source="test")
    assert counts["debate_traces"] >= 2 and ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 0
    answering.tick(seconds=1)
    assert dindon_messages(answering, place) == []


def test_somebody_who_votes_and_is_erased_takes_their_vote_back_and_the_answer_stays(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    privacy.erase_person(ingest_db, CAROL_ID, source="test")
    assert answers.counts(ingest_db, answer_id) == (0, 0) and ingest_db.execute("SELECT count(*) FROM debate_answers").fetchone()[0] == 1
    assert check(answering) is False and answering.checker.searched == []


def test_a_person_can_read_what_dindon_answered_to_them_and_how_they_voted_and_nothing_of_others(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    judge(answering, DAN_ID, place, answer_id, "valid")
    [bob] = privacy.export_person(ingest_db, BOB_ID)["debates"]
    assert bob["answers_to_them"] == [{"claim": CLAIM, "said": WRONG.said, "answer": WRONG.answer, "verdict": "false", "valid": 1, "invalid": 1, "searched": False}] and bob["votes_on_answers"] == []
    [carol] = privacy.export_person(ingest_db, CAROL_ID)["debates"]
    assert carol["answers_to_them"] == [] and [v["choice"] for v in carol["votes_on_answers"]] == ["invalid"] and CLAIM not in json.dumps(carol)     # (what somebody else said is not theirs to export)
    assert privacy.export_person(ingest_db, EVE_ID)["debates"] == []


# --- the statistics, the page, what the members are told ---------------------------------------------------------------------


def test_the_statistics_count_what_dindon_answered_how_it_was_judged_and_how_often_it_searched(answering, ingest_db):
    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, CAROL_ID, place, answer_id, "invalid")
    judge(answering, DAN_ID, place, answer_id, "invalid")
    judge(answering, EVE_ID, place, answer_id, "valid")
    assert check(answering) is True
    found = stats.collect(ingest_db, debate.id)
    assert found["totals"]["answers"] == {"true": 0, "false": 1, "valid": 1, "invalid": 2, "searched": 1}
    [given] = found["answers"]
    assert (given["claim"], given["verdict"], given["answer"], given["valid"], given["invalid"], given["searched"], given["found"], given["posted"]) == (CLAIM, "false", WRONG.answer, 1, 2, True, "contradicted", True)
    answering.click(ALICE_ID, place, debate.id, "end", "now", permissions=8)
    answering.tick(seconds=1)
    [closing] = answering.discord.posted(place, "Débat terminé")
    assert "Dindon a répondu à **1** affirmation(s) sans chercher sur Internet : 1 vote(s) Valide, 2 vote(s) Invalide, **1** recherche(s) sur Internet ensuite." in closing["embeds"][0]["description"]


def test_a_debate_where_dindon_answered_nothing_says_nothing_of_answers_and_no_longer_claims_that_nothing_was_checked_when_it_answered(answering, ingest_db):
    place, debate = opened(answering, ingest_db)
    said(answering, place, ingest_db, BOB, "La Terre tourne autour du Soleil, c'est établi depuis longtemps.")
    assert check(answering) is True
    answering.click(ALICE_ID, place, debate.id, "end", "now", permissions=8)
    answering.tick(seconds=1)
    text = answering.discord.posted(place, "Débat terminé")[0]["embeds"][0]["description"]
    assert "Dindon a répondu" not in text and "Aucune affirmation de fait n'a été vérifiée" not in text


def test_the_members_are_told_what_dindon_does_in_each_mode(answering, ingest_db):
    place, _ = opened(answering, ingest_db)
    assert texts.notice_short("answer") in answering.discord.posted(place)[0]["embeds"][0]["description"]
    first, second = info(answering)
    assert second[2]["content"] == f"**{texts.NOTICE_TITLE}.** {texts.NOTICE_ANSWER}" and len(second[2]["content"]) < 2000
    for notice in (texts.NOTICE_ANSWER, texts.NOTICE_LOCAL):
        assert len(notice) <= 1024 and "non fiable" in notice and "ne prend pas parti" in notice                                                     # (a field of an embed holds 1024)
    assert "Vérifier" in texts.NOTICE_ANSWER and "il peut se tromper" in texts.NOTICE_LOCAL
    assert "sur Internet" in texts.NOTICE_ANSWER and "Dindon ne cherche rien sur Internet" in texts.NOTICE_LOCAL and "phrase neutre" in texts.NOTICE_ANSWER and "phrase neutre" not in texts.NOTICE_LOCAL
    assert texts.notice("answer") == texts.NOTICE_ANSWER and texts.notice("local") == texts.NOTICE_LOCAL and texts.notice("live") == texts.NOTICE_LIVE and texts.notice("observe") == texts.NOTICE
    assert texts.notice(True) == texts.NOTICE_LIVE and texts.notice(False) == texts.NOTICE and texts.notice("anything") == texts.NOTICE


@pytest.mark.parametrize(("mode", "must_say"), [("observe", "phrase neutre"), ("answer", "non fiable"), ("local", "ne cherche rien sur Internet"), ("live", "source de confiance")])
def test_the_launch_message_says_in_one_line_what_dindon_does_and_the_whole_text_is_in_dindon_info(ingest_db, mode, must_say):
    debate = store.start(ingest_db, guild_id=1, channel_id=2, topic="Un sujet de débat", created_by=ALICE_ID, now=None)
    description = texts.question(debate, {"for": 0, "unsure": 0, "against": 0}, verifying=True, live=mode)["embeds"][0]["description"]
    lines = [line for line in description.split("\n") if line]
    assert len(lines) == 3 and lines[0] == "**Un sujet de débat**"                                                 # the subject, then the two lines: the buttons and the end, what Dindon does
    assert lines[1].startswith("Prenez position avec les boutons") and "Voter la fin" in lines[1] and "après 1 jour sans message" in lines[1]
    assert lines[2] == texts.notice_short(mode) and must_say in lines[2] and "/dindon info" in lines[2] and len(lines[2]) < 260 and "fields" not in texts.question(debate, {}, verifying=True, live=mode)["embeds"][0]
    open_in_the_channel = store.start(ingest_db, guild_id=1, channel_id=3, topic="Un autre sujet", created_by=BOB_ID, in_thread=False, now=None)
    assert len([line for line in texts.question(open_in_the_channel, {}, verifying=True, live=mode)["embeds"][0]["description"].split("\n") if line]) == 4      # (plus the warning that the channel is read)
    unchecked = store.start(ingest_db, guild_id=1, channel_id=4, topic="Sans vérification", created_by=CAROL_ID, verify=False, now=None)
    assert len([line for line in texts.question(unchecked, {}, verifying=True, live=mode)["embeds"][0]["description"].split("\n") if line]) == 2             # nothing said of what it does not do


def test_what_dindon_says_fits_discord_whatever_the_claim_and_never_mentions_anybody():
    long = "x" * 480
    message = texts.local_answer(long, "y" * 400, 7, 99, [dataclasses.replace(EVIDENCE, quote="q" * 300)] * 5)
    assert len(message["embeds"][0]["description"]) <= 4000 and all(len(b["label"]) <= 80 for row in message["components"] for b in row["components"]) and message["allowed_mentions"]["parse"] == []
    mention = texts.local_answer("@everyone **gras** [lien](http://x)", "<@123> a tort", 7, 99)
    assert "\\*\\*gras\\*\\*" in mention["embeds"][0]["description"] and mention["allowed_mentions"] == {"parse": [], "replied_user": False}
    after = texts.after_search("@everyone " + long, "z" * 400, "contradicted", "T2 2026", [EVIDENCE] * 5)
    assert len(after["embeds"][0]["description"]) <= 4000 and len(after["components"][0]["components"]) == 3 and after["allowed_mentions"]["parse"] == []
    assert texts.after_search("c", "r", "unverifiable", None, [EVIDENCE])["components"] == []                      # nothing settles it: no link to click
    assert texts.parse_custom_id("dindon:debat:val:12:valid") == ("val", 12, "valid") and texts.parse_custom_id("dindon:debat:val:12:for") is None
    assert texts.parse_custom_id("dindon:debat:val:12:check") == ("val", 12, "check")


def test_the_page_of_the_owner_lists_what_dindon_answered(ingest_url, tmp_path, answering, ingest_db):
    from fastapi.testclient import TestClient

    from dindon.api.main import create_app
    from synthetic import settings_for

    place, debate, _, answer_id = wrong(answering, ingest_db)
    judge(answering, DAN_ID, place, answer_id, "invalid")
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, "correct horse"), debate_checks="answer", searxng_url="http://searxng:8080")
    with TestClient(create_app(settings, background=False)) as client:
        assert client.post("/api/login", json={"password": "correct horse"}).status_code == 200
        overview = client.get("/api/debates").json()
        detail = client.get(f"/api/debates/{debate.id}").json()
    assert overview["checks"]["mode"] == "answer" and overview["checks"]["why_not"] is None
    assert detail["totals"]["answers"] == {"true": 0, "false": 1, "valid": 0, "invalid": 1, "searched": 0}
    assert [(a["claim"], a["answer"], a["valid"], a["invalid"]) for a in detail["answers"]] == [(CLAIM, WRONG.answer, 0, 1)] and "bob" not in json.dumps(detail["answers"]).lower()
