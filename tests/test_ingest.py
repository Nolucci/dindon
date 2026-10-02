"""The ingestion of JSON v2 exports: no loss, no duplicates, edits, interruptions, and the links of the graph.

Everything is invented (tools/make_demo_server.py). The database is a copy of the migrated one, with real commits.
"""
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from dindon.ingest.loader import InvalidExport, ingest_document, ingest_file
from make_demo_server import World, parse_iso, write_exports

TABLES = ["guilds", "channels", "users", "members", "roles", "member_roles", "identity_history", "emojis", "messages",
          "attachments", "mentions", "message_emojis", "reactions", "reaction_users", "edges"]


@pytest.fixture(scope="module")
def world():
    w = World(seed=7, people=40)
    w.generate(1800, days=30)
    # something of every kind: a bot, a reply to a person who then leaves no trace, a very long message
    return w


@pytest.fixture
def files(world, tmp_path):
    return write_exports(world, tmp_path / "exports")


def counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def edges_snapshot(conn) -> dict:
    rows = conn.execute("SELECT guild_id, from_user_id, to_user_id, kind, weight, n, last_at FROM edges").fetchall()
    return {(g, f, t, k): (w, n, at) for g, f, t, k, w, n, at in rows}


def assert_edges_equal_rebuild(conn, tolerance=1e-9):
    """The links kept up to date by the ingestion are the same as the ones rebuilt from the messages."""
    incremental = edges_snapshot(conn)
    conn.execute("SELECT rebuild_edges()")
    rebuilt = edges_snapshot(conn)
    assert incremental.keys() == rebuilt.keys()
    for key, (w, n, at) in incremental.items():
        w2, n2, at2 = rebuilt[key]
        assert (n, at) == (n2, at2), key
        assert w == pytest.approx(w2, rel=tolerance, abs=tolerance), key


def write_doc(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# No loss: every message of the database is the one of the file
# ---------------------------------------------------------------------------------------------


def test_round_trip_loses_nothing(ingest_db, files):
    conn = ingest_db
    total = 0
    for path in files:
        result = ingest_file(conn, path)
        assert result.status == "imported"
        total += result.messages_in_file
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == total > 1500

    messages = {r[0]: r for r in conn.execute(
        """SELECT id, channel_id, author_id, type, sent_at, edited_at, is_pinned, content, reference_message_id, reference_author_id,
                  reference_content, extra FROM messages""")}
    mentions, reactions, reaction_users, inline, attachments = {}, {}, {}, {}, {}
    for mid, uid in conn.execute("SELECT message_id, user_id FROM mentions"):
        mentions.setdefault(mid, set()).add(uid)
    for mid, key, n in conn.execute("SELECT message_id, emoji_key, count FROM reactions"):
        reactions.setdefault(mid, set()).add((key, n))
    for mid, key, uid in conn.execute("SELECT message_id, emoji_key, user_id FROM reaction_users"):
        reaction_users.setdefault(mid, set()).add((key, uid))
    for mid, key in conn.execute("SELECT message_id, emoji_key FROM message_emojis"):
        inline.setdefault(mid, set()).add(key)
    for mid, aid, url, name, size in conn.execute("SELECT message_id, id, url, file_name, size_bytes FROM attachments"):
        attachments.setdefault(mid, set()).add((aid, url, name, size))

    seen = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        for m in document["messages"]:
            mid = int(m["id"])
            row = messages[mid]
            ref = m.get("reference", {})
            assert row[1] == int(document["channel"]["id"]) and row[2] == int(m["authorId"]) and row[3] == m["type"]
            assert row[4] == parse_iso(m["timestamp"]) and row[5] == (parse_iso(m["timestampEdited"]) if "timestampEdited" in m else None)
            assert row[6] == m.get("isPinned", False) and row[7] == m["content"]
            assert row[8] == (int(ref["messageId"]) if "messageId" in ref else None)
            assert row[9] == (int(ref["authorId"]) if "authorId" in ref else None) and row[10] == ref.get("content")
            assert row[11] == ({k: m[k] for k in ("embeds", "stickers", "poll", "forwardedMessage") if k in m} or None)
            assert mentions.get(mid, set()) == {int(u) for u in m.get("mentionedUserIds", [])}
            assert reactions.get(mid, set()) == {(r["emoji"], r["count"]) for r in m.get("reactions", [])}
            assert reaction_users.get(mid, set()) == {(r["emoji"], int(u)) for r in m.get("reactions", []) for u in r["userIds"]}
            assert inline.get(mid, set()) == set(m.get("inlineEmojis", []))
            assert attachments.get(mid, set()) == {(int(a["id"]), a["url"], a["fileName"], a["fileSizeBytes"]) for a in m.get("attachments", [])}
            seen += 1
    assert seen == total

    # people and roles as well
    document = json.loads(files[0].read_text(encoding="utf-8"))
    guild_id = int(document["guild"]["id"])
    for u in document["users"]:
        name, global_name, nickname = conn.execute(
            "SELECT u.name, u.global_name, m.nickname FROM users u JOIN members m ON m.user_id = u.id AND m.guild_id = %s WHERE u.id = %s",
            (guild_id, int(u["id"]))).fetchone()
        assert (name, global_name, nickname) == (u["name"], u.get("globalName"), u.get("nickname"))
        roles = {r[0] for r in conn.execute("SELECT role_id FROM member_roles WHERE guild_id = %s AND user_id = %s", (guild_id, int(u["id"])))}
        assert roles == {int(r) for r in u.get("roleIds", [])}
    assert_edges_equal_rebuild(conn)


# ---------------------------------------------------------------------------------------------
# Idempotence and overlaps
# ---------------------------------------------------------------------------------------------


def test_the_same_file_twice_changes_nothing(ingest_db, files):
    conn = ingest_db
    for path in files[:4]:
        assert ingest_file(conn, path).status == "imported"
    before, edges_before = counts(conn), edges_snapshot(conn)
    for path in files[:4]:
        assert ingest_file(conn, path).status == "duplicate"
    assert counts(conn) == before and edges_snapshot(conn) == edges_before


def test_a_new_export_of_the_same_messages_changes_nothing(ingest_db, world, tmp_path):
    """The same channel exported again later (other exportedAt, so another file): no duplicate, no double count."""
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ingest_file(conn, write_doc(tmp_path / "a.json", json.loads(world.export_document(channel, exported_at=when))))
    before, edges_before = counts(conn), edges_snapshot(conn)
    result = ingest_file(conn, write_doc(tmp_path / "b.json", json.loads(world.export_document(channel, exported_at=when + timedelta(hours=1)))))
    assert result.status == "imported" and result.messages_new == 0
    assert counts(conn) == before
    assert edges_snapshot(conn) == edges_before  # nothing was counted twice
    assert_edges_equal_rebuild(conn)


def test_overlapping_exports_leave_no_duplicates(ingest_db, world, tmp_path):
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    ids = [int(m["id"]) for m in channel.messages]
    first, second = ids[len(ids) // 3], ids[len(ids) // 3 * 2]
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    docs = [world.export_document(channel, before_id=second, exported_at=when),                    # the beginning
            world.export_document(channel, after_id=first - 1, exported_at=when + timedelta(hours=1))]  # the end, overlapping
    for number, text in enumerate(docs):
        ingest_file(conn, write_doc(tmp_path / f"{number}.json", json.loads(text)))
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == len(ids)
    assert_edges_equal_rebuild(conn)


def test_imports_in_any_order_give_the_same_graph(ingest_db, world, files, tmp_path):
    conn = ingest_db
    for path in files:
        ingest_file(conn, path)
    in_order = edges_snapshot(conn)
    # another database, the same files in a random order, some of them twice in a different shape (partitions)
    shuffled = list(files)
    random.Random(3).shuffle(shuffled)
    conn.execute("TRUNCATE guilds CASCADE; TRUNCATE users CASCADE; TRUNCATE ingest_runs CASCADE")
    for path in shuffled:
        ingest_file(conn, path)
    again = edges_snapshot(conn)
    assert in_order.keys() == again.keys()
    for key in in_order:
        assert in_order[key][0] == pytest.approx(again[key][0], rel=1e-9) and in_order[key][1:] == again[key][1:]


# ---------------------------------------------------------------------------------------------
# Messages that change
# ---------------------------------------------------------------------------------------------


def _document_of(world, channel, when):
    return json.loads(world.export_document(channel, exported_at=when))


def test_an_edited_message_is_updated_and_its_children_replaced(ingest_db, world, tmp_path):
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ingest_file(conn, write_doc(tmp_path / "old.json", _document_of(world, channel, when)))

    document = _document_of(world, channel, when + timedelta(days=1))
    target = next(m for m in document["messages"] if m.get("reactions") and m.get("mentionedUserIds"))
    other_user = next(u for u in document["users"] if u["id"] not in target.get("mentionedUserIds", []) and u["id"] != target["authorId"])
    target["content"] = "contenu corrigé"
    target["timestampEdited"] = "2026-10-01T10:00:00.000Z"
    target["mentionedUserIds"] = [other_user["id"]]
    target["reactions"] = [{"emoji": "👍", "count": 2, "userIds": [other_user["id"], target["authorId"]]}]
    if not any(e["name"] == "👍" for e in document["emojis"]):
        document["emojis"].append({"name": "👍", "code": "thumbsup", "isAnimated": False, "imageUrl": "https://example.invalid/e.svg"})
    result = ingest_file(conn, write_doc(tmp_path / "new.json", document))
    assert result.messages_new == 0 and result.messages_updated == len(document["messages"])

    mid = int(target["id"])
    assert conn.execute("SELECT content, edited_at FROM messages WHERE id = %s", (mid,)).fetchone() == (
        "contenu corrigé", datetime(2026, 10, 1, 10, tzinfo=timezone.utc))
    assert conn.execute("SELECT user_id FROM mentions WHERE message_id = %s", (mid,)).fetchall() == [(int(other_user["id"]),)]
    assert conn.execute("SELECT emoji_key, count FROM reactions WHERE message_id = %s", (mid,)).fetchall() == [("👍", 2)]
    assert conn.execute("SELECT user_id FROM reaction_users WHERE message_id = %s ORDER BY user_id", (mid,)).fetchall() == sorted(
        [(int(other_user["id"]),), (int(target["authorId"]),)])
    assert_edges_equal_rebuild(conn)  # the old mention and reactions no longer count, the new ones do


def test_an_older_export_never_overwrites_a_newer_one(ingest_db, world, tmp_path):
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    newer = _document_of(world, channel, when + timedelta(days=1))
    target = newer["messages"][3]
    target["content"] = "version récente"
    older = _document_of(world, channel, when)
    older["users"][0]["nickname"] = "Ancien pseudo"
    older["users"][0]["roleIds"] = []
    ingest_file(conn, write_doc(tmp_path / "newer.json", newer))
    result = ingest_file(conn, write_doc(tmp_path / "older.json", older))  # arrives late
    assert result.messages_updated == 0
    assert conn.execute("SELECT content FROM messages WHERE id = %s", (int(target["id"]),)).fetchone() == ("version récente",)
    uid = int(older["users"][0]["id"])
    expected = newer["users"][0]
    assert conn.execute("SELECT nickname FROM members WHERE user_id = %s", (uid,)).fetchone() == (expected.get("nickname"),)
    assert_edges_equal_rebuild(conn)


def test_someone_who_left_keeps_the_nickname_and_roles_known(ingest_db, world, tmp_path):
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    full = _document_of(world, channel, when)
    person = next(u for u in full["users"] if u.get("roleIds") and u.get("nickname"))
    ingest_file(conn, write_doc(tmp_path / "full.json", full))
    # Later, the same person appears without any member data (they left the server)
    later = _document_of(world, channel, when + timedelta(days=1))
    for u in later["users"]:
        if u["id"] == person["id"]:
            for key in ("nickname", "color", "roleIds"):
                u.pop(key, None)
    ingest_file(conn, write_doc(tmp_path / "later.json", later))
    uid = int(person["id"])
    assert conn.execute("SELECT nickname FROM members WHERE user_id = %s", (uid,)).fetchone() == (person["nickname"],)
    assert {r[0] for r in conn.execute("SELECT role_id FROM member_roles WHERE user_id = %s", (uid,))} == {int(r) for r in person["roleIds"]}


def test_names_are_kept_in_the_history(ingest_db, world, tmp_path):
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    first = _document_of(world, channel, when)
    person = next(u for u in first["users"] if u.get("nickname"))
    ingest_file(conn, write_doc(tmp_path / "1.json", first))
    second = _document_of(world, channel, when + timedelta(days=1))
    for u in second["users"]:
        if u["id"] == person["id"]:
            u["nickname"] = "Nouveau pseudo"
    ingest_file(conn, write_doc(tmp_path / "2.json", second))
    uid = int(person["id"])
    assert conn.execute("SELECT nickname FROM members WHERE user_id = %s", (uid,)).fetchone() == ("Nouveau pseudo",)
    history = {r[0] for r in conn.execute("SELECT value FROM identity_history WHERE user_id = %s AND field = 'nickname'", (uid,))}
    assert history == {person["nickname"], "Nouveau pseudo"}  # the person is their ID, not their name


# ---------------------------------------------------------------------------------------------
# Deleted messages: a complete re-export of a window shows what is gone
# ---------------------------------------------------------------------------------------------


def test_the_nightly_catch_up_removes_deleted_messages(ingest_db, world, tmp_path):
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ingest_file(conn, write_doc(tmp_path / "all.json", _document_of(world, channel, when)))
    edges_before = sum(w[1] for w in edges_snapshot(conn).values())

    ids = [int(m["id"]) for m in channel.messages]
    window_start = ids[len(ids) * 2 // 3]
    document = json.loads(world.export_document(channel, after_id=window_start, exported_at=when + timedelta(days=1)))
    victims = [m for m in document["messages"][1:-1] if m.get("reference") or m.get("reactions")][:3]
    assert victims
    document["messages"] = [m for m in document["messages"] if m not in victims]
    document["messageCount"] = len(document["messages"])
    # An export that is not a complete window (manual, maybe filtered) never deletes anything
    ingest_file(conn, write_doc(tmp_path / "manual.json", document))
    assert conn.execute("SELECT count(*) FROM messages WHERE id = ANY(%s)", ([int(v["id"]) for v in victims],)).fetchone() == (3,)

    document["exportedAt"] = "2026-10-02T01:00:00.000Z"  # a different file for the catch-up run
    result = ingest_file(conn, write_doc(tmp_path / "catch-up.json", document), prune=True)
    assert result.messages_removed == 3
    assert conn.execute("SELECT count(*) FROM messages WHERE id = ANY(%s)", ([int(v["id"]) for v in victims],)).fetchone() == (0,)
    assert sum(w[1] for w in edges_snapshot(conn).values()) < edges_before
    assert_edges_equal_rebuild(conn)


# ---------------------------------------------------------------------------------------------
# Interruptions
# ---------------------------------------------------------------------------------------------


def test_a_failing_file_leaves_nothing_and_the_import_can_be_resumed(ingest_db, files, tmp_path):
    conn = ingest_db
    assert ingest_file(conn, files[0]).status == "imported"
    before = counts(conn)

    broken = json.loads(files[1].read_text(encoding="utf-8"))
    broken["messages"][-1]["authorId"] = "42"  # an author that is not in the file: a foreign key fails at the very end
    broken_path = write_doc(tmp_path / "broken.json", broken)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        ingest_file(conn, broken_path)
    assert counts(conn) == before  # nothing of it stayed
    assert conn.execute("SELECT count(*) FROM ingest_runs").fetchone() == (1,)

    # Restart: the files that were done are skipped, the others are imported
    statuses = [ingest_file(conn, path).status for path in files]
    assert statuses == ["duplicate"] + ["imported"] * (len(files) - 1)
    assert_edges_equal_rebuild(conn)


def test_a_file_that_is_not_an_export_is_refused_clearly(ingest_db, tmp_path):
    for name, content in (("junk.json", "{not json"), ("v1.json", '{"schemaVersion": 1}'), ("list.json", "[]"),
                          ("partial.json", '{"schemaVersion": 2, "users": []}')):
        path = tmp_path / name
        path.write_text(content)
        with pytest.raises(InvalidExport, match=name):
            ingest_file(ingest_db, path)
    assert ingest_db.execute("SELECT count(*) FROM ingest_runs").fetchone() == (0,)


# ---------------------------------------------------------------------------------------------
# What the rest of the system is told
# ---------------------------------------------------------------------------------------------


def test_an_ingestion_notifies_the_links_that_gained_an_exchange(ingest_db, ingest_url, world, tmp_path):
    conn = ingest_db
    channel = world.channels[0]
    alice, bob = world.people[0], world.people[1]
    first = world.post(channel, alice, "bonjour", datetime(2026, 10, 1, 8, tzinfo=timezone.utc))
    ingest_file(conn, write_doc(tmp_path / "1.json", json.loads(world.export_document(channel, exported_at=datetime(2026, 10, 1, 9, tzinfo=timezone.utc)))))
    listener = psycopg.connect(ingest_url, autocommit=True)
    listener.execute("LISTEN dindon")
    reply = world.post(channel, bob, "salut !", datetime(2026, 10, 1, 8, 5, tzinfo=timezone.utc), reply_to=first)
    document = json.loads(world.export_document(channel, after_id=int(first["id"]), exported_at=datetime(2026, 10, 1, 9, 5, tzinfo=timezone.utc)))
    result = ingest_file(conn, write_doc(tmp_path / "2.json", document))
    assert result.messages_new == 1
    events = [json.loads(n.payload) for n in listener.notifies(timeout=2, stop_after=2)]
    listener.close()
    kinds = {e["type"] for e in events}
    assert kinds == {"edge", "messages"}
    edge = next(e for e in events if e["type"] == "edge")
    assert (edge["from"], edge["to"], edge["kind"]) == (str(bob.id), str(alice.id), "reply")
    assert edge["weight"] > 0.9 and edge["n"] >= 1
    messages = next(e for e in events if e["type"] == "messages")
    assert messages["count"] == 1 and messages["last"] == reply["id"]


def test_the_analysis_of_a_changed_channel_is_queued_once(ingest_db, world, files):
    conn = ingest_db
    for path in files[:3]:
        ingest_file(conn, path)
    for path in files[:3]:  # the same again, and then new files: still one job per channel
        ingest_file(conn, path)
    jobs = conn.execute("SELECT kind, count(*) FROM jobs GROUP BY kind").fetchall()
    assert jobs == [("conversations", 3)]


def test_a_catch_up_that_seems_to_lack_most_of_a_window_deletes_nothing(ingest_db, world, tmp_path):
    """A broken export must not wipe what is known: more than 30% of a window missing is not believed."""
    conn = ingest_db
    channel = max(world.channels, key=lambda c: len(c.messages))
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    ingest_file(conn, write_doc(tmp_path / "all.json", _document_of(world, channel, when)))
    ids = [int(m["id"]) for m in channel.messages]
    document = json.loads(world.export_document(channel, after_id=ids[len(ids) // 4], exported_at=when + timedelta(days=1)))
    keep = document["messages"][::4] + [document["messages"][-1]]  # three quarters are missing
    missing = len(document["messages"]) - len(keep)
    assert missing > 60
    document["messages"], document["messageCount"] = keep, len(keep)
    before = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
    result = ingest_file(conn, write_doc(tmp_path / "broken.json", document), prune=True)
    assert result.messages_removed == 0 and result.prune_skipped >= 60
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == before


# ---------------------------------------------------------------------------------------------
# A document built in memory (the live bot) goes through the very same ingestion
# ---------------------------------------------------------------------------------------------


def _digest(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@pytest.fixture
def small_world():
    """Its own world: these tests add messages to it."""
    w = World(seed=11, people=12)
    w.generate(300, days=10)
    return w


def test_a_document_in_memory_and_the_same_file_share_one_ledger(ingest_db, small_world, tmp_path):
    conn = ingest_db
    channel = max(small_world.channels, key=lambda c: len(c.messages))
    text = small_world.export_document(channel, exported_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    first = ingest_document(conn, json.loads(text), "from memory", sha)
    assert first.status == "imported" and first.messages_new == len(channel.messages)
    after = counts(conn)
    # the file with the same bytes is the same document: skipped
    path = tmp_path / "same.json"
    path.write_text(text, encoding="utf-8")
    assert ingest_file(conn, path).status == "duplicate"
    assert counts(conn) == after
    assert_edges_equal_rebuild(conn)


def test_a_document_that_is_not_an_export_is_refused_whatever_its_origin(ingest_db):
    with pytest.raises(InvalidExport, match="schemaVersion"):
        ingest_document(ingest_db, {"schemaVersion": 3}, "memory", "0" * 64)
    with pytest.raises(InvalidExport, match="not a JSON v2 export"):
        ingest_document(ingest_db, ["not", "an", "object"], "memory", "1" * 64)  # type: ignore[arg-type]
    assert ingest_db.execute("SELECT count(*) FROM ingest_runs").fetchone()[0] == 0


def _announcement(world, channel, when):
    """What a source that only announces new messages sends: everything it knows, minus the reactions it knows nothing about,
    and with a content that differs from the database's (proving that an existing message is not rewritten)."""
    document = json.loads(world.export_document(channel, exported_at=when))
    for m in document["messages"]:
        m.pop("reactions", None)
        m["content"] = "REWRITTEN BY THE ANNOUNCEMENT"
    return document


def test_only_new_adds_the_new_message_and_leaves_every_other_one_untouched(ingest_db, small_world):
    conn = ingest_db
    world, channel = small_world, max(small_world.channels, key=lambda c: len(c.messages))
    alice, bob = world.people[0], world.people[1]
    t0 = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    first = world.post(channel, alice, "bonjour tout le monde", t0 - timedelta(hours=1))
    ingest_document(conn, json.loads(world.export_document(channel, exported_at=t0)), "export", "a" * 64)
    reactions_before = conn.execute("SELECT count(*) FROM reaction_users").fetchone()[0]
    assert reactions_before > 0,"the invented world should have reactions, or this test proves nothing"
    contents_before = dict(conn.execute("SELECT id, content FROM messages").fetchall())
    counts_before, edges_before = counts(conn), edges_snapshot(conn)

    world.post(channel, bob, "salut Alice", t0 + timedelta(minutes=5), reply_to=first)
    document = _announcement(world, channel, t0 + timedelta(minutes=5))
    result = ingest_document(conn, document, "live", _digest(document), only_new=True)

    assert (result.messages_new, result.messages_updated, result.messages_removed) == (1, 0, 0)
    assert dict(conn.execute("SELECT id, content FROM messages").fetchall()) == {
        **contents_before, int(document["messages"][-1]["id"]): "REWRITTEN BY THE ANNOUNCEMENT"}  # only the new one has the new text
    after = counts(conn)
    assert after["messages"] == counts_before["messages"] + 1
    assert {t: n for t, n in after.items() if t not in ("messages", "edges")} == {t: n for t, n in counts_before.items() if t not in ("messages", "edges")}
    assert conn.execute("SELECT count(*) FROM reaction_users").fetchone()[0] == reactions_before  # nobody's reaction was erased
    edges_after = edges_snapshot(conn)
    changed = {k for k in edges_before.keys() | edges_after.keys() if edges_before.get(k) != edges_after.get(k)}
    assert changed == {(world.guild_id, bob.id, alice.id, "reply")}  # no other link moved
    assert_edges_equal_rebuild(conn)


def test_the_same_new_message_announced_twice_counts_once(ingest_db, small_world):
    """A replayed event (after a reconnection, say) must not count a second time, nor erase anything."""
    conn = ingest_db
    world, channel = small_world, max(small_world.channels, key=lambda c: len(c.messages))
    alice, bob = world.people[0], world.people[1]
    t0 = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    first = world.post(channel, alice, "bonjour", t0 - timedelta(hours=1))
    ingest_document(conn, json.loads(world.export_document(channel, exported_at=t0)), "export", "b" * 64)
    world.post(channel, bob, "salut", t0 + timedelta(minutes=1), reply_to=first)

    def announce(when):
        document = _announcement(world, channel, when)
        return ingest_document(conn, document, "live", _digest(document), only_new=True), document

    one, document = announce(t0 + timedelta(minutes=1))
    assert one.messages_new == 1
    state = (counts(conn), edges_snapshot(conn))
    # delivered again: the same document is skipped, and the same message in a document of another moment changes nothing
    assert ingest_document(conn, document, "live", _digest(document), only_new=True).status == "duplicate"
    two, _ = announce(t0 + timedelta(minutes=2))
    assert two.status == "imported" and two.messages_new == 0 and two.messages_updated == 0
    assert counts(conn) == state[0] and edges_snapshot(conn) == state[1]
    assert_edges_equal_rebuild(conn)


def test_a_failed_attempt_leaves_the_document_intact_so_that_it_can_be_sent_again(ingest_db, small_world):
    """The bot retries the very same document after a database error: it must still have its messages."""
    conn = ingest_db
    channel = max(small_world.channels, key=lambda c: len(c.messages))
    document = json.loads(small_world.export_document(channel, exported_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    expected = len(document["messages"])
    broken = {**document, "messages": [*document["messages"], {"id": "9" * 15}]}  # one message lacks its fields: the file fails
    with pytest.raises(InvalidExport):
        ingest_document(conn, broken, "live", "c" * 64)
    assert len(broken["messages"]) == expected + 1 and conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    ok = ingest_document(conn, document, "live", "d" * 64)
    assert ok.messages_new == expected and len(document["messages"]) == expected
