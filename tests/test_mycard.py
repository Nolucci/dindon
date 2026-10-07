"""`/dindon mycard`: a person sets up their own card (pages fixed, content changes), with Dindon's suggestions per page (mycard.py). Level of proof: SIMULATED (real PostgreSQL, invented people)."""
import asyncio
import json

from dindon import cards, mycard, privacy
from test_privacy import BOB_ID, CAROL_ID, GUILD, card_interaction, commands, talk


def seeded(db):
    """Bob, with three positions: a clear one with proof, one read with little certainty and no proof, and another clear one that the card does not show by default."""
    one = lambda q, *a: db.execute(q, a).fetchone()[0]  # noqa: E731
    guild = int(GUILD)
    ids = {}
    for name, confidence, proof, at in (("faible", 0.4, False, "2026-10-02T20:00:00Z"), ("claire", 0.95, True, "2026-10-03T20:00:00Z"), ("autre", 0.9, True, "2026-10-04T20:00:00Z"),
                                        ("encore", 0.85, True, "2026-10-05T20:00:00Z"), ("derniere", 0.8, True, "2026-10-06T20:00:00Z")):
        proposition = one("INSERT INTO propositions (text, status) VALUES (%s, 'validated') RETURNING id", f"Position {name}")
        claim = one("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version)
                       VALUES (%s, %s, %s, 'opinion', 'dit', 1, %s, %s, 'm', 'v') RETURNING id""", guild, BOB_ID, proposition, confidence, at)
        if proof:
            db.execute("INSERT INTO claim_evidence VALUES (%s, 101, 'Salut Alice, tu as vu ça ?')", (claim,))
        ids[name] = claim
    return ids


def test_the_settings_stay_within_what_the_administrator_allows():
    cfg = cards.clean({"pages": ["profile", "positions"], "blocks": {"profile": ["headline", "roles"]}})
    prefs = mycard.clean({"blocks": {"profile": ["roles", "channels", "x"], "interactions": ["close"]}, "pinned": [5, 5, 6, 7, 8, "x"], "notes": {
        "section:profile": "  Bonjour   https://spam.example à tous  ", "pos:12": "précision", "pos:abc": "non", "other": "non", "section:positions": "x" * 500}}, cfg, [5, 6, 7, 8])
    assert prefs["blocks"]["profile"] == ["roles"]                                             # « channels » is off for everybody: it cannot be chosen
    assert prefs["pinned"] == [5, 6, 7]                                                          # three at most, only among what was read
    assert prefs["notes"]["section:profile"] == "Bonjour à tous" and prefs["notes"]["pos:12"] == "précision" and len(prefs["notes"]["section:positions"]) == 200
    assert "pos:abc" not in prefs["notes"] and "other" not in prefs["notes"]
    assert cards.effective_blocks(cfg, prefs, "profile") == ["roles"] and cards.effective_blocks(cfg, {}, "profile") == ["headline", "roles"]


def test_dindon_suggests_per_page_from_what_it_analysed_and_a_click_applies_it(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    ids = seeded(ingest_db)
    cfg = cards.load(ingest_db)
    card = cards.person_card(ingest_db, int(GUILD), BOB_ID)
    assert not [s for s in mycard.suggestions(card, cfg, {})["positions"] if "peu de certitude" in s["text"]]       # the clearest three are shown: nothing weak is
    prefs = mycard.apply(ingest_db, int(GUILD), BOB_ID, ("pinned", [ids["faible"], ids["claire"]]))                # the person chooses a position that Dindon read with little certainty
    todo = mycard.suggestions(card, cfg, prefs)
    texts = [s["text"] for s in todo["positions"]]
    assert any("Position faible" in t and "peu de certitude" in t for t in texts)                # « mal expliquée »: a note is suggested
    assert any(s["action"] == ("note", f"pos:{ids['faible']}") for s in todo["positions"])
    better = [s for s in todo["positions"] if s["action"] and s["action"][0] == "pin"]
    assert better and "Position claire non montrée" in better[0]["text"]                       # a clear position that is not shown is proposed
    prefs = mycard.apply(ingest_db, int(GUILD), BOB_ID, ("suggestion", "positions", todo["positions"].index(better[0])))
    assert prefs["pinned"] and better[0]["action"][1] in prefs["pinned"]
    shown = [p["id"] for p in cards.shown_positions(card, prefs)]
    assert better[0]["action"][1] in shown and len(shown) <= 3 and ids["faible"] in shown


def test_the_screen_keeps_the_four_pages_and_changes_only_their_content(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    ids = seeded(ingest_db)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)

    def component(custom_id, values=None, kind=3):
        return {"id": "910", "token": "tokm", "type": 3, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(BOB_ID)}},
                "data": {"custom_id": custom_id, "component_type": kind, **({"values": values} if values is not None else {})}}

    command = {"id": "909", "token": "tokm", "type": 2, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(BOB_ID)}},
               "data": {"name": "dindon", "options": [{"type": 1, "name": "mycard"}]}}
    asyncio.run(interactions.answer(command))
    body = sent.calls[-1][2]
    assert body["data"]["flags"] == 64                                                            # private
    first = body["data"]
    labels = [c["label"] for c in first["components"][0]["components"]]
    assert labels == ["Profil", "Interactions", "Positions", "Contradictions"]                    # the parts never move
    assert "Suggestions" in first["embeds"][1]["title"]

    asyncio.run(interactions.answer(component("dindon:mycard:b:0", ["headline", "roles"])))      # Profil: keep two blocks only
    page = sent.calls[-1][2]["data"]["embeds"][0]["description"]
    assert "messages" in page and "Salons" not in page and "Activité" not in page

    asyncio.run(interactions.answer(component("dindon:mycard:s:2", [str(ids["derniere"]), str(ids["autre"])])))     # Positions: show two others, from the base
    shown = json.dumps(sent.calls[-1][2]["data"]["embeds"][0], ensure_ascii=False)
    assert "Position derniere" in shown and "Position autre" in shown and "Position claire" not in shown

    note = {"id": "911", "token": "tokm", "type": 5, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(BOB_ID)}},
            "data": {"custom_id": f"dindon:mycard:note:2:p{ids['derniere']}", "components": [{"type": 1, "components": [{"type": 4, "custom_id": "note", "value": "Je l'explique mieux ici."}]}]}}
    asyncio.run(interactions.answer(note))
    assert "Note enregistrée" in sent.calls[-1][2]["data"]["content"]

    asyncio.run(interactions.answer(card_interaction(CAROL_ID, BOB_ID)))                         # what everybody sees of Bob's card: his settings
    public = sent.calls[-1][2]
    assert "Salons" not in public["embeds"][0]["description"] and [c["label"] for c in public["components"][0]["components"]] == ["Profil", "Interactions", "Positions", "Contradictions"]
    positions = _public_page(interactions, sent, 2)
    assert "Position derniere" in positions and "Je l'explique mieux ici." in positions and "Position claire" not in positions

    asyncio.run(interactions.answer(component("dindon:mycard:r:0")))                             # back to the start for the page
    assert "Salons" in sent.calls[-1][2]["data"]["embeds"][0]["description"]


def _public_page(interactions, sent, page):
    click = {"id": "912", "token": "tokp", "type": 3, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(CAROL_ID)}},
             "data": {"custom_id": f"dindon:card:{page}:{BOB_ID}"}, "message": {"embeds": [{"thumbnail": {"url": "https://cdn.discordapp.com/avatars/1/x.png"}}]}}
    asyncio.run(interactions.answer(click))
    return json.dumps(sent.calls[-1][2], ensure_ascii=False)


def test_a_person_who_stopped_has_no_screen_and_erasing_removes_the_settings(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    mycard.apply(ingest_db, int(GUILD), BOB_ID, ("note", "section:profile", "Une note"))
    assert ingest_db.execute("SELECT count(*) FROM card_prefs WHERE user_id = %s", (BOB_ID,)).fetchone()[0] == 1
    assert privacy.export_person(ingest_db, BOB_ID)["card_settings"][0]["notes"] == {"section:profile": "Une note"}
    privacy.erase_person(ingest_db, BOB_ID, source="test")
    assert ingest_db.execute("SELECT count(*) FROM card_prefs WHERE user_id = %s", (BOB_ID,)).fetchone()[0] == 0
