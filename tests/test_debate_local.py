"""Dindon's first answer to a claim, from its local model and without the Internet (docs/regles-du-bot.md, « Répondre d'abord, chercher ensuite »): what the CODE does with whatever a model says, and
how a message is shared between what Dindon answers itself and what goes on the Internet.

Level of proof: SIMULATED. The model is a script (it can lie, ramble or fail); no database, no network. These tests cannot show that a real model knows what it is asked: that is measured
separately (tools/measure_claims.py local, docs/regles-du-bot.md « Mesure »).
"""
import dataclasses
import logging
from pathlib import Path

import pytest

from dindon.analysis.ollama import OllamaError
from dindon.config import Settings
from dindon.analysis import irony
from dindon.debate import local
from dindon.debate.checker import Checker, build_checker, notice_mode, resolve_mode
from dindon.debate.claims import ClaimResult, Evidence
from dindon.debate.reading import Reading
from synthetic import settings_for

MESSAGE = "Le chômage est à 12 % en France, tout le monde le sait."
CLAIM = "Le taux de chômage en France est de 12 %"
READING = {"claims": [{"claim": CLAIM, "said": "Le chômage est à 12 % en France", "about_private_person": False, "personal_data": False, "query": "taux de chômage France"}]}
TWO = {"claims": [READING["claims"][0], {"claim": "La dette publique dépasse 110 % du PIB en France", "said": "la dette dépasse 110 % du PIB", "about_private_person": False,
                                          "personal_data": False, "query": "dette publique PIB France"}]}
FALSE = {"verdict": "false", "answer": "Le taux de chômage en France est de 7 %.", "certainty": 97}
WEB = ClaimResult(CLAIM, "Le chômage est à 12 % en France", "contradicted", None, "T2 2026", 1, 1, "m")


class Model:
    """A script for the local model: the first call reads the message, the next ones answer each claim in turn. Every call is recorded."""

    def __init__(self, *replies, relation="contradicts", recalled=None, tone="sincere"):
        self.replies, self.calls = list(replies), []
        self.irony = {"reasoning": "il le pense", "tone": tone, "certainty": 90}                     # the judgement of irony on a message that has claims (analysis/irony.py)
        self.relation, self.recalled = {"relation": relation}, recalled or {"fact": "", "certainty": 0}      # the two narrow questions that read a « false » again (local.py)

    def chat_json(self, model, system, user, schema, num_ctx=8192):
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema})
        if schema is irony.SCHEMA:
            return self.irony
        if schema is local.CHECK_SCHEMA:
            return self.relation
        if schema is local.RECALL_SCHEMA:
            return self.recalled
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Searching(Checker):
    """A checker whose search is a script (the real one reads pages: tests/test_debate_verify.py)."""

    def __init__(self, *args, found=WEB, **kwargs):
        super().__init__(*args, **kwargs)
        self.searched, self.found = [], found

    def search(self, reading, deep=False):
        self.searched.append(reading)
        return dataclasses.replace(self.found, claim=reading.claim)


def reading(claim=CLAIM) -> Reading:
    return Reading(claim, "le chômage est à 12 %", "taux de chômage France")


# --- what is done with what the model says ----------------------------------------------------------------------------------


def test_certain_it_is_true_certain_it_is_false_or_not_sure():
    assert local.answer_claim(Model({"verdict": "true", "answer": "", "certainty": 98}), "m", reading()) == local.Local("true")
    assert local.answer_claim(Model(FALSE), "m", reading()) == local.Local("false", "Le taux de chômage en France est de 7 %.")
    assert local.answer_claim(Model({"verdict": "unsure", "answer": "", "certainty": 20}), "m", reading()) == local.Local("unsure")


@pytest.mark.parametrize("said", [
    {"verdict": "banana", "answer": "Le taux est de 7 % en France.", "certainty": 99}, {"verdict": "", "answer": ""}, {"answer": "Le taux est de 7 % en France.", "certainty": 99}, {}, [], None, "false", 7,
    {"verdict": "false", "answer": "", "certainty": 99}, {"verdict": "false", "certainty": 99}, {"verdict": "false", "answer": "Non.", "certainty": 99}, {"verdict": "false", "answer": "x" * 401, "certainty": 99},
    {"verdict": "false", "answer": "Voir https://exemple.fr pour le vrai chiffre de la France.", "certainty": 99}, {"verdict": "false", "answer": "Voir www.insee.fr pour le vrai chiffre exact.", "certainty": 99},
    {"verdict": "false", "answer": "Le taux est de [membre] pour cent en France.", "certainty": 99}, {"verdict": "false", "answer": "Demandez à @quelqu'un le vrai chiffre exact.", "certainty": 99},
    {"verdict": "false", "answer": "<script>alert(1)</script> le chiffre exact", "certainty": 99},
])
def test_whatever_else_the_model_says_makes_dindon_say_nothing(said):
    assert local.answer_claim(Model(said), "m", reading()) == local.Local("unsure")


def test_a_sentence_is_tidied_and_a_true_or_unsure_answer_carries_no_sentence():
    assert local.answer_claim(Model({"verdict": "false", "answer": "  Le taux   est\nde 7 %  en France. ", "certainty": 95}), "m", reading()).answer == "Le taux est de 7 % en France."
    assert local.answer_claim(Model({"verdict": "TRUE", "answer": "Une phrase de trop sur l'affirmation.", "certainty": 95}), "m", reading()) == local.Local("true", None)
    assert local.answer_claim(Model({"verdict": " False ", "answer": FALSE["answer"], "certainty": 95}), "m", reading()).verdict == "false"


@pytest.mark.parametrize("claim", [
    "Le nucléaire représente plus de 50 % de la production d'électricité en France.", "Le SMIC brut mensuel est inférieur à 1 000 euros en France.", "Le chômage a dépassé 10 % en 2015 en France.",
    "Moins de la moitié des Français vivent en ville.", "La dette est au-dessus de 100 % du PIB.", "Il y a au moins 300 sénateurs.", "La population a doublé : c'est le double de 1900.", "Il y a une majorité de femmes.",
    "Le taux est > 5 % en France.", "Le prix est < 20 euros pour ce produit.",
])
def test_a_claim_that_compares_a_figure_with_a_threshold_needs_a_higher_certainty_from_the_model(claim):
    assert local.answer_claim(Model({**FALSE, "certainty": 85}), "m", reading(claim)) == local.Local("unsure")        # sure enough for a plain claim, not for a comparison
    assert local.answer_claim(Model({**FALSE, "certainty": 95, "answer": "Le chiffre exact est très différent de celui-là."}), "m", reading(claim)).verdict == "false"


@pytest.mark.parametrize("claim", ["Le Sénat compte 348 sénateurs.", "La capitale de l'Allemagne est Paris.", "Le droit de vote des femmes a été instauré en 1944.", "Le taux de chômage est de 12 %."])
def test_a_claim_with_a_plain_figure_or_fact_is_still_put_to_the_model(claim):
    model = Model({"verdict": "unsure", "answer": "", "certainty": 50})
    local.answer_claim(model, "m", reading(claim))
    assert len(model.calls) == 1


def test_a_model_that_is_not_certain_by_its_own_account_says_nothing_and_a_correction_that_keeps_the_figures_is_dropped():
    assert local.answer_claim(Model({**FALSE, "certainty": 79}), "m", reading()) == local.Local("unsure")
    assert local.answer_claim(Model({**FALSE, "certainty": 80}), "m", reading()).verdict == "false"
    assert local.answer_claim(Model({"verdict": "true", "answer": "", "certainty": 40}), "m", reading()) == local.Local("unsure")
    for certainty in ("beaucoup", None, -5, [90]):
        assert local.answer_claim(Model({**FALSE, "certainty": certainty}), "m", reading()) == local.Local("unsure")
    keeps = reading("Le Sénat compte 348 sénateurs.")
    assert local.answer_claim(Model({"verdict": "false", "answer": "Le Sénat compte 348 sénateurs en 2023, selon le chiffre exact.", "certainty": 99}), "m", keeps) == local.Local("unsure")
    assert local.answer_claim(Model({"verdict": "false", "answer": "Le Sénat compte 349 sénateurs depuis la dernière élection.", "certainty": 99}), "m", keeps).verdict == "false"
    spaced = reading("Le SMIC brut est de 1 800 euros par mois.")
    assert local.answer_claim(Model({"verdict": "false", "answer": "Le SMIC brut est de 1\u202f800 euros, et non l'inverse.", "certainty": 99}), "m", spaced) == local.Local("unsure")
    assert local.answer_claim(Model({"verdict": "false", "answer": "Le SMIC brut est de 5,5 euros par mois, pas davantage.", "certainty": 99}), "m", spaced).verdict == "false"


def test_the_model_is_blind_it_gets_the_claim_alone_and_a_failure_is_not_hidden():
    model = Model(FALSE)
    local.answer_claim(model, "qwen3:14b", reading())
    call = model.calls[0]
    assert [c["user"] for c in model.calls[1:]] == [f"AFFIRMATION : {CLAIM}\nCORRECTION : {FALSE['answer']}", "Question : taux de chômage France"]    # the second opinion sees the question alone
    assert call["model"] == "qwen3:14b" and call["user"] == f"Affirmation :\n«{CLAIM}»"                          # not who said it, not the message, not the debate, not the camps
    for word in ("débat", "camp", "pour", "contre", "auteur", "position"):
        assert word not in call["user"].lower()
    assert "certain" in (call["user"] + local.SYSTEM).lower() and "ne sais ni qui l'a dite" in local.SYSTEM
    with pytest.raises(OllamaError):
        local.answer_claim(Model(OllamaError("down")), "m", reading())                                          # the message stays unread and is tried again later


# --- a message shared between what Dindon answers and what goes on the Internet ---------------------------------------------------


PAGE = Evidence("https://blog.example/chomage", "Chômage", "other", "contradicts", "le taux de chômage s'établit à 7,3 % de la population active", "T2 2026", "searxng", "b" * 64)
NOTHING = ClaimResult(CLAIM, "Le chômage est à 12 % en France", "unverifiable", "no_source", None, 2, 3, "m")
PROVISIONAL = ClaimResult(CLAIM, "Le chômage est à 12 % en France", "likely_false", None, "T2 2026", 1, 2, "m", (PAGE,))
CONFIRMED = ClaimResult(CLAIM, "Le chômage est à 12 % en France", "confirmed", None, None, 1, 1, "m", (dataclasses.replace(PAGE, tier="official", stance="supports"),))
UNSURE = {"verdict": "unsure", "answer": "", "certainty": 30}


def checker(*replies, searching=True, mode="answer", found=WEB):
    if searching:
        return Searching(Model(*replies), "m", lambda: None, mode=mode, found=found)
    return Checker(Model(*replies), "m", None, mode=mode)


def test_a_claim_that_a_trusted_source_contradicts_is_a_result_to_be_corrected_as_certain_whatever_the_local_model_thought():
    for replies in ((READING, FALSE), (READING, UNSURE)):
        c = checker(*replies)
        found = c.consider(MESSAGE)
        assert found.answers == () and [(r.claim, r.verdict) for r in found.results] == [(CLAIM, "contradicted")] and [r.claim for r in c.searched] == [CLAIM]


def test_when_no_trusted_source_settles_a_claim_that_the_model_is_certain_is_false_dindon_answers_and_says_it_is_not_reliable_with_what_the_search_found():
    for found_result in (NOTHING, PROVISIONAL):
        c = checker(READING, FALSE, found=found_result)
        found = c.consider(MESSAGE)
        [answer] = found.answers
        assert (answer.claim, answer.said, answer.query, answer.verdict, answer.answer, answer.model, answer.basis) == (CLAIM, "Le chômage est à 12 % en France", "taux de chômage France", "false",
                                                                                                                    "Le taux de chômage en France est de 7 %.", "m", "model")
        assert answer.result.verdict == found_result.verdict and found.results == () and [r.claim for r in c.searched] == [CLAIM]
        assert len(c.llm.calls) == 5                                                                       # the reading, the tone of the message, the answer, and the two narrow questions that read a « false » again


def test_a_trusted_source_that_confirms_what_the_model_called_false_leaves_nothing_to_say_the_model_was_wrong():
    c = checker(READING, FALSE, found=CONFIRMED)
    found = c.consider(MESSAGE)
    assert found.answers == () and [r.verdict for r in found.results] == ["confirmed"]


def test_pages_that_are_not_trusted_sources_are_enough_for_a_first_opinion_marked_as_such_when_the_model_was_not_sure():
    c = checker(READING, UNSURE, found=PROVISIONAL)
    [answer] = c.consider(MESSAGE).answers
    assert (answer.verdict, answer.basis, answer.result.verdict) == ("false", "pages", "likely_false")
    assert answer.answer.startswith("D'après une page qui n'est pas une source de confiance : « le taux de chômage s'établit à 7,3 %") and len(answer.answer) <= 600


def test_a_claim_that_the_model_is_not_sure_of_and_that_nothing_settles_is_noted_and_nothing_is_said():
    c = checker(READING, UNSURE, found=NOTHING)
    found = c.consider(MESSAGE)
    assert found.answers == () and [r.verdict for r in found.results] == ["unverifiable"]
    likely_true = dataclasses.replace(PROVISIONAL, verdict="likely_true", evidence=(dataclasses.replace(PAGE, stance="supports"),))
    assert checker(READING, FALSE, found=likely_true).consider(MESSAGE).answers == ()                         # pages that suggest that it is TRUE: the model's « false » is not said


def test_a_claim_that_dindon_is_certain_is_true_is_noted_and_nothing_is_said_or_searched():
    c = checker(READING, {"verdict": "true", "answer": "", "certainty": 98})
    found = c.consider(MESSAGE)
    assert [(a.verdict, a.answer) for a in found.answers] == [("true", None)] and found.results == () and c.searched == []


def test_without_a_search_service_a_claim_that_dindon_is_certain_is_false_is_still_answered_and_the_rest_is_left_alone():
    c = checker(READING, FALSE, searching=False)
    [answer] = c.consider(MESSAGE).answers
    assert (answer.verdict, answer.result) == ("false", None) and c.can_search is False
    c = checker(READING, {"verdict": "unsure", "answer": ""}, searching=False)
    found = c.consider(MESSAGE)
    assert found.answers == () and found.results == () and c.can_search is False


def test_each_claim_of_a_message_is_dealt_with_on_its_own():
    c = checker(TWO, FALSE, UNSURE, found=NOTHING)
    found = c.consider("Le chômage est à 12 % en France, et la dette dépasse 110 % du PIB, c'est sûr.")
    assert [a.claim for a in found.answers] == [CLAIM] and [r.claim for r in found.results] == ["La dette publique dépasse 110 % du PIB en France"]


def test_a_message_with_nothing_to_check_asks_the_local_model_nothing_more():
    c = checker({"claims": []})
    found = c.consider("Je trouve que ce serait plus juste autrement, honnêtement.")
    assert found.answers == () and found.results == () and len(c.llm.calls) == 1                                   # read, found nothing: no answer was asked for
    assert checker().consider("Trop court").answers == ()                                                          # (too short to hold a claim: the model is not even asked to read it)


def test_a_model_that_fails_while_answering_leaves_the_message_unread():
    c = checker(READING, OllamaError("down"))
    with pytest.raises(OllamaError):
        c.consider(MESSAGE)


def test_checking_without_answering_is_what_it_was_every_claim_on_the_internet():
    c = checker(READING)
    assert [r.claim for r in c.check(MESSAGE)] == [CLAIM] and len(c.llm.calls) == 2                               # the reading and the tone of the message; the observation mode never asks the model what it knows


def test_the_search_asked_by_the_participants_needs_a_search_service():
    assert checker().can_search is True and checker(searching=False).can_search is False


# --- the modes: what is on, and what is said of it ------------------------------------------------------------------------


def settings(**changes) -> Settings:
    return dataclasses.replace(settings_for("postgresql://x", Path("/tmp/none")), **changes)


def test_answer_works_without_a_search_service_and_says_so_while_observe_has_nothing_to_do_without_one(caplog):
    with caplog.at_level(logging.WARNING, logger="dindon.bot.debate"):
        assert build_checker(settings(debate_checks="observe")) is None
        answering = build_checker(settings(debate_checks="answer"))
        asked_live = build_checker(settings(debate_checks="live", debate_precision=0.95))
    assert (answering.mode, answering.can_search, notice_mode(answering)) == ("answer", False, "local")
    assert (asked_live.mode, asked_live.can_search) == ("answer", False)                                         # `live` is corrections by sources: it needs sources to look up
    assert "answers from its local model only" in caplog.text


@pytest.mark.parametrize(("asked", "precision", "mode", "told"), [("observe", None, "observe", "observe"), ("answer", None, "answer", "answer"), ("live", None, "answer", "answer"),
                                                                    ("live", 0.8, "answer", "answer"), ("live", 0.95, "live", "live")])
def test_with_a_search_service_each_mode_is_what_was_asked_unless_the_lock_says_otherwise(asked, precision, mode, told):
    built = build_checker(settings(searxng_url="http://127.0.0.1:9", debate_checks=asked, debate_precision=precision))
    assert (built.mode, notice_mode(built), built.can_search) == (mode, told, True)


def test_the_settings_read_answer_and_nothing_else_unknown(monkeypatch):
    from dindon import config

    monkeypatch.setattr(config, "_load_dotenv", lambda path: None)
    for value, expected in (("answer", "answer"), (" Answer ", "answer"), ("répondre", "off"), ("answers", "off"), ("", "off")):
        monkeypatch.setenv("DINDON_DEBATE_CHECKS", value)
        assert config.load_settings().debate_checks == expected


def test_a_false_that_only_restates_the_claim_is_dropped_and_so_is_one_that_a_blind_second_opinion_contradicts():
    assert local.answer_claim(Model(FALSE, relation="same"), "m", reading()) == local.Local("unsure")                                 # the « correction » says what the claim says
    assert local.answer_claim(Model(FALSE, relation="unrelated"), "m", reading()) == local.Local("unsure")
    assert local.answer_claim(Model(FALSE, recalled={"fact": "Le chômage est à 12 % en France.", "certainty": 90}, relation="same"), "m", reading()) == local.Local("unsure")
    assert local.answer_claim(Model(FALSE, recalled={"fact": "Le chômage est à 7 % en France.", "certainty": 90}), "m", reading()).verdict == "false"


@pytest.mark.parametrize("answer", ["Le taux est généralement estimé autour de 7 %.", "Il n'y a pas de preuve que ce taux soit de 12 %.", "Cela dépend de la source et de la période choisie."])
def test_a_correction_that_hedges_is_not_a_correction(answer):
    assert local.answer_claim(Model({**FALSE, "answer": answer}), "m", reading()) == local.Local("unsure")
