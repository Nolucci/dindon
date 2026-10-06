"""What the /health endpoint and `dindon check` report: is the database in a good state?"""
import json
import urllib.request

import psycopg


def database_report(conn: psycopg.Connection) -> dict:
    """Counts what the schema is made of. The bookkeeping table of the migrations is not counted."""
    row = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name <> 'schema_migrations'),
          (SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'VIEW'),
          (SELECT count(*) FROM axes),
          (SELECT count(*) FROM axes WHERE is_active),
          (SELECT count(*) FROM schema_migrations)
        """
    ).fetchone()
    return {
        "tables": row[0],
        "views": row[1],
        "axes": row[2],
        "axes_active": row[3],
        "migrations_applied": row[4],
    }


def ollama_report(base_url: str) -> dict:
    """Is the local AI reachable, and which models does it have? Never fails: the AI is optional."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=1.5) as response:
            models = [m["name"] for m in json.load(response).get("models", [])]
        return {"reachable": True, "models": models}
    except Exception:
        return {"reachable": False, "models": []}


BOT_SILENT_AFTER = 120  # seconds without a sign of life from the bot (it gives one every 30): the same limit as the page « Système »


def bot_is_alive(conn: psycopg.Connection, max_age: int = BOT_SILENT_AFTER) -> bool:
    """Did the bot give a sign of life lately, and is it connected to Discord? (What `dindon bot-health` answers: the check of its container, which has no web port.)"""
    row = conn.execute("SELECT extract(epoch FROM now() - updated_at), coalesce((data->>'connected')::boolean, false) FROM service_status WHERE name = 'bot'").fetchone()
    return row is not None and row[0] <= max_age and row[1]
