"""Database connection."""
import time

import psycopg


def connect(database_url: str, wait: float = 0) -> psycopg.Connection:
    """Open a connection, retrying for up to `wait` seconds (the database may still be starting)."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return psycopg.connect(database_url)
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
