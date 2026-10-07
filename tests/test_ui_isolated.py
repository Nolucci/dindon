"""The points without a link, in a real browser (Chromium through Playwright): the box, the footer, the search, the card.

Optional: skipped when Playwright or the built interface (make web) is missing. The Content-Security-Policy stays on.
Set DINDON_SHOTS=/some/folder to keep a screenshot.
"""
import dataclasses
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.api.main import create_app  # noqa: E402
from dindon.bot.adapter import Directory, build_document, digest  # noqa: E402
from dindon.ingest.loader import GATEWAY_SOURCE, ingest_document  # noqa: E402
from gateway_fixtures import ALICE, BOB, CAROL, GENERAL, GUILD, guild_create, member, message_create  # noqa: E402
from synthetic import settings_for  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def squeeze(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def app_port(ingest_db, ingest_url, tmp_path):
    directory = Directory([GUILD])
    directory.apply("GUILD_CREATE", guild_create())
    now = datetime.now(UTC)
    carol_says = message_create(3_000_000_000_000_000_001, "on y va ?", CAROL, timestamp=(now - timedelta(hours=2)).isoformat())
    messages = [
        carol_says,
        message_create(3_000_000_000_000_000_002, "oui", BOB, reply_to=carol_says, timestamp=(now - timedelta(hours=1)).isoformat()),
        message_create(3_000_000_000_000_000_003, "je parle seule", ALICE, member_data=member("Ali"), timestamp=(now - timedelta(days=1)).isoformat()),
    ]
    document = build_document(directory, GUILD, GENERAL, messages)
    ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), web_dir=WEB)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(create_app(settings, background=False), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield port
    server.should_exit = True
    thread.join(timeout=10)


def test_people_without_a_link_can_be_shown_hidden_searched_and_opened(app_port):
    outside, errors = [], []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        base = f"http://127.0.0.1:{app_port}"
        page.on("request", lambda r: outside.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("footer span:has-text('personne')", timeout=20000)

        box = page.get_by_label("Sans lien")
        assert box.is_checked()                                                         # on by default
        page.wait_for_selector("footer span:has-text('sans lien')")
        assert "3 personnes (dont 1 sans lien)" in squeeze(page.inner_text("footer"))   # Bob and Carol linked, Alice alone
        assert "2 liens" not in squeeze(page.inner_text("footer")) and "1 lien" in squeeze(page.inner_text("footer")) and "1 liens" not in squeeze(page.inner_text("footer"))
        time.sleep(2)  # the points find their places
        if os.environ.get("DINDON_SHOTS"):
            Path(os.environ["DINDON_SHOTS"]).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(os.environ["DINDON_SHOTS"]) / "isolated-on.png"))

        page.fill("input[type=search]", "Ali")                                          # the lonely person can be found and opened
        page.wait_for_selector(".search li button")
        page.click(".search li button >> nth=0")
        page.wait_for_selector("aside h2")
        assert "Ali" in page.inner_text("aside h2") and "1" in page.inner_text("aside")

        box.uncheck()                                                                   # hidden: as before, at once
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=5000)
        assert "sans lien" not in page.inner_text("footer")
        box.check()
        page.wait_for_selector("footer span:has-text('3 personnes')", timeout=5000)
        assert "sans lien" in page.inner_text("footer")
        browser.close()
    assert not outside, f"the page asked for things outside the application: {sorted(set(outside))[:3]}"
    assert not errors, f"errors in the page: {errors[:2]}"
