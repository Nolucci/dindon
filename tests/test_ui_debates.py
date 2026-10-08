"""The page Débats, in a real browser: the list, the detail of a debate, the checked claims with their links. The Content-Security-Policy stays on.

Optional: skipped when Playwright or the built interface (make web) is missing."""
import dataclasses
import os
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from test_ui_agencement import assert_fits
from dindon.api.main import create_app  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_debate_checks import EVIDENCE  # noqa: E402
from test_debate_bot import BOB_ID  # noqa: E402
from test_debates_api import prepared  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(ingest_url, tmp_path):
    import uvicorn

    world, _ = prepared(ingest_url, tmp_path)
    world.command(BOB_ID, topic="", axis="structure")                                                      # a second debate, opened from an axis: its answers are the two poles
    from dindon.db import connect
    from dindon.debate import store

    with connect(ingest_url) as conn:                                                                      # and Dindon answered a claim in it, which one person found invalid
        conn.autocommit = True
        second = store.active(conn)[-1]
        answer_id = conn.execute("INSERT INTO debate_answers (debate_id, message_id, author_id, claim, said, query, verdict, answer) VALUES (%s, 5, %s, %s, 'le chômage est à 12 %%', 'chômage', 'false', %s) RETURNING id",
                                 (second.id, BOB_ID, "Le chômage est à 12 % en France", "Le taux de chômage en France est d'environ 7 %.")).fetchone()[0]
        conn.execute("INSERT INTO debate_answer_votes (answer_id, user_id, choice) VALUES (%s, %s, 'invalid')", (answer_id, BOB_ID + 1))
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


def test_the_person_in_charge_reads_a_debate_with_its_checked_claims_and_their_links(base):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        page.get_by_role("button", name="Débats").click()
        page.get_by_role("heading", name="Débats", exact=True).wait_for()
        assert page.get_by_label("État de la vérification").count() == 0
        page.get_by_role("button", name="Faut-il réduire le temps de travail").click()
        page.get_by_label("Participants").wait_for()
        page.get_by_text("Détails du débat", exact=True).click()
        summary = page.get_by_label("Informations du débat", exact=True).inner_text()
        assert "en cours" in summary and "dans un fil" in summary and "affirmations vérifiées" in summary and "fin si personne n’écrit pendant 24 heures" in summary
        assert "période" not in summary and "vote" not in summary
        page.locator(".participant > summary").first.click()
        page.get_by_label("Participants").get_by_text("Message phare", exact=True).first.click()
        page.get_by_role("button", name="Comment est choisi le message phare ?", exact=True).click()
        table = page.get_by_label("Participants").inner_text()
        assert "Bobby" in table and "✅ Pour" in table and "❌ Contre" in table and "Le même critère pour tout le monde" in table
        page.keyboard.press("Escape")
        claims = page.get_by_label("Affirmations examinées")
        text = claims.inner_text()
        assert "contredite" in text and "non vérifiable" in text and EVIDENCE.quote in text and "insee.fr" in text
        link = claims.get_by_role("link", name="insee.fr")
        assert link.get_attribute("href") == EVIDENCE.url and "noopener" in link.get_attribute("rel") and link.get_attribute("target") == "_blank"
        page.get_by_text("Répartition par position", exact=True).click()
        assert page.get_by_label("Parité par position").inner_text().count("✅ Pour") == 1
        for width in (1920, 1440, 1024, 720, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_timeout(400)
            assert_fits(page, ("debate participants and claims", width))
            if os.environ.get("DINDON_SHOTS"):
                folder = Path(os.environ["DINDON_SHOTS"]); folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(folder / f"{width}-debates-participants.png"))
        page.get_by_role("button", name="Tous les débats").click()
        page.get_by_role("button", name="Le pouvoir doit-il être réparti").click()
        page.get_by_label("Informations du débat", exact=True).locator("p").filter(has_text="Structure de l").first.wait_for()
        summary = page.get_by_label("Informations du débat", exact=True).inner_text()
        assert "Structure de l’État" in summary.replace("'", "’") and "Pour" not in summary
        assert page.get_by_label("Informations du débat", exact=True).locator(".bars li").count() == 0
        answered = page.get_by_label("Réponses de Dindon", exact=True).inner_text()
        assert all(words in answered for words in ("jugée fausse", "d'environ 7 %", "✅ Valide 0 · ❌ Invalide 1")), answered
        page.get_by_role("button", name="À propos des réponses de Dindon", exact=True).click()
        assert "sans source" in page.locator("[popover]:popover-open").inner_text()
        page.keyboard.press("Escape")
        for width in (1920, 1440, 1024, 720, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_timeout(400)
            assert_fits(page, ("debate detail", width))
            if os.environ.get("DINDON_SHOTS"):
                folder = Path(os.environ["DINDON_SHOTS"]); folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(folder / f"{width}-debates-review.png"))
        browser.close()
    assert errors == []


def test_computers_refresh_and_the_summary_updates_every_twenty_minutes(base, ingest_db):
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.clock.install()
        fleet = {'computers': [{'url': 'http://100.100.1.2:11434', 'local': False, 'active': 0, 'online': True, 'has_model': True, 'calls': 4, 'errors': 0, 'average': 2, 'running_for': 8}], 'fresh': True, 'age_seconds': 0}
        page.route('**/api/debates/computers', lambda route: route.fulfill(json=fleet))
        page.goto(base + '/#/debats')
        page.fill('#password', PASSWORD); page.click('button[type=submit]')
        fleet_panel = page.get_by_role('region', name='Ordinateurs des débats')
        sync_api.expect(fleet_panel).to_contain_text('Disponible')
        fleet['computers'][0]['active'] = 1
        page.clock.fast_forward(5000)
        sync_api.expect(fleet_panel).to_contain_text('En cours')
        fleet['fresh'] = False
        page.clock.fast_forward(5000)
        sync_api.expect(fleet_panel).to_contain_text('État ancien')
        page.get_by_role('button', name='Faut-il réduire le temps de travail').click()
        digest = page.get_by_role('complementary', name='Résumé actuel du débat')
        sync_api.expect(digest).to_contain_text('✅ Pour')
        middle = page.get_by_label('Informations du débat', exact=True).bounding_box()
        right = digest.bounding_box()
        assert middle['x'] + middle['width'] <= right['x']
        if os.environ.get('DINDON_SHOTS'):
            folder = Path(os.environ['DINDON_SHOTS']); folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(folder / '1440-debates-overview.png'))
        page.locator('.participant > summary').first.click()
        sync_api.expect(page.get_by_label('Fiche de la personne')).to_be_visible()
        debate_id = ingest_db.execute("SELECT id FROM debates WHERE topic LIKE 'Faut-il réduire%' ORDER BY id LIMIT 1").fetchone()[0]
        ingest_db.execute("UPDATE debate_positions SET position = 'against' WHERE debate_id = %s AND user_id = %s", (debate_id, BOB_ID))
        page.clock.fast_forward(20000)
        sync_api.expect(page.locator('.participant > summary').first).to_contain_text('Contre')
        sync_api.expect(page.locator('.participant[open]')).to_have_count(1)
        sync_api.expect(digest).to_contain_text('✅ Pour')
        page.clock.fast_forward(20 * 60 * 1000)
        sync_api.expect(digest).not_to_contain_text('✅ Pour')
        sync_api.expect(digest.locator('.bars')).to_contain_text('Contre2')
        page.get_by_role('button', name='Tous les débats').click()
        sync_api.expect(digest).to_have_count(0)
        browser.close()
