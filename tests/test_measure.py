"""The measure of the checking of claims (docs/DEBAT.md « Mesure »): the reference set is well formed, and the figures are computed as they say.

Level of proof: SIMULATED (invented predictions). What these tests show is that the calculation is right; the figures of the real model are in docs/DEBAT.md, from a run of tools/measure_claims.py.
"""
import json
from pathlib import Path

import pytest

from dindon.debate import measure, reading

REFERENCE = json.loads((Path(__file__).resolve().parents[1] / "tools" / "claims_reference.json").read_text(encoding="utf-8"))
MESSAGES, CLAIMS = REFERENCE["messages"], REFERENCE["claims"]


def test_the_reference_set_is_well_formed():
    assert len({m["id"] for m in MESSAGES}) == len(MESSAGES) and len({c["id"] for c in CLAIMS}) == len(CLAIMS)
    assert all(len(m["text"]) >= reading.MIN_CHARS for m in MESSAGES), "a message shorter than the reader's minimum would never be read"
    assert sum(1 for m in MESSAGES if m["expect"]) >= 20 and sum(1 for m in MESSAGES if not m["expect"]) >= 15
    private = {m["category"] for m in MESSAGES if not m["expect"]}
    assert {"personne privée", "données personnelles", "opinion", "question", "prévision", "plaisanterie", "citation", "lien seul"} <= private
    assert {c["expected"] for c in CLAIMS} == {"confirmed", "contradicted", "unverifiable"}
    assert all(c["confidence"] in ("high", "medium") and c["query"] and len(c["claim"]) >= 15 for c in CLAIMS)
    assert "CHECKED BY A HUMAN" in REFERENCE["labelled_by"].upper()


def test_the_mirrored_pairs_have_two_camps_and_the_same_expected_verdict():
    pairs: dict[str, list[dict]] = {}
    for c in CLAIMS:
        if c["pair"]:
            pairs.setdefault(c["pair"], []).append(c)
    assert len(pairs) >= 5
    for name, members in pairs.items():
        assert len(members) == 2 and {m["side"] for m in members} == {"camp_1", "camp_2"} and len({m["expected"] for m in members}) == 1, name
    assert {m["expected"] for members in pairs.values() for m in members} == {"confirmed", "contradicted"}


def test_a_claim_matches_whatever_the_spaces_the_case_and_the_decimal_comma():
    assert measure.claim_matches("Le SMIC brut dépasse 1 800 euros", ["smic", "1800"])
    assert measure.claim_matches("L'inflation a atteint 5,2 % en 2022", ["inflation", "5.2"])
    assert not measure.claim_matches("Le SMIC brut dépasse 1 500 euros", ["smic", "1800"])


def perfect_reading() -> dict:
    return {m["id"]: [" ".join(group).capitalize() + " (selon le message)" for group in m["expect"]] for m in MESSAGES}


def test_a_perfect_reading_scores_one_and_leaks_nothing():
    scores = measure.score_reading(MESSAGES, perfect_reading())
    assert (scores["recall_of_claims"], scores["messages_fully_read"], scores["precision_of_claims"], scores["silent_messages_with_a_claim"]) == (1.0, 1.0, 1.0, 0.0)
    assert scores["private_leaks"] == [] and scores["missed"] == [] and scores["false_positives"] == []


def test_a_claim_found_about_a_private_person_is_a_leak_counted_on_its_own():
    found = perfect_reading()
    [private] = [m for m in MESSAGES if m["category"] == "données personnelles"]
    [opinion] = [m for m in MESSAGES if m["category"] == "opinion"][:1]
    found[private["id"]], found[opinion["id"]] = ["Jean habite à Lyon"], ["Le nucléaire est formidable"]
    scores = measure.score_reading(MESSAGES, found)
    assert [leak["id"] for leak in scores["private_leaks"]] == [private["id"]]
    assert {f["id"] for f in scores["false_positives"]} == {private["id"], opinion["id"]} and scores["silent_messages_with_a_claim"] > 0


def test_a_missed_claim_lowers_the_recall_and_is_named():
    found = perfect_reading()
    [first] = [m for m in MESSAGES if m["expect"]][:1]
    found[first["id"]] = []
    scores = measure.score_reading(MESSAGES, found)
    assert scores["recall_of_claims"] < 1 and [m["id"] for m in scores["missed"]] == [first["id"]]


def predictions(**overrides) -> dict:
    """Every claim right, except the ones given."""
    return {c["id"]: {"verdict": overrides.get(c["id"], c["expected"])} for c in CLAIMS}


def test_a_perfect_verification_is_ready_and_a_missing_prediction_counts_as_not_checked():
    scores = measure.score_verification(CLAIMS, predictions())
    assert (scores["precision_of_contradicted"], scores["recall_of_decisive"], scores["false_accusations"]) == (1.0, 1.0, [])
    assert scores["ready_for_live"] == {"ok": True, "precision": 1.0, "reasons": []}
    unchecked = measure.score_verification(CLAIMS, {})
    assert unchecked["contradicted_declared"] == 0 and unchecked["ready_for_live"]["ok"] is False


def test_declaring_a_true_claim_false_is_the_worst_error_and_blocks_the_public_corrections():
    true_claim = next(c for c in CLAIMS if c["expected"] == "confirmed")
    scores = measure.score_verification(CLAIMS, predictions(**{true_claim["id"]: "contradicted"}))
    assert [f["id"] for f in scores["false_accusations"]] == [true_claim["id"]] and scores["precision_of_contradicted"] < 1
    ready = scores["ready_for_live"]
    assert ready["ok"] is False and any("sur une affirmation vraie" in reason for reason in ready["reasons"])


def test_below_the_threshold_or_with_too_few_corrections_it_is_not_ready():
    false_claims = [c for c in CLAIMS if c["expected"] == "contradicted"]
    wrong = {c["id"]: "contradicted" for c in CLAIMS if c["expected"] == "unverifiable"}              # three corrections of what nobody can settle
    scores = measure.score_verification(CLAIMS, predictions(**wrong))
    assert scores["precision_of_contradicted"] == round(len(false_claims) / (len(false_claims) + 3), 4)
    few = measure.score_verification(CLAIMS[:3], {c["id"]: {"verdict": "contradicted"} for c in CLAIMS[:3]})
    assert any("au moins" in reason for reason in few["ready_for_live"]["reasons"])


def test_a_wrongly_cleared_false_claim_is_counted_and_an_abstention_is_not_an_error():
    false_claim = next(c for c in CLAIMS if c["expected"] == "contradicted")
    scores = measure.score_verification(CLAIMS, predictions(**{false_claim["id"]: "confirmed"}))
    assert [w["id"] for w in scores["wrongly_cleared"]] == [false_claim["id"]]
    abstain = measure.score_verification(CLAIMS, predictions(**{false_claim["id"]: "unverifiable"}))
    assert abstain["wrongly_cleared"] == [] and abstain["false_accusations"] == [] and abstain["abstained_on_decisive"] > 0


def test_the_two_camps_of_the_mirrored_pairs_are_scored_apart_and_a_gap_between_them_blocks():
    """The same standard for every camp: errors on one side only are caught, even when the overall precision looks fine."""
    pairs = [c for c in CLAIMS if c["pair"] and c["expected"] == "confirmed"]
    camp_2_true = [c for c in pairs if c["side"] == "camp_2"]
    scores = measure.score_verification(CLAIMS, predictions(**{c["id"]: "contradicted" for c in camp_2_true}))
    assert scores["precision_by_side"]["camp_2"] < scores["precision_by_side"]["camp_1"]
    assert scores["by_side"]["camp_2"]["wrong"] == len(camp_2_true) and scores["pairs"]["split"] >= len(camp_2_true)
    assert any("camp" in reason for reason in scores["ready_for_live"]["reasons"])


def test_the_report_says_the_figures_and_the_verdict_in_words():
    text = measure.report("verify", measure.score_verification(CLAIMS, predictions()))
    assert "PRÉCISION DE « CONTREDIT » : 100 %" in text and "PRÊT POUR LES CORRECTIONS PUBLIQUES : OUI" in text
    reading = measure.report("reading", measure.score_reading(MESSAGES, perfect_reading()))
    assert "FUITES" in reading and ": 0" in reading
    bad = measure.report("verify", measure.score_verification(CLAIMS, {}))
    assert "NON" in bad


@pytest.mark.parametrize("tool", ["measure_claims.py"])
def test_the_tool_scores_a_saved_file_without_any_model_or_network(tool, tmp_path, capsys, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import measure_claims

    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps({"kind": "verify", "predictions": predictions()}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["measure_claims.py", "score", "verify", str(saved)])
    measure_claims.main()
    assert "PRÊT POUR LES CORRECTIONS PUBLIQUES : OUI" in capsys.readouterr().out


# --- what Dindon says without the Internet (debate/local.py) ----------------------------------------------------------------------


def local_said(**overrides) -> dict:
    """Every claim answered as it should be (false for the false ones, true for the true ones, nothing for what nobody can settle), except the ones given."""
    right = {"contradicted": "false", "confirmed": "true", "unverifiable": "unsure"}
    return {c["id"]: {"verdict": overrides.get(c["id"], right[c["expected"]]), "answer": "La bonne information."} for c in CLAIMS}


def test_a_perfect_answer_without_the_internet_is_right_every_time_and_leaves_alone_what_nobody_can_settle():
    scores = measure.score_local(CLAIMS, local_said())
    assert (scores["precision_of_false"], scores["precision_of_true"], scores["coverage"], scores["recall_of_false"], scores["unverifiable_left_alone"]) == (1.0, 1.0, 1.0, 1.0, 1.0)
    assert scores["false_wrong"] == [] and scores["true_wrong"] == [] and scores["false_on_a_true_claim"] == 0


def test_saying_false_of_a_true_claim_is_the_worst_error_and_is_counted_apart():
    true_claim = next(c for c in CLAIMS if c["expected"] == "confirmed")
    scores = measure.score_local(CLAIMS, local_said(**{true_claim["id"]: "false"}))
    assert [f["id"] for f in scores["false_wrong"]] == [true_claim["id"]] and scores["false_on_a_true_claim"] == 1 and scores["precision_of_false"] < 1
    assert scores["false_wrong"][0]["answer"] == "La bonne information."


def test_saying_false_of_what_nobody_can_settle_is_wrong_too_but_not_an_accusation_of_a_true_claim():
    unsettled = next(c for c in CLAIMS if c["expected"] == "unverifiable")
    scores = measure.score_local(CLAIMS, local_said(**{unsettled["id"]: "false"}))
    assert [f["id"] for f in scores["false_wrong"]] == [unsettled["id"]] and scores["false_on_a_true_claim"] == 0 and scores["unverifiable_left_alone"] < 1


def test_letting_a_false_claim_pass_as_true_or_say_nothing_is_not_an_accusation_but_lowers_the_recall():
    false_claims = [c for c in CLAIMS if c["expected"] == "contradicted"]
    scores = measure.score_local(CLAIMS, local_said(**{false_claims[0]["id"]: "true", false_claims[1]["id"]: "unsure"}))
    assert [f["id"] for f in scores["true_wrong"]] == [false_claims[0]["id"]] and scores["precision_of_false"] == 1.0
    assert scores["recall_of_false"] == round((len(false_claims) - 2) / len(false_claims), 4) and scores["coverage"] < 1 and scores["precision_of_true"] < 1


def test_a_claim_that_was_not_answered_counts_as_not_sure_and_nothing_said_has_no_precision():
    scores = measure.score_local(CLAIMS, {})
    assert (scores["said_false"], scores["precision_of_false"], scores["coverage"], scores["recall_of_false"], scores["unverifiable_left_alone"]) == (0, None, 0.0, 0.0, 1.0)


def test_the_two_camps_of_the_mirrored_pairs_are_scored_apart_for_what_dindon_says_false():
    camp_2 = [c for c in CLAIMS if c.get("pair") and c["side"] == "camp_2" and c["expected"] == "confirmed"]
    scores = measure.score_local(CLAIMS, local_said(**{c["id"]: "false" for c in camp_2}))
    assert scores["precision_by_side"]["camp_2"] < scores["precision_by_side"]["camp_1"] and scores["by_side"]["camp_2"]["said_false"] > scores["by_side"]["camp_2"]["said_false_right"]


def test_the_report_of_the_local_answer_says_the_figures_and_names_each_error():
    true_claim = next(c for c in CLAIMS if c["expected"] == "confirmed")
    text = measure.report("local", measure.score_local(CLAIMS, local_said(**{true_claim["id"]: "false"})))
    assert "RÉPONSE SANS INTERNET" in text and "QUAND DINDON DIT « FAUX »" in text and "dont 1 sur une affirmation vraie" in text and f"! à tort {true_claim['id']}" in text and "PARITÉ" in text
    assert "! à tort" not in measure.report("local", measure.score_local(CLAIMS, local_said()))


def test_the_tool_scores_a_saved_local_file_without_any_model_or_network(tmp_path, capsys, monkeypatch):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import measure_claims

    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps({"kind": "local", "predictions": local_said()}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["measure_claims.py", "score", "local", str(saved)])
    measure_claims.main()
    assert "QUAND DINDON DIT « FAUX » : 100 %" in capsys.readouterr().out
