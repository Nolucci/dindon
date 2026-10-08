"""The card of a person with the bars of the axes, and the page Cohérence, in a real browser. Optional: skipped without Playwright or the built interface."""
import dataclasses
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.api.main import create_app  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_axes import a_socialist_and_a_liar  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(ingest_url, ingest_db, tmp_path):
    import uvicorn

    a_socialist_and_a_liar(ingest_db)
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
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_the_contradiction_is_listed_and_the_card_shows_the_axes(base):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)

        page.get_by_role("button", name="Analyse", exact=True).click()
        page.get_by_role("button", name="Contradictions", exact=True).click()
        page.get_by_role("heading", name="Contradictions").wait_for()
        page.wait_for_selector(".person")
        assert page.locator(".person").count() == 1                                      # only Bobby: Alice is coherent
        assert "Propriété des moyens de production" in page.locator(".person").inner_text()
        page.get_by_label("Filtrer par verdict").select_option("all")
        assert page.locator(".person").count() == 2

        page.get_by_role("button", name="Carte", exact=True).click()
        page.fill("input[type=search]", "bob")
        page.wait_for_selector(".search li button")
        page.locator(".search li button").first.click()
        page.locator("aside").get_by_role("button", name="Positions", exact=True).click()
        page.get_by_text("Où elle se situe").wait_for()
        assert page.get_by_text("contredit « Socialiste »").is_visible()
        assert page.locator("aside .axes li").count() == 1 and page.locator("aside .axes .dot").count() == 1     # twenty-one bars, a dot on the one that has a score
        page.get_by_role("button", name="Propriété des moyens de production").click()
        page.get_by_text("L'État doit posséder le secteur").first.wait_for()
        import os
        if os.environ.get("DINDON_SHOTS"):
            page.screenshot(path=str(Path(os.environ["DINDON_SHOTS"]) / "person-positions.png"))
        page.locator("aside").get_by_role("button", name="Rôles", exact=True).click()
        assert page.get_by_text("contradiction", exact=True).first.is_visible()
        browser.close()
    assert errors == []
