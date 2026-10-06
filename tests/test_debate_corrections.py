"""The public corrections (docs/regles-du-bot.md « Corrections publiques », step D5): what Dindon says when trusted sources contradict a claim, what it never says, and how it takes it back.

Level of proof: SIMULATED, like test_debate_checks.py: the real engine, ingestion and database, a fake Discord in memory, a script for the checker. Nothing has been posted on a real Discord.
"""
import dataclasses
import json
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from dindon import privacy
from dindon.bot.privacy_commands import PrivacyService
from dindon.bot.runner import build_interactions
from dindon.debate import claims, texts
from dindon.debate.checker import build_checker, resolve_mode
from dindon.debate.claims import ClaimResult, Evidence
from gateway_fixtures import BOB, CAROL, GENERAL, GUILD, message_create
from synthetic import settings_for
from test_bot import event, flush
from test_debate_bot import BOB_ID, CAROL_ID, World, run
from test_debate_checks import EVIDENCE, QUOTE, RESULT, SAYS, FakeChecker, check, claims_in, info, opened, said

TITLE = "🔎 Vérification"


def corrections(world, thread):
    return world.discord.posted(thread, "Vérification")


@pytest.fixture
def live(ingest_url, tmp_path):
    checker = FakeChecker()
    checker.mode = "live"
    return World(ingest_url, tmp_path, checker=checker)


@pytest.fixture
def observing(ingest_url, tmp_path):
    return World(ingest_url, tmp_path, checker=FakeChecker())


def contradicted_message(world, db, author=BOB, content=SAYS):
    thread, debate = opened(world, db)
    message_id = said(world, thread, db, author, content)
    assert check(world) is True
    return thread, debate, message_id


# --- what is posted, and to whom ------------------------------------------------------------------------------------------------------


def test_in_observation_nothing_is_ever_corrected_in_public(observing, ingest_db):
    thread, debate, _ = contradicted_message(observing, ingest_db)
    observing.tick(seconds=30)
    assert corrections(observing, thread) == [] and ingest_db.execute("SELECT count(*) FROM debate_corrections").fetchone()[0] == 0


@pytest.mark.parametrize(("verify", "posted"), [(True, 1), (False, 0)])
def test_a_contradicted_claim_is_answered_only_in_a_debate_that_checks_even_when_the_owner_allows_corrections(live, ingest_db, verify, posted):
    thread, debate = opened(live, ingest_db, verify=verify)
    message_id = said(live, thread, ingest_db, BOB, SAYS)
    claim_id = ingest_db.execute("INSERT INTO debate_claims (debate_id, message_id, author_id, claim, said, verdict, period) VALUES (%s, %s, %s, 'Le taux de chômage en France est de 12 %%', "
                                 "'le chômage est à 12 %%', 'contradicted', 'T2 2026') RETURNING id", (debate.id, message_id, BOB_ID)).fetchone()[0]
    ingest_db.execute("INSERT INTO debate_sources (claim_id, url, tier, stance, quote, sha256) VALUES (%s, %s, 'official', 'contradicts', %s, %s)", (claim_id, EVIDENCE.url, QUOTE, "a" * 64))
    live.tick(seconds=30)
    assert len(corrections(live, thread)) == posted                                                        # (the same claim, the same sources: only the choice made in the popup differs)


def test_in_a_debate_in_the_channel_a_correction_is_posted_in_the_channel_as_a_reply(live, ingest_db):
    thread, debate = opened(live, ingest_db, thread=False)
    message_id = said(live, thread, ingest_db, BOB, SAYS)
    assert check(live) is True
    live.tick(seconds=1)
    [posted] = live.discord.posted(GENERAL, "Vérification")
    assert posted["message_reference"] == {"message_id": str(message_id), "fail_if_not_exists": False} and thread == int(GENERAL)


def test_a_claim_contradicted_by_trusted_sources_is_answered_in_public_with_the_sources_to_click(live, ingest_db):
    thread, debate, message_id = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    [posted] = corrections(live, thread)
    embed = posted["embeds"][0]
    assert embed["title"] == TITLE and "Le taux de chômage en France est de 12 %" in embed["description"] and QUOTE in embed["description"] and "T2 2026" in embed["description"]
    assert f"[insee.fr]({EVIDENCE.url})" in embed["description"]
    [button] = posted["components"][0]["components"]
    assert button == {"type": 2, "style": 5, "label": "insee.fr", "url": EVIDENCE.url}                    # a link button: Discord opens the address when somebody clicks
    assert posted["message_reference"] == {"message_id": str(message_id), "fail_if_not_exists": False}
    assert posted["allowed_mentions"] == {"parse": [], "replied_user": False}                             # it answers the message, and pings nobody
    assert "ne prend pas parti" in embed["footer"]["text"]


def test_it_says_the_same_things_the_same_way_whoever_wrote_and_names_nobody(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db, BOB)
    live.tick(seconds=1)
    live.checker.results = [dataclasses.replace(RESULT, claim="La dette publique de la France est inférieure à 50 % du PIB")]
    said(live, thread, ingest_db, CAROL, "La dette publique est sous les 50 % du PIB, tout le monde le sait.")
    check(live)
    live.tick(seconds=21)
    first, second = corrections(live, thread)
    shape = lambda m: (m["embeds"][0]["title"], m["embeds"][0]["footer"], m["allowed_mentions"], [b["style"] for b in m["components"][0]["components"]])  # noqa: E731
    assert shape(first) == shape(second)
    everything = json.dumps([first, second], ensure_ascii=False).lower()
    for who in ("bobby", "bob", "carol", "alice", str(BOB_ID), str(CAROL_ID)):
        assert who not in everything, who


@pytest.mark.parametrize(("verdict", "stances"), [("confirmed", ("supports",)), ("partly", ("partly",)), ("disputed", ("supports", "contradicts")), ("unverifiable", ())])
def test_only_contradicted_claims_are_ever_corrected(live, ingest_db, verdict, stances):
    """A disputed claim has a source that contradicts it among others: it is still not corrected, because trusted sources disagree."""
    live.checker.results = [dataclasses.replace(RESULT, verdict=verdict, reason="no_source" if verdict == "unverifiable" else None,
                                                evidence=tuple(dataclasses.replace(EVIDENCE, stance=stance, url=f"https://www.insee.fr/fr/{n}") for n, stance in enumerate(stances)))]
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.tick(seconds=30)
    assert corrections(live, thread) == [] and claims_in(ingest_db) == 1                                   # the claim is kept and counted: it is only not answered


def test_only_the_sources_that_contradict_are_shown_and_at_most_three_official_first(live, ingest_db):
    sources = tuple(Evidence(f"https://factuel.afp.com/doc.{n}", "AFP", "checker", "contradicts", f"{QUOTE} (numéro {n})", None, "factcheck", "b" * 64) for n in range(1, 4))
    live.checker.results = [dataclasses.replace(RESULT, evidence=(*sources, EVIDENCE, dataclasses.replace(EVIDENCE, url="https://www.insee.fr/autre", stance="partly")))]
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    [posted] = corrections(live, thread)
    urls = [b["url"] for b in posted["components"][0]["components"]]
    assert urls == [EVIDENCE.url, sources[0].url, sources[1].url] and "insee.fr/autre" not in posted["embeds"][0]["description"]


def test_a_quotation_is_shown_as_written_a_long_address_is_still_a_link_and_a_period_may_be_missing():
    quote = "le taux *est* de _7,3_ % > de [la] population |active|"
    long_url = "https://www.insee.fr/fr/" + "a" * 520
    sources = [Evidence("https://www.insee.fr/fr/x(1)", "t", "official", "contradicts", quote, None, None, "a" * 64), Evidence(long_url, "t", "official", "contradicts", "une citation exacte de la page, assez longue", None, None, "a" * 64)]
    payload = texts.correction("Une affirmation *avec* des _marques_", None, sources, 5)
    description = payload["embeds"][0]["description"]
    assert "Une affirmation \\*avec\\* des \\_marques\\_" in description and "\\*est\\* de \\_7,3\\_ % \\> de \\[la\\] population \\|active\\|" in description
    assert "(T" not in description.split("Ce que disent les sources**")[1].split("\n")[0] and "x%281%29" in description
    assert [b["url"] for b in payload["components"][0]["components"]] == ["https://www.insee.fr/fr/x(1)"]    # too long for a button (512): in the text only
    assert "components" not in texts.correction("Une affirmation", None, [sources[1]], 5)


# --- once, spaced, recent -----------------------------------------------------------------------------------------------------------


def test_a_claim_is_corrected_once_even_after_many_ticks_and_a_restart(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    for _ in range(4):
        live.tick(seconds=1)
    live.restart()
    for _ in range(3):
        live.tick(seconds=1)
    assert len(corrections(live, thread)) == 1 and ingest_db.execute("SELECT count(*), count(posted_message_id) FROM debate_corrections").fetchone() == (1, 1)


def test_corrections_in_a_debate_are_spaced_and_one_per_tick(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    said(live, thread, ingest_db, CAROL, "La dette publique est sous les 50 % du PIB en France, c'est sûr.")
    live.checker.results = [dataclasses.replace(RESULT, claim="La dette de la France est sous les 50 % du PIB")]
    check(live)
    live.tick(seconds=1)
    assert len(corrections(live, thread)) == 1
    live.tick(seconds=15)
    assert len(corrections(live, thread)) == 1                                                             # too soon after the last one
    live.tick(seconds=10)
    assert len(corrections(live, thread)) == 2


def test_a_debate_gets_no_more_than_ten_corrections_an_hour(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    for n in range(claims.CORRECTIONS_PER_HOUR):                                                           # ten were posted in the last hour (and since taken back: they still count)
        ingest_db.execute("INSERT INTO debate_corrections (debate_id, thread_id, reply_to_message_id, posted_message_id, posted_at, retracted_at) VALUES (%s, %s, %s, %s, %s, %s)",
                          (debate.id, thread, 1000 + n, 2000 + n, live.time.now() - timedelta(minutes=5 + n), live.time.now()))
    live.tick(seconds=30)
    assert corrections(live, thread) == []
    ingest_db.execute("UPDATE debate_corrections SET posted_at = posted_at - interval '2 hours'")           # an hour later they no longer count
    live.tick(seconds=30)
    assert len(corrections(live, thread)) == 1


def test_a_claim_checked_more_than_half_an_hour_ago_is_not_corrected_any_more(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.time.advance(minutes=31)                                                                          # (a literal: the test must not depend on the value that it checks)
    live.tick(seconds=1)
    assert corrections(live, thread) == []


def test_nothing_is_corrected_for_somebody_who_stopped_being_recorded(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    privacy.stop_recording(ingest_db, BOB_ID)
    live.tick(seconds=1)
    assert corrections(live, thread) == []                                                                 # Bob asked not to be recorded: nothing more is said about his messages


def test_nothing_is_corrected_once_the_debate_is_over(live, ingest_db):
    from dindon.debate import store

    thread, debate, _ = contradicted_message(live, ingest_db)
    store.fail(ingest_db, debate.id, live.time.now())
    live.tick(seconds=1)
    assert corrections(live, thread) == []


# --- taken back ------------------------------------------------------------------------------------------------------------------------


def posted_ids(world, thread):
    return [m for (t, m) in world.discord.messages if t == thread and world.discord.messages[(t, m)].get("embeds", [{}])[0].get("title") == TITLE]


def test_when_the_message_is_edited_the_correction_is_taken_back_and_made_again_from_the_new_reading(live, ingest_db):
    thread, debate, message_id = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    [old] = posted_ids(live, thread)
    edited = message_create(message_id, "Finalement le chômage est à 7,3 % en France, j'avais tort.", BOB, channel_id=str(thread), edited_timestamp="2026-10-05T12:05:00.000000+00:00")
    live.runner.handle(event("MESSAGE_UPDATE", edited))
    flush(live.runner)
    live.checker.results = []                                                                              # read again: nothing to correct any more
    live.tick(seconds=1)
    assert old not in posted_ids(live, thread) and (thread, old) not in live.discord.messages
    assert ingest_db.execute("SELECT claim_id IS NULL, retracted_at IS NOT NULL FROM debate_corrections").fetchone() == (True, True)
    assert check(live) is True and corrections(live, thread) == []


def test_when_the_message_is_deleted_the_correction_goes_too(live, ingest_db):
    thread, debate, message_id = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    assert len(posted_ids(live, thread)) == 1
    live.runner.handle(event("MESSAGE_DELETE", {"id": str(message_id), "channel_id": str(thread), "guild_id": GUILD}))
    flush(live.runner)
    live.tick(seconds=1)
    assert posted_ids(live, thread) == []


def test_when_the_author_is_erased_the_correction_that_quoted_the_claim_is_deleted_from_discord(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    privacy.erase_person(ingest_db, BOB_ID, source="test")
    assert claims_in(ingest_db) == 0
    live.tick(seconds=1)
    assert posted_ids(live, thread) == []


def test_a_retraction_that_discord_refuses_is_tried_again_and_a_message_already_gone_is_not_an_error(live, ingest_db):
    thread, debate, message_id = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    live.discord.fail("DELETE", rf"/channels/{thread}/messages/\d+", 500, times=1)
    live.runner.handle(event("MESSAGE_DELETE", {"id": str(message_id), "channel_id": str(thread), "guild_id": GUILD}))
    flush(live.runner)
    live.tick(seconds=1)
    assert len(posted_ids(live, thread)) == 1 and live.debates.has_work()                                  # refused: it stays, and the engine keeps looking
    live.tick(seconds=3)
    assert posted_ids(live, thread) == []


def test_a_correction_that_is_already_gone_from_discord_is_simply_marked_taken_back(live, ingest_db):
    thread, debate, message_id = contradicted_message(live, ingest_db)
    live.tick(seconds=1)
    [mine] = posted_ids(live, thread)
    del live.discord.messages[(thread, mine)]                                                              # a moderator deleted it
    live.runner.handle(event("MESSAGE_DELETE", {"id": str(message_id), "channel_id": str(thread), "guild_id": GUILD}))
    flush(live.runner)
    live.tick(seconds=1)
    assert ingest_db.execute("SELECT retracted_at IS NOT NULL FROM debate_corrections").fetchone()[0] is True


# --- when posting goes wrong --------------------------------------------------------------------------------------------------------


def test_a_correction_that_cannot_be_posted_is_tried_again_with_growing_waits_and_posted_once(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.discord.fail("POST", rf"/channels/{thread}/messages", 500, times=2)
    live.tick(seconds=1)
    assert corrections(live, thread) == []
    live.tick(seconds=1)
    live.tick(seconds=2)
    assert corrections(live, thread) == []
    live.tick(seconds=6)
    assert len(corrections(live, thread)) == 1 and ingest_db.execute("SELECT attempts FROM debate_corrections").fetchone()[0] == 3


def test_a_correction_that_never_works_is_given_up_and_never_posted_late(live, ingest_db, caplog):
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.discord.fail("POST", rf"/channels/{thread}/messages", 500, times=99)
    with caplog.at_level(logging.WARNING, logger="dindon.bot.debate"):
        for _ in range(8):
            live.tick(seconds=61)
    assert "is given up" in caplog.text
    assert corrections(live, thread) == [] and ingest_db.execute("SELECT attempts, retracted_at IS NOT NULL FROM debate_corrections").fetchone() == (5, True)
    live.discord._failures.clear()
    live.tick(seconds=61)
    assert corrections(live, thread) == []


def test_a_thread_deleted_when_the_correction_is_posted_ends_the_debate(live, ingest_db):
    thread, debate, _ = contradicted_message(live, ingest_db)
    live.discord.delete_thread(thread)
    live.tick(seconds=1)
    assert ingest_db.execute("SELECT status, close_reason FROM debates").fetchone() == ("closed", "failed")


# --- the lock: only a measured precision opens the public corrections --------------------------------------------------------------------


@pytest.mark.parametrize(("asked", "precision", "mode", "why"), [
    ("off", None, "off", None), ("observe", None, "observe", None), ("observe", 0.99, "observe", None),
    ("answer", None, "answer", None), ("answer", 0.99, "answer", None),
    ("live", None, "answer", "DINDON_DEBATE_PRECISION"), ("live", 0.85, "answer", "sous le seuil"),            # not locked out of answering: only of the corrections that sources make by themselves
    ("live", 0.9, "live", None), ("live", 0.97, "live", None),
])
def test_corrections_in_public_need_a_measured_precision_that_reaches_the_threshold(asked, precision, mode, why):
    settings = dataclasses.replace(settings_for("postgresql://x", Path("/tmp/none")), debate_checks=asked, debate_precision=precision)
    resolved, reason = resolve_mode(settings)
    assert resolved == mode and (why is None or why in reason) and (why is not None or reason is None)


def test_the_bot_runs_live_only_when_the_lock_is_open_and_says_so_to_the_members(ingest_url, tmp_path, caplog):
    base = dataclasses.replace(settings_for(ingest_url, tmp_path), debate_checks="live", searxng_url="http://127.0.0.1:9")
    service = PrivacyService(ingest_url, ())
    with caplog.at_level(logging.WARNING, logger="dindon.bot.debate"):
        locked, _ = build_interactions(base, service)
    assert (locked.verification, locked.live) == (True, "answer") and "NOT on" in caplog.text                  # answering, and it says why the rest is off
    assert build_checker(dataclasses.replace(base, debate_precision=0.8)).mode == "answer"
    opened_lock, debates = build_interactions(dataclasses.replace(base, debate_precision=0.95), service)
    assert (opened_lock.live, debates.live, debates.checker.mode) == ("live", True, "live")


def test_the_notice_to_the_members_says_what_is_posted_when_corrections_are_on(live, ingest_db):
    thread, _ = opened(live, ingest_db)
    [question] = live.discord.posted(thread)
    assert texts.notice_short("live") in question["embeds"][0]["description"]
    assert "sur lesquelles vous pouvez cliquer" in texts.NOTICE_LIVE and "sans rien publier" not in texts.NOTICE_LIVE and "sans rien publier" in texts.NOTICE
    first, second = info(live)
    assert second[2]["content"].endswith(texts.NOTICE_LIVE) and len(second[2]["content"]) < 2000 and first[1].endswith("/callback")
