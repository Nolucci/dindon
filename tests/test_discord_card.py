"""The card on Discord is set by the administrator from the web panel (cards.py, api/discord_card.py): which pages and which blocks of each page. Level of proof: SIMULATED."""
import asyncio

from fastapi.testclient import TestClient

from dindon import cards
from dindon.api.main import create_app
from synthetic import settings_for
from test_privacy import BOB_ID, CAROL_ID, card_interaction, commands, talk

PASSWORD = "correct horse"
CARD = {"messages": 12, "days": 3, "rank": 1, "writers": 4, "recent": 5, "replies": 3, "hour": 21, "weekday": "mardi", "received": (2, 1), "channels": [("general", 12)], "roles": ["Libéral"],
        "first": __import__("datetime").datetime(2026, 9, 1), "last": __import__("datetime").datetime(2026, 10, 1), "name": "Bob", "color": None}


def test_the_settings_keep_only_known_pages_and_blocks_and_at_least_one_page():
    assert cards.clean(None) == cards.DEFAULT and cards.clean({}) == cards.DEFAULT
    cfg = cards.clean({"pages": ["positions", "nonsense"], "blocks": {"positions": ["axes", "x"], "profile": "bad"}})
    assert cfg["pages"] == ["positions"] and cfg["blocks"]["positions"] == ["axes"] and cfg["blocks"]["profile"] == list(cards.BLOCKS["profile"])
    assert cards.clean({"pages": []})["pages"] == list(cards.PAGE_KEYS)                         # a card with no page would show nothing


def test_a_block_that_is_switched_off_is_not_on_the_page_and_a_page_that_is_off_has_no_button():
    cfg = cards.clean({"pages": ["profile", "positions"], "blocks": {"profile": ["headline", "roles"]}})
    text = cards._page_profile(CARD, cfg["blocks"]["profile"])
    assert "12 messages" in text and "Se réclame de" in text and "Salons" not in text and "Activité" not in text and "Présent" not in text
    embed = cards.card_page({**CARD, "axes": [], "positions": [], "total_positions": 0, "verdicts": [], "against": [], "conflicts": [], "changes": []}, 1, None, cfg)
    assert "Profil" in embed["title"] and "Page 1/2" in embed["footer"]["text"]                  # page 1 (Interactions) is off: the first page shown instead
    row = cards.card_buttons(BOB_ID, 0, cfg)[0]["components"]
    assert [b["label"] for b in row] == ["Profil", "Positions"] and row[1]["custom_id"] == f"dindon:card:2:{BOB_ID}"


def test_only_the_administrator_changes_the_card_and_the_command_follows(ingest_db, ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False)) as client:
        assert client.get("/api/discord-card").status_code == 401 and client.put("/api/discord-card", json={}).status_code == 401
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        assert client.get("/api/discord-card").json()["pages"] == list(cards.PAGE_KEYS)
        saved = client.put("/api/discord-card", json={"pages": ["profile"], "blocks": {"profile": ["headline"]}}).json()
        assert saved == {"pages": ["profile"], "blocks": {**cards.DEFAULT["blocks"], "profile": ["headline"]}}
    talk(ingest_url)
    interactions, _, sent, _ = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(card_interaction(CAROL_ID, BOB_ID)))
    body = sent.calls[1][2]
    assert [c["label"] for c in body["components"][0]["components"]] == ["Profil"] and "Salons" not in body["embeds"][0]["description"]
