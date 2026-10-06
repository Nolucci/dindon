"""Measures the privacy operations on a big INVENTED server, in a scratch database that is dropped at the end.

    .venv/bin/python tools/measure_privacy.py [messages] [people]

The database is the one of DATABASE_URL / .env (the compose one), but a database of its own is created in it (dindon_scale) and removed:
the real data is never read. Numbers go to MESURES.md by hand.
"""
import statistics
import sys
import tempfile
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from dindon import privacy  # noqa: E402
from dindon.config import load_settings  # noqa: E402
from dindon.ingest.loader import ingest_file  # noqa: E402
from dindon.migrate import migrate  # noqa: E402
from make_demo_server import World, write_exports  # noqa: E402


def timed(label, fn):
    start = time.monotonic()
    out = fn()
    print(f"{label}: {time.monotonic() - start:.2f} s", flush=True)
    return out


def main(messages: int = 300_000, people: int = 5_000) -> None:
    settings = load_settings()
    base, _, _ = settings.database_url.rpartition("/")
    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS dindon_scale WITH (FORCE)")
        admin.execute("CREATE DATABASE dindon_scale")
    url = f"{base}/dindon_scale"
    try:
        with psycopg.connect(url) as conn:
            migrate(conn, settings.db_dir)
        world = World(seed=3, people=people, channels=60)
        timed(f"generate {messages} invented messages, {people} people", lambda: world.generate(messages, days=400))
        out = Path(tempfile.mkdtemp(prefix="dindon-scale-"))
        files = write_exports(world, out)
        with psycopg.connect(url, autocommit=True) as conn:
            timed(f"ingest {len(files)} files", lambda: [ingest_file(conn, f) for f in files])
            n = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
            e = conn.execute("SELECT count(*) FROM edges").fetchone()[0]
            print(f"database: {n} messages, {e} links", flush=True)
            top = conn.execute("SELECT author_id, count(*) c FROM messages GROUP BY 1 ORDER BY c DESC").fetchall()
            heavy, middle = top[0], top[len(top) // 2]

            # 1. the register costs nothing when it is short, and little when it is long
            register_ids = [r[0] for r in top[-1500:]]
            conn.execute("INSERT INTO privacy_subjects (user_id, status) SELECT unnest(%s::bigint[]), 'stopped'", (register_ids,))
            timed("blocked_ids() with 1500 people in the register", lambda: privacy.blocked_ids(conn))
            conn.execute("DELETE FROM privacy_subjects")
            sample = files[0]
            one = []
            for i in range(3):
                conn.execute("DELETE FROM ingest_runs")  # so that the same file is imported again (it is a duplicate otherwise)
                s = time.monotonic()
                ingest_file(conn, sample)
                one.append(time.monotonic() - s)
            conn.execute("INSERT INTO privacy_subjects (user_id, status) SELECT unnest(%s::bigint[]), 'stopped'", (register_ids,))
            two = []
            for i in range(3):
                conn.execute("DELETE FROM ingest_runs")
                s = time.monotonic()
                ingest_file(conn, sample)
                two.append(time.monotonic() - s)
            print(f"re-import of one file: {statistics.median(one) * 1000:.0f} ms without register, {statistics.median(two) * 1000:.0f} ms with 1500 people in it", flush=True)
            conn.execute("DELETE FROM privacy_subjects")

            # 2. the files of the archive
            archive = Path(tempfile.mkdtemp(prefix="dindon-archive-"))
            for i, f in enumerate(files * 40):
                (archive / f"{i}.json").write_bytes(f.read_bytes())
            size = sum(p.stat().st_size for p in archive.iterdir())
            timed(f"scrub {len(list(archive.iterdir()))} archived files ({size / 1e6:.0f} MB) for a person who is in them", lambda: privacy.scrub_files((archive,), heavy[0]))

            # 3. erasing
            print(f"most active person: {heavy[1]} messages; a median one: {middle[1]}", flush=True)
            timed("erase a median person (database only)", lambda: privacy.erase_person(conn, middle[0]))
            timed("erase the most active person (database only)", lambda: privacy.erase_person(conn, heavy[0]))
            timed("export the data of the 10th most active person", lambda: privacy.export_person(conn, top[10][0]))

            # 4. keeping for a limited time
            conn.execute("UPDATE messages SET sent_at = sent_at - interval '300 days'")

            timed("purge (everything is now older than 100 days: all messages) in batches of 20 000", lambda: privacy.purge_older_than(conn, 100))
            print("messages left:", conn.execute("SELECT count(*) FROM messages").fetchone()[0])
    finally:
        with psycopg.connect(settings.database_url, autocommit=True) as admin:
            admin.execute("DROP DATABASE IF EXISTS dindon_scale WITH (FORCE)")


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
