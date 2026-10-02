"""Importing a part of a server: some channels, some people, a period.

Level of proof: SIMULATED (a fake Discord and a fake exporter, a real database). The expression of the filter was also checked
against the real exporter's parser (a valid one is accepted, a wrong one is refused), without any connection.
"""
import json
import os
import sys
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from dindon.collector.discord_api import Watched
from dindon.collector.exporter import Exporter, ExporterCancelled, ExporterError
from dindon.collector.selection import ImportSelection, SelectionError, resolve_channels
from dindon.collector.snowflake import created_at
from dindon.collector.watch import Collector
from make_demo_server import parse_iso
from test_collector import collector, connection, exports_asked, fake, message_count, world  # noqa: F401 (fixtures)

# ---------------------------------------------------------------------------------------------
# Reading a selection
# ---------------------------------------------------------------------------------------------


def test_people_are_read_from_whatever_is_pasted_and_checked():
    selection = ImportSelection.parse(authors=["111111111111111111, 222222222222222222\n111111111111111111"],
                                      mentions=["<@333333333333333333>", " <@!444444444444444444> "])
    assert selection.authors == (111111111111111111, 222222222222222222)       # no duplicate
    assert selection.mentions == (333333333333333333, 444444444444444444)      # a pasted mention is understood
    for wrong in ("pseudo", "12ab", "1.5", "-3"):
        with pytest.raises(SelectionError, match="identifiant Discord"):
            ImportSelection.parse(authors=[wrong])
    with pytest.raises(SelectionError, match="50 au plus"):
        ImportSelection.parse(authors=[str(n) for n in range(1, 60)])


def test_dates_are_checked_and_the_period_is_the_right_way_round():
    selection = ImportSelection.parse(after="2025-03-01", before="2025-03-31")
    assert (selection.after, selection.before) == (date(2025, 3, 1), date(2025, 3, 31))
    for wrong in ("01/03/2025", "demain", "2025-13-01"):
        with pytest.raises(SelectionError, match="n'est pas une date"):
            ImportSelection.parse(after=wrong)
    with pytest.raises(SelectionError, match="à l'envers"):
        ImportSelection.parse(after="2025-04-01", before="2025-03-01")
    assert ImportSelection.parse(after="", before=None).after is None


def test_the_last_day_is_included_in_the_ids_given_to_the_exporter():
    selection = ImportSelection.parse(after="2025-03-01", before="2025-03-31")
    assert created_at(selection.after_id()) == datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert created_at(selection.before_id()) == datetime(2025, 4, 1, tzinfo=timezone.utc)   # up to the start of the next day
    assert ImportSelection().after_id() is None and ImportSelection().before_id() is None


def test_the_exporters_filter_groups_people_with_or_and_the_groups_with_and():
    assert ImportSelection().message_filter() is None
    assert ImportSelection.parse(authors=["1", "2"]).message_filter() == "(from:1 | from:2)"
    assert ImportSelection.parse(mentions=["3"]).message_filter() == "(mentions:3)"
    assert ImportSelection.parse(authors=["1", "2"], mentions=["3", "4"]).message_filter() == "(from:1 | from:2) (mentions:3 | mentions:4)"


def test_what_makes_an_import_partial():
    assert not ImportSelection().partial and not ImportSelection.parse(channels=["général"]).partial   # whole channels are complete
    assert ImportSelection.parse(authors=["1"]).partial and ImportSelection.parse(mentions=["1"]).partial
    assert ImportSelection.parse(after="2025-01-01").partial and ImportSelection.parse(before="2025-01-01").partial


def test_channels_are_read_by_name_or_id_ignoring_case_accents_and_the_hash():
    assert ImportSelection.parse(channels=["Général, #maths", "sql\n123"]).channels == ("Général", "#maths", "sql", "123")
    channels = [Watched(10, "général", "text", None, 1), Watched(20, "maths", "text", None, 1), Watched(30, "Maths", "text", None, 1),
                Watched(40, "sql", "text", None, 1), Watched(50, "un fil", "thread", 10, 1)]
    assert [c.id for c in resolve_channels(("GENERAL", "#sql", "50"), channels)] == [10, 40, 50]
    with pytest.raises(SelectionError, match="plusieurs salons portent ce nom.*20, 30"):
        resolve_channels(("maths",), channels)
    with pytest.raises(SelectionError, match="inconnu. Salons visibles : .*général.*sql"):
        resolve_channels(("sqll",), channels)
    with pytest.raises(SelectionError, match="Salon 99 : inconnu"):
        resolve_channels(("99",), channels)


# ---------------------------------------------------------------------------------------------
# The exporter: arguments, and stopping it
# ---------------------------------------------------------------------------------------------

RECORDER = """
import json, os, sys, time
from pathlib import Path
argv = sys.argv[1:]
Path(os.environ["REC_DIR"], "argv.json").write_text(json.dumps(argv))
Path(os.environ["REC_DIR"], "pid").write_text(str(os.getpid()))
out = Path(argv[argv.index("-o") + 1]); out.mkdir(parents=True, exist_ok=True)
if os.environ.get("REC_SLEEP"):
    time.sleep(float(os.environ["REC_SLEEP"]))
(out / "channel.json").write_text("{}")
"""


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    script = tmp_path / "recorder.py"
    script.write_text(RECORDER)
    monkeypatch.setenv("REC_DIR", str(tmp_path))
    return Exporter(f"{sys.executable} {script}", "secret-token-123", timeout=30), tmp_path


def test_the_exporter_is_given_the_window_and_the_filter_and_never_the_token(recorder):
    exporter, folder = recorder
    exporter.export(5, folder / "out", after=111, before=222, message_filter="(from:1 | from:2) (mentions:3)")
    argv = json.loads((folder / "argv.json").read_text())
    assert argv[argv.index("--after") + 1] == "111" and argv[argv.index("--before") + 1] == "222"
    assert argv[argv.index("--filter") + 1] == "(from:1 | from:2) (mentions:3)"
    assert "secret-token-123" not in " ".join(argv)
    exporter.export(5, folder / "out2")
    plain = json.loads((folder / "argv.json").read_text())
    assert "--before" not in plain and "--filter" not in plain and "--after" not in plain


def test_stopping_ends_the_exporter_quickly_and_leaves_no_process(recorder, monkeypatch):
    exporter, folder = recorder
    monkeypatch.setenv("REC_SLEEP", "60")
    cancel = threading.Event()
    threading.Timer(0.7, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(ExporterCancelled):
        exporter.export(5, folder / "out", cancel=cancel)
    assert time.monotonic() - started < 6
    pid = int((folder / "pid").read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)                                                            # it is really gone


def test_an_exporter_that_takes_too_long_is_ended_with_the_same_message_as_before(recorder, monkeypatch):
    exporter, folder = recorder
    exporter.timeout = 1
    monkeypatch.setenv("REC_SLEEP", "60")
    with pytest.raises(ExporterError, match="took more than 1s"):
        exporter.export(5, folder / "out")


def test_a_missing_exporter_is_reported_as_before(tmp_path):
    with pytest.raises(ExporterError, match="was not found"):
        Exporter(str(tmp_path / "nothing-here"), "t").export(5, tmp_path / "out")


# ---------------------------------------------------------------------------------------------
# Importing a part of a server, against the fake Discord
# ---------------------------------------------------------------------------------------------


def ids_in(conn) -> set[int]:
    return {r[0] for r in conn.execute("SELECT id FROM messages")}


def largest(world):
    return max(world.channels, key=lambda c: len(c.messages))


def run(collector, world, ingest_url, **selection):
    return collector.backfill(lambda: connection(ingest_url), world.guild_id, parallel=2, progress=lambda _: None,
                              selection=ImportSelection.parse(**selection))


def test_only_the_chosen_channels_are_imported_completely_and_this_is_not_partial(collector, fake, world, ingest_url):
    first, second = world.channels[0], world.channels[1]
    totals = run(collector, world, ingest_url, channels=[first.name, str(second.id)])
    with connection(ingest_url) as conn:
        assert message_count(conn) == len(first.messages) + len(second.messages) and totals["failed"] == 0
        assert {r[0] for r in conn.execute("SELECT DISTINCT channel_id FROM messages")} == {first.id, second.id}
        assert not any(r[0] for r in conn.execute("SELECT is_partial FROM ingest_runs"))               # whole channels: complete
    assert {c for r in exports_asked(fake) for c in (first.id, second.id) if f"channel={c}" in r} == {first.id, second.id}
    assert not any(f"channel={c.id}" in r for r in exports_asked(fake) for c in world.channels[2:])    # the others are not even asked
    asked = len(exports_asked(fake))
    run(collector, world, ingest_url, channels=[first.name])
    assert len(exports_asked(fake)) == asked                                                          # up to date: nothing to do, as always


def test_only_the_messages_of_the_chosen_people_are_imported_and_it_is_recorded_as_partial(collector, fake, world, ingest_url):
    channel = largest(world)
    author = Counter(m["authorId"] for m in channel.messages).most_common(1)[0][0]
    expected = {int(m["id"]) for m in channel.messages if m["authorId"] == author}
    assert 0 < len(expected) < len(channel.messages)
    run(collector, world, ingest_url, channels=[channel.name], authors=[author])
    with connection(ingest_url) as conn:
        assert ids_in(conn) == expected
        assert {r[0] for r in conn.execute("SELECT DISTINCT author_id FROM messages")} == {int(author)}
        assert all(r[0] for r in conn.execute("SELECT is_partial FROM ingest_runs")) and conn.execute("SELECT count(*) FROM ingest_runs").fetchone()[0] >= 1
    assert "filter=" in " ".join(exports_asked(fake))


def test_the_mentioned_people_and_the_two_kinds_of_filter_together(collector, fake, world, ingest_url):
    channel = largest(world)
    mentioning = [m for m in channel.messages if m.get("mentionedUserIds")]
    target = Counter(u for m in mentioning for u in m["mentionedUserIds"]).most_common(1)[0][0]
    assert any(m["authorId"] != target for m in mentioning)
    only_mentions = {int(m["id"]) for m in channel.messages if target in m.get("mentionedUserIds", [])}
    run(collector, world, ingest_url, channels=[channel.name], mentions=[target])
    with connection(ingest_url) as conn:
        assert ids_in(conn) == only_mentions
        conn.execute("TRUNCATE guilds CASCADE; TRUNCATE users CASCADE; TRUNCATE ingest_runs CASCADE")
    # both: written by A and mentioning M
    pair = next((m["authorId"], t) for m in mentioning for t in m["mentionedUserIds"])
    both = {int(m["id"]) for m in channel.messages if m["authorId"] == pair[0] and pair[1] in m.get("mentionedUserIds", [])}
    run(collector, world, ingest_url, channels=[channel.name], authors=[pair[0]], mentions=[pair[1]])
    with connection(ingest_url) as conn:
        assert ids_in(conn) == both and both


def test_a_period_includes_its_first_and_last_day(collector, fake, world, ingest_url):
    channel = largest(world)
    days = sorted({parse_iso(m["timestamp"]).date() for m in channel.messages})
    start, end = days[len(days) // 3], days[len(days) // 3 * 2]
    expected = {int(m["id"]) for m in channel.messages if start <= parse_iso(m["timestamp"]).date() <= end}
    assert expected and len(expected) < len(channel.messages)
    run(collector, world, ingest_url, channels=[channel.name], after=start.isoformat(), before=end.isoformat())
    with connection(ingest_url) as conn:
        assert ids_in(conn) == expected
        days_in = {r[0] for r in conn.execute("SELECT (sent_at AT TIME ZONE 'UTC')::date FROM messages")}
        assert start in days_in and end in days_in                                                   # both ends are in


def test_a_narrowed_import_is_never_taken_for_a_first_import_and_a_complete_one_still_brings_everything(collector, fake, world, ingest_db, ingest_url):
    channel = largest(world)
    author = Counter(m["authorId"] for m in channel.messages).most_common(1)[0][0]
    run(collector, world, ingest_url, channels=[channel.name], authors=[author])
    fake.requests.clear()
    assert collector.poll(ingest_db) == 0 and exports_asked(fake) == []                               # the watcher still waits for a first import
    assert collector.status()["needs_backfill"] == [str(world.guild_id)]
    assert collector._exported_up_to == {}                                                            # and does not think the channel is up to date
    run(collector, world, ingest_url)                                                                 # the complete import: everything, history included
    assert message_count(ingest_db) == sum(len(c.messages) for c in world.channels)


def test_stopping_before_the_start_exports_nothing(collector, fake, world, ingest_url):
    cancel = threading.Event()
    cancel.set()
    events = []
    totals = collector.backfill(lambda: connection(ingest_url), world.guild_id, progress=lambda _: None, selection=ImportSelection(),
                                cancel=cancel, report=events.append)
    assert totals["channels"] == 0 and totals["cancelled"] == events[0]["channels"] > 0
    assert exports_asked(fake) == [] and events[0]["event"] == "planned"


def test_what_is_reported_while_it_runs(collector, fake, world, ingest_url):
    events = []
    collector.backfill(lambda: connection(ingest_url), world.guild_id, progress=lambda _: None,
                       selection=ImportSelection.parse(channels=[world.channels[0].name]), report=events.append)
    assert events[0] == {"event": "planned", "channels": 1, "of": len(world.channels)}
    assert [e["event"] for e in events[1:]] == ["channel"] and events[1]["messages"] == len(world.channels[0].messages) and events[1]["ok"]


def test_a_wrong_channel_name_stops_everything_before_any_export(collector, fake, world, ingest_url):
    with pytest.raises(SelectionError, match="Salons visibles"):
        run(collector, world, ingest_url, channels=["nulle-part"])
    assert exports_asked(fake) == []


def test_the_command_line_asks_for_the_same_selection():
    import argparse

    from dindon.__main__ import selection_from

    args = argparse.Namespace(channels=["général", "sql"], authors=["111111111111111111"], mentions=None, after="2025-01-01", before=None)
    selection = selection_from(args)
    assert selection.channels == ("général", "sql") and selection.authors == (111111111111111111,) and selection.partial
    assert selection.message_filter() == "(from:111111111111111111)" and selection.after == date(2025, 1, 1)
    nothing = argparse.Namespace(channels=None, authors=None, mentions=None, after=None, before=None)
    assert selection_from(nothing) == ImportSelection() and not selection_from(nothing).partial
    with pytest.raises(SystemExit, match="n'est pas un identifiant"):
        selection_from(argparse.Namespace(channels=None, authors=["moi"], mentions=None, after=None, before=None))
