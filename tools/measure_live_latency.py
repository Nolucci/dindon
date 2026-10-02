"""Measures, on a real server, how long it takes from a message written on Discord to the live event that the page receives.

It listens to the same live flow (Server-Sent Events) as the page, and for each event compares the moment it arrives with the moment
the message was written, as Discord dated it: the time of the message that moved a link ('edge' events) or the time carried by the id of
the newest message ('messages' events). So it covers Discord -> Gateway -> bot -> ingestion -> PostgreSQL -> NOTIFY -> SSE.

    .venv/bin/python tools/measure_live_latency.py --count 5      # then write messages on Discord

The password of the interface is asked (nothing is shown as you type) or read from DINDON_PASSWORD. The token is not needed and not read.
Only the kind of event and the delay are printed: no name, no text.

The clock of this machine must be right (it is compared with Discord's): a few tens of milliseconds of error are to be expected, and a
machine whose clock is seconds off gives numbers that mean nothing.
"""
from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import statistics
import sys
import time
import urllib.parse
from datetime import datetime

DISCORD_EPOCH_MS = 1_420_070_400_000


def snowflake_time(snowflake: int | str) -> float:
    """When Discord created this id, in seconds since 1970."""
    return ((int(snowflake) >> 22) + DISCORD_EPOCH_MS) / 1000


def login(base_url: str, password: str) -> str:
    url = urllib.parse.urlparse(base_url)
    connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=10)
    connection.request("POST", "/api/login", json.dumps({"password": password}), {"Content-Type": "application/json"})
    response = connection.getresponse()
    cookie = response.getheader("Set-Cookie")
    connection.close()
    if response.status != 200 or not cookie:
        raise SystemExit(f"login refused ({response.status}): wrong password?")
    return cookie.split(";")[0]


def listen(base_url: str, cookie: str, count: int, timeout: float, on_event=None, now=time.time) -> list[tuple[str, str, float]]:
    """Waits for `count` events that carry a message ('edge' or 'messages'). Returns [(type, kind, delay in seconds)]."""
    url = urllib.parse.urlparse(base_url)
    connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=5)
    connection.request("GET", "/events", headers={"Cookie": cookie})
    response = connection.getresponse()
    if response.status != 200:
        raise SystemExit(f"cannot listen ({response.status})")
    results: list[tuple[str, str, float]] = []
    deadline = time.monotonic() + timeout
    while len(results) < count and time.monotonic() < deadline:
        try:
            line = response.readline()
        except (TimeoutError, OSError):
            continue
        received = now()
        if not line.startswith(b"data:"):
            continue
        event = json.loads(line[5:])
        if event.get("type") == "edge":
            result = ("edge", event["kind"], received - datetime.fromisoformat(event["at"]).timestamp())
        elif event.get("type") == "messages":
            result = ("messages", "", received - snowflake_time(event["last"]))
        else:
            continue
        results.append(result)
        if on_event:
            on_event(*result)
    connection.close()
    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--count", type=int, default=5, help="how many events to wait for (an exchange gives one 'edge' and one 'messages')")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait at most")
    args = parser.parse_args(argv)
    cookie = login(args.url, os.environ.get("DINDON_PASSWORD") or getpass.getpass("Password of the interface (DINDON_PASSWORD): "))
    print(f"listening on {args.url}: write messages on Discord now ({args.count} events or {args.timeout:.0f}s)", flush=True)
    results = listen(args.url, cookie, args.count, args.timeout,
                     on_event=lambda kind, detail, delay: print(f"  {kind:<9}{detail:<9}{delay * 1000:7.0f} ms", flush=True))
    if not results:
        print("nothing received")
        return 1
    delays = [r[2] * 1000 for r in results]
    print(f"{len(delays)} events: min {min(delays):.0f} ms, median {statistics.median(delays):.0f} ms, max {max(delays):.0f} ms")
    if min(delays) < 0:
        print("a NEGATIVE delay means that this machine's clock is behind Discord's: these numbers cannot be trusted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
