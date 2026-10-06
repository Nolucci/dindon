"""Command line: dindon migrate | check | serve | bot | ingest FILE... | backfill [--channel … --from … --mentioning … --after … --before …] | catchup | rebuild-edges | analyze | privacy | export CHANNEL"""
import argparse
import json
import sys
from pathlib import Path

from dindon.config import load_settings
from dindon.db import connect
from dindon.health import bot_is_alive, database_report
from dindon.migrate import migrate


def _cmd_ingest(settings, args) -> int:
    return _ingest(settings, args.paths, args.prune)


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

    guild_ids = tuple(guilds or settings.followed())
    if not settings.discord_token or not guild_ids:
        sys.exit("Set DISCORD_TOKEN and DINDON_GUILD_IDS in .env (or pass --guild).")
    collector = Collector(replace(settings, guild_ids=guild_ids))
    if collector.api.resolve_kind() == "account":
        print(ACCOUNT_WARNING, file=sys.stderr)
    return collector


def _analyze(settings, args) -> int:
    from dindon.analysis.job import ALL_STAGES, STAGES, AnalysisBusy, AnalysisJobs, NotReady

    with connect(settings.database_url, wait=60) as conn:
        migrate(conn, settings.db_dir)
        guild = args.guild or (settings.guild_ids[0] if settings.guild_ids else None)
        if guild is None:
            row = conn.execute("""SELECT g.id FROM guilds g ORDER BY (SELECT max(r.imported_at) FROM ingest_runs r WHERE r.guild_id = g.id)
                                  DESC NULLS LAST LIMIT 1""").fetchone()
            guild = row[0] if row else None
        known = guild is not None and conn.execute("SELECT 1 FROM guilds WHERE id = %s", (guild,)).fetchone() is not None
    if guild is None:
        print("No server yet: import something first (see README.md).", file=sys.stderr)
        return 1
    if not known:
        print(f"Server {guild} is not in the database: nothing has been imported for it (see --guild).", file=sys.stderr)
        return 1
    jobs = AnalysisJobs(settings, echo=print)
    stages = tuple(s for s in ALL_STAGES if (s in args.stages if args.stages else s in STAGES))   # the claims only when asked for
    try:
        jobs.start(guild, stages, topics=args.topics, rebuild=args.rebuild, limit=args.limit)
    except (NotReady, AnalysisBusy) as problem:
        print(f"Cannot start: {problem}", file=sys.stderr)
        return 1
    try:
        jobs.wait()
    except KeyboardInterrupt:
        jobs.cancel()
        jobs.wait()
    state = jobs.status()
    if state["error"]:
        print(f"Failed: {state['error']}", file=sys.stderr)
        return 1
    print("Cancelled." if state["state"] == "cancelled" else "Done. The proposed topics are in the interface, page Thèmes.")
    return 0


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


def _export(settings, args) -> int:
    from dindon.export import Exporter, ExporterError

    if not settings.discord_token:
        print("DISCORD_TOKEN is empty: put the token of the bot in .env", file=sys.stderr)
        return 2
    exporter = Exporter(settings.discord_token, settings.discord_api_url, workers=settings.export_workers,
                        reactions=args.reactions or settings.export_reactions, reactions_days=settings.export_reactions_days)
    try:
        files = exporter.export(args.channel, args.out, after=args.after, before=args.before, threads=args.threads or settings.exporter_threads,
                                partition=args.partition, message_filter=args.filter)
    except ExporterError as error:
        print(f"Export impossible : {error}", file=sys.stderr)
        return 1
    stats = exporter.stats
    print(f"{stats['messages']} messages in {len(files)} file(s) in {args.out} ({exporter.client.requests} requests, {stats['member_requests']} profiles, "
          f"{stats['reaction_requests']} reaction lists)" if files else "Nothing to export (no message in this window).")
    for f in files:
        print(f"  {f}")
    return 0


def _privacy(settings, args) -> int:
    from dindon import privacy

    with connect(settings.database_url) as conn:
        conn.autocommit = True
        if args.action == "list":
            for user_id, status, requested_at in conn.execute("SELECT user_id, status, requested_at FROM privacy_subjects ORDER BY requested_at"):
                print(f"{user_id}\t{status}\t{requested_at:%Y-%m-%d}")
            return 0
        if args.action == "purge":
            print(json.dumps(privacy.purge_older_than(conn, settings.retention_days)))
            return 0
        if args.user_id is None:
            print(f"privacy {args.action}: the Discord id of the person is needed", file=sys.stderr)
            return 2
        if args.action == "stop":
            print(json.dumps(privacy.stop_recording(conn, args.user_id, reason=args.reason or "objection", source="cli")))
        elif args.action == "erase":
            print(json.dumps(privacy.erase_person(conn, args.user_id, reason=args.reason or "erasure", source="cli",
                                                  file_directories=(settings.inbox_dir, settings.archive_dir))))
        elif args.action == "release":
            print(json.dumps({"released": privacy.release(conn, args.user_id, source="cli")}))
        else:
            print(json.dumps(privacy.export_person(conn, args.user_id), ensure_ascii=False, indent=2))
    return 0


def _cmd_forget_server(settings, args) -> int:
    from dindon import privacy

    with connect(settings.database_url) as conn:
        print(json.dumps(privacy.erase_server(conn, args.guild_id, source="cli", file_directories=(settings.inbox_dir, settings.archive_dir))))
    return 0


def _cmd_debate_report(settings, args) -> int:
    """What the claims of the debates came to, for the owner to read (docs/DEBAT.md): each claim with its verdict and its sources, and the parity table by position."""
    from dindon.debate import claims, store

    with connect(settings.database_url) as conn:
        ids = [args.debate] if args.debate else [row[0] for row in conn.execute("SELECT id FROM debates ORDER BY id DESC LIMIT 20").fetchall()]
        report = []
        for debate_id in ids:
            debate = store.get(conn, debate_id)
            if debate is not None:
                unread = conn.execute("SELECT count(*) FROM debate_messages WHERE debate_id = %s AND read_at IS NULL", (debate_id,)).fetchone()[0]
                report.append({"debate": debate_id, "topic": debate.topic, "status": debate.status, "messages_waiting_to_be_read": unread,
                               "claims": claims.claims_of(conn, debate_id), "parity_by_position": claims.parity(conn, debate_id)})
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dindon")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply the SQL files")
    sub.add_parser("check", help="print what the database is made of")
    sub.add_parser("serve", help="migrate, then run the application (ingestion, collection, API, interface)")
    sub.add_parser("bot", help="the live bot: receives the new messages of the followed servers from Discord's Gateway (needs a bot token)")
    sub.add_parser("bot-health", help="exit code 0 if the live bot is alive and connected (for the check of its container)")
    preflight = sub.add_parser("preflight", help="is it reasonable to run the bot for real on this server? Checks the configuration, Discord, the database (read only)")
    preflight.add_argument("--json", action="store_true", help="the result as JSON")
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
    analyze = sub.add_parser("analyze", help="the analysis: conversations, vectors, topics to validate (needs Ollama, see docs/ANALYSE.md)")
    analyze.add_argument("--guild", type=int, help="server ID (default: the first of DINDON_GUILD_IDS, else the most recently imported)")
    analyze.add_argument("--stage", action="append", dest="stages", choices=["conversations", "embeddings", "themes", "claims", "axes"],
                         help="only this stage (can be repeated; default: all, in order). A stage never redoes what is done")
    analyze.add_argument("--limit", type=int, help="for the stage claims: read at most this many conversations (the most important first)")
    analyze.add_argument("--topics", type=int, help="how many topics (default: found by the silhouette)")
    analyze.add_argument("--rebuild", action="store_true", help="forget the conversations (and the vectors made from them) and make them again")
    export = sub.add_parser("export", help="export one channel (and its threads) as JSON v2 files, with Dindon's own exporter (needs a token)")
    export.add_argument("channel", type=int, help="the id of the channel")
    export.add_argument("--out", type=Path, default=Path("export"), help="the folder of the files (made if missing)")
    export.add_argument("--after", type=int, help="only the messages after this message id")
    export.add_argument("--before", type=int, help="only the messages before this message id")
    export.add_argument("--threads", choices=["none", "active", "all"], help="the threads of the channel (default: DINDON_THREADS)")
    export.add_argument("--reactions", choices=["all", "recent", "none"], help="who reacted: all, only the recent messages, none (default: DINDON_EXPORT_REACTIONS)")
    export.add_argument("--partition", type=int, help="messages per file")
    export.add_argument("--filter", help="people who wrote and who are mentioned, e.g. \"(from:1 | from:2) (mentions:3)\"")
    rights = sub.add_parser("privacy", help="the rights of the people recorded: stop recording one, erase one, give them their data (docs/CONFORMITE.md)")
    rights.add_argument("action", choices=["list", "stop", "erase", "release", "export", "purge"],
                        help="stop: no longer record the person; erase: stop AND delete everything of them; release: record again; "
                             "export: print what is held of them (JSON); purge: delete what is older than DINDON_RETENTION_DAYS")
    rights.add_argument("user_id", nargs="?", type=int, help="Discord id of the person")
    rights.add_argument("--reason", default="", help="why (kept in the register; do not put anything personal)")
    report = sub.add_parser("debate-report", help="what the claims of the debates came to: each claim, its verdict and its sources, and the parity table by position (docs/DEBAT.md)")
    report.add_argument("--debate", type=int, help="one debate (default: the last 20)")
    forget = sub.add_parser("forget-server", help="delete everything held of one server (messages, members, links, scores, files). Cannot be undone")
    forget.add_argument("guild_id", type=int, help="Discord id of the server")
    catchup = sub.add_parser("catchup", help="export the last days again now, to see what was edited or deleted")
    catchup.add_argument("--guild", type=int, action="append")
    ingest = sub.add_parser("ingest", help="import JSON v2 exports (files or folders)")
    ingest.add_argument("paths", nargs="+", type=Path)
    ingest.add_argument("--prune", action="store_true", help="the files are complete re-exports of a window: remove what is gone from it")
    return parser


def _migrate_first(settings) -> None:
    with connect(settings.database_url, wait=60) as conn:
        applied = migrate(conn, settings.db_dir)
    print(f"migrations applied: {', '.join(applied) if applied else 'none (up to date)'}")


def _cmd_migrate(settings, args) -> int:
    _migrate_first(settings)
    return 0


def _cmd_check(settings, args) -> int:
    with connect(settings.database_url) as conn:
        print(json.dumps(database_report(conn), indent=2))
    return 0


def _cmd_bot_health(settings, args) -> int:
    """For the check of the bot's container: 0 when the bot is alive and connected, 1 otherwise (nothing is printed)."""
    try:
        with connect(settings.database_url) as conn:
            return 0 if bot_is_alive(conn) else 1
    except Exception:
        return 1


def _cmd_preflight(settings, args) -> int:
    """The check before the bot runs for real on a server (read only; never prints the token). Exit code 1 when something blocks."""
    from dindon.preflight import render, run_preflight

    checks = run_preflight(settings)
    if args.json:
        print(json.dumps([{"level": c.level, "area": c.area, "text": c.text} for c in checks], ensure_ascii=False, indent=2))
    else:
        print(render(checks))
    return 1 if any(c.level == "fail" for c in checks) else 0


def _cmd_rebuild_edges(settings, args) -> int:
    with connect(settings.database_url) as conn:
        print(f"{conn.execute('SELECT rebuild_edges()').fetchone()[0]} links rebuilt")
    return 0


def _cmd_bot(settings, args) -> int:
    from dindon.bot.runner import main as run_bot

    return run_bot(settings)


def _cmd_backfill(settings, args) -> int:
    from dindon.collector.selection import SelectionError

    selection = selection_from(args)
    collector = _collector(settings, args.guild)
    if selection.channels and len(collector.settings.guild_ids) > 1:
        return _fail("Plusieurs serveurs sont suivis : précisez lequel avec --guild pour choisir des salons.")
    with connect(settings.database_url, wait=60) as conn:
        migrate(conn, settings.db_dir)
    if selection.partial:
        print("Narrowed import: it brings only a part of the channels, so it does not count as a first import, "
              "and a complete `dindon backfill` later still brings everything.")
    for guild_id in collector.settings.guild_ids:
        print(f"server {guild_id}: reactions cost one request each, so a big server takes a while")
        try:
            print(collector.backfill(_new_connection(settings), guild_id, parallel=args.parallel, selection=selection))
        except SelectionError as error:
            return _fail(str(error))
    return 0


def _cmd_catchup(settings, args) -> int:
    collector = _collector(settings, args.guild)
    with _new_connection(settings)() as conn:
        print(f"{collector.catchup(conn)} channels exported again")
    return 0


def _cmd_serve(settings, args) -> int:
    import uvicorn

    from dindon.api.main import create_app

    _migrate_first(settings)
    # Open pages (live events) must not keep the application from stopping: `docker stop` waits 10 seconds
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info", timeout_graceful_shutdown=3)
    return 0


def _fail(message: str) -> int:
    """A message for a person, on the error output, and the exit code of a command that could not do what was asked."""
    print(message, file=sys.stderr)
    return 1


COMMANDS = {
    "migrate": _cmd_migrate, "check": _cmd_check, "rebuild-edges": _cmd_rebuild_edges, "bot": _cmd_bot, "bot-health": _cmd_bot_health, "preflight": _cmd_preflight, "backfill": _cmd_backfill, "catchup": _cmd_catchup, "forget-server": _cmd_forget_server,
    "serve": _cmd_serve, "analyze": _analyze, "export": _export,
    "privacy": _privacy, "ingest": _cmd_ingest, "debate-report": _cmd_debate_report,
}


def main() -> None:
    args = _build_parser().parse_args()
    sys.exit(COMMANDS[args.command](load_settings(), args))


if __name__ == "__main__":
    main()
