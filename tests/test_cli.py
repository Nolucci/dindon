"""The command line (`dindon …`) and the loops that run beside the API. Level of proof: real PostgreSQL, invented data."""
import asyncio
import dataclasses
import json
import sys
from datetime import UTC, datetime

import pytest

from dindon.__main__ import main
from dindon.api.background import inbox_loop, retention_loop
from synthetic import settings_for
from test_analysis import Talk, ingest
from test_extraction import ALICE_ID, GUILD_ID
from gateway_fixtures import ALICE


@pytest.fixture
def cli(ingest_url, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATABASE_URL", ingest_url)
    monkeypatch.setenv("DINDON_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("DINDON_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setenv("DISCORD_TOKEN", "")

    def run(*args: str) -> tuple[int, str]:
        monkeypatch.setattr(sys, "argv", ["dindon", *args])
        with pytest.raises(SystemExit) as stop:
            main()
        return (stop.value.code or 0), capsys.readouterr().out
    return run


def test_check_and_migrate_say_what_the_database_is(cli):
    code, out = cli("check")
    assert code == 0 and json.loads(out)["axes_active"] == 21
    code, out = cli("migrate")
    assert code == 0 and "up to date" in out


def test_the_register_of_people_is_managed_from_the_command_line(cli, ingest_db):
    ingest(ingest_db, [Talk().say("un message", ALICE)])
    assert cli("privacy", "stop", str(ALICE_ID), "--reason", "demande")[0] == 0
    code, out = cli("privacy", "list")
    assert code == 0 and str(ALICE_ID) in out
    assert cli("privacy", "stop")[0] == 2                                                  # the id of the person is needed
    code, out = cli("privacy", "export", str(ALICE_ID))
    assert code == 0 and json.loads(out)["discord_id"] == str(ALICE_ID)
    assert json.loads(cli("privacy", "release", str(ALICE_ID))[1]) == {"released": True}
    assert cli("privacy", "erase", str(ALICE_ID))[0] == 0
    assert ingest_db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert cli("privacy", "purge")[0] == 0


def test_the_bot_check_and_the_preflight_exit_codes(cli, monkeypatch):
    monkeypatch.setenv("DINDON_DEBATE_CHECKS", "off")                                      # (not the owner's real .env: with the checks on, the preflight asks the local AI, which a test never reaches)
    assert cli("bot-health")[0] == 1                                                       # no sign of life
    code, out = cli("preflight", "--json")
    assert code == 1 and any(c["level"] == "fail" for c in json.loads(out))                # no token: it blocks


def test_ingesting_a_folder_and_a_refused_file(cli, tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    (folder / "bad.json").write_text("{}")
    code, out = cli("ingest", str(folder))
    assert code == 1                                        # a file that is not an export is refused


def test_the_inbox_loop_imports_what_is_dropped_and_the_retention_loop_purges(ingest_url, ingest_db, tmp_path):
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, "pw"), retention_days=1)
    ingest(ingest_db, [Talk(start=datetime(2020, 1, 1, tzinfo=UTC)).say("très ancien", ALICE)])

    async def run():
        tasks = [asyncio.create_task(inbox_loop(settings)), asyncio.create_task(retention_loop(settings))]
        await asyncio.sleep(2.5)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(run())
    assert settings.inbox_dir.is_dir()                                                      # the loop made the folder
    assert ingest_db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0           # older than a day: purged


def test_digest_gives_themes_positions_and_contradictions_in_a_few_lines(cli, ingest_db):
    ingest(ingest_db, [Talk().say("un message", ALICE)])
    code, out = cli("digest", "--guild", str(GUILD_ID), "--json")
    digest = json.loads(out)
    assert code == 0 and digest["guild"] == GUILD_ID
    assert set(digest) == {"guild", "themes", "positions", "contradictions"}
    assert set(digest["contradictions"]) == {"against_own_roles", "opposed_roles", "changed_mind"}
    code, out = cli("digest", "--guild", str(GUILD_ID))
    assert code == 0 and "## Thèmes" in out and "## Positions" in out and "## Contradictions" in out
