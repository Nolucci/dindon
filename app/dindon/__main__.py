"""Command line: dindon migrate | check | serve | ingest FILE... | rebuild-edges"""
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="dindon")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply the SQL files")
    sub.add_parser("check", help="print what the database is made of")
    sub.add_parser("serve", help="migrate, then run the application (ingestion, collection, API, interface)")
    sub.add_parser("rebuild-edges", help="rebuild the links between people from the messages (after changing the half-life)")
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

    if args.command == "ingest":
        sys.exit(_ingest(settings, args.paths, args.prune))

    if args.command == "serve":
        import uvicorn

        from dindon.api.main import create_app

        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
