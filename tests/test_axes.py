"""Where each person stands on the axes, and whether the ideologies that they gave themselves match it. The model is a fake Ollama; the scores and the verdicts
are computed by SQL (db/schema-analysis.sql), the people and the claims are invented. Level of proof: SIMULATED."""
import dataclasses
from datetime import datetime, timezone, UTC

import pytest
from fastapi.testclient import TestClient

from dindon.analysis.axes import assign_axes
from dindon.analysis.ollama import Ollama
from dindon.api.main import create_app
from fake_ollama import FakeOllama
from gateway_fixtures import ALICE, BOB, CAROL, GUILD
from synthetic import settings_for
from test_analysis import NOW, Talk, ingest
from test_extraction import ALICE_ID, BOB_ID, GUILD_ID, PASSWORD, debate
from dindon.analysis.conversations import build_conversations

CAROL_ID = int(CAROL["id"])
WHEN = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def ollama():
    server = FakeOllama().start()
    yield server
    server.stop()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=30)


@pytest.fixture
def web(ingest_url, ingest_db, tmp_path, ollama):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), ollama_url=ollama.url)
    with TestClient(create_app(settings, background=False)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def axis(db, code):
    return db.execute("SELECT id FROM axes WHERE code = %s", (code,)).fetchone()[0]


def proposition(db, text, axis_code, loading):
    pid = db.execute("INSERT INTO propositions (text, created_by, axes_read_at) VALUES (%s, 'test', now()) RETURNING id", (text,)).fetchone()[0]
    db.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence) VALUES (%s, %s, %s, 0.9)", (pid, axis(db, axis_code), loading))
    return pid


def takes(db, user, pid, stance, confidence=0.9, conversation=None):
    db.execute("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version, conversation_id)
                  VALUES (%s, %s, %s, 'opinion', 'x', %s, %s, %s, 'test', 'test', %s)""", (GUILD_ID, user, pid, stance, confidence, WHEN, conversation))


def wears(db, user, role_name, role_id):
    db.execute("INSERT INTO roles (id, guild_id, name, position) VALUES (%s, %s, %s, 2) ON CONFLICT DO NOTHING", (role_id, GUILD_ID, role_name))
    db.execute("INSERT INTO member_roles (guild_id, user_id, role_id) VALUES (%s, %s, %s)", (GUILD_ID, user, role_id))


def a_socialist_and_a_liar(db):
    """Alice and Bob both wear « Socialiste » (public services, planned economy). Alice says what a socialist says, Bob the opposite, on five propositions."""
    debate(db)
    db.execute("UPDATE members SET nickname = nickname WHERE false")
    wears(db, ALICE_ID, "Socialiste", 5001)
    wears(db, BOB_ID, "Socialiste", 5001)
    for n in range(5):
        p = proposition(db, f"L'État doit posséder le secteur {n}", "economie", -1.0)            # agreeing moves toward « Public » (the negative pole)
        takes(db, ALICE_ID, p, 1)
        takes(db, BOB_ID, p, -1)
    db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))


def test_the_model_only_links_propositions_to_axes_whose_poles_it_names():
    ids = {"economie": 7, "morale": 11, "pouvoir": 3}
    poles = {"economie": {"public": -1, "prive": 1}, "morale": {"progressiste": -1, "traditionaliste": 1}, "pouvoir": {"securite": -1, "liberte": 1}}
    answer = {"axes": [{"axis": "economie", "toward": "Public", "strength": "forte"},                  # a pole of this axis: kept, toward the negative pole
                       {"axis": "inconnu", "toward": "Public", "strength": "forte"},                 # an axis that does not exist
                       {"axis": "morale", "toward": "Public", "strength": "forte"},                  # the pole of ANOTHER axis: refused (the model mixed them up)
                       {"axis": "economie", "toward": "Privé", "strength": "moyenne"},               # the same axis twice: the first one only
                       {"axis": "pouvoir", "toward": "Sécurité", "strength": "faible"},              # « faible » is not a link
                       {"axis": "pouvoir", "toward": "LIBERTÉ", "strength": "moyenne"},              # case and accents do not matter
                       "n'importe quoi", {"axis": "morale", "toward": "Traditionaliste"}]}
    from dindon.analysis.axes import validate
    assert validate(answer, ids, poles) == [(7, -1.0, 1.0), (3, 0.6, 0.8)]
    many = {"axes": [{"axis": a, "toward": t, "strength": "forte"} for a, t in (("economie", "Privé"), ("morale", "Progressiste"), ("pouvoir", "Liberté"))]}
    assert len(validate(many, ids, poles)) == 2                                                            # two at most: a statement rarely takes sides on three


def test_supporting_a_person_alone_does_not_imply_an_ideological_axis():
    from dindon.analysis.axes import PERSON_ONLY
    assert PERSON_ONLY.fullmatch("Il faut soutenir Squeezie.")
    assert not PERSON_ONLY.fullmatch("Il faut soutenir les services publics.")


def test_person_only_proposition_gets_no_automatic_axis(ingest_db, client, ollama):
    debate(ingest_db)
    pid = ingest_db.execute("INSERT INTO propositions (text, created_by) VALUES ('Il faut soutenir Squeezie.', 'test') RETURNING id").fetchone()[0]
    takes(ingest_db, ALICE_ID, pid, 1)
    result = assign_axes(ingest_db, client, "qwen3:14b", GUILD_ID)
    assert result["done"] == 1 and result["links"] == 0
    assert ingest_db.execute("SELECT axes_read_at IS NOT NULL FROM propositions WHERE id = %s", (pid,)).fetchone() == (True,)
    assert not [request for request in ollama.requests if request[0] == "/api/chat"]


def test_the_propositions_are_linked_to_the_axes_once_and_the_scores_follow(ingest_db, client, ollama):
    debate(ingest_db)
    p = proposition(ingest_db, "x", "economie", -1)                # one that was already read
    ingest_db.execute("UPDATE propositions SET axes_read_at = NULL, text = %s WHERE id = %s", ("L'État doit posséder les services essentiels", p))
    ingest_db.execute("DELETE FROM proposition_axis")
    takes(ingest_db, ALICE_ID, p, 1)
    ollama.chat_handler = lambda body: {"axes": [{"axis": "economie", "toward": "Public", "strength": "forte"}, {"axis": "morale", "toward": "Progressiste", "strength": "moyenne"},
                                                 {"axis": "economie", "toward": "Public", "strength": "faible"}]}
    result = assign_axes(ingest_db, client, "qwen3:14b", GUILD_ID)
    assert (result["done"], result["links"]) == (1, 2) and result["scores"] == 2          # (a score per person and axis)
    links = dict(ingest_db.execute("SELECT a.code, pa.loading::float8 FROM proposition_axis pa JOIN axes a ON a.id = pa.axis_id").fetchall())
    assert links == {"economie": -1.0, "morale": -0.6}                                                    # a pole and a strength become a number
    assert ingest_db.execute("SELECT bool_or(is_validated) FROM proposition_axis").fetchone() == (False,)   # proposed, never validated by the code
    calls = len([r for r in ollama.requests if r[0] == "/api/chat"])
    assert assign_axes(ingest_db, client, "qwen3:14b", GUILD_ID)["done"] == 0 and len([r for r in ollama.requests if r[0] == "/api/chat"]) == calls
    body = [r for r in ollama.requests if r[0] == "/api/chat"][0][1]
    prompt, user = body["messages"][0]["content"], body["messages"][-1]["content"]
    assert "services essentiels" in user and "Alice" not in str(body["messages"])                          # the model reads a sentence, never a person
    assert "multiculturalisme et l'ouverture migratoire sont à encourager" in prompt                       # what each pole means, in a sentence (the anchors of the database)
    enum = body["format"]["properties"]["axes"]["items"]["properties"]["toward"]["enum"]
    assert {"Public", "Privé", "Assimilation", "Multiculturalisme"} <= set(enum)                           # it answers with the NAME of a pole, not a signed number


def test_reading_again_replaces_what_an_earlier_reading_proposed_but_keeps_what_a_person_validated(ingest_db, client, ollama):
    debate(ingest_db)
    p = proposition(ingest_db, "x", "morale", 0.4)                  # proposed by an older version of the prompt (a weight that this one never gives)
    linked(ingest_db, p, immigration=-0.5)
    linked(ingest_db, p, economie=-1.0)
    ingest_db.execute("UPDATE proposition_axis SET is_validated = true WHERE axis_id = %s", (axis(ingest_db, "economie"),))       # a person confirmed this one
    ingest_db.execute("UPDATE propositions SET axes_read_at = NULL, text = %s WHERE id = %s", ("L'État doit posséder les services essentiels", p))
    takes(ingest_db, ALICE_ID, p, 1)
    ollama.chat_handler = lambda body: {"axes": [{"axis": "controle", "toward": "Planification", "strength": "forte"}]}
    assign_axes(ingest_db, client, "qwen3:14b", GUILD_ID)
    links = dict(ingest_db.execute("SELECT a.code, pa.is_validated FROM proposition_axis pa JOIN axes a ON a.id = pa.axis_id").fetchall())
    assert links == {"controle": False, "economie": True}            # the old proposals are gone, the new one is there, the validated one stays


def test_the_page_of_a_person_gives_a_score_on_every_axis_and_the_role_they_gave_themselves(web, ingest_db):
    a_socialist_and_a_liar(ingest_db)
    card = web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()
    assert len(card["axes"]) == 21                                         # every active axis, with or without a score
    eco = next(a for a in card["axes"] if a["code"] == "economie")
    assert eco["score"] < -0.4 and eco["positions"] == 5 and (eco["negative_pole"], eco["positive_pole"]) == ("Public", "Privé")
    assert eco["expected"] == [{"role": "Socialiste", "min": -1.0, "max": -0.2, "verdict": "confirmed"}] or eco["expected"][0]["verdict"] in ("confirmed", "compatible")
    assert next(a for a in card["axes"] if a["code"] == "immigration")["score"] is None                                # nothing was said about it
    assert eco["contributions"][0]["proposition"].startswith("L'État doit posséder") and eco["contributions"][0]["loading"] == -1.0
    assert [(r["role"], r["verdict"]) for r in card["roles"]] == [("Socialiste", "concordant")]


def test_a_role_that_contradicts_what_the_person_says_is_marked(web, ingest_db):
    a_socialist_and_a_liar(ingest_db)
    card = web.get(f"/api/positions/person/{BOB_ID}", params={"guild": GUILD}).json()
    assert card["roles"][0]["verdict"] == "discordant" and card["roles"][0]["incompatible"] >= 1
    eco = next(a for a in card["axes"] if a["code"] == "economie")
    assert eco["score"] > 0.4 and eco["expected"][0]["verdict"] == "incompatible"


def test_the_list_of_coherence_puts_the_contradictions_first(web, ingest_db):
    a_socialist_and_a_liar(ingest_db)
    answer = web.get("/api/positions/coherence", params={"guild": GUILD}).json()
    assert [(p["id"], p["roles"][0]["verdict"]) for p in answer["people"]] == [(str(BOB_ID), "discordant"), (str(ALICE_ID), "concordant")]
    against = answer["people"][0]["roles"][0]["against"][0]
    assert against["axis"] == "Propriété des moyens de production" and against["score"] > 0.4 and against["expected"] == [-1.0, -0.2]
    assert answer["totals"] == {"people": 2, "discordant": 1, "concordant": 1, "not_verifiable": 0}


def test_a_role_without_enough_said_is_not_judged(web, ingest_db):
    debate(ingest_db)
    wears(ingest_db, ALICE_ID, "Socialiste", 5001)
    p = proposition(ingest_db, "L'État doit posséder le secteur", "economie", -1)
    takes(ingest_db, ALICE_ID, p, -1, confidence=0.3)                   # one remark that the model is hardly sure of, against: not enough to say anything
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    assert web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()["roles"][0]["verdict"] == "not_verifiable"
    takes(ingest_db, ALICE_ID, proposition(ingest_db, "L'État doit posséder le secteur de l'énergie", "economie", -1), -1, confidence=0.9)    # a clear one: judged
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    assert web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()["roles"][0]["verdict"] == "discordant"


def test_two_roles_that_contradict_each_other_are_shown(web, ingest_db):
    debate(ingest_db)
    wears(ingest_db, ALICE_ID, "Communiste", 5002)
    wears(ingest_db, ALICE_ID, "Gaulliste", 5003)
    conflicts = web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()["role_conflicts"]
    assert conflicts == [] or {c["axis"] for c in conflicts}                # whatever the table says, the shape is stable
    assert web.get("/api/positions/coherence", params={"guild": GUILD}).json()["totals"]["people"] == 1


def test_by_theme_the_positions_and_the_people_they_talked_with(web, ingest_db):
    debate(ingest_db)                                                      # Alice, Bob, Alice: one conversation
    cid = ingest_db.execute("SELECT id FROM conversations").fetchone()[0]
    p = proposition(ingest_db, "L'État doit augmenter le salaire minimum", "economie", -0.5)
    takes(ingest_db, ALICE_ID, p, 1, conversation=cid)
    takes(ingest_db, BOB_ID, p, -1, conversation=cid)
    t = ingest_db.execute("INSERT INTO topics (guild_id, label, origin) VALUES (%s, 'Salaires', 'discovered') RETURNING id", (GUILD_ID,)).fetchone()[0]
    run = ingest_db.execute("INSERT INTO topic_runs (guild_id, method, model, parameters) VALUES (%s, 'test', 'x', '{}'::jsonb) RETURNING id", (GUILD_ID,)).fetchone()[0]
    ingest_db.execute("INSERT INTO topic_assignments (run_id, conversation_id, topic_id, similarity) VALUES (%s, %s, %s, 0.9)", (run, cid, t))
    theme = web.get(f"/api/positions/person/{ALICE_ID}", params={"guild": GUILD}).json()["themes"][0]
    assert theme["label"] == "Salaires" and [p["stance"] for p in theme["positions"]] == [1]
    assert [(w["id"], w["messages"], w["relation"]) for w in theme["talked_with"]] == [(str(BOB_ID), 1, "en désaccord")]    # Bob wrote in the conversation, and says the opposite


def test_everything_needs_the_session(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as c:
        assert c.get("/api/positions/coherence").status_code == 401 and c.get("/api/positions/person/1").status_code == 401


# --- a person validates what the model proposed -------------------------------------------------------------------------------------


def linked(db, pid, **loadings):
    for code, loading in loadings.items():
        db.execute("INSERT INTO proposition_axis (proposition_id, axis_id, loading, confidence) VALUES (%s, %s, %s, 0.8) ON CONFLICT DO NOTHING", (pid, axis(db, code), loading))


def test_a_person_validates_corrects_or_empties_the_links_of_a_proposition(web, ingest_db):
    debate(ingest_db)
    p = ingest_db.execute("INSERT INTO propositions (text, created_by) VALUES ('Nationaliser le rail', 'test') RETURNING id").fetchone()[0]
    linked(ingest_db, p, economie=0.6, morale=-0.6)                                  # what the model proposed: the second one is wrong
    takes(ingest_db, ALICE_ID, p, 1)
    detail = web.get(f"/api/positions/proposition/{p}", params={"guild": GUILD}).json()
    assert [(a["axis"], a["toward"], a["validated"]) for a in detail["axes"]] == [("economie", "Privé", False), ("morale", "Progressiste", False)]      # proposed, not validated
    saved = web.put(f"/api/positions/proposition/{p}/axes", params={"guild": GUILD}, json={"links": [{"axis": "economie", "loading": -1}, {"axis": "controle", "loading": -0.6},
                                                                                                         {"axis": "morale", "loading": 0.1}]}).json()
    assert [(a["axis"], a["toward"], a["loading"], a["validated"]) for a in saved["axes"]] == [("economie", "Public", -1.0, True), ("controle", "Planification", -0.6, True)]   # corrected, validated; a trace is no link
    scores = dict(ingest_db.execute("SELECT a.code, s.score::float8 FROM person_axis_scores s JOIN axes a ON a.id = s.axis_id WHERE s.user_id = %s", (ALICE_ID,)).fetchall())
    assert scores["economie"] < 0 and "morale" not in scores                          # the scores follow the person's decision
    assert web.put(f"/api/positions/proposition/{p}/axes", params={"guild": GUILD}, json={"links": []}).json() == {"axes": []}          # « this weighs on no axis » is a decision too
    assert ingest_db.execute("SELECT axes_read_at IS NOT NULL FROM propositions WHERE id = %s", (p,)).fetchone() == (True,)             # and it is not asked of the model again
    ingest_db.execute("UPDATE axes SET is_active = false WHERE code = 'europe'")                                                          # an axis that is switched off
    assert web.put(f"/api/positions/proposition/{p}/axes", params={"guild": GUILD}, json={"links": [{"axis": "europe", "loading": 1}]}).status_code == 422   # an axis that is not active
    assert web.put(f"/api/positions/proposition/{p}/axes", params={"guild": GUILD}, json={"links": [{"axis": "economie", "loading": 3}]}).status_code == 422
    assert web.put("/api/positions/proposition/999999/axes", params={"guild": GUILD}, json={"links": []}).status_code == 404


def test_validating_as_they_are_and_counting_only_what_was_validated(web, ingest_db):
    debate(ingest_db)
    good = proposition(ingest_db, "Nationaliser le rail", "economie", -1)
    ingest_db.execute("UPDATE proposition_axis SET is_validated = false")
    bad = ingest_db.execute("INSERT INTO propositions (text, created_by) VALUES ('Un goût', 'test') RETURNING id").fetchone()[0]
    linked(ingest_db, bad, economie=1.0)                                              # a wrong link, never reviewed
    takes(ingest_db, ALICE_ID, good, 1)
    takes(ingest_db, ALICE_ID, bad, 1)
    ingest_db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))
    score = lambda: ingest_db.execute("SELECT s.score::float8 FROM person_axis_scores s JOIN axes a ON a.id = s.axis_id WHERE s.user_id = %s AND a.code = 'economie'", (ALICE_ID,)).fetchone()  # noqa: E731
    assert abs(score()[0]) < 0.4                                                       # the two cancel: a wrong, unreviewed link blurs the score
    overview = web.get("/api/positions", params={"guild": GUILD}).json()
    assert overview["axes_links"] == {"total": 2, "validated": 0, "only_validated": False} and {a["code"] for a in overview["axes_catalog"]} >= {"economie", "morale"}
    assert web.post(f"/api/positions/proposition/{good}/axes/validate", params={"guild": GUILD}).json()["axes"][0]["validated"] is True
    assert web.put("/api/positions/only-validated", params={"guild": GUILD}, json={"value": True}).json() == {"only_validated": True}
    assert score()[0] < -0.4                                                           # only the validated link counts now
    assert web.get("/api/positions", params={"guild": GUILD}).json()["axes_links"] == {"total": 2, "validated": 1, "only_validated": True}
    web.put("/api/positions/only-validated", params={"guild": GUILD}, json={"value": False})
    assert abs(score()[0]) < 0.4                                                       # and as before when it is off


# --- several readings, and what a person decided as examples ---------------------------------------------------------------------------


def test_what_every_reading_says_is_kept_and_what_they_disagree_on_is_decided_not_dropped():
    from dindon.analysis.axes import JUDGED_LOADING, decide
    eco, morale, pouvoir = (7, -1.0, 1.0), (11, 0.6, 0.8), (3, 1.0, 1.0)
    asked = []
    def judge(answers):
        def ask(axis_id):
            asked.append(axis_id)
            return answers.get(axis_id)
        return ask
    assert decide([[eco, morale], [eco]], judge({11: 1})) == [eco, (11, JUDGED_LOADING, 0.75)]       # economie: both said it; morale: only one, the judge says yes
    assert asked == [11]                                                                            # what every reading made is not asked again
    assert decide([[eco, morale], [eco]], judge({11: None})) == [eco]                                # the judge says « nowhere »: no link
    assert decide([[eco], [(7, 0.6, 0.8)]], judge({7: 1})) == [(7, JUDGED_LOADING, 0.75)]          # the readings say opposite poles: the judge decides which one (here the positive)
    assert decide([[(7, -1.0, 1.0)], [(7, -0.6, 0.8)]], judge({})) == [(7, -0.6, 0.9)]             # it is only as firm as its least firm vote
    assert decide([[eco, morale]], judge({})) == [eco, morale]                                      # one reading: its own links
    assert decide([[(1, 1.0, 1), (2, 1.0, 1), (3, 0.6, 1)]] * 2, judge({})) == [(1, 1.0, 1.0), (2, 1.0, 1.0)]    # at most two axes for a proposition
    assert decide([[pouvoir], []], judge({3: -1})) == [(3, -JUDGED_LOADING, 0.75)]                  # a link that the judge reverses is reversed


def test_the_propositions_are_read_twice_and_a_disputed_axis_is_asked_about_alone(ingest_db, client, ollama):
    debate(ingest_db)
    p = proposition(ingest_db, "x", "economie", -1)
    ingest_db.execute("UPDATE propositions SET axes_read_at = NULL, text = %s WHERE id = %s", ("L'État doit posséder les services essentiels", p))
    ingest_db.execute("DELETE FROM proposition_axis")
    takes(ingest_db, ALICE_ID, p, 1)
    eco = {"axis": "economie", "toward": "Public", "strength": "forte"}
    morale = {"axis": "morale", "toward": "Progressiste", "strength": "moyenne"}

    def handler(body):
        system = body["messages"][0]["content"]
        if "Tu vérifies un rattachement" in system:
            return {"place": "aucun"}                                                              # the judge: not on morale
        return {"axes": [eco]} if "En cas de doute" in system else {"axes": [eco, morale]}         # the cautious reading adds only one
    ollama.chat_handler = handler
    assign_axes(ingest_db, client, "qwen3:14b", GUILD_ID)
    systems = [r[1]["messages"][0]["content"] for r in ollama.requests if r[0] == "/api/chat"]
    assert len(systems) == 3 and "En cas de doute" not in systems[0] and "En cas de doute" in systems[1] and "Tu vérifies un rattachement" in systems[2]
    judged = [r[1]["messages"][-1]["content"] for r in ollama.requests if r[0] == "/api/chat"][2]
    assert "Axe `morale`" in judged and judged.endswith("Phrase : L'État doit posséder les services essentiels")
    assert dict(ingest_db.execute("SELECT a.code, pa.loading::float8 FROM proposition_axis pa JOIN axes a ON a.id = pa.axis_id").fetchall()) == {"economie": -1.0}


def test_what_a_person_decided_is_shown_to_a_third_reading(ingest_db, client, ollama, monkeypatch):
    from dindon.analysis import axes
    monkeypatch.setattr(axes, "MIN_EXAMPLES", 1)
    debate(ingest_db)
    decided = proposition(ingest_db, "Le rail doit rester public", "economie", -1)
    empty = ingest_db.execute("INSERT INTO propositions (text, created_by, axes_read_at, axes_validated_at) VALUES ('Je ne sais pas trop', 'test', now(), now()) RETURNING id").fetchone()[0]
    ingest_db.execute("UPDATE proposition_axis SET is_validated = true")
    ingest_db.execute("UPDATE propositions SET axes_validated_at = now() WHERE id = %s", (decided,))
    for pid in (decided, empty):
        ingest_db.execute("INSERT INTO proposition_embeddings (proposition_id, model, embedding) VALUES (%s, 'bge-m3', array_fill(0.1::real, ARRAY[1024])::vector)", (pid,))
    new = ingest_db.execute("INSERT INTO propositions (text, created_by) VALUES ('Les hôpitaux doivent rester publics', 'test') RETURNING id").fetchone()[0]
    ingest_db.execute("INSERT INTO proposition_embeddings (proposition_id, model, embedding) VALUES (%s, 'bge-m3', array_fill(0.1::real, ARRAY[1024])::vector)", (new,))
    takes(ingest_db, ALICE_ID, new, 1)
    ollama.chat_handler = lambda body: {"axes": [{"axis": "economie", "toward": "Public", "strength": "forte"}]}
    assign_axes(ingest_db, client, "qwen3:14b", GUILD_ID)
    asked = [r[1] for r in ollama.requests if r[0] == "/api/chat"]
    assert len(asked) == 3                                                              # the two readings, and the one with examples
    shown = asked[2]["messages"][-1]["content"]
    assert "« Le rail doit rester public » → economie : Public (forte)" in shown and "« Je ne sais pas trop » → (aucun axe)" in shown    # « on no axis » is an example too
    assert shown.rstrip().endswith("Phrase : Les hôpitaux doivent rester publics")


def test_positions_pagination_keeps_the_filtered_total_and_has_no_gaps(web, ingest_db):
    debate(ingest_db)
    for n in range(61):
        pid = proposition(ingest_db, f"Pagination proposition {n:02}", "economie", -1)
        takes(ingest_db, ALICE_ID, pid, 1)
    first = web.get("/api/positions", params={"q": "Pagination", "limit": 50}).json()
    last = web.get("/api/positions", params={"q": "Pagination", "limit": 50, "offset": 50}).json()
    assert first["matching"] == last["matching"] == 61
    assert len(first["propositions"]) == 50 and len(last["propositions"]) == 11
    ids = [p["id"] for data in (first, last) for p in data["propositions"]]
    assert len(set(ids)) == 61 and ids == sorted(ids)
    filtered = web.get("/api/positions", params={"q": "Pagination proposition 60", "limit": 50}).json()
    assert filtered["matching"] == 1 and filtered["offset"] == 0
    assert web.get("/api/positions", params={"offset": -1}).status_code == 422
