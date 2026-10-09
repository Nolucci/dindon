"""The page Positions, in a real browser: the propositions with their bars, the people and their quotes, the reading from the button.
Optional: skipped when Playwright or the built interface (make web) is missing. The Content-Security-Policy stays on."""
import dataclasses
import os
import socket
import threading
import time
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.analysis.conversations import build_conversations  # noqa: E402
from dindon.analysis.extraction import extract_claims  # noqa: E402
from dindon.analysis.ollama import Ollama  # noqa: E402
from dindon.api.main import create_app  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_extraction import GOOD, GUILD_ID, SAYS_A, debate  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(ingest_url, ingest_db, tmp_path):
    import uvicorn

    ollama = FakeOllama().start()
    ollama.chat_handler = lambda body: {"claims": GOOD}
    debate(ingest_db)
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


def test_the_person_reads_the_positions_then_sees_who_says_what_with_the_quote(base, ingest_db):
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
        page.get_by_role("button", name="Positions", exact=True).click()
        page.get_by_role("heading", name="Positions", exact=True).wait_for()
        page.get_by_text("Aucune position pour l’instant").wait_for()
        page.locator(".embedded").get_by_text("Analyse et réglages", exact=True).click()
        page.get_by_role("button", name="Analyser les conversations restantes").click()
        page.get_by_text("Terminée").wait_for(timeout=30000)
        row = page.get_by_role("button", name="L'État doit augmenter le salaire minimum")
        row.wait_for()
        assert "1 pour · 0 nuancés · 1 contre" in row.inner_text()
        row.click()
        page.locator(".people .person").first.wait_for()
        assert page.locator(".people .person").count() == 2                                          # each person is one line…
        assert not page.get_by_text(SAYS_A, exact=False).is_visible()                                # …and the quote is behind it
        assert page.get_by_text("Contre", exact=True).is_visible() and page.get_by_text("Pour", exact=True).is_visible()
        page.locator(".people .person > summary").first.click()
        page.get_by_text(SAYS_A, exact=False).wait_for()
        assert ingest_db.execute("SELECT count(*) FROM claims").fetchone() == (2,)
        browser.close()
    assert errors == []


@pytest.mark.parametrize("section", ["Thèmes", "Positions"])
@pytest.mark.parametrize("width", [390, 1440])
def test_analysis_launch_and_progress_work_before_results_and_readiness_load(base, section, width):
    """Hold every heavy GET: launch and progress must still work, with one shared monitor."""
    errors = []
    counts = Counter()
    held = []
    submitted = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": width, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        job = page.request.get(base + "/api/analysis/status").json()["job"]

        def intercept(route):
            nonlocal job
            request = route.request
            path = urlsplit(request.url).path
            counts[request.method, path] += 1
            if path == "/api/analysis" and request.method == "POST":
                submitted.append(request.post_data_json)
                job = {**job, "state": "running", "guild": str(submitted[-1]["guild"]), "stage": "classeur", "round": 1, "rounds": 1, "of": 10, "done": 3}
                route.fulfill(json=job)
            elif path == "/api/analysis/status":
                route.fulfill(json={"job": job})
            elif request.method == "GET" and path in ("/api/analysis", "/api/positions", "/api/topics", "/api/positions/coherence"):
                held.append(route)
            else:
                route.continue_()

        page.route("**/api/**", intercept)
        page.get_by_role("navigation", name="Pages" if width == 390 else "Navigation principale", exact=True).get_by_role("button", name="Analyse", exact=True).click()
        page.get_by_role("button", name=section, exact=True).click()
        button = page.get_by_role("button", name="Analyser les conversations restantes" if section == "Positions" else "Analyser les conversations", exact=True)
        sync_api.expect(button).to_be_enabled()
        if section == "Positions":
            page.get_by_text("Analyse et réglages", exact=True).click()
            page.get_by_text("Options de lecture", exact=True).click()
            page.get_by_label("Nombre de conversations lues par étape").fill("7")
            page.get_by_label("Nombre d’étapes", exact=True).fill("2")
        button.click()
        sync_api.expect(page.get_by_role("button", name="Arrêter la lecture" if section == "Positions" else "Annuler l’analyse", exact=True)).to_be_visible()
        assert len(submitted) == 1
        if section == "Positions":
            assert submitted[0]["stages"] == ["claims"]
            assert submitted[0]["limit"] == 7 and submitted[0]["rounds"] == 2
        page.wait_for_timeout(4300)
        assert 2 <= counts["GET", "/api/analysis/status"] <= 4
        assert counts["GET", "/api/analysis"] == 1
        assert counts["GET", "/api/positions/coherence"] == 0
        result_path = "/api/positions" if section == "Positions" else "/api/topics"
        assert counts["GET", result_path] == 1
        if os.environ.get("DINDON_SHOTS"):
            folder = Path(os.environ["DINDON_SHOTS"]); folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(folder / f"analysis-launch-{width}-{section}.png"))
        job = {**job, "state": "done", "done": 10}
        sync_api.expect(page.get_by_text("Terminée", exact=True)).to_be_visible(timeout=5000)
        # Completion refreshes the results once, without waiting for the blocked first response.
        page.wait_for_timeout(100)
        assert counts["GET", result_path] == 2
        assert counts["GET", "/api/analysis"] == 2
        for route in held:
            route.abort()
        browser.close()
    assert errors == []
