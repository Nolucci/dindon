"""How fast Dindon's exporter reads a channel, against a fake Discord with a latency per request (what a real network costs), for several settings.

    .venv/bin/python tools/bench_export.py [messages] [latency_ms]

The numbers are what the exporter does with THAT latency and no rate limit: they show what the settings change (requests, parallelism, who reacted), not the
speed of a real Discord (which also limits the rate: about 50 requests per second at most, and fewer per route).
"""
import sys
import tempfile
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from dindon.export import Exporter  # noqa: E402
from fake_discord import FakeDiscord  # noqa: E402
from make_demo_server import World  # noqa: E402


def main(messages: int = 20_000, latency_ms: int = 25) -> None:
    world = World(seed=5, people=60, channels=1)
    world.generate(messages, days=60, end=datetime.now(UTC) - timedelta(minutes=30))
    channel = world.channels[0]
    with_reactions = sum(1 for m in channel.messages if m.get("reactions"))
    print(f"{len(channel.messages)} messages, {with_reactions} with reactions, {latency_ms} ms per request")
    server = FakeDiscord(world, token="t").start()
    server.latency = latency_ms / 1000
    try:
        print(f"{'reactions':>12} {'workers':>8} {'seconds':>8} {'messages/s':>11} {'requests':>9} {'profiles':>9} {'reaction lists':>15}")
        for reactions, days, workers in (("none", 30, 6), ("recent", 7, 1), ("recent", 7, 6), ("recent", 30, 6), ("all", 30, 1), ("all", 30, 6), ("all", 30, 12)):
            exporter = Exporter("t", server.api_url, workers=workers, reactions=reactions, reactions_days=days)
            with tempfile.TemporaryDirectory() as out:
                started = time.monotonic()
                exporter.export(channel.id, Path(out), partition=50_000)
                seconds = time.monotonic() - started
            label = reactions + (f" {days} d" if reactions == "recent" else "")
            print(f"{label:>12} {workers:>8} {seconds:>8.1f} {len(channel.messages) / seconds:>11.0f} {exporter.client.requests:>9} {exporter.stats['member_requests']:>9} {exporter.stats['reaction_requests']:>15}")
    finally:
        server.stop()


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
