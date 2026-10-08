"""The page Débats, in a real browser: the list, the detail of a debate, the checked claims with their links. The Content-Security-Policy stays on.

Optional: skipped when Playwright or the built interface (make web) is missing."""
import dataclasses
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

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
        summary = page.get_by_label("Résumé").inner_text()
        assert "en cours" in summary and "dans un fil" in summary and "affirmations vérifiées" in summary and "fin si personne n’écrit pendant 24 heures" in summary
        assert "période" not in summary and "vote" not in summary
        table = page.get_by_label("Participants").inner_text()
        assert "Bobby" in table and "✅ Pour" in table and "❌ Contre" in table and "le même critère pour tout le monde" in table
        claims = page.get_by_label("Affirmations examinées")
        text = claims.inner_text()
        assert "contredite" in text and "non vérifiable" in text and EVIDENCE.quote in text and "insee.fr" in text
        link = claims.get_by_role("link", name="insee.fr")
        assert link.get_attribute("href") == EVIDENCE.url and "noopener" in link.get_attribute("rel") and link.get_attribute("target") == "_blank"
        page.get_by_text("Répartition par position", exact=True).click()
        assert page.get_by_label("Parité par position").inner_text().count("✅ Pour") == 1
        page.get_by_role("button", name="Le pouvoir doit-il être réparti").click()
        page.get_by_label("Résumé").get_by_text("Question posée par Dindon").wait_for()
        summary = page.get_by_label("Résumé").inner_text()
        assert "axe « Structure de l’État »" in summary.replace("'", "’") and "🔵 Fédéral" in summary and "🟠 Unitaire" in summary and "Pour" not in summary
        answered = page.get_by_label("Réponses de Dindon").inner_text()
        assert all(words in answered for words in ("jugée fausse", "d'environ 7 %", "✅ Valide 0 · ❌ Invalide 1", "sans source")), answered
        browser.close()
    assert errors == []
