"""The latency measuring tool: it must read the delay right (the arithmetic is the whole point), without printing names or texts."""
import socket
import threading
import time
from datetime import datetime, timedelta, timezone, UTC

import pytest
import uvicorn

from dindon.api.main import create_app
from dindon.bot.adapter import Directory, build_document, digest
from dindon.ingest.loader import GATEWAY_SOURCE, ingest_document
from gateway_fixtures import ALICE, BOB, GENERAL, GUILD, guild_create, message_create
from measure_live_latency import DISCORD_EPOCH_MS, listen, login, snowflake_time
from synthetic import settings_for

PASSWORD = "correct horse"


def snowflake_at(when: datetime) -> int:
    return (int(when.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22


def test_the_time_carried_by_an_id_is_read_back():
    when = datetime(2026, 10, 2, 21, 43, 16, 229000, tzinfo=UTC)
    assert snowflake_time(snowflake_at(when)) == pytest.approx(when.timestamp(), abs=0.001)


@pytest.fixture
def port(ingest_url, tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        number = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings_for(ingest_url, tmp_path, PASSWORD), background=False),
                                           host="127.0.0.1", port=number, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield number
    server.should_exit = True
    thread.join(timeout=10)


def test_a_message_written_two_seconds_ago_is_measured_at_two_seconds_and_nothing_else_is_printed(port, ingest_db, capsys):
    """An exchange gives an 'edge' event and a 'messages' event: both are dated from the message, as Discord dated it."""
    base = f"http://127.0.0.1:{port}"
    cookie = login(base, PASSWORD)
    written = datetime.now(UTC) - timedelta(seconds=2)
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    alice_says = message_create(snowflake_at(written - timedelta(seconds=5)), "secret one", ALICE,
                                timestamp=(written - timedelta(seconds=5)).isoformat())
    bob_replies = message_create(snowflake_at(written), "secret two", BOB, reply_to=alice_says, timestamp=written.isoformat())
    document = build_document(directory, GUILD, GENERAL, [alice_says, bob_replies])
    found: list = []
    thread = threading.Thread(target=lambda: found.extend(listen(base, cookie, 2, 20, on_event=print)), daemon=True)
    thread.start()
    time.sleep(1)  # the listener is connected before the exchange arrives
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    thread.join(timeout=20)
    assert sorted(kind for kind, _, _ in found) == ["edge", "messages"]
    for kind, _, delay in found:
        assert 1.5 < delay < 4.5, (kind, delay)  # about two seconds plus the time to get through, and not 0 or 7
    printed = capsys.readouterr().out
    assert "secret" not in printed and ALICE["id"] not in printed and BOB["id"] not in printed
