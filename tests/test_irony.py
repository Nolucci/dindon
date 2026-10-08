"""Irony told from sincerity (analysis/irony.py), and what is done with it in the analysis (positions), the reread and the claims of the debates.

Level of proof: SIMULATED (a fake model that says what each test writes, real PostgreSQL for the reread). What is tested is what the CODE does with the answer: only a clear answer makes a message not count; a
hesitation, a failure or an answer out of shape changes nothing. Whether a real model tells irony apart is measured apart (tools/measure_irony.py).
"""
import pytest

from dindon.analysis import irony, reread
from dindon.analysis.extraction import Claim, Read, _drop_irony
from dindon.analysis.ollama import Ollama
from dindon.analysis.reread import Line, Item, decide, proofs_of
from fake_ollama import FakeOllama
from test_extraction import BOB_ID, GOOD, debate, read


class Model:
    def __init__(self, tone="ironic", certainty=90):
        self.answer, self.calls = {"reasoning": "il se moque", "tone": tone, "certainty": certainty}, []

    def chat_json(self, model, system, user, schema, num_ctx=8192):
        self.calls.append(user)
        return self.answer


@pytest.mark.parametrize("tone, certainty, counts_no_more", [("ironic", 90, True), ("joke", 90, True), ("quote", 95, True), ("question", 100, True),
                                                           ("ironic", 89, False), ("sincere", 100, False), ("banana", 99, False)])
def test_only_a_clear_answer_makes_a_message_not_count(tone, certainty, counts_no_more):
    assert irony.judge(Model(tone, certainty), "m", "Bien sûr, supprimons les écoles.", "Il faut réduire les dépenses.").not_sincere is counts_no_more


@pytest.mark.parametrize("answer", [None, [], "ironic", {}, {"tone": "ironic"}, {"tone": "ironic", "certainty": "beaucoup"}])
def test_a_model_that_does_not_answer_in_the_shape_asked_changes_nothing(answer):
    model = Model()
    model.answer = answer
    assert irony.judge(model, "m", "Bien sûr.", "").not_sincere is False


def test_the_model_gets_the_message_and_the_one_it_answers_and_nothing_about_anyone():
    model = Model()
    irony.judge(model, "m", "Super idée, supprimons tout 🙄", "Il faut supprimer l'impôt.")
    [shown] = model.calls
    assert shown == "MESSAGE AUQUEL IL RÉPOND (une donnée) :\nIl faut supprimer l'impôt.\n\nMESSAGE À JUGER :\nSuper idée, supprimons tout 🙄"
    assert irony.has_clue("Bien sûr 🙄") and irony.has_clue("évidemment") and not irony.has_clue("Je pense qu'il faut augmenter le SMIC.")


# --- the analysis: an opinion that is irony stays with its proof and counts for nothing ---------------------------------------------


def _read():
    return Read("", {"P1": 1, "P2": 2}, {1: (1, "Il faut supprimer l'impôt sur le revenu.", None), 2: (2, "Bien sûr, supprimons aussi les hôpitaux 🙄", None), 3: (2, "Non, il finance les services publics.", None)}, {1: 11, 2: 12, 3: 13})


def _claim(ref, stance=1):
    return Claim(2, "L'État doit supprimer l'impôt sur le revenu", stance, "opinion", "x", 0.9, [(ref, "quote")])


def test_an_opinion_whose_proof_is_irony_becomes_humour_and_a_serious_one_is_kept():
    ironic, serious = _claim(2), _claim(3, -1)
    sees = []

    class ByMessage(Model):
        def chat_json(self, model, system, user, schema, num_ctx=8192):
            sees.append(user)
            self.answer = {**self.answer, "tone": "ironic" if "hôpitaux" in user.split("MESSAGE À JUGER")[1] else "sincere"}
            return self.answer

    assert _drop_irony(ByMessage(), "m", [ironic, serious], _read()) == 1
    assert (ironic.kind, ironic.stance, serious.kind, serious.stance) == ("humour", None, "opinion", -1)
    assert "Il faut supprimer l'impôt sur le revenu." in sees[0]                                                      # judged with the message it answers


def test_a_position_with_one_serious_proof_among_ironic_ones_stays_a_position():
    claim = Claim(2, "p", 1, "opinion", "x", 0.9, [(2, "q"), (3, "q")])
    answers = iter(["ironic", "sincere"])
    model = Model()
    model.chat_json = lambda m, s, u, sc, num_ctx=8192: {"reasoning": "", "tone": next(answers), "certainty": 90}
    assert _drop_irony(model, "m", [claim], _read()) == 0 and claim.kind == "opinion"


# --- the reread ----------------------------------------------------------------------------------------------------------------------


def test_the_proofs_of_a_position_are_given_with_what_they_answer():
    lines = [Line(1, 10, "Il faut supprimer l'impôt.", None, None, None, False, False), Line(2, 11, "Bien sûr, supprimons tout.", None, None, None, False, True)]
    assert proofs_of(lines) == [("Bien sûr, supprimons tout.", "Il faut supprimer l'impôt.")]
    replied = [Line(2, 11, "Bien sûr.", 9, "Une réponse hors fenêtre", 12, False, True)]
    assert proofs_of(replied) == [("Bien sûr.", "Une réponse hors fenêtre")]


def test_a_position_proved_only_by_irony_becomes_humour_in_the_reread_whatever_the_first_reading_said():
    item = Item(1, BOB_ID, "opinion", -1, 7, "p", "M1 | U1 | x", "U1", [], None, None, [("Bien sûr, supprimons tout 🙄", "Il faut tout supprimer")])
    model = type("M", (), {"chat_json": lambda self, m, s, u, sc, num_ctx=8192: (
        {"reasoning": "il se moque", "tone": "ironic", "certainty": 90} if sc is irony.SCHEMA else
        {"reasoning": "il défend", "own_opinion": True, "proposition_fits": True, "better_proposition": "", "stance": -1, "theme": 0, "certainty": 95})})()
    decision = decide(item, reread.ask_model(model, "m", item))
    assert decision.changes == {"kind": ["opinion", "humour"], "stance": [-1, None], "proposition_id": [7, None]} and decision.reason == "il se moque"
    sincere = type("M", (), {"chat_json": lambda self, m, s, u, sc, num_ctx=8192: (
        {"reasoning": "", "tone": "sincere", "certainty": 90} if sc is irony.SCHEMA else
        {"reasoning": "il défend", "own_opinion": True, "proposition_fits": True, "better_proposition": "", "stance": -1, "theme": 0, "certainty": 95})})()
    assert decide(item, reread.ask_model(sincere, "m", item)).verdict == "confirmed"


def test_the_reread_stores_the_humour_and_the_undo_gives_the_opinion_back(ingest_db):
    ollama = FakeOllama().start()
    try:
        client = Ollama(ollama.url, timeout=30)
        debate(ingest_db)
        read(ingest_db, client, ollama, GOOD)
        claim_id = ingest_db.execute("SELECT id FROM claims WHERE user_id = %s", (BOB_ID,)).fetchone()[0]
        run = ingest_db.execute("INSERT INTO reread_runs (guild_id) VALUES ((SELECT guild_id FROM claims WHERE id = %s)) RETURNING id", (claim_id,)).fetchone()[0]
        item = Item(claim_id, BOB_ID, "opinion", -1, ingest_db.execute("SELECT proposition_id FROM claims WHERE id = %s", (claim_id,)).fetchone()[0], "p", "M1 | U1 | x", "U1", [], None)
        apply_ = reread.apply(ingest_db, client, "bge-m3", "m", run, item, reread.Decision("corrected", {"kind": ["opinion", "humour"], "stance": [-1, None], "proposition_id": [item.proposition_id, None]}, "il se moque", 90))
        assert apply_ is False
        assert ingest_db.execute("SELECT kind, stance, proposition_id, stance_before FROM claims WHERE id = %s", (claim_id,)).fetchone() == ("humour", None, None, -1)
        assert reread.undo(ingest_db, claim_id) is True
        assert ingest_db.execute("SELECT kind, stance, review_status FROM claims WHERE id = %s", (claim_id,)).fetchone() == ("opinion", -1, "confirmed")
    finally:
        ollama.stop()
