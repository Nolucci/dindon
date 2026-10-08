"""Real browser checks for the redesigned navigation, pagination and inline evidence."""
import os
from pathlib import Path
import pytest
sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect
from test_ui_filters import base, PASSWORD
from test_axes import proposition, takes, ALICE_ID, BOB_ID


def test_results_navigation_pagination_and_evidence(base, ingest_db):
    for n in range(61):
        pid = proposition(ingest_db, f"Pagination proposition {n:02}", "economie", -1)
        takes(ingest_db, ALICE_ID, pid, 1)
    claim = ingest_db.execute("SELECT id FROM claims WHERE user_id = %s ORDER BY id LIMIT 1", (BOB_ID,)).fetchone()[0]
    message = ingest_db.execute("SELECT id, content FROM messages WHERE author_id = %s ORDER BY id LIMIT 1", (BOB_ID,)).fetchone()
    ingest_db.execute("INSERT INTO claim_evidence (claim_id, message_id, quote) VALUES (%s, %s, %s)", (claim, message[0], message[1]))
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + '/#/analyse/positions')
        page.fill('#password', PASSWORD)
        page.click('button[type=submit]')
        expect(page.get_by_role('heading', name='Positions', exact=True)).to_be_visible()
        page.get_by_label('Chercher une proposition ou une personne').fill('Pagination')
        expect(page.locator('.prop')).to_have_count(50)
        page.get_by_role('button', name='Suivant', exact=True).click()
        expect(page.locator('.prop')).to_have_count(11)
        expect(page.get_by_role('navigation', name='Pages des propositions')).to_contain_text('51–61 sur 61')
        page.get_by_label('Chercher une proposition ou une personne').fill('Pagination proposition 60')
        expect(page.locator('.prop')).to_have_count(1)
        expect(page.get_by_role('button', name='Précédent', exact=True)).to_have_count(0)
        page.get_by_label('Filtrer par thème').select_option('0')
        expect(page.locator('.prop')).to_have_count(1)
        page.get_by_role('button', name='Contradictions', exact=True).click()
        page.wait_for_selector('.person')
        assert not page.locator('.said').count()
        page.get_by_role('button', name='Voir les citations', exact=True).click()
        expect(page.locator('.said blockquote').first).to_contain_text(message[1][:280])
        assert page.url.endswith('/#/analyse/coherence')
        page.go_back()
        expect(page.get_by_role('heading', name='Positions', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role('heading', name='Positions', exact=True)).to_be_visible()
        # All consulting/admin sections at desktop and phone widths, using actual seeded data.
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            for route in ('carte', 'analyse/themes', 'analyse/positions', 'analyse/coherence', 'debats', 'systeme/status', 'systeme/automation', 'systeme/discord', 'systeme/performance', 'systeme/maintenance', 'vie-privee'):
                page.goto(base + '/#/' + route)
                expect(page.locator('.navbar')).to_have_count(1)
                page.wait_for_timeout(400)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), route
                if os.environ.get('DINDON_SHOTS'):
                    folder = Path(os.environ['DINDON_SHOTS']); folder.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(folder / f'{width}-{route.replace("/", "-")}.png'))
        browser.close()
    assert not errors
