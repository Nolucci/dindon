"""The page Relecture, in a real browser: what there is to reread, the button, and what the reread corrected with its « Annuler ». Optional: skipped without Playwright or the built interface."""
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
    guild = ingest_db.execute("SELECT guild_id FROM claims LIMIT 1").fetchone()[0]
    run = ingest_db.execute("INSERT INTO reread_runs (guild_id, state, finished_at, model, version, counts) VALUES (%s, 'done', now(), 'qwen3:14b', 'reread-1', "
                            "'{\"confirmed\": 3, \"corrected\": 1, \"stance_changed\": 1, \"audit\": {\"checked\": 8, \"different\": 0}}'::jsonb) RETURNING id", (guild,)).fetchone()[0]
    claim = ingest_db.execute("SELECT id FROM claims ORDER BY id LIMIT 1").fetchone()[0]
    ingest_db.execute("INSERT INTO claim_rereads (run_id, claim_id, verdict, changes, reason, certainty) VALUES (%s, %s, 'corrected', '{\"stance\": [1, -1]}'::jsonb, 'il contredit ce qui précède', 88)", (run, claim))
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


def test_the_page_shows_what_there_is_to_reread_the_last_reread_and_its_corrections_and_undoes_one(base):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        page.get_by_role("button", name="Analyse", exact=True).click()
        page.get_by_role("button", name="Relecture", exact=True).click()
        page.get_by_role("heading", name="Relecture", exact=True).wait_for()
        page.get_by_role("button", name="Lancer la relecture").wait_for()
        assert "à relire" in page.locator("section[aria-label='Lancer une relecture']").inner_text()
        last = page.locator("section[aria-label='Dernière relecture']")
        last.wait_for()
        assert "1 corrigées" in last.inner_text().replace("\n", " ") or "corrigées" in last.inner_text()
        assert "aucun écart" in last.inner_text()
        item = page.locator(".changes li").first
        item.wait_for()
        assert "Position" in item.inner_text() and "il contredit ce qui précède" in item.inner_text()
        item.get_by_role("button", name="Annuler cette correction").click()
        page.get_by_text("annulée").first.wait_for()
        browser.close()
    assert errors == []
