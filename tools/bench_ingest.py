"""Measures what a live increment costs on a big database.

Rebuilds the same invented server as `make_demo_server.py --people 400 --messages 500000 --channels 40 --days 365`
(same seed), adds new messages to one channel, exports only those (like the collector does with --after) and
imports them into the database that DATABASE_URL points to, which must already hold the 500,000 messages.

    DATABASE_URL=postgresql://dindon:PASSWORD@127.0.0.1:5432/dindon_bench python tools/bench_ingest.py
"""
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from dindon.ingest.loader import ingest_file
from make_demo_server import World, parse_iso

world = World(seed=1, people=400, channels=40)
world.generate(500_000, days=365)
channel = max(world.channels, key=lambda c: len(c.messages))
members = world.people[:30]
last = int(channel.messages[-1]["id"])
when = parse_iso(channel.messages[-1]["timestamp"])

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn, tempfile.TemporaryDirectory() as tmp:
    for size in (10, 100, 1000):
        before_last = int(channel.messages[-1]["id"])
        world._conversation(channel, members, size, channel_end := parse_iso(channel.messages[-1]["timestamp"]) + timedelta(minutes=5))
        path = Path(tmp) / f"increment-{size}.json"
        path.write_text(world.export_document(channel, after_id=before_last, exported_at=datetime.now(timezone.utc)), encoding="utf-8")
        result = ingest_file(conn, path)
        print(f"{size:>5} new messages in one channel (database of 500,000): {result.seconds * 1000:7.1f} ms  "
              f"({result.messages_new} new, {result.edges_changed} links changed)")
