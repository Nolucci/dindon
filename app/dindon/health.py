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
