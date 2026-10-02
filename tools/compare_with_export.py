"""Compares what the bot wrote in the database with a real export of the same messages.

The bot builds its documents itself, and the exporter is the reference: the same message must come out the same (type, text,
author, time, who it replied to, who it mentions). This is the check, on a real server, that the bot writes what the exporter
would have written. Messages that were edited after the bot saw them are counted apart: the bot does not apply edits yet.

    docker compose exec app sh -c '/opt/exporter/DiscordChatExporter.Cli export -c CHANNEL_ID -f Json -o /tmp/parity/'
    docker compose cp app:/tmp/parity ./parity
    .venv/bin/python tools/compare_with_export.py parity/*.json            # which fields differ, without showing any text
    .venv/bin/python tools/compare_with_export.py --show parity/*.json     # and the two values (cut at 80 characters)

The export is only read. Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg

FIELDS = ("type", "content", "author", "sent_at", "pinned", "reply_to", "reply_author", "reply_content", "mentions")


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _expected(message: dict) -> dict:
    ref = message.get("reference") or {}
    return {"type": message["type"], "content": message["content"], "author": int(message["authorId"]), "sent_at": _when(message["timestamp"]),
            "pinned": bool(message.get("isPinned", False)),
            "reply_to": int(ref["messageId"]) if "messageId" in ref else None,
            "reply_author": int(ref["authorId"]) if "authorId" in ref else None, "reply_content": ref.get("content"),
            "mentions": {int(u) for u in message.get("mentionedUserIds", [])}}


def compare(conn: psycopg.Connection, document: dict) -> dict:
    """{'compared', 'same', 'edited_since', 'not_in_database', 'differences': [(message id, field, in the database, in the export)]}"""
    result = {"compared": 0, "same": 0, "edited_since": 0, "not_in_database": 0, "differences": []}
    for message in document["messages"]:
        mid = int(message["id"])
        row = conn.execute(
            """SELECT type, content, author_id, sent_at, is_pinned, reference_message_id, reference_author_id, reference_content
               FROM messages WHERE id = %s""", (mid,)).fetchone()
        if row is None:
            result["not_in_database"] += 1
            continue
        if "timestampEdited" in message:
            result["edited_since"] += 1
            continue
        mentions = {r[0] for r in conn.execute("SELECT user_id FROM mentions WHERE message_id = %s", (mid,))}
        have = dict(zip(FIELDS, (*row, mentions)))
        want = _expected(message)
        wrong = [(mid, field, have[field], want[field]) for field in FIELDS if have[field] != want[field]]
        result["compared"] += 1
        if wrong:
            result["differences"].extend(wrong)
        else:
            result["same"] += 1
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("exports", nargs="+", type=Path)
    parser.add_argument("--show", action="store_true", help="also print the two values of each difference (cut at 80 characters)")
    args = parser.parse_args(argv)
    from dindon.config import load_settings

    totals = {"compared": 0, "same": 0, "edited_since": 0, "not_in_database": 0}
    differences: list = []
    with psycopg.connect(load_settings().database_url) as conn:
        for path in args.exports:
            result = compare(conn, json.loads(path.read_text(encoding="utf-8")))
            for key in totals:
                totals[key] += result[key]
            differences.extend(result["differences"])
    print(f"compared {totals['compared']} messages: {totals['same']} identical, {len({d[0] for d in differences})} different; "
          f"{totals['edited_since']} edited since (not applied yet), {totals['not_in_database']} not in the database")
    for mid, field, have, want in differences:
        print(f"  message {mid}: {field}" + (f"\n      database: {str(have)[:80]!r}\n      export:   {str(want)[:80]!r}" if args.show else ""))
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
