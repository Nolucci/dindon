"""The statistics of a debate (docs/regles-du-bot.md « Statistiques de fin », step D6): what is counted, the message picked out for each person, the pages, the buttons that turn them, and the closing
message that waits for what is still being read.

Level of proof: SIMULATED: real PostgreSQL, real engine and ingestion, fake Discord, a script for the checker. Nothing has been posted on a real Discord.
"""
import dataclasses

import pytest

from dindon import privacy
from dindon.debate import claims, rules, stats, store, texts
from dindon.debate.claims import ClaimResult
from gateway_fixtures import ALICE, BOB, CAROL, GUILD, message_create
from test_bot import flush
from test_debate_bot import ALICE_ID, BOB_ID, CAROL_ID, button, run
from test_debate_checks import EVIDENCE, RESULT, FakeChecker, check, opened
from test_debate_bot import World  # noqa: F401  (the fixture module of the other files)


@pytest.fixture
def world(ingest_url, tmp_path):
    return World(ingest_url, tmp_path)


@pytest.fixture
def checked(ingest_url, tmp_path):
    return World(ingest_url, tmp_path, checker=FakeChecker())


def talk(world, thread, db, author, content, **extra):
    world.write(thread, author, content, **extra)
    run(world.debates.tick())
    flush(world.runner)
    return db.execute("SELECT max(message_id) FROM debate_messages").fetchone()[0]


def reply_to(world, thread, db, original, author, content="Je réponds à ce message avec un texte assez long."):
    ref = message_create(original["id"], original["text"], original["author"], channel_id=str(thread))
    return talk(world, thread, db, author, content, reply_to=ref)


def message(world, thread, db, author, content):
    return {"id": talk(world, thread, db, author, content), "text": content, "author": author}


def ended(world, db, thread, debate):
    """The person who opened the debate presses « Terminer » and the engine looks at it once."""
    world.click(ALICE_ID, thread, debate.id, "end", "now", permissions=8)       # (a moderator ends it at once)
    world.tick(seconds=1)
    assert store.get(db, debate.id).status == "closed"


# --- what is counted --------------------------------------------------------------------------------------------------------------------


def test_the_figures_the_positions_and_the_changes_of_mind(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    for author, text in ((BOB, "Un premier message de Bob sur le sujet."), (BOB, "Un second message de Bob."), (CAROL, "Le message unique de Carol sur le sujet.")):
        talk(world, thread, ingest_db, author, text)
    world.click(ALICE_ID, thread, debate.id, "pos", "for")                                                  # Alice only takes a position
    world.click(BOB_ID, thread, debate.id, "pos", "for")
    world.click(BOB_ID, thread, debate.id, "pos", "against")                                                # Bob changes his mind
    world.click(CAROL_ID, thread, debate.id, "pos", "unsure")                                               # (Carol was « pour » when she wrote)
    found = stats.collect(ingest_db, debate.id)
    totals = found["totals"]
    assert (totals["participants"], totals["messages"], totals["changed_mind"]) == (3, 3, 2)
    assert totals["initial"] == {"for": 3, "unsure": 0, "against": 0, "witness": 0, "none": 0} and totals["final"] == {"for": 1, "unsure": 1, "against": 1, "witness": 0, "none": 0}
    bob, carol, alice = found["participants"]                                                               # most messages first
    assert (bob["user_id"], bob["position"], bob["first_position"], bob["changed"], bob["messages"], bob["share"]) == (str(BOB_ID), "against", "for", True, 2, round(2 / 3, 3))
    assert (carol["position"], carol["changed"], carol["messages"]) == ("unsure", True, 1) and (alice["messages"], alice["share"], alice["key_message"]) == (0, 0.0, None)
    assert [entry["position"] for entry in carol["position_history"]] == ["for", "unsure"]
    assert all(entry["at"] for entry in carol["position_history"])


def test_a_person_who_asked_not_to_be_recorded_is_in_no_figure(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    talk(world, thread, ingest_db, BOB, "Un message de Bob qui compte pour le débat.")
    talk(world, thread, ingest_db, CAROL, "Un message de Carol qui compte pour le débat.")
    privacy.stop_recording(ingest_db, CAROL_ID)
    found = stats.collect(ingest_db, debate.id)
    assert [p["user_id"] for p in found["participants"]] == [str(BOB_ID)] and (found["totals"]["participants"], found["totals"]["messages"]) == (1, 1)
    assert stats.collect(ingest_db, 424242) is None


def test_the_message_picked_out_is_the_one_the_debate_picked_the_same_rule_for_everybody(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    short = message(world, thread, ingest_db, BOB, "Oui, exactement ça !")                                  # 20 characters: no substance
    answered = message(world, thread, ingest_db, BOB, "Voici un argument développé, avec assez de matière pour compter vraiment.")
    liked = message(world, thread, ingest_db, BOB, "Un autre argument tout aussi développé, mais que personne n'a commenté du tout.")
    for n in range(4):
        reply_to(world, thread, ingest_db, short, CAROL, f"Réponse numéro {n} au message court de Bob, pour le principe.")
    reply_to(world, thread, ingest_db, answered, CAROL)
    ingest_db.execute("INSERT INTO emojis (key, name, image_url) VALUES ('👍', 'thumbsup', 'x')")
    ingest_db.execute("INSERT INTO reactions (message_id, emoji_key, count) VALUES (%s, '👍', 2)", (liked["id"],))
    only_short = message(world, thread, ingest_db, ALICE, "Bien dit.")
    found = {p["user_id"]: p for p in stats.collect(ingest_db, debate.id)["participants"]}
    key = found[str(BOB_ID)]["key_message"]
    assert key["message_id"] == str(answered["id"]) and (key["replies"], key["reactions"]) == (1, 0)       # 3 points beat 2, and 4 answers to a short message do not beat substance
    assert key["url"] == f"https://discord.com/channels/{GUILD}/{thread}/{answered['id']}" and key["excerpt"].startswith("Voici un argument développé")
    assert found[str(ALICE_ID)]["key_message"]["message_id"] == str(only_short["id"])                       # nothing else to choose from: the short one
    assert found[str(CAROL_ID)]["key_message"]["replies"] == 0


def test_the_excerpt_hides_raw_mentions_and_is_cut(world, ingest_db):
    assert stats._excerpt("<@!1000000000000000003> a raison sur <#1234567890123456789> et <@&42> <:pouce:99>") == "@membre a raison sur #salon et @membre"
    thread, debate = opened(world, ingest_db)
    talk(world, thread, ingest_db, BOB, "<@1000000000000000003> a raison sur <#1234567890123456789> " + "et voilà un très long propos " * 12)
    [bob] = stats.collect(ingest_db, debate.id)["participants"]
    excerpt = bob["key_message"]["excerpt"]
    assert "1000000000000000003" not in excerpt and "1234567890123456789" not in excerpt and len(excerpt) <= stats.EXCERPT and excerpt.endswith("…")


def test_the_recent_debates_are_listed_with_their_headline_figures(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    talk(world, thread, ingest_db, BOB, "Un message de Bob qui compte pour le débat en cours.")
    [row] = stats.list_recent(ingest_db)
    assert (row["id"], row["participants"], row["messages"], row["claims"], row["status"]) == (debate.id, 1, 1, 0, "open")


# --- the pages ------------------------------------------------------------------------------------------------------------------------------


def fake_stats(people=14, claims_n=0, **overrides):
    verdicts = dict.fromkeys(claims.VERDICTS, 0)
    participants = [{"user_id": str(1000 + n), "position": ("for", "against", "unsure", None)[n % 4], "first_position": ("for", "for", "unsure", None)[n % 4], "changed": n % 4 == 1,
                     "messages": 20 - n, "share": round((20 - n) / 200, 3), "claims": dict.fromkeys(claims.VERDICTS, 0),
                     "key_message": {"message_id": str(9000 + n), "excerpt": f"Le *propos* numéro {n} du participant", "replies": n, "reactions": 1, "url": f"https://discord.com/channels/1/2/{9000 + n}"}}
                    for n in range(people)]
    checked_claims = [{"id": n, "message_id": str(8000 + n), "author_id": "1000", "claim": f"Une affirmation numéro {n} de _test_", "said": "x", "verdict": ("confirmed", "contradicted", "partly", "disputed", "unverifiable")[n % 5], "reason": None,
                       "period": "2026" if n % 2 else None, "queries": 1, "pages": 1, "model": "m", "checked_at": "2026-10-05T12:00:00",
                       "sources": [{"url": f"https://www.insee.fr/fr/{n}(a)", "title": "t", "tier": "official", "stance": "supports", "quote": "q" * 30, "page_period": None, "via": "x"}]}
                      for n in range(claims_n)]
    for c in checked_claims:
        verdicts[c["verdict"]] += 1
    base = {"debate": {"id": 7, "topic": "Le *nucléaire*", "context": None, "status": "closed", "close_reason": "ended", "in_thread": True, "verify": True, "quiet_seconds": 86_400,
                       "started_at": "2026-10-05T12:00:00+00:00", "closed_at": "2026-10-05T13:30:00+00:00", "guild_id": "1", "thread_id": "2"},
            "totals": {"participants": people, "messages": 200, "initial": {"for": 5, "unsure": 4, "against": 0, "none": 5}, "final": {"for": 4, "unsure": 4, "against": 3, "none": 3},
                       "changed_mind": 3, "verdicts": verdicts},
            "participants": participants, "claims": checked_claims, "parity": {"for": {**dict.fromkeys(claims.VERDICTS, 0), "confirmed": 2, "contradicted": 1, "total": 3}}}
    return {**base, **overrides}


def test_the_summary_says_why_it_ended_and_the_figures_and_what_was_checked():
    page = texts.stats_page(fake_stats(claims_n=5), 0)
    embed = page["embeds"][0]
    assert embed["title"] == "🏁 Débat terminé" and "terminé à la demande d'un modérateur" in embed["description"] and "Le \\*nucléaire\\*" in embed["description"]
    assert "**14** participant(s) · **200** message(s) · durée **1 h 30 min**" in embed["description"] and "période" not in embed["description"]
    assert "✅ Pour **4** · ❔ Ne sait pas **4** · ❌ Contre **3** · sans position **3**" in embed["description"]
    assert "3 personne(s) ont changé de position" in embed["description"] and "**5** affirmation(s) vérifiée(s)" in embed["description"]
    assert "le même critère pour tout le monde" in embed["footer"]["text"] and page["allowed_mentions"] == {"parse": []}
    assert "Aucune affirmation de fait n'a été vérifiée." in texts.stats_page(fake_stats(), 0, checks_on=True)["embeds"][0]["description"]
    assert "Aucune affirmation" not in texts.stats_page(fake_stats(), 0)["embeds"][0]["description"]


def test_a_debate_opened_without_verification_says_nothing_of_it_even_when_the_checks_are_on():
    unchecked = fake_stats()
    unchecked["debate"]["verify"] = False
    assert "affirmation" not in texts.stats_page(unchecked, 0, checks_on=True)["embeds"][0]["description"]


@pytest.mark.parametrize(("reason", "words"), [
    ("ended", "terminé à la demande"),
    ("silence", "Plus personne n'a écrit depuis un moment"),
    ("no_participants", "Personne n'a pris part"),
    ("failed", "Le débat est terminé."),
    (None, "Le débat est terminé."),
])
def test_each_way_a_debate_can_end_is_said_in_words(reason, words):
    found = fake_stats(people=2)
    found["debate"]["close_reason"] = reason
    assert words in texts.stats_page(found, 0)["embeds"][0]["description"]


@pytest.mark.parametrize(("seconds", "words"), [(0, "durée **1 s**"), (45, "durée **45 s**"), (89, "durée **89 s**"), (90, "durée **1 min**"), (3_600, "durée **1 h 0 min**"),
                                                 (5_400, "durée **1 h 30 min**"), (86_400 * 3 + 4 * 3_600 + 1_800, "durée **3 j 4 h**"), (86_400 * 40, "durée **40 j 0 h**")])
def test_how_long_the_debate_lasted_is_said_in_the_unit_that_fits(seconds, words):
    from datetime import UTC, datetime, timedelta

    found = fake_stats(people=2)
    start = datetime(2026, 10, 5, 12, tzinfo=UTC)
    found["debate"]["started_at"], found["debate"]["closed_at"] = start.isoformat(), (start + timedelta(seconds=seconds)).isoformat()
    assert words in texts.stats_page(found, 0)["embeds"][0]["description"]


def test_the_statistics_of_a_debate_opened_from_an_axis_use_its_poles_everywhere():
    found = fake_stats(people=3, claims_n=2)
    found["debate"]["axis"] = {"code": "structure", "name": "Structure", "for": "Fédéral", "against": "Unitaire"}
    summary = texts.stats_page(found, 0)["embeds"][0]["description"]
    assert "🔵 Fédéral **4** · ❔ Ne sait pas **4** · 🟠 Unitaire **3** · sans position **3**" in summary and "Pour" not in summary and "Contre" not in summary
    people = texts.stats_page(found, 1)["embeds"][0]["description"]
    assert "<@1001> — 🟠 Unitaire (avant : 🔵 Fédéral)" in people and "<@1000> — 🔵 Fédéral" in people and "✅" not in people
    assert "🔵 Fédéral : 3 vérifiée(s)" in texts.stats_page(found, 2)["embeds"][0]["description"]
    free = texts.stats_page(fake_stats(people=3), 0)["embeds"][0]["description"]
    assert "✅ Pour **4**" in free and "🔵" not in free                                                      # a free debate is unchanged


def test_a_debate_with_no_dates_says_no_duration_rather_than_a_wrong_one():
    found = fake_stats(people=2)
    found["debate"]["started_at"] = found["debate"]["closed_at"] = None
    assert "durée **—**" in texts.stats_page(found, 0)["embeds"][0]["description"]


def test_the_people_come_six_to_a_page_with_position_messages_and_the_message_picked_out():
    found = fake_stats(people=14)
    assert texts.stats_pages(found) == 1 + 3
    page = texts.stats_page(found, 1)
    embed = page["embeds"][0]
    assert embed["title"] == "👥 Les participants (1/3)" and embed["description"].count("<@") == 6
    assert "<@1001> — ❌ Contre (avant : ✅ Pour)" in embed["description"] and "<@1000> — ✅ Pour\n**20** message(s) (10 %)" in embed["description"]
    assert "> « Le \\*propos\\* numéro 0 du participant » · [message phare](https://discord.com/channels/1/2/9000) (0 réponse(s), 1 réaction(s))" in embed["description"]
    assert page["allowed_mentions"] == {"parse": []}                                                        # a mention shows the name and pings nobody
    assert texts.stats_page(found, 3)["embeds"][0]["description"].count("<@") == 2


def test_the_claims_pages_have_the_parity_table_the_verdicts_the_links_to_the_message_and_to_the_sources():
    found = fake_stats(people=3, claims_n=8)
    assert texts.stats_pages(found) == 1 + 1 + 2
    first = texts.stats_page(found, 2)["embeds"][0]
    assert first["title"] == "🔎 Affirmations vérifiées (1/2)" and "✅ Pour : 3 vérifiée(s) (2 confirmée, 1 contredite)" in first["description"]
    assert "✅ « Une affirmation numéro 0 de \\_test\\_ » : **confirmée** · [le message](https://discord.com/channels/1/2/8000) · [insee.fr](https://www.insee.fr/fr/0%28a%29)" in first["description"]
    assert "(2026)" in first["description"] and first["description"].count("« Une affirmation") == 6
    assert "**contredite**" in first["description"] and "**non vérifiable**" in first["description"] and "**contestée**" in first["description"]
    assert texts.stats_page(found, 3)["embeds"][0]["description"].count("« Une affirmation") == 2 and "Contre" not in texts.stats_page(found, 3)["embeds"][0]["description"]


def test_the_buttons_turn_the_pages_and_a_page_out_of_range_is_the_last_or_first():
    found = fake_stats(people=14)
    first, last = texts.stats_page(found, 0), texts.stats_page(found, 3)
    buttons = lambda page: {b["label"]: (b["custom_id"], b["disabled"]) for b in page["components"][0]["components"]}  # noqa: E731
    assert buttons(first) == {"Précédent": ("dindon:debat:stats:7:0", True), "Suivant": ("dindon:debat:stats:7:1", False)}
    assert buttons(last) == {"Précédent": ("dindon:debat:stats:7:2", False), "Suivant": ("dindon:debat:stats:7:3", True)}
    assert texts.stats_page(found, 99)["embeds"][0]["footer"]["text"].startswith("Page 4/4") and texts.stats_page(found, -5)["embeds"][0]["footer"]["text"].startswith("Page 1/4")
    assert all(texts.parse_custom_id(b["custom_id"]) for b in first["components"][0]["components"] + last["components"][0]["components"])
    assert texts.stats_page(fake_stats(people=0), 0)["components"] == []                                    # one page: nothing to turn


@pytest.mark.parametrize("raw", ["dindon:debat:stats:7:abc", "dindon:debat:stats:7:-1", "dindon:debat:stats:7:1234", "dindon:debat:stats:x:1", "dindon:debat:stats:7"])
def test_a_page_button_that_is_malformed_is_not_ours(raw):
    assert texts.parse_custom_id(raw) is None


def test_no_page_is_longer_than_discord_allows():
    found = fake_stats(people=60, claims_n=40)
    for n in range(texts.stats_pages(found)):
        embed = texts.stats_page(found, n)["embeds"][0]
        assert len(embed["description"]) <= 4000 and len(embed["title"]) <= 256 and len(embed["footer"]["text"]) <= 2048 and len(embed["description"]) + len(embed["footer"]["text"]) < 6000


# --- the closing message and its buttons --------------------------------------------------------------------------------------------------------


def stats_message(world, thread):
    [closing] = world.discord.posted(thread, "Débat terminé")
    return closing


def test_the_closing_message_is_the_first_page_with_buttons_and_a_click_shows_the_next_made_again_from_the_database(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    talk(world, thread, ingest_db, BOB, "Un message de Bob qui compte pour le débat en cours.")
    talk(world, thread, ingest_db, CAROL, "Un message de Carol qui compte pour le débat en cours.")
    ended(world, ingest_db, thread, debate)
    closing = stats_message(world, thread)
    assert "**2** participant(s) · **2** message(s)" in closing["embeds"][0]["description"]
    assert [b["label"] for b in closing["components"][0]["components"]] == ["Précédent", "Suivant", "Noter les participants"]
    privacy.stop_recording(ingest_db, CAROL_ID)                                                             # Carol stops after the message was posted…
    world.time.advance(seconds=3)
    run(world.interactions.answer(button(BOB_ID, thread, f"dindon:debat:stats:{debate.id}:1", id="901")))
    shown = world.sent.calls[-1]
    assert shown[:2] == ("POST", "/interactions/901/tok2/callback") and shown[2]["type"] == 7
    page = shown[2]["data"]
    assert page["embeds"][0]["title"].startswith("👥") and f"<@{BOB_ID}>" in page["embeds"][0]["description"] and f"<@{CAROL_ID}>" not in page["embeds"][0]["description"]   # …and is gone at the click


def test_a_debate_that_no_longer_exists_says_so_and_a_double_click_is_ignored(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    talk(world, thread, ingest_db, BOB, "Un message de Bob qui compte pour le débat en cours.")
    ended(world, ingest_db, thread, debate)
    custom_id = f"dindon:debat:stats:{debate.id}:1"
    world.time.advance(seconds=3)
    run(world.interactions.answer(button(BOB_ID, thread, custom_id, id="902")))
    count = len(world.sent.calls)
    run(world.interactions.answer(button(BOB_ID, thread, custom_id, id="903")))                             # the same second: a double click
    assert len(world.sent.calls) == count
    ingest_db.execute("DELETE FROM debates WHERE id = %s", (debate.id,))
    world.time.advance(seconds=3)
    run(world.interactions.answer(button(BOB_ID, thread, custom_id, id="904")))
    assert "n'existe plus" in world.sent.last()


# --- the closing waits for what is being read ---------------------------------------------------------------------------------------------------


def test_with_the_checks_on_the_closing_waits_for_the_messages_that_are_left_and_shows_what_was_checked(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    talk(checked, thread, ingest_db, BOB, "Le chômage est à 12 % en France, tout le monde le sait.")
    ended(checked, ingest_db, thread, debate)
    checked.tick(seconds=30)
    assert checked.discord.posted(thread, "Débat terminé") == []                                            # one message is still to be read: the statistics wait
    assert check(checked) is True                                                                           # it is read, even though the debate just ended
    checked.tick(seconds=3)
    closing = stats_message(checked, thread)
    assert "**1** affirmation(s) vérifiée(s) : 1 contredite" in closing["embeds"][0]["description"]
    assert [b["label"] for b in closing["components"][0]["components"]] == ["Précédent", "Suivant", "Noter les participants"]
    checked.time.advance(seconds=3)
    run(checked.interactions.answer(button(BOB_ID, thread, f"dindon:debat:stats:{debate.id}:2", id="905")))
    claims_page = checked.sent.calls[-1][2]["data"]["embeds"][0]
    assert claims_page["title"].startswith("🔎") and "**contredite**" in claims_page["description"] and EVIDENCE.url.split("/")[2].removeprefix("www.") in claims_page["description"]


def test_when_the_model_is_away_the_closing_is_posted_after_five_minutes_as_it_is(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    talk(checked, thread, ingest_db, BOB, "Le chômage est à 12 % en France, tout le monde le sait.")
    ended(checked, ingest_db, thread, debate)
    checked.tick(minutes=claims.GRACE_MINUTES - 1)
    assert checked.discord.posted(thread, "Débat terminé") == []
    checked.tick(minutes=2)
    assert "**1** participant(s)" in stats_message(checked, thread)["embeds"][0]["description"]


def test_without_the_checks_the_closing_is_not_delayed_and_says_nothing_of_claims(world, ingest_db):
    thread, debate = opened(world, ingest_db)
    talk(world, thread, ingest_db, BOB, "Un message de Bob qui compte pour le débat en cours.")
    ended(world, ingest_db, thread, debate)
    assert "affirmation" not in stats_message(world, thread)["embeds"][0]["description"]


def test_results_of_checked_claims_are_in_the_statistics_per_person_without_naming_anyone_in_the_list(checked, ingest_db):
    checked.checker.results = [RESULT, dataclasses.replace(RESULT, claim="La dette est sous les 50 % du PIB", verdict="unverifiable", reason="no_source", evidence=())]
    thread, debate = opened(checked, ingest_db)
    talk(checked, thread, ingest_db, BOB, "Le chômage est à 12 % en France, et la dette est sous les 50 % du PIB, c'est sûr.")
    check(checked)
    found = stats.collect(ingest_db, debate.id)
    assert found["participants"][0]["claims"]["contradicted"] == 1 and found["participants"][0]["claims"]["unverifiable"] == 1 and found["totals"]["verdicts"]["contradicted"] == 1
    people = texts.stats_page(found, 1)["embeds"][0]["description"]
    assert "vérifiées : 1 contredite, 1 non vérifiable" in people
    listing = texts.stats_page(found, 2)["embeds"][0]["description"]
    assert f"<@{BOB_ID}>" not in listing and "Bob" not in listing                                            # the list of claims links the messages, it does not point at the person
