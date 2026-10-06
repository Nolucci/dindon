"""The window to import a part of a server, in a real browser (Chromium through Playwright), against the fake Discord.

Optional: skipped when Playwright or the built interface (make web) is missing. The Content-Security-Policy stays on.
Set DINDON_SHOTS=/some/folder to keep screenshots.
"""
import dataclasses
import os
import socket
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.api.main import create_app  # noqa: E402
from test_collector import fake, message_count, world  # noqa: E402,F401 (fixtures)
from test_import_api import settings  # noqa: E402,F401 (fixture)
from test_import_selection import connection, ids_in, largest  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def squeeze(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def base(settings):
    import uvicorn

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(dataclasses.replace(settings, web_dir=WEB), background=False),
                                           host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def shot(page, name):
    if os.environ.get("DINDON_SHOTS"):
        Path(os.environ["DINDON_SHOTS"]).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(os.environ["DINDON_SHOTS"]) / name))


def test_the_window_imports_a_part_of_the_server_shows_errors_and_can_stop(base, fake, world, ingest_url, monkeypatch):
    channel = largest(world)
    author = Counter(m["authorId"] for m in channel.messages).most_common(1)[0][0]
    expected = {int(m["id"]) for m in channel.messages if m["authorId"] == author}
    names = sorted((c.name for c in world.channels if not c.parent_id), key=str.casefold)
    outside, errors = [], []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("request", lambda r: outside.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None)
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("text=Aucun serveur importé", timeout=20000)             # nothing imported yet: the window is how to start

        page.get_by_role("button", name="Importer").click()
        dialog = page.locator("[role=dialog]")
        dialog.wait_for()
        page.wait_for_selector(".channels li")
        assert page.locator(".channels li").count() == len(names)                        # the channels that Discord shows, imported or not
        start = page.get_by_role("button", name="Lancer l’import")
        assert start.is_disabled() and "Choisissez au moins un salon" in dialog.inner_text()

        page.locator(f".channels li >> nth={names.index(channel.name)}").locator("input").check()   # one channel, one person
        assert start.is_enabled()
        assert "Import partiel" not in dialog.inner_text()
        dialog.get_by_label("Auteurs").fill(author)
        assert "Import partiel" in dialog.inner_text()                                   # told before the start that it is not a complete import
        shot(page, "import-form.png")
        start.click()
        page.wait_for_selector("section.progress h3:has-text('Terminé')", timeout=30000)
        text = squeeze(dialog.inner_text())
        assert f"1 salon(s) sur 1 · {len(expected)} nouveaux messages" in text.replace(" ", " ")
        shot(page, "import-done.png")
        with connection(ingest_url) as conn:
            assert ids_in(conn) == expected

        dialog.get_by_label("Auteurs").fill("pseudo")                                    # a mistake is told in words, and nothing starts
        start.click()
        page.wait_for_selector("[role=alert]:has-text('identifiant Discord')")
        assert dialog.locator("section.progress h3").inner_text() == "Terminé"           # still the previous result

        page.keyboard.press("Escape")                                                    # closing: the map shows what was imported
        dialog.wait_for(state="detached")
        page.wait_for_selector("footer span:has-text('personne')", timeout=15000)

        fake.latency = 0.6                                                               # a slow import, to stop it
        page.get_by_role("button", name="Importer").click()
        page.wait_for_selector(".channels li")
        dialog.get_by_role("button", name="Tous").click()
        dialog.get_by_label("Auteurs").fill("")
        start.click()
        page.wait_for_selector("section.progress h3:has-text('En cours')", timeout=15000)
        stop = dialog.get_by_role("button", name="Annuler l’import")
        stop.wait_for()
        stop.click()
        page.wait_for_selector("section.progress h3:has-text('Annulé')", timeout=30000)
        assert "annulé(s)" in dialog.inner_text()
        browser.close()
    assert not outside, f"the page asked for things outside the application: {sorted(set(outside))[:3]}"
    assert not errors, f"errors in the page: {errors[:2]}"


def test_the_channels_of_a_big_server_can_be_searched(base, fake, world):
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("text=Aucun serveur importé", timeout=20000)
        page.get_by_role("button", name="Importer").click()
        page.wait_for_selector(".channels li")
        total = page.locator(".channels li").count()
        word = next(c.name for c in world.channels if not c.parent_id and "é" in c.name)           # an accent: the search ignores them
        page.get_by_label("Chercher un salon").fill(word.replace("é", "e")[:4])
        shown = page.locator(".channels li").count()
        assert 0 < shown < total and all(word.replace("é", "e")[:4] in n.lower().replace("é", "e").replace("è", "e") for n in page.locator(".channelName").all_inner_texts())
        page.get_by_role("button", name="Tous ceux affichés").click()                              # only the ones that are shown
        assert page.locator(".channels li input:checked").count() == shown
        page.get_by_label("Chercher un salon").fill("zzzz")
        page.get_by_text("Aucun salon ne correspond").wait_for()
        browser.close()
