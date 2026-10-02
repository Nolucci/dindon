"""Command line: dindon migrate | check | serve | bot | ingest FILE... | backfill [--channel … --from … --mentioning … --after … --before …] | catchup | rebuild-edges"""
import argparse
import json
import sys
from pathlib import Path

from dindon.config import load_settings
from dindon.db import connect
from dindon.health import database_report
from dindon.migrate import migrate


def _ingest(settings, paths: list[Path], prune: bool) -> int:
    from dindon.ingest.loader import InvalidExport, ingest_file

    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    imported = skipped = failed = 0
    totals = {"new": 0, "updated": 0, "seconds": 0.0}
    with connect(settings.database_url, wait=5) as conn:
        conn.autocommit = True
        for path in files:
            try:
                result = ingest_file(conn, path, prune=prune)
            except InvalidExport as error:
                failed += 1
                print(f"refused: {error}", file=sys.stderr)
                continue
            if result.status == "duplicate":
                skipped += 1
                continue
            imported += 1
            totals["new"] += result.messages_new
            totals["updated"] += result.messages_updated
            totals["seconds"] += result.seconds
            print(f"{result.messages_new:>7} new {result.messages_updated:>6} updated  {result.seconds:6.1f}s  {path.name[-60:]}", flush=True)
    print(f"{imported} imported, {skipped} already known, {failed} refused; {totals['new']} new messages, "
          f"{totals['updated']} updated, {totals['seconds']:.1f}s")
    return 1 if failed else 0


ACCOUNT_WARNING = (
    "WARNING: this token belongs to a personal account. Automating a personal account is against Discord's terms of\n"
    "service and can get it closed. A bot token is recommended (see README.md)."
)


def _collector(settings, guilds: list[int] | None):
    from dataclasses import replace

    from dindon.collector.watch import Collector

    guild_ids = tuple(guilds or settings.guild_ids)
    if not settings.discord_token or not guild_ids:
        sys.exit("Set DISCORD_TOKEN and DINDON_GUILD_IDS in .env (or pass --guild).")
    collector = Collector(replace(settings, guild_ids=guild_ids))
    if collector.api.resolve_kind() == "account":
        print(ACCOUNT_WARNING, file=sys.stderr)
    return collector


def selection_from(args):
    """What the command line asks to import (a part of a server, or all of it), or an end of the program that says what is wrong."""
    from dindon.collector.selection import ImportSelection, SelectionError

    try:
        return ImportSelection.parse(args.channels, args.authors, args.mentions, args.after, args.before)
    except SelectionError as error:
        sys.exit(str(error))


def _new_connection(settings):
    def new():
        conn = connect(settings.database_url, wait=5)
        conn.autocommit = True
        return conn

    return new


def main() -> None:
    parser = argparse.ArgumentParser(prog="dindon")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply the SQL files")
    sub.add_parser("check", help="print what the database is made of")
    sub.add_parser("serve", help="migrate, then run the application (ingestion, collection, API, interface)")
    sub.add_parser("bot", help="the live bot: receives the new messages of the followed servers from Discord's Gateway (needs a bot token)")
    sub.add_parser("rebuild-edges", help="rebuild the links between people from the messages (after changing the half-life)")
    backfill = sub.add_parser("backfill", help="first import of a whole server (can be stopped and started again)")
    backfill.add_argument("--guild", type=int, action="append", help="server ID (default: DINDON_GUILD_IDS)")
    backfill.add_argument("--parallel", type=int, default=2, help="channels exported at the same time (default 2)")
    backfill.add_argument("--channel", action="append", dest="channels", metavar="NAME_OR_ID",
                          help="only this channel, by name or id (can be repeated). It is imported completely")
    backfill.add_argument("--from", action="append", dest="authors", metavar="USER_ID",
                          help="only the messages written by this person, by Discord id (can be repeated). A partial import")
    backfill.add_argument("--mentioning", action="append", dest="mentions", metavar="USER_ID",
                          help="only the messages that mention this person, by Discord id (can be repeated). A partial import")
    backfill.add_argument("--after", metavar="YYYY-MM-DD", help="only from this day (included). A partial import")
    backfill.add_argument("--before", metavar="YYYY-MM-DD", help="only up to this day (included). A partial import")
    catchup = sub.add_parser("catchup", help="export the last days again now, to see what was edited or deleted")
    catchup.add_argument("--guild", type=int, action="append")
    ingest = sub.add_parser("ingest", help="import JSON v2 exports (files or folders)")
    ingest.add_argument("paths", nargs="+", type=Path)
    ingest.add_argument("--prune", action="store_true", help="the files are complete re-exports of a window: remove what is gone from it")
    args = parser.parse_args()
    settings = load_settings()

    if args.command in ("migrate", "serve"):
        with connect(settings.database_url, wait=60) as conn:
            applied = migrate(conn, settings.db_dir)
        print(f"migrations applied: {', '.join(applied) if applied else 'none (up to date)'}")

    if args.command == "check":
        with connect(settings.database_url) as conn:
            print(json.dumps(database_report(conn), indent=2))

    if args.command == "rebuild-edges":
        with connect(settings.database_url) as conn:
            print(f"{conn.execute('SELECT rebuild_edges()').fetchone()[0]} links rebuilt")

    if args.command == "bot":
        from dindon.bot.runner import main as run_bot

        sys.exit(run_bot(settings))

    if args.command == "ingest":
        sys.exit(_ingest(settings, args.paths, args.prune))

    if args.command == "backfill":
        selection = selection_from(args)
        collector = _collector(settings, args.guild)
        if selection.channels and len(collector.settings.guild_ids) > 1:
            sys.exit("Plusieurs serveurs sont suivis : précisez lequel avec --guild pour choisir des salons.")
        with connect(settings.database_url, wait=60) as conn:
            migrate(conn, settings.db_dir)
        if selection.partial:
            print("Narrowed import: it brings only a part of the channels, so it does not count as a first import, "
                  "and a complete `dindon backfill` later still brings everything.")
        from dindon.collector.selection import SelectionError

        for guild_id in collector.settings.guild_ids:
            print(f"server {guild_id}: reactions cost one request each, so a big server takes a while")
            try:
                print(collector.backfill(_new_connection(settings), guild_id, parallel=args.parallel, selection=selection))
            except SelectionError as error:
                sys.exit(str(error))

    if args.command == "catchup":
        collector = _collector(settings, args.guild)
        with _new_connection(settings)() as conn:
            print(f"{collector.catchup(conn)} channels exported again")

    if args.command == "serve":
        import uvicorn

        from dindon.api.main import create_app

        # Open pages (live events) must not keep the application from stopping: `docker stop` waits 10 seconds
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
