"""The comparison with a real export (tools/compare_with_export.py): it must see a difference when there is one."""
import copy

import pytest

from compare_with_export import compare
from dindon.bot.adapter import Directory, build_document, digest
from dindon.ingest.loader import ingest_document
from gateway_fixtures import ALICE, BOB, GENERAL, GUILD, guild_create, member, message_create


@pytest.fixture
def written(ingest_db):
    """Two messages written by the bot, and the document that a real export of them would be (here: the same)."""
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    first = message_create(100, "Bonjour <@1000000000000000002>", ALICE, mentions=((BOB, member("Bobo")),), member_data=member("Ali"))
    second = message_create(101, "Oui", BOB, reply_to=first, member_data=member("Bobo"))
    document = build_document(directory, GUILD, GENERAL, [first, second])
    ingest_document(ingest_db, document, "gateway", digest(document), only_new=True)
    return ingest_db, document


def test_identical_messages_give_no_difference(written):
    conn, export = written
    assert compare(conn, export) == {"compared": 2, "same": 2, "edited_since": 0, "rewritten_by_export": 0, "not_in_database": 0, "differences": []}


def test_a_difference_in_the_text_a_mention_or_the_reply_is_named(written):
    conn, export = written
    export = copy.deepcopy(export)
    export["messages"][0]["content"] = "Bonjour @bob"
    export["messages"][0]["mentionedUserIds"] = []
    export["messages"][1]["reference"]["content"] = "autre"
    result = compare(conn, export)
    assert result["same"] == 0 and result["compared"] == 2
    assert {(mid, field) for mid, field, _, _ in result["differences"]} == {(100, "content"), (100, "mentions"), (101, "reply_content")}


def test_an_edited_message_and_an_unknown_one_are_counted_apart(written):
    conn, export = written
    export = copy.deepcopy(export)
    export["messages"][0]["content"] = "modifié depuis"
    export["messages"][0]["timestampEdited"] = "2026-10-02T20:00:00.000Z"
    export["messages"].append({**export["messages"][1], "id": "999"})
    result = compare(conn, export)
    assert (result["compared"], result["same"], result["edited_since"], result["not_in_database"], result["differences"]) == (1, 1, 1, 1, [])


def test_a_message_that_an_export_has_rewritten_since_proves_nothing_about_the_bot_and_is_counted_apart(written):
    """After a catch-up (or any export), the row is the exporter's: comparing it with an export would say 'identical' whatever the bot
    had written. Only what the bot wrote and nobody has rewritten is compared."""
    conn, document = written
    rewritten = copy.deepcopy(document)
    rewritten["exportedAt"] = "2026-10-04T03:00:00.000Z"
    rewritten["messages"] = [m for m in rewritten["messages"] if m["id"] == "100"]
    rewritten["messageCount"] = 1
    ingest_document(conn, rewritten, "export.json", "f" * 64)                    # a real export of message 100, later
    result = compare(conn, document)
    assert result["rewritten_by_export"] == 1 and result["compared"] == 1 and result["same"] == 1
