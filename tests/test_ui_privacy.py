"""The page Vie privée, in a real browser: find a person, stop, erase (two clicks), see the register. The Content-Security-Policy stays on.

Optional: skipped when Playwright or the built interface (make web) is missing."""
import dataclasses
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.api.main import create_app  # noqa: E402
from gateway_fixtures import CAROL  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_privacy import talk  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(ingest_url, ingest_db, tmp_path):
    import uvicorn

    talk(ingest_url)
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


def test_the_person_in_charge_erases_someone_in_two_clicks(base, ingest_db):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        page.get_by_role("button", name="Vie privée").click()
        page.get_by_role("heading", name="Vie privée").wait_for()
        page.get_by_text("Personne n’a demandé").wait_for()

        page.fill("#privacy-q", "carol")
        page.get_by_role("button", name="Chercher").click()
        page.get_by_role("button", name="carol").click()
        erase = page.get_by_role("button", name="Ne plus enregistrer et effacer")
        erase.click()
        assert ingest_db.execute("SELECT count(*) FROM messages WHERE author_id = %s", (int(CAROL["id"]),)).fetchone()[0] == 1   # one click: nothing yet
        page.get_by_role("button", name="Confirmer : effacer pour toujours").click()
        page.get_by_text("Effacé : 1 messages").wait_for()
        page.get_by_text("Personnes non enregistrées (1)").wait_for()
        assert ingest_db.execute("SELECT count(*) FROM messages WHERE author_id = %s", (int(CAROL["id"]),)).fetchone()[0] == 0
        browser.close()
    assert errors == []
