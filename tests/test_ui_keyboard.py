"""What a person does with the keyboard, and what the page says when there is nothing to show, in a real browser (Chromium through
Playwright): the search, the person's card, the windows (focus in, Tab kept inside, focus back), the filters that apply at once.

Optional: skipped when Playwright or the built interface (make web) is missing. The Content-Security-Policy stays on.
"""
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from test_ui_servers import WEB, open_page, running  # noqa: E402

pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def wait_for_count(page, selector: str, expected: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.locator(selector).count() == expected:
            return
        time.sleep(0.1)
    raise AssertionError(f"{selector}: {page.locator(selector).count()} elements, expected {expected}")


def focused_in(page, selector: str) -> bool:
    return page.evaluate(f"!!document.activeElement.closest('{selector}')")


def test_the_search_the_card_and_the_filters_work_with_the_keyboard(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = open_page(p, base)
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=20000)

        page.fill("input[type=search]", "bo")                                           # Bobby
        page.wait_for_selector(".search li button")
        page.press("input[type=search]", "ArrowDown")
        assert focused_in(page, ".search li")                                          # Down goes into the suggestions
        page.press(".search li button", "Escape")
        assert page.locator(".search li button").count() == 0                          # Escape closes them...
        assert focused_in(page, ".search")                                             # ...and goes back to the box
        assert page.locator("aside h2").count() == 0                                   # without opening the card behind
        page.fill("input[type=search]", "bob")                                         # typing opens them again
        page.wait_for_selector(".search li button")
        page.press("input[type=search]", "Enter")                                      # Enter opens the first one
        page.wait_for_selector("aside h2", timeout=10000)
        assert "Bobby" in page.inner_text("aside h2")

        page.keyboard.press("Escape")                                                  # Escape closes the card
        wait_for_count(page, "aside h2", 0)

        page.get_by_role("button", name="Filtres", exact=True).click()
        before = page.inner_text("footer")
        page.get_by_role("button", name="Mentions").click()                            # a filter applies at once, not after several seconds
        page.get_by_role("button", name="Réponses").click()
        page.get_by_role("button", name="Réactions").click()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and "Aucun type d’échange choisi" not in page.inner_text("main"):
            time.sleep(0.1)
        assert "Aucun type d’échange choisi" in page.inner_text("main")                # nothing chosen: the page says so
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and "2 personnes" in page.inner_text("footer"):
            time.sleep(0.1)
        assert "2 personnes" not in page.inner_text("footer") and before != page.inner_text("footer")   # and the counts are gone
        page.get_by_role("button", name="Réponses").click()
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=4000)    # and shows again as soon as one is back
        browser.close()


def test_a_window_takes_the_focus_keeps_it_and_gives_it_back(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = open_page(p, base)
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=20000)
        opener = page.get_by_role("button", name="Inviter le bot")
        opener.focus()
        opener.click()
        dialog = page.locator("[role=dialog]")
        dialog.wait_for()
        assert focused_in(page, "[role=dialog]")                                       # the focus entered the window
        for _ in range(30):                                                            # Tab, in both directions, never leaves it
            page.keyboard.press("Tab")
            assert focused_in(page, "[role=dialog]")
        for _ in range(30):
            page.keyboard.press("Shift+Tab")
            assert focused_in(page, "[role=dialog]")
        page.keyboard.press("Escape")
        dialog.wait_for(state="detached")
        assert page.evaluate("document.activeElement.textContent.includes('Inviter le bot')")   # the focus is back on what opened it
        browser.close()


def test_the_themes_page_says_so_when_no_server_is_imported(ingest_url, tmp_path):
    from fake_ollama import FakeOllama  # noqa: F401  (the page does not need it: Ollama is not asked without a server)

    from dindon.api.main import create_app
    import dataclasses
    import socket
    import threading

    import uvicorn

    from synthetic import settings_for

    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, "correct horse"), web_dir=WEB)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, background=False), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        with sync_api.sync_playwright() as p:
            browser, page = open_page(p, f"http://127.0.0.1:{port}")
            page.wait_for_selector("nav", timeout=20000)
            page.get_by_role("button", name="Analyse", exact=True).click()
            page.wait_for_selector("text=Aucun serveur n’est encore importé", timeout=10000)
            assert page.get_by_role("button", name="Lancer l’analyse").count() == 0       # no button that cannot work, no English error
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_the_system_page_shows_each_piece_and_what_to_look_at(ingest_db, ingest_url, tmp_path):
    import json
    from datetime import UTC, datetime, timedelta

    ingest_db.execute("INSERT INTO service_status (name, updated_at, data) VALUES ('bot', %s, %s::jsonb)",
                      (datetime.now(UTC) - timedelta(minutes=10), json.dumps({"connected": True, "sessions": 3, "gaps": 2, "received": 7, "new": 5})))
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = open_page(p, base)
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=20000)
        page.get_by_role("button", name="Système").click()
        page.wait_for_selector("h1:has-text('Système')")
        page.wait_for_selector("section[aria-label='Base de données']")
        assert "En ligne" in page.inner_text("section[aria-label='Base de données']")
        assert "Ollama ne répond pas" in page.inner_text("section[aria-label='IA locale']")      # no Ollama in this test: it says so
        assert page.locator("section[aria-label='Bot Discord']").count() == 1
        browser.close()
