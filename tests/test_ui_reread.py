"""The page Relecture, in a real browser: what there is to reread, the button, and what the reread corrected with its « Annuler ». Optional: skipped without Playwright or the built interface."""
import dataclasses
import os
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from dindon.api.main import create_app  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_ui_agencement import assert_fits
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
    claim, author = ingest_db.execute("SELECT id, user_id FROM claims ORDER BY id LIMIT 1").fetchone()
    ingest_db.execute("INSERT INTO claim_rereads (run_id, claim_id, verdict, changes, reason, certainty, context, people) VALUES (%s, %s, 'corrected', '{\"stance\": [1, -1]}'::jsonb, "
                      "'il contredit ce qui précède', 88, 'M1 | U1 | Il faut augmenter le SMIC.' || chr(10) || 'M2 | U2 | Non, c''est faux. | EVIDENCE', %s::jsonb)", (run, claim, '{"U1": "1", "U2": "%d"}' % author))
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
        assert "corrigées" in last.inner_text().lower()
        last.get_by_text("Contrôle des scores", exact=True).click()
        assert "aucun écart" in last.inner_text()
        item = page.locator(".changes li").first
        item.wait_for()
        assert "Position" in item.inner_text() and "Pour" in item.inner_text() and "Contre" in item.inner_text()
        assert not item.get_by_text("il contredit ce qui précède").is_visible()
        item.get_by_text("Citations et motif", exact=True).click()
        assert "il contredit ce qui précède" in item.inner_text()
        item.get_by_text("Voir tout le contexte lu", exact=True).click()
        assert "EVIDENCE" in item.locator("pre").inner_text() and "Il faut augmenter le SMIC." in item.locator("pre").inner_text()
        assert "(la personne évaluée)" in item.inner_text()
        item.get_by_role("button", name="Annuler cette correction").click()
        item.get_by_text("annulée", exact=True).wait_for()
        browser.close()
    assert errors == []


def test_reread_layout_and_help_fit_with_long_results(base, ingest_db):
    long_text = 'OrganisationCollectiveEtConstitution' * 8
    ingest_db.execute("UPDATE propositions SET text = %s", (long_text,))
    ingest_db.execute("UPDATE users SET global_name = %s", (long_text,))
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto(base + '/#/analyse/reread')
        page.fill('#password', PASSWORD); page.click('button[type=submit]')
        page.locator('.changes li').first.wait_for()
        for width in (1440, 1024, 720, 390, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            page.wait_for_timeout(400)
            assert_fits(page, ('reread', width))
            assert page.locator('.card').first.evaluate('el => parseFloat(getComputedStyle(el).paddingLeft)') >= 12
            help_button = page.get_by_role('button', name='À propos de la relecture', exact=True)
            help_button.click()
            bubble = page.locator('[popover]:popover-open')
            sync_api.expect(bubble).to_be_visible()
            box = bubble.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert 'validées ou rejetées' in bubble.inner_text()
            page.keyboard.press('Escape')
            sync_api.expect(bubble).to_have_count(0)
            help_button.focus(); page.keyboard.press('Enter')
            sync_api.expect(page.locator('[popover]:popover-open')).to_be_visible()
            page.keyboard.press('Escape')
            if os.environ.get('DINDON_SHOTS'):
                folder = Path(os.environ['DINDON_SHOTS']); folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(folder / f'{width}-reread-review.png'))
        browser.close()


def test_the_live_page_is_a_page_of_its_own_in_the_analysis(base):
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
        page.get_by_role("button", name="Temps réel", exact=True).click()
        page.get_by_role("heading", name="Temps réel", exact=True).wait_for()
        task = page.locator("section[aria-label='Tâche en cours']")
        task.get_by_text("Aucune analyse ni relecture en cours").wait_for()
        machines = page.locator("section[aria-label='Répartition entre les ordinateurs']")
        machines.get_by_text("Un seul ordinateur travaille").wait_for()
        assert page.url.endswith("/live")
        browser.close()
    assert errors == []
