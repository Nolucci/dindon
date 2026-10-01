"""The inbox: files are imported when ready, archived, and the broken ones put aside."""
import json
import os
import time

from dindon.ingest.inbox import GIVE_UP_SECONDS, scan_once
from make_demo_server import World


def make_export(tmp_path, name="a.json", messages=60):
    world = World(seed=11, people=15)
    world.generate(messages, days=10)
    channel = max(world.channels, key=lambda c: len(c.messages))
    path = tmp_path / "inbox" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(world.export_document(channel), encoding="utf-8")
    return path, len(channel.messages)


def age(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_a_ready_file_is_imported_and_archived(ingest_db, tmp_path):
    path, n = make_export(tmp_path)
    age(path, 10)
    original = path.read_text()
    outcomes = scan_once(ingest_db, tmp_path / "inbox", tmp_path / "archive")
    assert [o.result.messages_new for o in outcomes] == [n]
    assert not path.exists()
    archived = list((tmp_path / "archive").glob("*/*-a.json"))
    assert len(archived) == 1 and archived[0].read_text() == original  # kept as it was
    assert ingest_db.execute("SELECT count(*) FROM messages").fetchone() == (n,)


def test_a_file_that_is_still_being_written_waits(ingest_db, tmp_path):
    empty = tmp_path / "inbox" / "empty.json"          # the exporter leaves its file empty until the end
    empty.parent.mkdir()
    empty.write_text("")
    age(empty, 3600)
    fresh, _ = make_export(tmp_path, "fresh.json")      # modified just now
    half = tmp_path / "inbox" / "half.json"
    half.write_text(fresh.read_text()[:500])             # being copied: unreadable for now
    age(half, 10)
    assert scan_once(ingest_db, tmp_path / "inbox", tmp_path / "archive") == []
    assert empty.exists() and fresh.exists() and half.exists()
    assert ingest_db.execute("SELECT count(*) FROM ingest_runs").fetchone() == (0,)


def test_an_unreadable_file_is_put_aside_with_the_reason(ingest_db, tmp_path):
    bad = tmp_path / "inbox" / "bad.json"
    bad.parent.mkdir()
    bad.write_text("{not json at all")
    age(bad, GIVE_UP_SECONDS + 5)
    outcomes = scan_once(ingest_db, tmp_path / "inbox", tmp_path / "archive")
    assert len(outcomes) == 1 and "not valid JSON" in outcomes[0].error
    assert not bad.exists() and (tmp_path / "inbox" / "failed" / "bad.json").exists()
    assert "bad.json" in (tmp_path / "inbox" / "failed" / "bad.json.error.txt").read_text()


def test_the_same_file_dropped_twice_is_imported_once(ingest_db, tmp_path):
    path, n = make_export(tmp_path)
    age(path, 10)
    scan_once(ingest_db, tmp_path / "inbox", tmp_path / "archive")
    again = tmp_path / "inbox" / "a.json"
    next(iter((tmp_path / "archive").glob("*/*-a.json"))).replace(again)  # dropped back in
    age(again, 10)
    outcomes = scan_once(ingest_db, tmp_path / "inbox", tmp_path / "archive")
    assert outcomes[0].result.status == "duplicate"
    assert ingest_db.execute("SELECT count(*) FROM messages").fetchone() == (n,)
