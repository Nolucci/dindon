"""Drives a real browser against a running Dindon and checks what a person would see: the login, the map, a person's
card, and that a new exchange on the (fake) Discord lights up its line in the page. Prints the delay of the light.

It is optional (it needs a browser) and not part of `make test`:

    .venv/bin/pip install -e ".[e2e]" && .venv/bin/playwright install chromium
    make demo            # in another terminal, leave it running
    .venv/bin/python tools/check_ui.py --shots /tmp/dindon-shots

The Content-Security-Policy stays on during the check: the page really may not load anything from outside.
"""
import argparse
import json
import random
import statistics
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_demo_server import World  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--app", default="http://127.0.0.1:8011")
parser.add_argument("--fake", default="http://127.0.0.1:8765")
parser.add_argument("--password", default="demo")
parser.add_argument("--people", type=int, default=60, help="the same as the fake Discord was started with")
parser.add_argument("--trials", type=int, default=8)
parser.add_argument("--shots", type=Path, default=None, help="folder for screenshots")
args = parser.parse_args()

world = World(seed=3, people=args.people)  # the same invented server as the fake Discord, to know its channels and people


def post(channel, author, content, reply_to=None):
    request = urllib.request.Request(f"{args.fake}/_fake/post", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"channel": channel.id, "author": author.id, "content": content, "reply_to": reply_to}).encode())
    return json.load(urllib.request.urlopen(request))


def shot(page, name):
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.shots / name))


failures = []
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    outside, errors = [], []
    page.on("request", lambda r: outside.append(r.url) if not r.url.startswith((args.app, "data:", "blob:")) else None)
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))

    page.goto(args.app)
    page.fill("#password", "not the password")
    page.click("button[type=submit]")
    page.wait_for_selector("[role=alert]")
    print("wrong password ->", page.inner_text("[role=alert]"))
    page.fill("#password", args.password)
    page.click("button[type=submit]")
    page.wait_for_selector("footer span:has-text('personnes')", timeout=20000)
    time.sleep(6)  # the points find their places
    shot(page, "map.png")
    print("footer:", page.inner_text("footer").replace("\n", " | "))

    page.fill("input[type=search]", world.people[0].name[:3])
    page.wait_for_selector(".search li button")
    page.click(".search li button >> nth=0")
    page.wait_for_selector("aside h2")
    time.sleep(1.5)
    shot(page, "card.png")
    print("card:", page.inner_text("aside h2"))
    page.click("aside .close")
    page.click("text=Tout voir")
    time.sleep(1)

    channel = max(world.channels, key=lambda c: len(c.messages))
    a, b = world.people[2], world.people[3]
    delays = []
    for i in range(args.trials):
        before = int(page.get_attribute(".canvas", "data-flashes") or 0)
        started = time.monotonic()
        first = post(channel, a, f"Essai {i} : qu'en pensez-vous ?")
        post(channel, b, "Je ne suis pas d'accord, voilà pourquoi…", first["id"])
        while time.monotonic() < started + 30 and int(page.get_attribute(".canvas", "data-flashes") or 0) <= before:
            time.sleep(0.02)
        else:
            if int(page.get_attribute(".canvas", "data-flashes") or 0) <= before:
                failures.append("a line never lit up")
                break
        delays.append(time.monotonic() - started)
        if i == 0:
            time.sleep(0.3)
            shot(page, "flash.png")
        time.sleep(3.5 + random.random() * 2.5)
    if delays:
        print(f"delay between an exchange and the light, in seconds: min {min(delays):.2f}, median {statistics.median(delays):.2f}, max {max(delays):.2f}")
    if outside:
        failures.append(f"the page asked for things outside the application: {sorted(set(outside))[:3]}")
    if errors:
        failures.append(f"errors in the page: {errors[:2]}")
    browser.close()

print("FAILED: " + "; ".join(failures) if failures else "OK: nothing loaded from outside, no error in the page, every exchange lit its line")
sys.exit(1 if failures else 0)
