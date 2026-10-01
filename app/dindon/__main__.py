"""Command line: dindon migrate | check | serve"""
import argparse
import json
import sys

from dindon.config import load_settings
from dindon.db import connect
from dindon.health import database_report
from dindon.migrate import migrate


def main() -> None:
    parser = argparse.ArgumentParser(prog="dindon")
    parser.add_argument("command", choices=["migrate", "check", "serve"])
    command = parser.parse_args().command
    settings = load_settings()

    if command in ("migrate", "serve"):
        with connect(settings.database_url, wait=60) as conn:
            applied = migrate(conn, settings.db_dir)
        print(f"migrations applied: {', '.join(applied) if applied else 'none (up to date)'}")

    if command == "check":
        with connect(settings.database_url) as conn:
            print(json.dumps(database_report(conn), indent=2))

    if command == "serve":
        import uvicorn

        from dindon.api.main import create_app

        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
