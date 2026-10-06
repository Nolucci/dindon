"""The page of the topics, in a real browser (Chromium through Playwright), against a fake Ollama: start the analysis, follow it, then
validate, rename, merge and reject what it proposes.

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
from dindon.ingest.loader import ingest_file  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from make_demo_server import World, write_exports  # noqa: E402
from synthetic import settings_for  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(ingest_db, ingest_url, tmp_path):
    import uvicorn

    world = World(seed=7, people=30)
    world.generate(2500, days=20, end=datetime.now(UTC) - timedelta(days=3))
    for path in write_exports(world, tmp_path / "exports"):
        ingest_file(ingest_db, path)
    ollama = FakeOllama().start()
    settings = dataclasses.replace(settings_for(ingest_url, tmp_path, PASSWORD), web_dir=WEB, ollama_url=ollama.url)
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
    ollama.stop()


def wait_for_count(page, selector: str, expected: int, timeout: float = 15) -> None:
    """Waits until `selector` matches `expected` elements. (No evaluated string: the Content-Security-Policy forbids it, as it should.)"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.locator(selector).count() == expected:
            return
        time.sleep(0.1)
    raise AssertionError(f"{selector}: {page.locator(selector).count()} elements, expected {expected}")


def test_the_page_runs_the_analysis_and_the_person_decides_what_each_topic_becomes(base):
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

        page.get_by_role("button", name="Thèmes").click()
        page.wait_for_selector("text=Ollama prêt", timeout=15000)
        assert page.locator("article.topic").count() == 0 and "Aucun thème à examiner" in page.inner_text(".page")

        page.get_by_role("button", name="Lancer l’analyse").click()
        page.wait_for_selector("article.topic", timeout=60000)                              # the page follows the job, then shows its result
        page.wait_for_selector(".progress .badge:has-text('Terminée')", timeout=60000)
        cards = page.locator("article.topic")
        total = cards.count()
        assert total >= 5 and "proposé" in cards.first.inner_text()
        assert cards.first.locator("details li").count() >= 1                               # typical excerpts, to be able to judge
        if os.environ.get("DINDON_SHOTS"):
            Path(os.environ["DINDON_SHOTS"]).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(os.environ["DINDON_SHOTS"]) / "themes.png"))

        first = cards.first
        first.get_by_role("button", name="Valider").click()
        page.wait_for_selector("h2:has-text('Validés')")
        assert page.locator("article.topic.isValidated").count() == 1

        card = page.locator("article.topic").filter(has_text="proposé").first
        card.get_by_role("button", name="Renommer").click()
        card.get_by_label("Nom du thème").fill("Mon propre nom")
        card.get_by_role("button", name="Enregistrer").click()
        page.wait_for_selector("h3:has-text('Mon propre nom')")

        merging = page.locator("article.topic").filter(has_text="proposé").first
        merging.get_by_role("button", name="Fusionner…").click()
        merging.get_by_label("Fusionner avec").select_option(index=1)
        merging.get_by_role("button", name="Fusionner", exact=True).click()
        wait_for_count(page, "article.topic", total - 1)                                    # the merged topic is no longer listed

        rejected = page.locator("article.topic").filter(has_text="proposé").first
        rejected.get_by_role("button", name="Rejeter").click()
        wait_for_count(page, "article.topic", total - 2)                                    # a rejected topic leaves the page...
        page.get_by_label("Montrer les thèmes rejetés").check()
        wait_for_count(page, "article.topic", total - 1)                                    # ...and comes back when it is asked for
        assert page.locator("article.topic").filter(has_text="rejeté").count() == 1
        browser.close()
    assert not errors, errors
    assert not outside, f"the page asked for something outside the application: {outside}"
