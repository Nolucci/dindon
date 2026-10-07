"""`/dindon map`: the picture of the map on Discord, what the admins let it show, and who is never on it.

Level of proof: SIMULATED (invented people, a real PostgreSQL, a fake Discord REST, the picture is decoded but never looked at by a person). Nothing here has run on a real server.
"""
import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dindon import discord_map
from dindon.api.main import create_app
from dindon.bot.privacy_commands import COMMAND
from synthetic import settings_for
from test_privacy import ALICE_ID, BOB_ID, CAROL_ID, GUILD, PASSWORD, commands, talk


def _small_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 90)).save(buffer, "PNG")
    return buffer.getvalue()


def map_command(asker, *, period=None, person=None, id="950"):
    options = ([{"type": 3, "name": "periode", "value": period}] if period else []) + ([{"type": 6, "name": "personne", "value": str(person)}] if person else [])
    return {"id": id, "token": "tokm", "type": 2, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(asker)}},
            "data": {"name": "dindon", "options": [{"type": 1, "name": "map", "options": options}]}}


def switch_on(db, **values):
    discord_map.save(db, {"enabled": True, **values})


def posted(sent):
    method, path, body, authorized, file = sent.calls[-1]
    assert (method, path) == ("PATCH", "/webhooks/42/tokm/messages/@original")
    return body, file


def test_the_command_only_offers_periods_and_people(ingest_url, tmp_path):
    option = next(o for o in COMMAND["options"] if o["name"] == "map")
    periode, personne = option["options"]
    assert [c["value"] for c in periode["choices"]] == ["7", "30", "90", "all"] and periode["type"] == 3
    assert personne["type"] == 6                                                          # Discord's picker of members: nothing typed freely


def test_it_is_off_until_the_admins_switch_it_on(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID)))
    assert sent.calls[0][2] == {"type": 5, "data": {"flags": 0}}                           # public acknowledgement: the picture is for the channel
    body, file = posted(sent)
    assert "pas activée" in body["content"] and file is None


def test_the_picture_is_posted_with_a_menu_of_periods(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    switch_on(ingest_db)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID, period="7")))
    body, file = posted(sent)
    name, png = file
    image = Image.open(io.BytesIO(png))
    assert name == "carte.png" and image.format == "PNG" and image.size == (discord_map.WIDTH, discord_map.HEIGHT)
    assert "7 derniers jours" in body["content"] and "3 personnes" in body["content"] and body["allowed_mentions"] == {"parse": []}
    menu = body["components"][0]["components"][0]
    assert menu["type"] == 3 and menu["custom_id"] == "dindon:map:0" and [o["value"] for o in menu["options"] if o.get("default")] == ["7"]


def test_a_period_that_is_not_offered_is_replaced_by_the_default(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    switch_on(ingest_db)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID, period="999999")))
    assert "30 derniers jours" in posted(sent)[0]["content"]


def test_a_person_in_focus_shows_their_links_and_their_name(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    switch_on(ingest_db)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID, person=BOB_ID)))
    body, file = posted(sent)
    assert "autour de" in body["content"] and file is not None
    assert body["components"][0]["components"][0]["custom_id"] == f"dindon:map:{BOB_ID}"        # the menu keeps the person


def test_somebody_who_asked_to_stop_is_nowhere_on_the_map(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    switch_on(ingest_db)
    cfg = discord_map.load(ingest_db)
    assert BOB_ID in {p["id"] for p in discord_map.collect(ingest_db, int(GUILD), 30, None, cfg)["people"]}
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (BOB_ID,))
    assert discord_map.collect(ingest_db, int(GUILD), 30, None, cfg) is None                       # every link of this small server went through Bob: the points that talked to him go too
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID, person=BOB_ID)))
    body, file = posted(sent)
    assert file is None and "rien à montrer" in body["content"]                                   # asking for them shows nothing, not even that they exist


def test_the_settings_limit_the_people_and_the_kinds(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    cfg = discord_map.save(ingest_db, {"enabled": True, "max_people": 5, "kinds": ["reaction"]})
    assert cfg["kinds"] == ["reaction"] and cfg["max_people"] == 5
    assert discord_map.collect(ingest_db, int(GUILD), 30, None, cfg) is None                      # nobody reacted: the replies and mentions are not shown
    cfg = discord_map.save(ingest_db, {"enabled": True, "max_people": 2000, "names": -4, "kinds": ["bogus"]})
    assert cfg["max_people"] == 350 and cfg["names"] == 0 and cfg["kinds"] == list(discord_map.KINDS)
    cfg = discord_map.save(ingest_db, {"enabled": True, "max_people": 120, "names": 350})
    assert cfg["max_people"] == cfg["names"] == 120


def test_the_menu_draws_the_same_message_again(ingest_db, ingest_url, tmp_path):
    talk(ingest_url)
    switch_on(ingest_db)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    click = {"id": "951", "token": "tokm", "type": 3, "application_id": "42", "guild_id": GUILD, "member": {"user": {"id": str(CAROL_ID)}},
             "data": {"custom_id": "dindon:map:0", "component_type": 3, "values": ["90"]}}
    asyncio.run(interactions.answer(click))
    assert sent.calls[0][2] == {"type": 6}                                                         # the message is updated in place
    assert "90 derniers jours" in posted(sent)[0]["content"]
    count = len(sent.calls)
    asyncio.run(interactions.answer({**click, "data": {**click["data"], "values": ["abc"]}}))
    asyncio.run(interactions.answer({**click, "data": {**click["data"], "custom_id": "dindon:map:x"}}))
    assert len(sent.calls) == count                                                                # forged: nothing


def test_the_admin_sets_it_from_the_interface(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path), background=False)) as web:
        assert web.get("/api/discord-map").status_code == 401
        assert web.post("/api/login", json={"password": PASSWORD}).status_code == 200
        assert web.get("/api/discord-map").json()["enabled"] is False
        saved = web.put("/api/discord-map", json={"enabled": True, "max_people": 20, "names": 5, "kinds": ["reply"]}).json()
        assert saved == {"enabled": True, "max_people": 20, "names": 5, "kinds": ["reply"], "sections": ["activity", "months", "habits", "links"], "filters": ["weight"], "acknowledged": False} == web.get("/api/discord-map").json()
        many = web.put("/api/discord-map", json={"enabled": True, "max_people": 350, "names": 350})
        assert many.status_code == 200 and many.json()["max_people"] == many.json()["names"] == 350
        assert web.put("/api/discord-map", json={"max_people": 351}).status_code == 422
        assert web.put("/api/discord-map", json={"max_people": 1}).status_code == 422
        refused = web.put("/api/discord-map", json={"enabled": True, "sections": ["activity", "axes"]})                     # what reads the people needs the confirmation
        assert refused.status_code == 422 and "informées" in refused.json()["detail"]
        ok = web.put("/api/discord-map", json={"enabled": True, "sections": ["links", "axes", "bogus"], "acknowledged": True}).json()
        assert ok["sections"] == ["links", "axes"] and ok["acknowledged"] is True


# ---------------------------------------------------------------------------------------------
# The Activity (api/activity.py): the same map in a voice channel, for members only
# ---------------------------------------------------------------------------------------------

import dataclasses  # noqa: E402

from dindon.api import activity  # noqa: E402

REAL_FETCH = activity._fetch_image            # (before the tests put a fake CDN in its place)


class FakeDiscord:
    """What Discord answers to the server: the token of the code, and the servers of the person behind a token."""

    def __init__(self, guilds):
        self.guilds, self.calls = guilds, []

    def __call__(self, settings, method, path, *, token=None, form=None):
        self.calls.append((method, path, token, form))
        if path == "/oauth2/token":
            return {"access_token": "member-token"} if form["code"] == "good" else {}
        if path == "/users/@me/guilds":
            return [{"id": g} for g in self.guilds] if token == "member-token" else []
        raise AssertionError(path)


@pytest.fixture
def activity_web(ingest_url, tmp_path, monkeypatch):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<p>interface</p>")
    (web_dir / "activity.html").write_text("<p>carte</p>")
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path), discord_client_id="42", discord_client_secret="s3cret", web_dir=web_dir)
    fake = FakeDiscord([GUILD])
    monkeypatch.setattr(activity, "_discord", fake)
    activity._members.clear()
    with TestClient(create_app(settings, background=False)) as web:
        web.fake = fake
        yield web


def member_map(web, **params):
    return web.get("/activity/map", params={"guild": GUILD, "period": "30", **params}, headers={"Authorization": "Bearer member-token"})


def test_the_activity_does_not_exist_without_the_identifiers_of_the_application(ingest_url, tmp_path):
    with TestClient(create_app(settings_for(ingest_url, tmp_path), background=False)) as web:
        assert web.get("/activity/config").status_code == 404 and web.post("/activity/token", json={"code": "x"}).status_code == 404
        assert member_map(web).status_code == 404


def test_the_page_trades_the_code_for_a_token_with_the_secret_kept_on_the_server(activity_web):
    assert activity_web.get("/activity/config").json() == {"client_id": "42"}               # the id is public; the secret is never sent to the page
    assert activity_web.post("/activity/token", json={"code": "good"}).json() == {"access_token": "member-token"}
    assert activity_web.fake.calls[-1][3] == {"client_id": "42", "client_secret": "s3cret", "grant_type": "authorization_code", "code": "good"}
    assert activity_web.post("/activity/token", json={"code": "bad"}).status_code == 401


def test_only_a_member_of_the_server_reads_the_map(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    switch_on(ingest_db)
    assert activity_web.get("/activity/map", params={"guild": GUILD}).status_code == 401                         # no token
    assert activity_web.get("/activity/map", params={"guild": GUILD}, headers={"Authorization": "Bearer other"}).status_code == 403   # a token of nobody in the server
    assert member_map(activity_web, guild="999").status_code == 403                                               # a server that the person is not in
    assert member_map(activity_web, period="1000").status_code == 422
    body = member_map(activity_web).json()
    assert {n["id"] for n in body["nodes"]} == {str(ALICE_ID), str(BOB_ID), str(CAROL_ID)} and len(body["edges"]) == 2
    assert all(n["messages"] == 0 and "text" not in n for n in body["nodes"])                                    # no message, no count of them
    count = len(activity_web.fake.calls)
    member_map(activity_web, period="7")
    assert len(activity_web.fake.calls) == count                                                                  # the membership is remembered a few minutes


def test_the_activity_follows_the_settings_and_the_register(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    assert member_map(activity_web).status_code == 403                                                            # off by default, like the picture
    discord_map.save(ingest_db, {"enabled": True, "names": 1})
    nodes = member_map(activity_web).json()["nodes"]
    assert sum(1 for n in nodes if n["label"]) == 1                                                               # only as many names as the admins allow
    focused = member_map(activity_web, focus=str(BOB_ID)).json()["nodes"]
    assert next(n for n in focused if n["id"] == str(BOB_ID))["label"]                                            # the person in focus is named
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (BOB_ID,))
    assert member_map(activity_web).json()["nodes"] == [] and member_map(activity_web, focus=str(BOB_ID)).json()["nodes"] == []


def test_the_activity_page_is_the_only_one_that_may_be_framed(activity_web):
    framed = activity_web.get("/?frame_id=1&instance_id=2&platform=desktop")
    assert framed.text == "<p>carte</p>" and "frame-ancestors https://discord.com" in framed.headers["content-security-policy"] and "x-frame-options" not in framed.headers
    plain = activity_web.get("/")
    assert plain.text == "<p>interface</p>" and "frame-ancestors 'none'" in plain.headers["content-security-policy"] and plain.headers["x-frame-options"] == "DENY"
    assert activity_web.get("/api/guilds").status_code == 401                                                     # the Activity opens no other route of the API


def member_card(web, person, **params):
    return web.get(f"/activity/person/{person}", params={"guild": GUILD, "period": "30", **params}, headers={"Authorization": "Bearer member-token"})


def test_the_card_of_a_person_is_shorter_than_the_one_of_the_interface(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    switch_on(ingest_db)
    assert activity_web.get(f"/activity/person/{BOB_ID}", params={"guild": GUILD}).status_code == 401              # a member's token, like the map
    card = member_card(activity_web, BOB_ID).json()
    assert card["id"] == str(BOB_ID) and card["activity"]["messages"] == 1 and card["activity"]["active_days"] == 1 and card["by_month"]
    assert card["activity"]["rank"] >= 1 and card["activity"]["writers"] == 3 and card["activity"]["contacts"] == 2 and card["activity"]["recent"] >= 0
    assert len(card["habits"]["hours"]) == 24 and len(card["habits"]["weekdays"]) == 7 and sum(card["habits"]["hours"]) == 1 == sum(card["habits"]["weekdays"])
    assert {link["id"] for link in card["top_links"]} == {str(ALICE_ID), str(CAROL_ID)} and all(link["n"] >= 1 for link in card["top_links"])    # who Bob talked to, with how many exchanges
    # what the interface shows of a person and this card does not: the names they went by, the channels (maybe private), what the AI read of them, the roles
    assert not {"names", "top_channels", "claimed_roles", "axes", "roles", "themes"} & set(card)


def test_the_card_follows_the_names_that_the_admins_allow(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    discord_map.save(ingest_db, {"enabled": True, "names": 0})
    assert member_card(activity_web, BOB_ID).status_code == 404                                                    # no names on the map: no card either
    assert member_card(activity_web, BOB_ID, focus=str(BOB_ID)).status_code == 200                                   # choosing a point names that person
    discord_map.save(ingest_db, {"enabled": True, "names": 1})
    named = [n["id"] for n in member_map(activity_web).json()["nodes"] if n["label"]]
    assert len(named) == 1
    assert member_card(activity_web, named[0]).status_code == 200
    others = [str(i) for i in (ALICE_ID, BOB_ID, CAROL_ID) if str(i) != named[0]]
    assert all(member_card(activity_web, o).status_code == 404 for o in others)                                    # only the people that the map names have a card
    assert member_card(activity_web, named[0]).json()["top_links"] == []                                           # …and it only cites people that the map names too


def test_the_card_of_somebody_who_stopped_is_gone(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    switch_on(ingest_db)
    assert member_card(activity_web, CAROL_ID).status_code == 200
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (CAROL_ID,))
    assert member_card(activity_web, CAROL_ID).status_code == 404
    assert str(CAROL_ID) not in {link["id"] for link in member_card(activity_web, BOB_ID).json().get("top_links", [])}    # nor does she appear on the card of another


def test_the_admin_chooses_what_the_card_shows(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    discord_map.save(ingest_db, {"enabled": True, "sections": ["links"]})
    card = member_card(activity_web, BOB_ID).json()
    assert set(card) == {"id", "label", "top_links"}                                                                 # nothing but the name and what was ticked
    discord_map.save(ingest_db, {"enabled": True, "sections": ["activity", "months", "habits"]})
    assert set(member_card(activity_web, BOB_ID).json()) == {"id", "label", "activity", "by_month", "habits"}
    discord_map.save(ingest_db, {"enabled": True, "sections": []})
    assert set(member_card(activity_web, BOB_ID).json()) == {"id", "label"}


def test_the_sections_that_read_the_people_need_the_confirmation_everywhere(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    cfg = discord_map.save(ingest_db, {"enabled": True, "sections": ["activity", "roles", "axes"]})                  # saved without the confirmation (not through the API)
    assert cfg["sections"] == ["activity"]                                                                           # …they are dropped, whatever the way in
    cfg = discord_map.save(ingest_db, {"enabled": True, "sections": ["roles", "axes"], "acknowledged": True})
    card = member_card(activity_web, BOB_ID).json()
    assert cfg["sections"] == ["roles", "axes"] and card["roles"] == [] and card["axes"] == []                       # nobody read anything about Bob here: empty, and never a quote
    assert not {"claim", "quote", "evidence", "contributions"} & set(str(card))


@pytest.fixture
def pictures(ingest_db, ingest_url, activity_web, monkeypatch):
    """Bob has a picture in the database; Discord's CDN is a fake that counts what is fetched."""
    talk(ingest_url)
    ingest_db.execute("UPDATE members SET avatar_url = NULL")
    ingest_db.execute("UPDATE members SET avatar_url = %s WHERE user_id = %s", (f"https://cdn.discordapp.com/avatars/{BOB_ID}/abc.png?size=512", BOB_ID))
    fetched = []
    monkeypatch.setattr(activity.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the network must not be reached")))
    original = activity._fetch_image
    monkeypatch.setattr(activity, "_fetch_image", lambda url: (fetched.append(url), (b"\x89PNG-fake", "image/png"))[1])
    activity._avatars.clear()
    activity_web.original_fetch, activity_web.fetched = original, fetched
    return activity_web


def member_avatar(web, person, **params):
    return web.get(f"/activity/avatar/{person}", params={"guild": GUILD, **params}, headers={"Authorization": "Bearer member-token"})


def test_the_map_points_to_the_picture_of_the_people_it_names(ingest_db, pictures):
    switch_on(ingest_db, names=1)
    nodes = pictures.get("/activity/map", params={"guild": GUILD, "period": "30"}, headers={"Authorization": "Bearer member-token"}).json()["nodes"]
    pictured = [n for n in nodes if n["avatar"]]
    assert all(n["label"] for n in pictured) and all(n["avatar"] == f"/activity/avatar/{n['id']}?guild={GUILD}" for n in pictured)   # a picture only where a name is shown
    assert not [n for n in nodes if n["avatar"] and not n["label"]]


def test_a_member_gets_the_picture_through_the_server_and_it_is_kept(ingest_db, pictures):
    switch_on(ingest_db)
    assert pictures.get(f"/activity/avatar/{BOB_ID}", params={"guild": GUILD}).status_code == 401                      # a member's token, like the rest
    first = member_avatar(pictures, BOB_ID)
    assert first.status_code == 200 and first.headers["content-type"] == "image/png" and first.content == b"\x89PNG-fake"
    member_avatar(pictures, BOB_ID)
    assert pictures.fetched == [f"https://cdn.discordapp.com/avatars/{BOB_ID}/abc.png?size=512"]                       # asked to Discord once
    assert member_avatar(pictures, ALICE_ID).status_code == 404                                                         # no picture known


def test_no_picture_when_the_names_are_hidden_or_the_person_stopped(ingest_db, pictures):
    discord_map.save(ingest_db, {"enabled": True, "names": 0})
    assert member_avatar(pictures, BOB_ID).status_code == 404                                                           # no names: no faces either
    switch_on(ingest_db)
    assert member_avatar(pictures, BOB_ID).status_code == 200
    ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (BOB_ID,))
    assert member_avatar(pictures, BOB_ID).status_code == 404                                                           # even if it was kept in memory


def test_only_an_address_of_discords_cdn_is_ever_fetched(pictures):
    for url in ("http://cdn.discordapp.com/avatars/1/a.png", "https://evil.example/avatars/1/a.png", "https://cdn.discordapp.com/../etc/passwd", "https://cdn.discordapp.com.evil.example/avatars/1/a.png",
                "file:///etc/passwd"):
        with pytest.raises(activity.HTTPException):
            REAL_FETCH(url)


def test_the_member_can_filter_the_kinds_of_exchange_within_what_the_admins_allow(ingest_db, ingest_url, activity_web):
    talk(ingest_url)                                    # in this small server: a reply (Bob to Alice) and a mention (Bob to Carol)
    discord_map.save(ingest_db, {"enabled": True, "kinds": ["reply", "mention"]})
    both = member_map(activity_web).json()
    assert both["meta"]["kinds_allowed"] == ["reply", "mention"] and len(both["edges"]) == 2
    replies = member_map(activity_web, kinds="reply").json()
    assert replies["meta"]["kinds"] == ["reply"] and len(replies["edges"]) == 1
    assert len(member_map(activity_web, kinds="reaction").json()["edges"]) == 2                # not allowed by the admins: nothing changes (never more than allowed)
    assert len(member_map(activity_web, kinds="").json()["edges"]) == 2                        # none ticked: everything allowed
    assert {link["id"] for link in member_card(activity_web, BOB_ID, kinds="reply").json()["top_links"]} == {str(ALICE_ID)}    # the card follows the same filter


def test_the_picture_of_a_person_in_focus_has_their_card_and_the_photos_of_the_people_it_names(ingest_db, ingest_url, tmp_path, fake_cdn):
    talk(ingest_url)
    switch_on(ingest_db, names=40)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID, person=BOB_ID)))
    body, file = posted(sent)
    assert file is not None and Image.open(io.BytesIO(file[1])).size == (discord_map.WIDTH, discord_map.HEIGHT) and "autour de" in body["content"]
    assert len(fake_cdn) == 3                                                                         # the photos of the three people named, once each (and kept)
    asyncio.run(interactions.answer(map_command(CAROL_ID, person=BOB_ID, id="951")))
    assert len(fake_cdn) == 3


def test_no_names_on_the_map_means_no_photos_either(ingest_db, ingest_url, tmp_path, fake_cdn):
    talk(ingest_url)
    switch_on(ingest_db, names=0)
    interactions, service, sent, clock = commands(ingest_url, tmp_path)
    asyncio.run(interactions.answer(map_command(CAROL_ID, period="7")))
    assert posted(sent)[1] is not None and fake_cdn == []                                             # a plain disc per person: nothing was fetched


def test_the_card_on_the_picture_only_has_what_the_admins_allowed(ingest_db):
    data = {"people": [{"id": 1, "label": "Alice", "color": "#E91E63", "influence": 5.0}, {"id": 2, "label": "Bob", "color": None, "influence": 3.0}],
            "links": [(1, 2, 2.0)], "focus": 1, "counts": {(1, 2): 4}}
    full = {"id": "1", "label": "Alice", "activity": {"messages": 1204, "active_days": 86, "messages_per_active_day": 14.0, "average_length": 57, "share_of_replies": 0.38,
                                                      "first_message_at": "2024-03-02T10:00:00+00:00", "last_message_at": "2026-10-05T21:00:00+00:00", "recent": 12, "rank": 3,
                                                      "writers": 120, "reactions_received": 431, "contacts": 34},
            "by_month": [{"month": "2026-01", "messages": 5}, {"month": "2026-02", "messages": 9}], "habits": {"hours": list(range(24)), "weekdays": [1] * 7},
            "top_links": [{"id": "2", "label": "Bob", "weight": 2.0, "n": 4}], "roles": ["Socialiste"], "axes": [{"name": "Économie", "pole": "Redistribution", "score": -0.6}]}
    for card in (full, {"id": "1", "label": "Alice"}, None):                                          # everything, nothing but the name, no card at all: all draw
        assert Image.open(io.BytesIO(discord_map.render(data, 5, {1: _small_png()}, card))).size == (discord_map.WIDTH, discord_map.HEIGHT)


def test_the_interface_shows_photos_too(ingest_db, ingest_url, tmp_path, fake_cdn):
    """The map of the interface (behind the password) has the photos: a path in the nodes, served by the server, never for somebody who asked not to be recorded."""
    talk(ingest_url)
    ingest_db.execute("UPDATE members SET avatar_url = NULL")
    ingest_db.execute("UPDATE members SET avatar_url = %s WHERE user_id IN (%s, %s)", ("https://cdn.discordapp.com/avatars/1/abc.png?size=512", BOB_ID, ALICE_ID))
    with TestClient(create_app(settings_for(ingest_url, tmp_path), background=False)) as web:
        assert web.get(f"/api/avatar/{BOB_ID}", params={"guild": GUILD}).status_code == 401
        assert web.post("/api/login", json={"password": PASSWORD}).status_code == 200
        nodes = {n["id"]: n for n in web.get("/api/graph", params={"guild": GUILD}).json()["nodes"]}
        assert nodes[str(BOB_ID)]["avatar"] == f"/api/avatar/{BOB_ID}?guild={GUILD}" and nodes[str(CAROL_ID)]["avatar"] is None          # Carol has no photo
        photo = web.get(nodes[str(BOB_ID)]["avatar"])
        assert photo.status_code == 200 and photo.headers["content-type"] == "image/png" and web.get(f"/api/avatar/{CAROL_ID}", params={"guild": GUILD}).status_code == 404
        ingest_db.execute("INSERT INTO privacy_subjects (user_id, status, reason, source) VALUES (%s, 'stopped', 'objection', 'discord')", (BOB_ID,))
        assert web.get(f"/api/avatar/{BOB_ID}", params={"guild": GUILD}).status_code == 404                                                 # nor for somebody who stopped
        assert all(n["avatar"] is None for n in web.get("/api/graph", params={"guild": GUILD}).json()["nodes"] if n["id"] == str(BOB_ID))


def test_the_member_narrows_the_map_only_with_the_filters_that_the_admins_offer(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    discord_map.save(ingest_db, {"enabled": True, "kinds": ["reply", "mention"]})
    plain = member_map(activity_web).json()
    assert plain["meta"]["filters_allowed"] == ["weight"] and plain["meta"]["choices"] == {} and len(plain["edges"]) == 2
    assert member_map(activity_web, weight=10).json()["edges"] == []                           # the strength is always offered
    assert member_map(activity_web, weight=7).status_code == 422                               # only the choices of the page
    assert len(member_map(activity_web, theme=999999, ideology=999).json()["edges"]) == 2      # not offered: ignored, never more than allowed
    discord_map.save(ingest_db, {"enabled": True, "kinds": ["reply", "mention"], "filters": ["weight", "theme", "ideology"]})
    assert discord_map.load(ingest_db)["filters"] == ["weight"]                                # a topic and a role need the confirmation of the admin
    discord_map.save(ingest_db, {"enabled": True, "kinds": ["reply", "mention"], "filters": ["weight", "theme", "ideology"], "acknowledged": True})
    offered = member_map(activity_web).json()["meta"]
    assert offered["filters_allowed"] == ["weight", "theme", "ideology"] and set(offered["choices"]) == {"themes", "ideologies"}
    assert member_map(activity_web, theme=999999).json()["edges"] == []                        # no conversation about it
    assert member_map(activity_web, ideology=999).json()["edges"] == []                        # nobody has this role
    assert member_card(activity_web, BOB_ID, ideology=999).status_code == 404                  # the card follows the same filter


def test_a_member_chooses_how_many_people_to_see_never_more_than_the_administrators_allow(ingest_db, ingest_url, activity_web):
    talk(ingest_url)
    discord_map.save(ingest_db, {"enabled": True, "max_people": 5, "names": 5})
    everyone = member_map(activity_web).json()
    assert len(everyone["nodes"]) == 3 and everyone["meta"]["max_people"] == 5 and everyone["meta"]["people"] == 5
    two = member_map(activity_web, people=2).json()
    assert len(two["nodes"]) == 2 and two["meta"]["people"] == 2 and sum(1 for n in two["nodes"] if n["label"]) <= 2
    assert member_map(activity_web, people=300).json()["meta"]["people"] == 5                  # the ceiling is the administrators'
    assert member_map(activity_web, people=0).status_code == 422 and member_map(activity_web, people="x").status_code == 422
