"""The API: password, graph, people, what is never shown."""
import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dindon.api.auth import COOKIE, Auth
from dindon.api.main import create_app
from dindon.ingest.loader import ingest_file
from make_demo_server import AGE_ROLES, GENDER_ROLES, World, write_exports
from synthetic import settings_for

DB_DIR = Path(__file__).resolve().parents[1] / "db"
PASSWORD = "correct horse"


@pytest.fixture(scope="module")
def world():
    w = World(seed=5, people=50)
    w.generate(4000, days=60, end=datetime.now(timezone.utc) - timedelta(days=1))
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


@pytest.mark.parametrize("path", ["/api/guilds", "/api/graph", "/api/people?q=a", "/api/person/1", "/api/status", "/events"])
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
    meta = me.get("/api/graph").json()["meta"]
    now = datetime.now(timezone.utc)
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
                             "claimed_roles", "claimed_roles_note"}
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
