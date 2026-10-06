"""The window to invite the bot, in a real browser (Chromium through Playwright), against the fake Discord (a bot token).

Optional: skipped when Playwright or the built interface (make web) is missing. The Content-Security-Policy stays on.
Set DINDON_SHOTS=/some/folder to keep a screenshot.
"""
import dataclasses
import os
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.api.main import create_app  # noqa: E402
from fake_discord import FakeDiscord  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_collector import TOKEN, world  # noqa: E402,F401 (fixture)

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(world, ingest_url, tmp_path):
    import uvicorn

    discord = FakeDiscord(world, token=TOKEN, bot=True).start()
    discord.other_servers = [{"id": "999000000000000001", "name": "Un autre serveur"}]
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), web_dir=WEB, discord_api_url=discord.api_url,
                                   discord_token=TOKEN, guild_ids=(world.guild_id,))
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
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    discord.stop()


def test_the_window_gives_the_link_and_says_which_servers_are_followed(base, world):
    outside, errors = [], []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("request", lambda r: outside.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)

        page.get_by_role("button", name="Inviter le bot").click()
        dialog = page.locator("[role=dialog]")
        dialog.wait_for()
        link = dialog.get_by_role("link", name="Ouvrir Discord")
        link.wait_for()
        href = link.get_attribute("href")
        assert href.startswith("https://discord.com/oauth2/authorize?") and "client_id=424242424242424242" in href and "scope=bot" in href
        assert link.get_attribute("target") == "_blank" and "noopener" in link.get_attribute("rel")      # it opens Discord elsewhere, cut off from the page
        assert dialog.get_by_label("Lien d’invitation").input_value() == href
        assert "Voir les salons" in dialog.inner_text() and "Lire l’historique des messages" in dialog.inner_text()

        rows = {row.locator(".name").inner_text(): row.inner_text() for row in dialog.locator(".servers li").all()}
        assert set(rows) == {world.name, "Un autre serveur"}
        assert "non suivi" not in rows[world.name] and "suivi" in rows[world.name]
        assert "non suivi" in rows["Un autre serveur"]
        assert "DINDON_GUILD_IDS" in dialog.inner_text()                                                   # and how to follow the other one
        if os.environ.get("DINDON_SHOTS"):
            Path(os.environ["DINDON_SHOTS"]).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(os.environ["DINDON_SHOTS"]) / "invite.png"))

        page.keyboard.press("Escape")
        dialog.wait_for(state="detached")
        browser.close()
    assert not errors, errors
    assert not outside, f"the page asked for something outside the application: {outside}"                  # the link is only followed by the person
