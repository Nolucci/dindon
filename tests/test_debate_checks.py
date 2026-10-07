"""The checking of claims inside the bot (docs/regles-du-bot.md, step D4b): the queue of messages to read, what is kept, what is cleaned, what the members are told, and that nothing is published.

Level of proof: SIMULATED. Real PostgreSQL, the real engine and ingestion; the Discord is the fake of test_debate_bot.py; the checker (what reads the message and checks on the Internet) is a script
here, tested for itself in test_debate_verify.py. Nothing talks to the Internet or to a model.
"""
import asyncio
import dataclasses
import inspect
import logging
from datetime import UTC, datetime, timedelta

import pytest

from dindon import privacy
from dindon.analysis.ollama import OllamaError
from dindon.bot import runner as runner_module
from dindon.bot.runner import build_interactions
from dindon.debate import claims, rules, store, texts
from dindon.debate.checker import Checker
from dindon.debate.claims import AnswerFound, ClaimResult, Considered, Evidence
from gateway_fixtures import BOB, CAROL, GENERAL, GUILD, message_create
from synthetic import settings_for
from test_bot import event, flush
from test_debate_bot import ALICE_ID, BOB_ID, CAROL_ID, T0, TOPIC, World, debat, only_debate, run, submission, the_debate

QUOTE = "le taux de chômage s'établit à 7,3 % de la population active"
EVIDENCE = Evidence("https://www.insee.fr/fr/statistiques/1", "Taux de chômage", "official", "contradicts", QUOTE, "T2 2026", "searxng", "a" * 64)
RESULT = ClaimResult("Le taux de chômage en France est de 12 %", "le chômage est à 12 %", "contradicted", None, "T2 2026", 1, 1, "qwen3:14b", (EVIDENCE,))
SAYS = "Le chômage est à 12 % en France, tout le monde le sait."


class FakeChecker:
    """What reads a message and checks it: here a script that records what it was given. `local`: what Dindon answers by itself, without the Internet (a function of the text that gives its
    answers, or None: it is sure of nothing, and every claim goes to the Internet). `can_search`: whether there is a search service at all."""

    def __init__(self, results=(RESULT,), error=None, local=None, can_search=True):
        self.texts, self.results, self.error, self.local, self.can_search = [], results, error, local, can_search
        self.searched, self.search_result = [], RESULT                # the claims that the participants asked to be searched, and what the search finds

    def check(self, text):
        self.texts.append(text)
        if self.error is not None:
            raise self.error
        return list(self.results(text) if callable(self.results) else self.results)

    def consider(self, text):
        self.texts.append(text)
        if self.error is not None:
            raise self.error
        answers = tuple(self.local(text)) if self.local else ()
        results = () if answers or not self.can_search else tuple(self.results(text) if callable(self.results) else self.results)
        return Considered(answers, results)

    def search(self, reading):
        self.searched.append(reading)
        return self.search_result(reading) if callable(self.search_result) else self.search_result


@pytest.fixture
def checked(ingest_url, tmp_path):
    return World(ingest_url, tmp_path, checker=FakeChecker())


@pytest.fixture
def plain(ingest_url, tmp_path):
    return World(ingest_url, tmp_path)


def opened(world, db, **answers):
    """A debate that is running, opened from the popup (in a thread unless `thread=False`). Returns (its place, the debate)."""
    world.command(ALICE_ID, **answers)
    debate = only_debate(db)
    run(world.debates.tick())
    return debate.thread_id, the_debate(db, debate.thread_id)


def said(world, thread, db, author=BOB, content=SAYS):
    """A person writes in the thread; the debate counts it and the ingestion stores it. Returns the number of the message."""
    world.write(thread, author, content)
    run(world.debates.tick())
    flush(world.runner)
    return db.execute("SELECT max(message_id) FROM debate_messages").fetchone()[0]


def check(world):
    return run(world.debates.check_next())


def claims_in(db):
    return db.execute("SELECT count(*) FROM debate_claims").fetchone()[0]


# --- what the members are told ------------------------------------------------------------------------------------------------------


def test_with_the_checks_on_every_debate_thread_says_what_leaves_the_machine_and_without_them_it_says_nothing_of_the_kind(checked, plain, ingest_db):
    thread, debate = opened(checked, ingest_db)
    [question] = checked.discord.posted(thread)
    assert "fields" not in question["embeds"][0] and texts.notice_short("observe") in question["embeds"][0]["description"]                  # one line in the launch message…
    first, second = info(checked)
    assert second[2]["content"] == f"**{texts.NOTICE_TITLE}.** {texts.NOTICE}"                                                            # …and the whole text in /dindon info
    for needed in ("phrase neutre", "sans votre nom, sans votre message", "au plus trois des pages", "personne privée", "n'ouvre pas les liens que vous écrivez", "ne prend pas parti",
                   "Rien d'autre ne quitte cet ordinateur", "sans rien publier"):
        assert needed in texts.NOTICE
    assert len(texts.NOTICE) <= 1024                                                                       # the limit of an embed field
    plain.command(BOB_ID)                                                                                   # (another person: the two worlds share one database, and one debate per person)
    assert "🔎" not in plain.discord.posted(max(plain.discord.threads))[0]["embeds"][0]["description"]


def test_the_notice_stays_when_the_question_is_refreshed_or_posted_again_and_goes_when_the_debate_is_over(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    checked.click(BOB_ID, thread, debate.id, "pos", "for")
    checked.tick(seconds=6)
    refreshed = checked.discord.messages[(thread, debate.question_message_id)]
    assert texts.notice_short("observe") in refreshed["embeds"][0]["description"]
    old = debate.question_message_id
    del checked.discord.messages[(thread, old)]
    checked.runner.handle(event("MESSAGE_DELETE", {"id": str(old), "channel_id": str(thread), "guild_id": GUILD}))
    checked.tick(seconds=1)
    new = store.get(ingest_db, debate.id).question_message_id
    assert texts.notice_short("observe") in checked.discord.messages[(thread, new)]["embeds"][0]["description"]
    checked.click(ALICE_ID, thread, debate.id, "end", "now", permissions=8)
    checked.tick(seconds=1)
    assert "🔎" not in checked.discord.messages[(thread, new)]["embeds"][0]["description"]


def info(world):
    run(world.interactions.answer({"id": "9", "token": "tk", "type": 2, "application_id": "42", "guild_id": GUILD, "channel_id": "200",
                                   "data": {"name": "dindon", "options": [{"type": 1, "name": "info"}]}, "member": {"user": {"id": str(ALICE_ID)}}}))
    return [c for c in world.sent.calls if c[1].startswith("/interactions/9/tk") or c[1].startswith("/webhooks/42/tk")]    # (this answer only, not the one that opened the debate)


def test_dindon_info_adds_the_notice_as_a_second_private_message_only_when_the_checks_are_on(checked, plain):
    first, second = info(checked)
    assert first[1] == "/interactions/9/tk/callback" and "Ce qui est gardé" in first[2]["data"]["content"] and len(first[2]["data"]["content"]) < 2000
    assert second[:2] == ("POST", "/webhooks/42/tk") and second[2]["flags"] == 64 and second[2]["allowed_mentions"] == {"parse": []}
    assert second[2]["content"] == f"**{texts.NOTICE_TITLE}.** {texts.NOTICE}" and len(second[2]["content"]) < 2000
    [only] = info(plain)
    assert "Vérification des affirmations" not in only[2]["data"]["content"]


def test_the_bot_is_built_with_the_checks_off_unless_the_owner_switched_them_on_with_a_search_service(ingest_url, tmp_path):
    from dindon.bot.privacy_commands import PrivacyService

    base = settings_for(ingest_url, tmp_path)
    service = PrivacyService(ingest_url, ())
    off, debates_off = build_interactions(base, service)
    assert (off.verification, debates_off.checker, debates_off.verifying) == (False, None, False)
    no_service, _ = build_interactions(dataclasses.replace(base, debate_checks="observe"), service)
    assert no_service.verification is False                                                                # on, but nothing to search with: nothing is read, nothing is said
    on, debates_on = build_interactions(dataclasses.replace(base, debate_checks="observe", searxng_url="http://127.0.0.1:9"), service)
    assert on.verification is True and debates_on.checker is not None and debates_on.has_checks() is False   # (no debate runs yet)


def test_the_settings_read_the_environment_and_anything_but_observe_means_off(monkeypatch):
    from dindon import config

    monkeypatch.setattr(config, "_load_dotenv", lambda path: None)                                         # (not the owner's real .env)
    for name in ("DINDON_DEBATE_CHECKS", "DINDON_DEBATE_MODEL", "DINDON_FACTCHECK_API_KEY", "DINDON_SEARXNG_URL"):
        monkeypatch.delenv(name, raising=False)
    default = config.load_settings()
    assert (default.debate_checks, default.debate_model, default.factcheck_api_key, default.searxng_url) == ("off", "qwen3:14b", "", "")
    for value in ("on", "true", "1", "enabled", ""):
        monkeypatch.setenv("DINDON_DEBATE_CHECKS", value)
        assert config.load_settings().debate_checks == "off"
    monkeypatch.setenv("DINDON_DEBATE_CHECKS", " Observe ")
    monkeypatch.setenv("DINDON_DEBATE_MODEL", "gemma4:12b")
    monkeypatch.setenv("DINDON_FACTCHECK_API_KEY", " secret ")
    monkeypatch.setenv("DINDON_SEARXNG_URL", "http://searxng:8080/")
    configured = config.load_settings()
    assert (configured.debate_checks, configured.debate_model, configured.factcheck_api_key, configured.searxng_url) == ("observe", "gemma4:12b", "secret", "http://searxng:8080")
    assert (configured.debate_precision, configured.debate_min_precision) == (None, 0.9)
    monkeypatch.setenv("DINDON_DEBATE_CHECKS", "LIVE")
    monkeypatch.setenv("DINDON_DEBATE_PRECISION", "0,93")                                                   # the French decimal comma
    monkeypatch.setenv("DINDON_DEBATE_MIN_PRECISION", "0.2")                                                # never below 0.5
    live = config.load_settings()
    assert (live.debate_checks, live.debate_precision, live.debate_min_precision) == ("live", 0.93, 0.5)
    monkeypatch.setenv("DINDON_DEBATE_PRECISION", "beaucoup")
    assert config.load_settings().debate_precision is None
    assert "secret" not in repr(configured)


# --- the queue ------------------------------------------------------------------------------------------------------------------------


def test_with_the_checks_off_nothing_waits_to_be_read_and_nothing_is_read(plain, ingest_db):
    thread, debate = opened(plain, ingest_db)
    said(plain, thread, ingest_db)
    assert ingest_db.execute("SELECT count(*) FROM debate_messages WHERE read_at IS NULL").fetchone()[0] == 0
    assert check(plain) is False and claims.unread_count(ingest_db) == 0 and not plain.debates.has_checks()


def test_messages_are_read_oldest_first_once_the_ingestion_has_stored_them_and_each_only_once(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    checked.write(thread, BOB, "Premier message : le chômage est à 12 % en France.")
    checked.write(thread, CAROL, "Deuxième message : la dette dépasse 110 % du PIB.")
    run(checked.debates.tick())
    assert claims.unread_count(ingest_db) == 2 and check(checked) is False                                 # counted, but not stored yet by the ingestion: nothing to read
    flush(checked.runner)
    assert [check(checked), check(checked), check(checked)] == [True, True, False]
    assert checked.checker.texts == ["Premier message : le chômage est à 12 % en France.", "Deuxième message : la dette dépasse 110 % du PIB."]
    assert claims_in(ingest_db) == 2 and claims.unread_count(ingest_db) == 0


def test_the_reader_is_given_the_text_of_the_message_and_nothing_else(checked, ingest_db):
    """Blind: not the author, not the position, not the subject of the debate, not the camps."""
    assert list(inspect.signature(Checker.check).parameters) == ["self", "text"]
    thread, debate = opened(checked, ingest_db)
    checked.click(BOB_ID, thread, debate.id, "pos", "for")
    checked.click(CAROL_ID, thread, debate.id, "pos", "against")
    said(checked, thread, ingest_db, BOB, SAYS)
    said(checked, thread, ingest_db, CAROL, "La dette publique dépasse 110 % du PIB en France.")
    check(checked)
    check(checked)
    seen = " ".join(checked.checker.texts).lower()
    assert checked.checker.texts == [SAYS, "La dette publique dépasse 110 % du PIB en France."]
    for secret in ("bobby", "carol", "alice", TOPIC.lower(), "pour", "contre", "ne sait pas", str(BOB_ID), str(CAROL_ID)):
        assert secret not in seen


def test_what_is_found_is_kept_with_its_sources_and_nothing_is_published(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    checked.click(BOB_ID, thread, debate.id, "pos", "for")
    message_id = said(checked, thread, ingest_db)
    published = len(checked.discord.calls)
    assert check(checked) is True
    assert len(checked.discord.calls) == published                                                         # reading, searching and keeping: not a word on Discord
    [found] = claims.claims_of(ingest_db, debate.id)
    assert (found["message_id"], found["claim"], found["said"], found["verdict"], found["period"], found["queries"], found["pages"]) == (
        str(message_id), RESULT.claim, RESULT.said, "contradicted", "T2 2026", 1, 1)
    assert found["sources"] == [{"url": EVIDENCE.url, "title": "Taux de chômage", "tier": "official", "stance": "contradicts", "quote": QUOTE, "page_period": "T2 2026", "via": "searxng"}]
    assert claims.parity(ingest_db, debate.id) == {"for": {"confirmed": 0, "contradicted": 1, "partly": 0, "disputed": 0, "unverifiable": 0, "total": 1}}
    assert ingest_db.execute("SELECT read_at IS NOT NULL FROM debate_messages WHERE message_id = %s", (message_id,)).fetchone()[0] is True


def test_a_message_with_no_claim_is_read_and_leaves_no_trace(ingest_db, ingest_url, tmp_path):
    world = World(ingest_url, tmp_path, checker=FakeChecker(results=()))
    thread, debate = opened(world, ingest_db)
    said(world, thread, ingest_db, BOB, "Je trouve que ce serait mieux autrement, honnêtement.")
    assert check(world) is True and claims_in(ingest_db) == 0 and claims.unread_count(ingest_db) == 0


def test_the_parity_table_counts_every_verdict_by_the_side_of_the_author_and_hides_those_who_stopped(checked, ingest_db):
    checker = FakeChecker(results=lambda text: [dataclasses.replace(RESULT, verdict="confirmed" if "dette" in text else "contradicted", evidence=())])
    checked.checker = checker
    checked.debates.checker = checker
    thread, debate = opened(checked, ingest_db)
    checked.click(BOB_ID, thread, debate.id, "pos", "for")
    checked.click(CAROL_ID, thread, debate.id, "pos", "against")
    for author, text in ((BOB, "Le chômage est à 12 % en France."), (BOB, "La dette dépasse 110 % du PIB."), (CAROL, "La dette dépasse 110 % du PIB."), (CAROL, "Le chômage a doublé depuis 2022.")):
        said(checked, thread, ingest_db, author, text)
    while check(checked):
        pass
    table = claims.parity(ingest_db, debate.id)
    assert (table["for"]["confirmed"], table["for"]["contradicted"], table["against"]["confirmed"], table["against"]["contradicted"]) == (1, 1, 1, 1)
    privacy.stop_recording(ingest_db, CAROL_ID)
    assert list(claims.parity(ingest_db, debate.id)) == ["for"] and {c["author_id"] for c in claims.claims_of(ingest_db, debate.id)} == {str(BOB_ID)}


# --- what changes under it -----------------------------------------------------------------------------------------------------------


def test_an_edited_message_loses_its_claims_and_is_read_again_with_its_new_text(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    message_id = said(checked, thread, ingest_db)
    check(checked)
    assert claims_in(ingest_db) == 1
    edited = message_create(message_id, "Finalement le chômage est à 7,3 % en France, j'avais tort.", BOB, channel_id=str(thread), edited_timestamp="2026-10-05T12:05:00.000000+00:00")
    checked.runner.handle(event("MESSAGE_UPDATE", edited))
    flush(checked.runner)
    assert claims_in(ingest_db) == 0 and claims.unread_count(ingest_db) == 1                               # what was read of the old words is gone
    assert check(checked) is True and checked.checker.texts[-1] == "Finalement le chômage est à 7,3 % en France, j'avais tort." and claims_in(ingest_db) == 1


def test_a_deleted_message_takes_its_claims_and_their_sources_with_it(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    message_id = said(checked, thread, ingest_db)
    check(checked)
    assert ingest_db.execute("SELECT count(*) FROM debate_sources").fetchone()[0] == 1
    checked.runner.handle(event("MESSAGE_DELETE", {"id": str(message_id), "channel_id": str(thread), "guild_id": GUILD}))
    flush(checked.runner)
    assert (claims_in(ingest_db), ingest_db.execute("SELECT count(*) FROM debate_sources").fetchone()[0]) == (0, 0)


def test_a_result_is_not_written_if_the_message_was_edited_or_deleted_while_it_was_being_checked(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    message_id = said(checked, thread, ingest_db)
    [taken] = claims.next_unread(ingest_db, 1)                                                              # a check starts…
    ingest_db.execute("UPDATE messages SET content = 'Un tout autre texte, après modification.' WHERE id = %s", (message_id,))   # …the message is edited…
    assert claims.finish_reading(ingest_db, taken, [RESULT], T0) is False and claims_in(ingest_db) == 0 and claims.unread_count(ingest_db) == 1
    ingest_db.execute("DELETE FROM messages WHERE id = %s", (message_id,))                                  # …or deleted
    [again] = [taken]
    assert claims.finish_reading(ingest_db, again, [RESULT], T0) is False and claims_in(ingest_db) == 0


def test_two_checks_of_the_same_message_write_it_once(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db)
    [taken] = claims.next_unread(ingest_db, 1)
    assert claims.finish_reading(ingest_db, taken, [RESULT], T0) is True and claims.finish_reading(ingest_db, taken, [RESULT], T0) is False
    assert claims_in(ingest_db) == 1


# --- people who asked not to be recorded, debates that are over -------------------------------------------------------------------------


def test_the_messages_of_a_person_who_stopped_are_not_read_and_a_check_in_progress_keeps_nothing_of_them(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db, BOB)
    said(checked, thread, ingest_db, CAROL, "La dette publique dépasse 110 % du PIB en France.")
    privacy.stop_recording(ingest_db, BOB_ID)                                                               # Bob stops before his message is read
    assert check(checked) is True and check(checked) is False
    assert checked.checker.texts == ["La dette publique dépasse 110 % du PIB en France."]                   # only Carol's was read
    said(checked, thread, ingest_db, CAROL, "Le SMIC brut est de 1 800 euros en France.")
    [taken] = claims.next_unread(ingest_db, 1)
    privacy.stop_recording(ingest_db, CAROL_ID)                                                             # Carol stops while her message is being checked
    assert claims.finish_reading(ingest_db, taken, [RESULT], T0) is True                                    # the message is read, and nothing of hers is kept
    assert claims_in(ingest_db) == 1 and claims.next_unread(ingest_db) == []                                # (the claim she made before stopping is still there: stopping is not erasing; and Bob's message is never read)


def test_nothing_is_read_in_a_debate_that_ended_long_ago(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db)
    checked.click(ALICE_ID, thread, debate.id, "end", "now", permissions=8)
    checked.tick(seconds=1)                                                                                 # over, with one message still unread: its statistics wait for it (claims.GRACE_MINUTES)…
    assert checked.discord.posted(thread, "Débat terminé") == []
    checked.tick(minutes=claims.GRACE_MINUTES + 1)                                                          # …and after the grace they are posted as they are, and nothing is read any more
    assert store.get(ingest_db, debate.id).status == "closed" and store.get(ingest_db, debate.id).final_message_id and check(checked) is False and checked.checker.texts == []


# --- what the popup decides: whether to check, and where ----------------------------------------------------------------------------------


def test_a_debate_opened_without_verification_reads_nothing_and_queues_nothing(checked, ingest_db):
    thread, debate = opened(checked, ingest_db, verify=False)
    said(checked, thread, ingest_db)
    assert claims.unread_count(ingest_db) == 0 and check(checked) is False and checked.checker.texts == [] and claims_in(ingest_db) == 0
    assert "🔎" not in checked.discord.posted(thread)[0]["embeds"][0]["description"]                          # and it does not announce what it does not do
    checked.click(ALICE_ID, thread, debate.id, "end", "now", permissions=8)
    checked.tick(seconds=1)
    assert "vérifiée" not in checked.discord.posted(thread, "Débat terminé")[0]["embeds"][0]["description"]


def test_in_a_debate_in_the_channel_the_messages_of_the_channel_are_read_for_claims(checked, ingest_db):
    place, debate = opened(checked, ingest_db, thread=False)
    assert place == int(GENERAL)
    checked.checker.results = lambda text: [RESULT] if "chômage" in text else []                              # (the script finds a claim in the first message only)
    said(checked, place, ingest_db, BOB, SAYS)
    said(checked, place, ingest_db, CAROL, "Je suis allé au marché ce matin, il faisait beau.")
    assert claims.unread_count(ingest_db) == 2 and check(checked) is True and check(checked) is True
    assert checked.checker.texts == [SAYS, "Je suis allé au marché ce matin, il faisait beau."] and claims_in(ingest_db) == 1


def test_a_message_that_waited_more_than_an_hour_is_not_read_any_more_but_stays_counted(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db)
    checked.time.advance(minutes=claims.STALE_MINUTES + 1)
    assert check(checked) is False and checked.checker.texts == [] and claims.unread_count(ingest_db) == 0
    assert store.summary(ingest_db, debate.id)["messages"] == 1                                              # (counted in the statistics all the same)


# --- how much, and when the model is away -------------------------------------------------------------------------------------------------


def test_a_debate_gets_no_more_than_twenty_claims_checked_an_hour_and_the_rest_waits(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db)
    for n in range(claims.MAX_CHECKS_PER_HOUR):
        ingest_db.execute("INSERT INTO debate_claims (debate_id, message_id, author_id, claim, said, verdict, checked_at) VALUES (%s, %s, %s, 'Une affirmation', 'une affirmation', 'confirmed', %s)",
                          (debate.id, 10_000 + n, BOB_ID, checked.time.now() - timedelta(minutes=30)))
    assert check(checked) is False and checked.checker.texts == [] and claims.unread_count(ingest_db) == 1
    checked.time.advance(minutes=31)                                                                        # the twenty were checked 61 minutes ago, the message was written 31 minutes ago
    assert check(checked) is True and len(checked.checker.texts) == 1                                        # the hour passed: it goes on


def test_a_model_that_is_away_leaves_the_message_unread_is_told_once_and_is_tried_again_later(checked, ingest_db, caplog):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db)
    checked.checker.error = OllamaError("Ollama ne répond pas")
    with caplog.at_level(logging.WARNING, logger="dindon.bot.debate"):
        assert check(checked) is False
        checked.time.advance(seconds=31)
        assert check(checked) is False
    assert claims.unread_count(ingest_db) == 1 and len(checked.checker.texts) == 2
    assert len([r for r in caplog.records if "could not be checked" in r.getMessage()]) == 1                 # said once, with the kind of error and nothing else
    assert "ne répond pas" not in caplog.text                                                                # (the text of the error is not in the log)
    checked.time.advance(seconds=10)
    assert check(checked) is False and len(checked.checker.texts) == 2                                      # (waiting)
    checked.checker.error = None
    checked.time.advance(seconds=31)
    assert check(checked) is True and claims.unread_count(ingest_db) == 0 and claims_in(ingest_db) == 1


def test_what_waits_to_be_read_survives_a_restart_of_the_bot(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    said(checked, thread, ingest_db, BOB, "Premier message : le chômage est à 12 % en France.")
    said(checked, thread, ingest_db, CAROL, "Deuxième message : la dette dépasse 110 % du PIB.")
    checked.restart()                                                                                       # the bot stops and starts again: a new engine, the same database
    run(checked.debates.tick())
    assert claims.unread_count(ingest_db) == 2 and checked.debates.has_checks()
    assert check(checked) is True and check(checked) is True and len(checked.checker.texts) == 2


def test_the_engine_reads_the_messages_by_itself_in_a_task_that_does_not_hold_up_its_loop(checked, ingest_db, monkeypatch):
    monkeypatch.setattr(runner_module, "DEBATE_TICK_SECONDS", 0.05)

    async def scenario():
        events, stop = asyncio.Queue(), asyncio.Event()
        engine = asyncio.create_task(checked.runner.run(events, stop))
        await checked.interactions.answer(debat(ALICE_ID))
        await checked.interactions.answer(submission(ALICE_ID, checked.popup(), thread=True))
        [thread] = checked.discord.threads
        store.set_position(ingest_db, only_debate(ingest_db).id, BOB_ID, "for", T0)                           # (only a participant is read)
        events.put_nowait(event("MESSAGE_CREATE", message_create(7001, SAYS, BOB, channel_id=str(thread), timestamp=checked.time.now().isoformat())))
        for _ in range(200):
            if checked.checker.texts:
                break
            await asyncio.sleep(0.05)
        stop.set()
        await engine

    run(scenario())
    assert checked.checker.texts == [SAYS]


# --- the rights of the people ---------------------------------------------------------------------------------------------------------


def _with_a_claim(db, author=BOB_ID):
    debate = store.start(db, guild_id=1, channel_id=2, topic="Un sujet", created_by=ALICE_ID, now=T0)
    claim_id = db.execute(
        "INSERT INTO debate_claims (debate_id, message_id, author_id, claim, said, verdict, period) VALUES (%s, 77, %s, 'Le chômage est à 12 %%', 'le chômage est à 12 %%', 'contradicted', 'T2 2026') RETURNING id",
        (debate.id, author)).fetchone()[0]
    db.execute("INSERT INTO debate_sources (claim_id, url, tier, stance, quote, sha256) VALUES (%s, 'https://www.insee.fr/x', 'official', 'contradicts', %s, %s)", (claim_id, QUOTE, "a" * 64))
    return debate


def test_erasing_a_person_erases_their_claims_and_the_sources_behind_them(ingest_db):
    debate = _with_a_claim(ingest_db)
    counts = privacy.erase_person(ingest_db, BOB_ID, source="test")
    assert counts["debate_traces"] == 1 and claims_in(ingest_db) == 0 and ingest_db.execute("SELECT count(*) FROM debate_sources").fetchone()[0] == 0 and store.get(ingest_db, debate.id)


def test_a_person_can_see_the_claims_of_theirs_that_were_checked_and_what_they_were_checked_against(ingest_db):
    _with_a_claim(ingest_db)
    [mine] = privacy.export_person(ingest_db, BOB_ID)["debates"]
    assert mine["claims_checked"] == [{"claim": "Le chômage est à 12 %", "said": "le chômage est à 12 %", "verdict": "contradicted", "period": "T2 2026",
                                       "sources": [{"url": "https://www.insee.fr/x", "quote": QUOTE, "stance": "contradicts"}]}]
    assert privacy.export_person(ingest_db, CAROL_ID)["debates"] == []


def test_a_deletion_event_removes_the_claims_of_a_message_that_the_map_no_longer_holds(ingest_db):
    """The message may be gone from `messages` already (the retention, say) while its claims are still there: the deletion that Discord then reports must clean them too."""
    from dindon.ingest.loader import forget_messages

    _with_a_claim(ingest_db)
    assert claims_in(ingest_db) == 1
    forget_messages(ingest_db, 1, [77])
    assert claims_in(ingest_db) == 0 and ingest_db.execute("SELECT count(*) FROM debate_sources").fetchone()[0] == 0


def test_removing_a_server_or_the_end_of_the_retention_takes_the_claims_with_the_debates(ingest_db):
    debate = _with_a_claim(ingest_db)
    privacy.erase_server(ingest_db, 1, source="test")
    assert claims_in(ingest_db) == 0 and store.get(ingest_db, debate.id) is None
    debate = _with_a_claim(ingest_db)
    store.fail(ingest_db, debate.id, datetime.now(UTC) - timedelta(days=100))                               # closed long ago
    assert privacy.purge_older_than(ingest_db, 30)["debates"] == 1 and claims_in(ingest_db) == 0


def test_the_interface_gets_the_same_debate_settings_as_the_bot_so_that_its_page_tells_the_truth():
    """The page Débats said « Désactivée » while the bot ran in `answer`: the interface's container did not receive the settings. Both must get the same ones."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^  ([a-z]+):\n", text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0])
    services = dict(zip(blocks[1::2], blocks[2::2], strict=True))
    wanted = {"DINDON_DEBATE_CHECKS", "DINDON_DEBATE_PRECISION", "DINDON_DEBATE_MIN_PRECISION", "DINDON_DEBATE_MODEL", "DINDON_FACTCHECK_API_KEY", "DINDON_SEARXNG_URL"}
    found = {name: {line.split(":")[0].strip() for line in block.split("\n") if re.match(r"^      DINDON_(DEBATE|FACTCHECK|SEARXNG)", line)} for name, block in services.items() if name in ("app", "bot")}
    assert found["bot"] == wanted and found["app"] == wanted
