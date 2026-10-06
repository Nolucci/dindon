"""The server picker (top left of the page), in a real browser (Chromium through Playwright): it is a menu with one server as with
several, it changes the map, and it leads to the invitation of the bot for a server that is not there yet.

Optional: skipped when Playwright or the built interface (make web) is missing. The Content-Security-Policy stays on.
"""
import contextlib
import dataclasses
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
from gateway_fixtures import ALICE, BOB, CAROL, GENERAL, GUILD, channel, guild_create, message_create, role  # noqa: E402
from synthetic import settings_for  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
OTHER, OTHER_CHANNEL = "101", "290"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def ingest_servers(ingest_db, second: bool) -> None:
    now = datetime.now(UTC)
    def when(**delta):
        return (now - timedelta(**delta)).isoformat()
    directory = Directory([GUILD, OTHER])
    directory.apply("GUILD_CREATE", guild_create())
    carol = message_create(3_000_000_000_000_000_001, "on y va ?", CAROL, timestamp=when(hours=2))
    documents = [build_document(directory, GUILD, GENERAL, [carol, message_create(3_000_000_000_000_000_002, "oui", BOB, reply_to=carol, timestamp=when(hours=1))])]
    if second:                                       # an older server, with three people: it is not the one shown first
        other = guild_create(OTHER, "Autre serveur")
        other["roles"], other["channels"], other["threads"] = [role(OTHER, "@everyone", 0)], [channel(OTHER_CHANNEL, "autre-salon", 0, None, None, OTHER)], []
        directory.apply("GUILD_CREATE", other)
        first = message_create(3_000_000_000_000_000_011, "salut", ALICE, channel_id=OTHER_CHANNEL, guild_id=OTHER, timestamp=when(days=3))
        second_message = message_create(3_000_000_000_000_000_012, "salut Alice", BOB, channel_id=OTHER_CHANNEL, guild_id=OTHER, reply_to=first, timestamp=when(days=3, minutes=-1))
        third = message_create(3_000_000_000_000_000_013, "moi aussi", CAROL, channel_id=OTHER_CHANNEL, guild_id=OTHER, reply_to=second_message, timestamp=when(days=3, minutes=-2))
        documents.append(build_document(directory, OTHER, OTHER_CHANNEL, [first, second_message, third]))
    for document in documents:
        ingest_document(ingest_db, document, GATEWAY_SOURCE, digest(document), only_new=True)


@contextlib.contextmanager
def running(ingest_db, ingest_url, tmp_path, second: bool):
    import uvicorn

    ingest_servers(ingest_db, second)
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), web_dir=WEB)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, background=False), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def open_page(playwright, base):
    browser = playwright.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(base)
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    return browser, page


def squeeze(text: str) -> str:
    return " ".join(text.split())


def test_with_several_servers_the_picker_changes_the_map(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=True) as base, sync_api.sync_playwright() as p:
        browser, page = open_page(p, base)
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=20000)              # the most recent server first
        assert "Serveur test" in page.inner_text(".guildPicker")
        page.click(".guildPicker")
        menu = page.get_by_role("menu")
        menu.wait_for()
        servers = menu.get_by_role("menuitemradio")
        assert [squeeze(s.inner_text()) for s in servers.all()] == ["Autre serveur", "Serveur test"]   # alphabetical
        assert servers.nth(1).get_attribute("aria-checked") == "true" and servers.nth(0).get_attribute("aria-checked") == "false"
        servers.nth(0).click()
        menu.wait_for(state="detached")
        page.wait_for_selector("footer span:has-text('3 personnes')", timeout=25000)               # the map of the other server (a reload waits a few seconds)
        assert "Autre serveur" in page.inner_text(".guildPicker")
        browser.close()


def test_with_one_server_the_picker_is_still_a_menu_that_leads_to_the_invitation(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = open_page(p, base)
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=20000)
        page.click(".guildPicker")
        menu = page.get_by_role("menu")
        menu.wait_for()
        assert [squeeze(s.inner_text()) for s in menu.get_by_role("menuitemradio").all()] == ["Serveur test"]
        assert "une fois suivi" in menu.inner_text()                                              # why there is no other server
        menu.get_by_role("menuitem", name="Ajouter un autre serveur…").click()
        dialog = page.locator("[role=dialog]")
        dialog.wait_for()
        assert "Inviter le bot" in dialog.inner_text()
        page.keyboard.press("Escape")
        dialog.wait_for(state="detached")
        browser.close()
