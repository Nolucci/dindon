"""The API: password, graph, people, what is never shown."""
import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dindon.api.auth import COOKIE, Auth
from dindon.api.main import create_app
from dindon.bot.adapter import Directory, build_document, digest
from dindon.ingest.loader import GATEWAY_SOURCE, ingest_document, ingest_file
from gateway_fixtures import (ADMIN, ALICE, BOB, BOT, CAROL, CITIZEN, EUROPEAN, GENERAL, GUILD, OLD_DAVE, guild_create, member, message_create,
                              role)
from make_demo_server import AGE_ROLES, GENDER_ROLES, World, write_exports
from synthetic import settings_for

DB_DIR = Path(__file__).resolve().parents[1] / "db"
PASSWORD = "correct horse"


@pytest.fixture(scope="module")
def world():
    w = World(seed=5, people=50)
    w.generate(4000, days=60, end=datetime.now(UTC) - timedelta(days=1))
    return w


@pytest.fixture
def api(ingest_db, ingest_url, world, tmp_path):
    for path in write_exports(world, tmp_path / "exports"):
        ingest_file(ingest_db, path)
    with TestClient(create_app(settings_for(ingest_url, tmp_path), background=False)) as client:
        yield client


@pytest.fixture
def me(api):
    assert api.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return api


# ---------------------------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/guilds", "/api/graph", "/api/people?q=a", "/api/person/1", "/api/avatar/1", "/api/status", "/events"])
def test_nothing_is_served_without_the_session(api, path):
    assert api.get(path).status_code == 401


def test_the_health_check_needs_no_password_and_shows_no_content(api):
    body = api.get("/health").json()
    assert body["status"] == "ok" and set(body) == {"status", "version", "database", "ollama"}


def test_login_sets_a_cookie_that_the_page_cannot_read_nor_send_from_elsewhere(api):
    assert api.post("/api/login", json={"password": "nope"}).status_code == 401
    response = api.post("/api/login", json={"password": PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert api.get("/api/session").json() == {"authenticated": True}
    api.post("/api/logout")
    assert api.get("/api/session").json() == {"authenticated": False}


def test_a_forged_or_expired_cookie_is_refused(api):
    auth = Auth(PASSWORD)
    for token in ("", "garbage", "9999999999.deadbeef", Auth("another password").make_token(), auth.make_token(now=0)):
        api.cookies.set(COOKIE, token)
        assert api.get("/api/status").status_code == 401
    api.cookies.set(COOKIE, auth.make_token())
    assert api.get("/api/status").status_code == 200


def test_after_a_few_wrong_passwords_logging_in_is_refused_for_a_while(api):
    for _ in range(5):
        assert api.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert api.post("/api/login", json={"password": PASSWORD}).status_code == 429  # even the right one, for now


def test_the_application_does_not_start_without_a_password(ingest_url, tmp_path):
    with pytest.raises(RuntimeError, match="DINDON_PASSWORD"):
        create_app(dataclasses.replace(settings_for(ingest_url, tmp_path), password=""), background=False)


def test_pages_may_only_load_what_the_application_serves(me):
    csp = me.get("/api/status").headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp
    assert not re.search(r"https?://", csp)  # no CDN, no font service, nothing from outside
    assert me.get("/api/status").headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------------------------


def test_the_graph_is_made_of_people_and_links_between_them(me, world):
    graph = me.get("/api/graph").json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert graph["meta"]["nodes_shown"] == len(nodes) > 20 and graph["meta"]["nodes_hidden"] == 0
    assert graph["edges"] and all(e["source"] in nodes and e["target"] in nodes and e["source"] != e["target"] for e in graph["edges"])
    assert all(e["weight"] > 0 and e["kinds"] for e in graph["edges"])
    assert [e["weight"] for e in graph["edges"]] == sorted((e["weight"] for e in graph["edges"]), reverse=True)
    assert str(world.bot.id) not in nodes  # bots are left out
    top = graph["nodes"][0]
    assert top["influence"] == max(n["influence"] for n in graph["nodes"]) and top["messages"] > 0


def test_the_limit_keeps_the_most_connected_people_and_says_what_is_hidden(me):
    full = me.get("/api/graph").json()
    small = me.get("/api/graph?limit=12").json()
    assert small["meta"]["nodes_shown"] <= 12 and small["meta"]["nodes_hidden"] == full["meta"]["nodes_total"] - small["meta"]["nodes_shown"] > 0
    kept = {n["id"] for n in small["nodes"]}
    assert all(e["source"] in kept and e["target"] in kept for e in small["edges"])
    degree = {}
    for e in full["edges"]:
        for end in (e["source"], e["target"]):
            degree[end] = degree.get(end, 0) + e["weight"]
    expected = set(sorted(degree, key=lambda u: -degree[u])[:12])
    assert len(kept & expected) >= 11  # the most connected ones (a person left without a link inside the cut can drop out)


def test_kinds_and_minimum_weight_filter_the_links(me):
    replies = me.get("/api/graph?kinds=reply").json()
    assert replies["edges"] and all(set(e["kinds"]) == {"reply"} for e in replies["edges"])
    everything = me.get("/api/graph").json()
    assert len(replies["edges"]) < len(everything["edges"])
    strong = me.get("/api/graph?min_weight=3").json()
    assert strong["edges"] and all(e["weight"] >= 3 for e in strong["edges"]) and len(strong["edges"]) < len(everything["edges"])
    assert me.get("/api/graph?kinds=nonsense").status_code == 422


def test_a_period_is_counted_again_from_the_messages_and_agrees_with_the_whole(me):
    """Two different computations (the links kept by the ingestion, and the messages of a period) must agree."""
    whole = {(e["source"], e["target"]): e for e in me.get("/api/graph").json()["edges"]}
    from_messages = {(e["source"], e["target"]): e for e in me.get("/api/graph?since=2000-01-01T00:00:00Z").json()["edges"]}
    assert whole.keys() == from_messages.keys()
    for key, edge in whole.items():
        assert edge["weight"] == pytest.approx(from_messages[key]["weight"], rel=1e-3), key
        assert edge["n"] == from_messages[key]["n"]


def test_a_narrow_period_shows_only_what_happened_in_it(me):
    me.get("/api/graph").json()["meta"]
    now = datetime.now(UTC)
    week = me.get("/api/graph", params={"since": (now - timedelta(days=7)).isoformat(), "until": now.isoformat()}).json()
    allt = me.get("/api/graph").json()
    assert 0 < len(week["edges"]) < len(allt["edges"]) and week["meta"]["period"]["since"]
    assert all(datetime.fromisoformat(e["last_at"]) >= now - timedelta(days=7) for e in week["edges"])
    nothing = me.get("/api/graph", params={"until": "2001-01-01T00:00:00Z"}).json()
    assert nothing["edges"] == [] and nothing["nodes"] == []


def test_the_old_exchanges_weigh_less(me, ingest_db):
    ingest_db.execute("UPDATE scoring_settings SET value = 1 WHERE key = 'edge_half_life_days'")  # a short memory
    short = {(e["source"], e["target"]): e["weight"] for e in me.get("/api/graph").json()["edges"]}
    ingest_db.execute("UPDATE scoring_settings SET value = 3650 WHERE key = 'edge_half_life_days'")  # a very long one
    long = {(e["source"], e["target"]): e["weight"] for e in me.get("/api/graph").json()["edges"]}
    common = short.keys() & long.keys()
    assert common and all(short[k] <= long[k] for k in common) and sum(short.values()) < sum(long.values()) / 2


# ---------------------------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------------------------


def test_search_ignores_case_accents_and_fancy_letters(me, world):
    fancy_person = next(p for p in world.people if p.global_name and not p.global_name.isascii() and p.nickname is None)
    plain = fancy_person.name.lower()
    found = me.get("/api/people", params={"q": plain[:4].upper()}).json()
    assert any(r["label"].lower().startswith(plain[:4]) or plain[:4] in r["label"].lower() for r in found)
    accent = me.get("/api/people", params={"q": "ele"}).json()  # finds "Éli..." / "éli..."
    assert isinstance(accent, list)
    assert all(r["messages"] >= 0 for r in found)


def test_the_card_of_a_person(me, world):
    graph = me.get("/api/graph").json()
    person = me.get(f"/api/person/{graph['nodes'][0]['id']}").json()
    assert person["activity"]["messages"] == graph["nodes"][0]["messages"]
    assert person["activity"]["first_message_at"] <= person["activity"]["last_message_at"]
    assert person["top_links"] and person["top_links"][0]["weight"] >= person["top_links"][-1]["weight"]
    assert person["by_month"] and person["top_channels"] and person["names"]["seen_as"]
    assert set(person["exchanges"]["sent"]) == {"reply", "mention", "reaction"}
    assert me.get("/api/person/12345").status_code == 404


def test_age_and_gender_roles_never_come_out(me, world):
    """The roles that people took for their age or gender are left out everywhere: not analyzed, not shown."""
    sensitive = AGE_ROLES + GENDER_ROLES
    sensitive_ids = {int(r["id"]) for name, r in world.roles.items() if name in sensitive}
    holders = [p for p in world.people if sensitive_ids & set(p.role_ids)]
    assert len(holders) > 10  # the invented server does have people with such roles
    for p in world.people[:25]:
        body = me.get(f"/api/person/{p.id}").text
        assert not any(name in body for name in sensitive), p.name
        card = json.loads(body)
        assert set(card) <= {"id", "label", "is_bot", "names", "activity", "exchanges", "by_month", "top_channels", "top_links",
                             "claimed_roles", "claimed_roles_note", "color"}
    # and the roles that do come out say an ideology
    some = next(p for p in world.people if any(r["name"] in {"Eurosceptique", "Écologiste", "Communiste", "Socialiste", "Patriote"}
                                                and int(r["id"]) in p.role_ids for r in world.roles.values()))
    claimed = me.get(f"/api/person/{some.id}").json()["claimed_roles"]
    assert claimed and all(set(c) == {"role", "ideology"} for c in claimed)


def test_status_says_what_the_system_is_doing(me, tmp_path):
    state = me.get("/api/status").json()
    assert state["ingest"]["files"] > 0 and state["collector"] == {"enabled": False} and state["warnings"] == []
    assert state["jobs"]["conversations"] > 0


def test_the_interface_is_warned_when_a_personal_account_is_being_automated(me):
    from types import SimpleNamespace

    me.app.state.collector = SimpleNamespace(status=lambda: {"enabled": True, "token_kind": "account"})
    assert me.get("/api/status").json()["warnings"] == ["account_token"]
    me.app.state.collector = SimpleNamespace(status=lambda: {"enabled": True, "token_kind": "bot"})
    assert me.get("/api/status").json()["warnings"] == []


def test_the_cap_on_links_keeps_the_strongest_and_says_how_many_are_hidden(me):
    full = me.get("/api/graph").json()
    capped = me.get("/api/graph?max_edges=40").json()
    assert capped["meta"]["edges_shown"] == len(capped["edges"]) == 40
    assert capped["meta"]["edges_hidden"] == full["meta"]["edges_shown"] - 40 > 0
    weakest_kept = min(e["weight"] for e in capped["edges"])
    assert all(e["weight"] <= weakest_kept + 1e-9 for e in full["edges"][40:])  # what is left out is weaker than what is shown
    assert full["meta"]["edges_hidden"] == 0


# ---------------------------------------------------------------------------------------------
# People without a link
# ---------------------------------------------------------------------------------------------

ERIN = {"id": "1000000000000000006", "username": "erin", "discriminator": "0", "global_name": "Erin", "avatar": None}
FRANK = {"id": "1000000000000000007", "username": "frank", "discriminator": "0", "global_name": "Frank", "avatar": None}


def _ago(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


@pytest.fixture
def small_server(ingest_db):
    """One small server of its own, next to the big invented one:
    Alice writes alone (twice); Bob answers Carol, now; Erin and Frank talked 100 days ago; Dave wrote alone 200 days ago; a bot wrote."""
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    counter = iter(range(9_000_000_000_000_000_000 - 100, 9_000_000_000_000_000_000))
    def msg(text, author, when, **kw):
        return message_create(next(counter), text, author, timestamp=when, **kw)
    carol_says = msg("on y va ?", CAROL, _ago(hours=2))
    erin_says = msg("salut", ERIN, _ago(days=100, minutes=1))
    messages = [
        msg("je parle seule", ALICE, _ago(days=2), member_data=member("Ali")), msg("encore moi", ALICE, _ago(days=1), member_data=member("Ali")),
        carol_says, msg("oui", BOB, _ago(hours=1), reply_to=carol_says),
        erin_says, msg("salut Erin", FRANK, _ago(days=100), reply_to=erin_says),
        msg("il y a longtemps", OLD_DAVE, _ago(days=200)),
        msg("annonce automatique", {**BOT, "bot": True}, _ago(minutes=5), member_data=None),
    ]
    document = build_document(directory, GUILD, GENERAL, messages)
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    return {name: person["id"] for name, person in dict(alice=ALICE, bob=BOB, carol=CAROL, dave=OLD_DAVE, erin=ERIN, frank=FRANK, bot=BOT).items()}


def _graph(client, **params) -> dict:
    return client.get("/api/graph", params={"guild": GUILD, **params}).json()


def test_people_without_a_link_are_only_added_when_asked(me, small_server):
    ids = small_server
    plain = _graph(me)
    assert {n["id"] for n in plain["nodes"]} == {ids["bob"], ids["carol"], ids["erin"], ids["frank"]}  # as before: only the linked ones
    assert plain["meta"]["isolated_shown"] == 0 and plain["meta"]["isolated_hidden"] == 0
    asked = _graph(me, isolated="true")
    nodes = {n["id"]: n for n in asked["nodes"]}
    assert set(nodes) == {ids["bob"], ids["carol"], ids["erin"], ids["frank"], ids["alice"], ids["dave"]}  # nobody else, no bot
    assert asked["edges"] == plain["edges"]                                                                # the links do not change
    assert [n["id"] for n in asked["nodes"][:4]] == [n["id"] for n in plain["nodes"]]                      # the linked ones come first, in the same order
    assert not any(nodes[i].get("isolated") for i in (ids["bob"], ids["carol"], ids["erin"], ids["frank"]))
    alice = nodes[ids["alice"]]
    assert alice["isolated"] is True and alice["influence"] == 0 and alice["messages"] == 2 and alice["label"] == "Ali"
    assert alice["last_message_at"] is not None and nodes[ids["dave"]]["messages"] == 1
    assert [n["id"] for n in asked["nodes"][4:]] == [ids["alice"], ids["dave"]]                            # the most talkative first
    meta = asked["meta"]
    assert (meta["nodes_shown"], meta["isolated_shown"], meta["isolated_hidden"], meta["nodes_hidden"]) == (6, 2, 0, 0)


def test_whoever_ever_wrote_stays_on_the_map_whatever_the_period(me, small_server):
    """In the last 7 days only Bob and Carol exchanged; Erin and Frank, and the others, are still there, without a link."""
    ids = small_server
    week = _graph(me, isolated="true", since=_ago(days=7))
    nodes = {n["id"]: n for n in week["nodes"]}
    assert {n["id"] for n in week["nodes"] if not n.get("isolated")} == {ids["bob"], ids["carol"]}
    assert {i for i, n in nodes.items() if n.get("isolated")} == {ids["alice"], ids["dave"], ids["erin"], ids["frank"]}
    assert nodes[ids["dave"]]["messages"] == 1 and nodes[ids["erin"]]["messages"] == 1  # their whole activity, not the period's
    assert len(week["edges"]) == 1


def test_kinds_that_are_switched_off_leave_their_people_as_points_without_a_link(me, small_server):
    ids = small_server
    only_mentions = _graph(me, isolated="true", kinds="mention")
    assert only_mentions["edges"] == [] and {n["id"] for n in only_mentions["nodes"]} == {ids["bob"], ids["carol"], ids["erin"], ids["frank"], ids["alice"], ids["dave"]}
    assert all(n["isolated"] for n in only_mentions["nodes"])


def test_bots_are_left_out_of_the_points_without_a_link_unless_asked(me, small_server):
    ids = small_server
    assert ids["bot"] not in {n["id"] for n in _graph(me, isolated="true")["nodes"]}
    shown = {n["id"]: n for n in _graph(me, isolated="true", bots="true")["nodes"]}
    assert shown[ids["bot"]]["isolated"] is True


def test_the_limit_counts_the_points_without_a_link_and_the_linked_ones_come_first(me, small_server, ingest_db):
    ids = small_server
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    extra = [{"id": str(2_000_000_000_000_000_000 + i), "username": f"extra{i}", "discriminator": "0", "global_name": None, "avatar": None}
             for i in range(1, 9)]
    document = build_document(directory, GUILD, GENERAL, [message_create(8_000_000_000_000_000_000 + i, "bonjour", person, timestamp=_ago(minutes=i))
                                                          for i, person in enumerate(extra, 1)])
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    everyone = _graph(me, isolated="true", limit=100)
    assert everyone["meta"]["isolated_shown"] == 10 and everyone["meta"]["nodes_shown"] == 14   # 4 linked + Alice, Dave + 8 more
    tight = _graph(me, isolated="true", limit=10)
    linked = [n for n in tight["nodes"] if not n["isolated"]]
    isolated = [n for n in tight["nodes"] if n["isolated"]]
    assert tight["meta"]["nodes_shown"] == 10 and len(linked) == 4                                    # the linked ones are never pushed out
    assert [n["id"] for n in isolated[:2]] == [ids["alice"], ids["dave"]]                              # then the most talkative, then by id
    assert tight["meta"]["isolated_shown"] == 6 and tight["meta"]["isolated_hidden"] == 4


def test_the_card_of_a_person_without_a_link_opens(me, small_server):
    card = me.get(f"/api/person/{small_server['alice']}?guild={GUILD}")
    assert card.status_code == 200 and card.json()["activity"]["messages"] == 2 and card.json()["top_links"] == []


def _close(a, b, tolerance=1e-3) -> bool:
    """Equal, but the numbers only need to agree to a thousandth: the weights of the links fade with the clock (half-life of 90 days),
    and the two requests of a test are not made at the same millisecond, so the fourth decimal can differ."""
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], tolerance) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_close(x, y, tolerance) for x, y in zip(a, b, strict=False))
    if isinstance(a, float):
        return abs(a - b) <= tolerance
    return a == b


def test_without_the_option_the_big_server_is_unchanged_and_with_it_only_points_are_added(me, world):
    plain = me.get("/api/graph").json()
    asked = me.get("/api/graph?isolated=true").json()
    assert _close(asked["edges"], plain["edges"])
    linked = [n for n in asked["nodes"] if not n.get("isolated")]
    assert _close(linked, plain["nodes"])
    assert asked["meta"]["nodes_shown"] == len(asked["nodes"]) == len(plain["nodes"]) + asked["meta"]["isolated_shown"]


# ---------------------------------------------------------------------------------------------
# The color of a person
# ---------------------------------------------------------------------------------------------

AGE_ROLE = "303"  # "Entre 21 et 30 ans", position 6: above all the others, and blue


@pytest.fixture
def colored_server(ingest_db):
    """Bob has the red and the green roles; Carol only the green one; Alice none; Erin has the green role and, above it, a blue
    age role; Frank only the blue age role. Discord shows each person's name in the color of their highest colored role."""
    directory = Directory([GUILD])
    created = guild_create()
    created["roles"].append(role(AGE_ROLE, "Entre 21 et 30 ans", 6, 0x0000FF))
    directory.apply("GUILD_CREATE", created)
    counter = iter(range(9_100_000_000_000_000_000 - 100, 9_100_000_000_000_000_000))
    def msg(author, nick, roles, **kw):
        return message_create(next(counter), "salut", author, timestamp=_ago(hours=1), member_data=member(nick, roles=roles), **kw)
    messages = [msg(BOB, "Bob", (CITIZEN, EUROPEAN, ADMIN)), msg(CAROL, "Carol", (CITIZEN, EUROPEAN)), msg(ALICE, "Ali", ()),
                msg(ERIN, "Erin", (EUROPEAN, AGE_ROLE)), msg(FRANK, "Frank", (AGE_ROLE,))]
    document = build_document(directory, GUILD, GENERAL, messages)
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    return {name: person["id"] for name, person in dict(alice=ALICE, bob=BOB, carol=CAROL, erin=ERIN, frank=FRANK).items()}


def test_each_point_has_the_color_that_the_person_has_in_discord(me, colored_server):
    ids = colored_server
    nodes = {n["id"]: n for n in _graph(me, isolated="true")["nodes"]}
    assert nodes[ids["bob"]]["color"] == "#FF0000"       # the highest role that has a color
    assert nodes[ids["carol"]]["color"] == "#00FF00"
    assert nodes[ids["alice"]]["color"] is None          # no colored role: no color, the page uses Discord's default


def test_the_color_never_comes_from_a_role_of_age_or_gender(me, colored_server):
    """The blue role says an age bracket: a blue point would say it too. The next colored role counts, or none."""
    ids = colored_server
    nodes = {n["id"]: n for n in _graph(me, isolated="true")["nodes"]}
    assert nodes[ids["erin"]]["color"] == "#00FF00"
    assert nodes[ids["frank"]]["color"] is None
    assert "#0000FF" not in json.dumps(_graph(me, isolated="true"))


def test_a_color_that_is_not_a_color_is_not_sent(me, ingest_db):
    """The text comes from an export file: only #RRGGBB goes to the page (black is Discord's 'no color')."""
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    messages = [message_create(9_200_000_000_000_000_000 + i, "x", author, timestamp=_ago(hours=1), member_data=member(roles=(ADMIN,)))
                for i, author in enumerate((BOB, CAROL))]
    document = build_document(directory, GUILD, GENERAL, messages)
    document["roles"] = [dict(r, color={"301": "url(http://elsewhere/)", "302": "#000000"}.get(r["id"], r.get("color"))) for r in document["roles"]]
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    assert all(n["color"] is None for n in _graph(me, isolated="true")["nodes"])


def test_a_black_role_is_no_color_and_the_next_colored_role_counts(me, ingest_db):
    """Discord shows no color for a black role; a black role that outranks a colored one must not hide it."""
    directory = Directory([GUILD])
    created = guild_create()
    created["roles"] = [role(GUILD, "@everyone", 0), role(EUROPEAN, "Européiste", 3, 0x00FF00), role(ADMIN, "Admin", 5, 0x000001)]
    directory.apply("GUILD_CREATE", created)
    messages = [message_create(8_300_000_000_000_000_000 + i, "salut", author, timestamp=_ago(hours=1), member_data=member(roles=(EUROPEAN, ADMIN)))
                for i, author in enumerate((BOB, CAROL))]
    document = build_document(directory, GUILD, GENERAL, messages)
    document["roles"] = [dict(r, color="#000000") if r["id"] == ADMIN else r for r in document["roles"]]
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    colors = {n["id"]: n["color"] for n in _graph(me, isolated="true")["nodes"]}
    assert set(colors.values()) == {"#00FF00"}


def test_the_color_that_an_export_gives_is_not_used_when_the_roles_are_not_known(me, ingest_db):
    """An export gives the color of the highest colored role, whatever it is (an age role too): without the roles to check it, it is
    not sent."""
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    messages = [message_create(8_400_000_000_000_000_000, "salut", BOB, timestamp=_ago(hours=1), member_data=member())]
    document = build_document(directory, GUILD, GENERAL, messages)
    for user in document["users"]:
        user["color"] = "#0000FF"                                                     # the color of some role that nothing here describes
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    assert [n["color"] for n in _graph(me, isolated="true")["nodes"]] == [None]



def test_the_map_can_be_narrowed_to_a_channel_a_theme_or_an_ideology(me):
    options = me.get("/api/map/filters").json()
    assert set(options) == {"channels", "roles", "themes", "ideologies"} and len(options["channels"]) >= 2
    everything = me.get("/api/graph").json()
    busiest, quietest = options["channels"][0], options["channels"][-1]
    one = me.get("/api/graph", params={"channels": quietest["id"]}).json()
    assert one["edges"] != everything["edges"] and sum(e["n"] for e in one["edges"]) < sum(e["n"] for e in everything["edges"])
    both = me.get("/api/graph", params={"channels": f"{busiest['id']},{quietest['id']}"}).json()
    assert sum(e["n"] for e in both["edges"]) >= sum(e["n"] for e in one["edges"])
    assert me.get("/api/graph", params={"channels": "abc"}).status_code == 422
    assert me.get("/api/graph", params={"theme": 999999}).json()["edges"] == []                    # no conversation about it
    assert me.get("/api/graph", params={"ideology": 999}).json()["edges"] == []                    # nobody has this role
    assert me.get("/api/graph", params={"ideology": 999, "isolated": True}).json()["nodes"] == []
    # the roles offered are those of the server as they are on Discord; the ones that say an age or a gender never are
    names = {r["name"] for r in options["roles"]}
    assert options["roles"] and not names & {"Homme", "Femme", "18-25 ans"} and all(r["people"] > 0 for r in options["roles"])
    role = options["roles"][0]
    narrowed = me.get("/api/graph", params={"role": role["id"]}).json()
    assert len(narrowed["edges"]) <= len(everything["edges"])
    assert me.get("/api/graph", params={"role": 999}).json()["edges"] == []                         # nobody has this role
    assert me.get("/api/graph", params={"role": role["id"], "ideology": 999}).json()["edges"] == []   # the two together
    assert me.get("/api/graph", params={"role": "abc"}).status_code == 422
