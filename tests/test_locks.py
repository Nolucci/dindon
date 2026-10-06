"""The advisory locks: what rewrites the messages waits for the others, and a migration does not wait for them. Level of proof: real PostgreSQL."""
import psycopg
import pytest

from dindon import locks
from dindon.analysis.conversations import build_conversations
from test_extraction import GUILD_ID


def test_the_locks_are_different_numbers_where_they_must_be():
    assert len({locks.MIGRATION, locks.DATA}) == 2                                     # a migration never waits for an import


def test_building_the_conversations_waits_for_an_import_or_an_erasure(ingest_db, ingest_url):
    with psycopg.connect(ingest_url) as other:                                          # somebody holds the lock of the data (an import, an erasure…)
        other.execute("SELECT pg_advisory_xact_lock(%s)", (locks.DATA,))
        ingest_db.execute("SET lock_timeout = '300ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            build_conversations(ingest_db, GUILD_ID)
        other.rollback()
    ingest_db.execute("SET lock_timeout = 0")
    assert build_conversations(ingest_db, GUILD_ID)["total"] == 0                       # and it goes on once the lock is free
