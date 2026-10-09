"""Synthetic PostgreSQL + fake Discord: positions, destination-channel proofs, privacy and PNG."""
import asyncio
import io
from datetime import UTC, datetime, timedelta

from PIL import Image, ImageChops

from dindon import cards, discord_map, mycard, politimetre
from dindon.bot.privacy_commands import COMMAND
from dindon.debate import store
from test_privacy import ALICE_ID, BOB_ID, CAROL_ID, GUILD, commands, talk


def seed(db, url):
    talk(url)
    channel = db.execute("SELECT channel_id FROM messages WHERE id = 101").fetchone()[0]
    axis = db.execute("SELECT id FROM axes WHERE code = 'economie'").fetchone()[0]
    db.execute("INSERT INTO person_axis_scores (guild_id, user_id, axis_id, score, uncertainty, evidence_weight, n_propositions) VALUES (%s, %s, %s, -0.7, 0.2, 3, 3)",
               (int(GUILD), BOB_ID, axis))
    ids = []
    for index, confidence in enumerate((0.9, 0.85, 0.8, 0.5)):
        prop = db.execute("INSERT INTO propositions (text, status) VALUES (%s, 'validated') RETURNING id", (f"Position {index}",)).fetchone()[0]
        claim = db.execute("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version)
                              VALUES (%s, %s, %s, 'opinion', 'Position', 1, %s, now(), 'test', 'test') RETURNING id""",
                           (int(GUILD), BOB_ID, prop, confidence)).fetchone()[0]
        db.execute("INSERT INTO claim_evidence VALUES (%s, 101, 'Salut Alice, tu as vu ça ?')", (claim,))
        ids.append(claim)
    discord_map.save(db, {"enabled": True, "acknowledged": True, "sections": ["axes"]})
    return channel, ids


def test_current_sourced_positions_preferences_and_privacy(ingest_db, ingest_url):
    db = ingest_db
    channel, ids = seed(db, ingest_url)
    data = politimetre.collect(db, int(GUILD), BOB_ID, channel)
    assert [p["id"] for p in data["positions"]] == ids[:3]
    assert sum(axis[3] is not None for axis in data["axes"]) == 1
    assert len(data["axes"]) == db.execute("SELECT count(*) FROM axes WHERE is_active").fetchone()[0]
    # Positions cover the guild, but a quote from another channel is never republished.
    elsewhere = politimetre.collect(db, int(GUILD), BOB_ID, channel + 999)["positions"]
    assert len(elsewhere) == 3 and all(not p["quote"] for p in elsewhere)
    assert all(p["url"].endswith(f"/{channel}/101") for p in elsewhere)
    db.execute("UPDATE claim_evidence SET message_id = 100 WHERE claim_id = %s", (ids[0],))
    assert ids[0] not in [p["id"] for p in politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"]]
    db.execute("UPDATE claim_evidence SET message_id = 101 WHERE claim_id = %s", (ids[0],))
    mycard.save(db, int(GUILD), BOB_ID, {"pinned": [ids[2]], "blocks": {"positions": ["positions"]}})
    data = politimetre.collect(db, int(GUILD), BOB_ID, channel)
    assert [p["id"] for p in data["positions"]] == [ids[2]] and not data["axes"]
    db.execute("UPDATE claims SET review_status = 'rejected' WHERE id = %s", (ids[2],))
    assert ids[2] not in [p["id"] for p in politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"]]
    cards.save(db, {"pages": ["profile"]})
    assert politimetre.collect(db, int(GUILD), BOB_ID, channel) is None
    cards.save(db, {})
    db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (BOB_ID,))
    assert politimetre.collect(db, int(GUILD), BOB_ID, channel) is None
    assert politimetre.collect(db, int(GUILD) + 99, BOB_ID, channel) is None


def test_command_posts_portrait_and_sources_and_defaults_to_requester(ingest_db, ingest_url, tmp_path, monkeypatch):
    channel, ids = seed(ingest_db, ingest_url)
    interactions, service, sent, _ = commands(ingest_url, tmp_path)
    monkeypatch.setattr(service, "_pictures", lambda *args: {})
    option = next(o for o in COMMAND["options"] if o["name"] == "politimetre")
    assert option["options"][0]["type"] == 6 and not option["options"][0]["required"]
    interaction = {"id": "950", "token": "tokm", "type": 2, "application_id": "42", "guild_id": GUILD, "channel_id": str(channel),
                   "member": {"user": {"id": str(BOB_ID)}}, "data": {"name": "dindon", "options": [{"name": "politimetre", "type": 1}]}}
    asyncio.run(interactions.answer(interaction))
    assert sent.calls[0][2] == {"type": 5, "data": {"flags": 0}}
    body, file = sent.calls[-1][2], sent.calls[-1][4]
    assert file[0] == "politimetre.png" and Image.open(io.BytesIO(file[1])).width == 1024
    assert body["allowed_mentions"] == {"parse": []}
    sources = body["components"][0]["components"]
    assert len(sources) == 3 and sources[0]["url"].endswith(f"/{channel}/101")
    # Explicit target is independent of the requester; same public PNG workflow.
    interaction["member"]["user"]["id"] = str(CAROL_ID)
    interaction["data"]["options"][0]["options"] = [{"name": "personne", "type": 6, "value": str(BOB_ID)}]
    asyncio.run(interactions.answer(interaction))
    assert sent.calls[-1][4][0] == "politimetre.png"
    discord_map.save(ingest_db, {"enabled": True})
    assert service.politimetre(int(GUILD), BOB_ID, channel).file is None


def test_render_handles_empty_sections_long_labels_and_bad_avatar():
    data = {"name": "Très long pseudonyme " * 30, "axes": [("Un axe " * 30, "Pôle négatif " * 30, "Pôle positif " * 30, -0.7, 0.2, 99)] * 5,
            "positions": [{"stance": stance, "text": "Une proposition très longue " * 100, "quote": "Extrait " * 100, "at": datetime.now(UTC)} for stance in (-1, 0, 1)]}
    for sample in (data, {**data, "axes": []}, {**data, "positions": []}):
        image = Image.open(io.BytesIO(politimetre.render(sample, b"bad avatar")))
        assert image.size == (politimetre.WIDTH, politimetre.HEIGHT) and image.mode == "RGB"


def test_all_defined_axes_include_central_scores_and_extend_the_card(ingest_db, ingest_url):
    channel, _ = seed(ingest_db, ingest_url)
    existing = ingest_db.execute("SELECT axis_id FROM person_axis_scores WHERE guild_id = %s AND user_id = %s", (int(GUILD), BOB_ID)).fetchone()[0]
    others = ingest_db.execute("SELECT id FROM axes WHERE is_active AND id <> %s ORDER BY position, id LIMIT 7", (existing,)).fetchall()
    assert len(others) == 7
    for (axis,) in others:
        ingest_db.execute("""INSERT INTO person_axis_scores (guild_id, user_id, axis_id, score, uncertainty, evidence_weight, n_propositions)
                              VALUES (%s, %s, %s, 0, 0.4, 2, 2)""", (int(GUILD), BOB_ID, axis))
    data = politimetre.collect(ingest_db, int(GUILD), BOB_ID, channel)
    assert sum(axis[3] is not None for axis in data["axes"]) == 8 and sum(axis[3] == 0 for axis in data["axes"]) == 7
    assert any(axis[3] is None for axis in data["axes"])
    tall = Image.open(io.BytesIO(politimetre.render(data)))
    short = Image.open(io.BytesIO(politimetre.render({**data, "axes": data["axes"][:5]})))
    assert tall.width == short.width == 1024 and tall.height > short.height
    # The ornament and turkey at the top must stay identical, rather than stretch with the card.
    assert ImageChops.difference(tall.crop((0, 0, 1024, 290)), short.crop((0, 0, 1024, 290))).getbbox() is None
    # The complete highlights and bottom frame are still present below the extra axes.
    assert ImageChops.difference(tall.crop((0, tall.height - 600, 1024, tall.height)), short.crop((0, short.height - 600, 1024, short.height))).getbbox() is None


def test_votes_from_other_channels_show_for_nuanced_against_and_latest_choice(ingest_db, ingest_url):
    db = ingest_db
    channel, _ = seed(db, ingest_url)
    db.execute("DELETE FROM claims WHERE user_id = %s", (BOB_ID,))
    now = datetime.now(UTC)
    debates = []
    for index, position in enumerate(("for", "unsure", "against")):
        axis = store.axis(db, "economie") if index == 0 else None
        debate = store.start(db, guild_id=int(GUILD), channel_id=channel, topic=f"Sujet politique {index}", created_by=ALICE_ID,
                             axis=axis, now=now, max_per_person=5, max_per_server=5)
        debate = store.attach_thread(db, debate.id, thread_id=700 + index, question_message_id=800 + index, now=now)
        store.set_position(db, debate.id, BOB_ID, position, now)
        debates.append(debate)
    data = politimetre.collect(db, int(GUILD), BOB_ID, channel + 999)
    assert [p["stance"] for p in data["positions"]] == [1, 0, -1]
    assert politimetre.STANCES[0] == "NUANCÉ"
    assert all(not p["quote"] for p in data["positions"])
    assert data["positions"][0]["text"] == f"Privilégier {debates[0].axis['for']} plutôt que {debates[0].axis['against']}."
    # The fallback source uses the debate thread, even if a poll destination is configured.
    db.execute("UPDATE debate_polls SET channel_id = 9999 WHERE debate_id = %s", (debates[0].id,))
    assert politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"][0]["url"].endswith('/700/800')
    db.execute("UPDATE debate_polls SET channel_id = 9999, message_id = 8888 WHERE debate_id = %s", (debates[0].id,))
    assert politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"][0]["url"].endswith('/9999/8888')
    # The new choice replaces the old one; witness is not presented as a political stance.
    store.set_position(db, debates[0].id, BOB_ID, "against", now + timedelta(seconds=1))
    changed = politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"]
    assert not any(p["stance"] == 1 for p in changed)
    store.set_position(db, debates[2].id, BOB_ID, "witness", now + timedelta(seconds=2))
    assert f"vote:{debates[2].id}" not in [p["id"] for p in politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"]]
    # A newer uncertain reading must not resurrect the previous, opposite vote.
    proposition = db.execute("SELECT proposition_id FROM debate_polls WHERE debate_id = %s", (debates[0].id,)).fetchone()[0]
    claim = db.execute("""INSERT INTO claims (guild_id, user_id, proposition_id, kind, text, stance, confidence, stated_at, model, prompt_version)
                          VALUES (%s, %s, %s, 'opinion', 'Position récente', 1, 0.5, %s, 'test', 'test') RETURNING id""",
                       (int(GUILD), BOB_ID, proposition, now + timedelta(seconds=3))).fetchone()[0]
    db.execute("INSERT INTO claim_evidence VALUES (%s, 101, 'Salut Alice, tu as vu ça ?')", (claim,))
    current = politimetre.collect(db, int(GUILD), BOB_ID, channel)["positions"]
    assert f"vote:{debates[0].id}" not in [p["id"] for p in current] and claim not in [p["id"] for p in current]
