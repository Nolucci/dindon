"""How much live traffic the bot's engine absorbs, with a real database: invented MESSAGE_CREATE events spread over many channels at a given
rate, counting how long the oldest message waits before it is in the database. Scratch database (dindon_load), dropped at the end.

    .venv/bin/python tools/measure_bot_load.py [messages_per_second] [seconds] [channels]
"""
import asyncio
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

from dindon.bot.events import GatewayEvent  # noqa: E402
from dindon.bot.runner import BotRunner, Writer  # noqa: E402
from dindon.config import load_settings  # noqa: E402
from dindon.migrate import migrate  # noqa: E402
from gateway_fixtures import ALICE, BOB, CAROL, GUILD, channel, guild_create, message_create  # noqa: E402


async def main(rate: int, seconds: int, channels: int) -> None:
    settings = load_settings()
    base, _, _ = settings.database_url.rpartition("/")
    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS dindon_load WITH (FORCE)")
        admin.execute("CREATE DATABASE dindon_load")
    url = f"{base}/dindon_load"
    try:
        with psycopg.connect(url) as conn:
            migrate(conn, settings.db_dir)
        guild = guild_create()
        guild["channels"] = [channel(str(5000 + i), f"salon-{i}") for i in range(channels)]
        runner = BotRunner([GUILD], Writer(url))
        runner.handle(GatewayEvent("dispatch", "GUILD_CREATE", guild))
        queue: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()
        engine = asyncio.create_task(runner.run(queue, stop))
        authors = [ALICE, BOB, CAROL]
        total, sent_at, next_id = rate * seconds, {}, 10**17
        start = time.monotonic()
        for i in range(total):
            while time.monotonic() - start < i / rate:
                await asyncio.sleep(0.001)
            next_id += 1
            payload = message_create(next_id, f"message numéro {i} sur un sujet", authors[i % 3], channel_id=str(5000 + (i * 7) % channels),
                                     timestamp="2026-10-02T19:00:00.000000+00:00")
            sent_at[next_id] = time.monotonic()
            queue.put_nowait(GatewayEvent("dispatch", "MESSAGE_CREATE", payload))
        deadline = time.monotonic() + 60
        while (runner.status()["waiting"] or not queue.empty()) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        elapsed = time.monotonic() - start
        stop.set()
        await engine
        with psycopg.connect(url) as conn:
            n = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        status = runner.status()
        print(f"{rate} msg/s over {channels} channels for {seconds} s: {n}/{total} messages in the database, drained {elapsed - seconds:.1f} s after the last one, "
              f"{status['batches']} documents, retries={status['database_retries']}, dropped={status['dropped']}, rejected={status['rejected']}")
    finally:
        with psycopg.connect(settings.database_url, autocommit=True) as admin:
            admin.execute("DROP DATABASE IF EXISTS dindon_load WITH (FORCE)")


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]] + [100, 20, 40][len(sys.argv) - 1:]
    asyncio.run(main(*a[:3]))
