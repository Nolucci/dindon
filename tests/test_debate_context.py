"""What was said just before a message of a debate, given to the model so that it reads the message the way it was meant (debate/context.py), and what the reading does with it.

Level of proof: SIMULATED for the model (a script), REAL for the database (the messages are stored by the ingestion, the window is read from them). What these tests show is what the CODE
puts in front of the model and what it keeps of its answer; whether a real model understands irony better with the context is measured apart (tools/measure_claims.py reading --with-context).
"""
import pytest

from dindon.debate import context, reading
from dindon.debate.context import Said, render, tidy
from dindon.debate.reading import CONTEXT_RULES, read_message

from gateway_fixtures import ALICE, BOB, CAROL
from test_debate_bot import ALICE_ID, BOB_ID, CAROL_ID
from test_debate_checks import checked, opened, said  # noqa: F401  (the fixture and the helpers of the debate tests)


def test_the_window_is_a_few_lines_with_anonymous_authors_and_the_parent_of_a_reply():
    before = [Said(1, 10, "Le chômage est à 25 % en France."), Said(2, 11, "Tu es sûr ?", 1, "Le chômage est à 25 % en France.", 10), Said(3, 10, "Oui.", 2)]
    text = render(before, 11, 3)
    assert text.splitlines() == ["M1 | U1 | Le chômage est à 25 % en France.", "M2 | U2 | Tu es sûr ? | reply:M1", "M3 | U1 | Oui. | reply:M2", "", "Message à lire : écrit par U2, en réponse à M3."]
    assert "10" not in text.replace("25", "") and "11" not in text                                       # never an id of a person, never a name


def test_a_parent_that_is_out_of_the_window_is_a_reference_and_a_bot_is_not_a_person():
    text = render([Said(5, 99, "Question du débat ?", bot=True)], 10, 4, "Un message plus ancien", 12)
    assert text.splitlines() == ["M1 | Bot | Question du débat ?", "R1 | U2 | Un message plus ancien", "", "Message à lire : écrit par U1, en réponse à R1."]


def test_without_anything_before_there_is_no_context_and_the_message_stands_alone():
    assert render([], 10) == ""


def test_what_goes_in_is_tidied_mentions_links_quotes_and_length():
    assert tidy("Voir <@123456789> sur https://exemple.fr <#42>\n> ce que dit un autre\nla suite") == "Voir [membre] sur [lien] [salon] la suite"
    assert len(tidy("x" * 1000)) == context.LINE_CHARS and tidy("x" * 1000).endswith("…")


CLAIMS = {"claims": [{"claim": "Le chômage est de 25 % en France", "said": "Oui exactement, 25 %", "about_private_person": False, "personal_data": False, "query": "chômage France 25 %", "author_asserts": True}]}


class Model:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat_json(self, model, system, user, schema, num_ctx=8192):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self.reply


def test_with_a_context_the_model_is_told_it_is_data_and_the_claim_must_still_be_said_in_the_message():
    model = Model(CLAIMS)
    ctx = render([Said(1, 10, "Le chômage est à 25 % en France.")], 11)
    [found] = read_message(model, "m", "Oui exactement, 25 %.", ctx)
    assert found.claim == "Le chômage est de 25 % en France" and found.said == "Oui exactement, 25 %"
    [call] = model.calls
    assert call["system"].endswith(CONTEXT_RULES) and "DONNÉES" in CONTEXT_RULES and ctx in call["user"] and call["user"].endswith("«Oui exactement, 25 %.»")
    assert "author_asserts" in call["schema"]["properties"]["claims"]["items"]["properties"]
    # a claim whose words are only in the context is not noted: the context helps to understand, it does not provide claims
    model.reply = {"claims": [{**CLAIMS["claims"][0], "said": "Le chômage est à 25 % en France"}]}
    assert read_message(model, "m", "Oui exactement, 25 %.", ctx) == []


def test_what_the_author_quotes_mocks_or_asks_is_not_noted_but_only_when_there_is_a_context():
    item = {**CLAIMS["claims"][0], "author_asserts": False}
    ctx = render([Said(1, 10, "Le chômage est à 25 % en France.")], 11)
    assert read_message(Model({"claims": [item]}), "m", "Oui exactement, 25 %.", ctx) == []
    plain = Model({"claims": [{k: v for k, v in item.items() if k != "author_asserts"}]})
    assert len(read_message(plain, "m", "Oui exactement, 25 %.")) == 1                                    # without context: the reading is the blind one of before
    assert "author_asserts" not in plain.calls[0]["schema"]["properties"]["claims"]["items"]["properties"] and CONTEXT_RULES not in plain.calls[0]["system"]


def test_the_unread_message_comes_with_what_was_said_before_and_nothing_of_a_person_who_asked_not_to_be_recorded(checked, ingest_db):
    thread, debate = opened(checked, ingest_db)
    first = said(checked, thread, ingest_db, BOB, "Le chômage est à 25 % en France.")
    said(checked, thread, ingest_db, CAROL, "Ceci vient de quelqu'un qui ne veut plus être enregistré.")
    last = said(checked, thread, ingest_db, ALICE, "Oui exactement, 25 %.")
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (CAROL_ID,))
    from dindon.debate import claims

    unread = {u.message_id: u for u in claims.next_unread(ingest_db, 30)}
    assert unread[first].context == ""                                                                    # the first message of the thread stands alone
    assert unread[last].context.splitlines()[0] == "M1 | U1 | Le chômage est à 25 % en France."
    assert "Message à lire : écrit par U2" in unread[last].context
    for private in ("Bob", "Carol", "quelqu'un", str(BOB_ID), str(CAROL_ID), str(ALICE_ID)):
        assert private not in unread[last].context                                                       # no name, no id, nothing of a person who asked to stop
