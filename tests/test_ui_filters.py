"""The search and the filters of every list of the interface, in a real browser, with the keyboard shortcut (« / »). Invented data.
Optional: skipped without Playwright or the built interface."""
import dataclasses
import socket
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

from dindon.analysis.conversations import build_conversations  # noqa: E402
from dindon.api.main import create_app  # noqa: E402
from gateway_fixtures import ALICE, BOB, CAROL  # noqa: E402
from synthetic import settings_for  # noqa: E402
from test_analysis import NOW, Talk, ingest  # noqa: E402
from test_axes import GUILD_ID, a_socialist_and_a_liar, proposition, takes  # noqa: E402
from test_extraction import ALICE_ID, BOB_ID  # noqa: E402

CAROL_ID = int(CAROL["id"])
WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def seed(db):
    """Two conversations, two themes, four propositions, a socialist who is and one who is not, a few people in the privacy register."""
    a_socialist_and_a_liar(db)
    talk = Talk(NOW - timedelta(hours=30))
    talk.next_id += 1000
    ingest(db, [talk.say("la constitution est dépassée, il faut une nouvelle république", CAROL), talk.say("oui, plus de pouvoir au parlement serait sain", ALICE)])
    build_conversations(db, GUILD_ID, now=NOW)
    first, second = [r[0] for r in db.execute("SELECT id FROM conversations ORDER BY started_at").fetchall()][:2]
    run = db.execute("INSERT INTO topic_runs (guild_id, method, model, parameters) VALUES (%s, 'test', 'x', '{}'::jsonb) RETURNING id", (GUILD_ID,)).fetchone()[0]
    topics = {}
    for label, status, conv in (("Économie et salaires", "proposed", first), ("Institutions et constitution", "validated", second), ("Écologie et énergie", "proposed", None)):
        topics[label] = db.execute("INSERT INTO topics (guild_id, label, origin, status, keywords) VALUES (%s, %s, 'discovered', %s, %s) RETURNING id",
                                   (GUILD_ID, label, status, ["mot", label.split()[0].lower()])).fetchone()[0]
        if conv:
            db.execute("INSERT INTO topic_assignments (run_id, conversation_id, topic_id, similarity) VALUES (%s, %s, %s, 0.9)", (run, conv, topics[label]))
    p1 = proposition(db, "Taxer les très hauts revenus", "economie", -0.5)
    p2 = proposition(db, "Écrire une nouvelle constitution", "representation", -0.5)
    takes(db, ALICE_ID, p1, 1, conversation=first)
    takes(db, BOB_ID, p1, -1, conversation=first)
    takes(db, CAROL_ID, p2, 1, conversation=second)
    takes(db, ALICE_ID, p2, -1, conversation=second)
    for uid, status in ((ALICE_ID, "stopped"), (BOB_ID, "erased"), (CAROL_ID, "stopped"), (111111111111111111, "stopped")):
        db.execute("INSERT INTO privacy_subjects (user_id, status, source) VALUES (%s, %s, 'interface')", (uid, status))
    for n in range(5):
        db.execute("INSERT INTO privacy_log (user_id, action, source, detail) VALUES (%s, %s, 'interface', '{}'::jsonb)", (ALICE_ID, "stop" if n % 2 else "erase"))
    db.execute("SELECT refresh_person_axis_scores(%s)", (GUILD_ID,))


@pytest.fixture
def base(ingest_url, ingest_db, tmp_path):
    import uvicorn

    seed(ingest_db)
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


def open_page(browser, base, name):
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(base)
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_selector("nav", timeout=20000)
    if name in ("Thèmes", "Positions", "Contradictions"):
        page.get_by_role("button", name="Analyse", exact=True).click()
        if name != "Thèmes":
            page.get_by_role("button", name=name, exact=True).click()
    elif name != "Carte":
        page.get_by_role("button", name=name, exact=True).click()
    return page


def test_every_list_can_be_searched_and_filtered(base):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])

        # --- Thèmes: words (accents ignored), state, and the shortcut
        page = open_page(browser, base, "Thèmes")
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        expect(page.get_by_role("heading", name="Analyse", exact=True)).to_be_visible()
        expect(page.get_by_role("navigation", name="Sections de l’analyse")).to_be_visible()
        assert page.locator(".navItems .navItem").filter(has_text="Analyse").count() == 1
        page.wait_for_selector(".topic")
        assert page.locator(".topic").count() == 3
        page.keyboard.press("/")                                                                    # the shortcut puts the cursor in the box
        page.keyboard.type("ecolo")
        expect(page.locator(".topic")).to_have_count(1)
        assert "Écologie et énergie" in page.locator(".topic").inner_text()
        page.get_by_role("button", name="Effacer les filtres").click()
        page.get_by_label("Filtrer par état").select_option("validated")
        expect(page.locator(".topic")).to_have_count(1)
        assert "Institutions" in page.locator(".topic").inner_text()
        page.get_by_label("Filtrer par état").select_option("all")
        page.get_by_label("Chercher un thème").fill("zzzz")
        page.get_by_text("Aucun thème ne correspond").wait_for()

        # --- Positions: a word of the proposition, a person's name, a theme, a position
        page.get_by_role("button", name="Positions", exact=True).click()
        page.wait_for_selector(".prop")
        everything = page.locator(".prop").count()
        assert everything >= 7                                                                      # the five of the socialists, and two more
        page.get_by_label("Chercher une proposition ou une personne").fill("constitution")
        expect(page.locator(".prop")).to_have_count(1)
        assert "Écrire une nouvelle constitution" in page.locator(".prop").inner_text()
        page.get_by_label("Chercher une proposition ou une personne").fill("bobby")                 # a person: the propositions where Bobby takes a position
        expect(page.get_by_text("Écrire une nouvelle constitution")).to_have_count(0)               # Bobby takes no position on it: it goes
        assert 0 < page.locator(".prop").count() < everything and page.get_by_text("Taxer les très hauts revenus").count() == 1
        page.get_by_role("button", name="Effacer les filtres").click()
        page.get_by_label("Filtrer par thème").select_option(label="Institutions et constitution (1)")
        expect(page.locator(".prop")).to_have_count(1)
        page.get_by_label("Filtrer par thème").select_option("")
        page.get_by_label("Chercher une proposition ou une personne").fill("zzzz")
        page.get_by_text("Aucune proposition ne correspond").wait_for()
        page.get_by_label("Chercher une proposition ou une personne").fill("")
        page.get_by_label("Trier").select_option("divided")                                         # the most divided first: where there are a « pour » and a « contre »
        expect(page.locator(".prop")).to_have_count(everything)
        assert page.locator(".prop >> nth=0 >> .nums").inner_text().split("·")[2].strip().startswith(("1", "5"))

        # --- Cohérence: the verdict, the name, the role
        page.get_by_role("button", name="Contradictions", exact=True).click()
        page.wait_for_selector(".person")
        assert page.locator(".person").count() == 1                                                 # the contradictions by default
        page.get_by_label("Filtrer par verdict").select_option("all")
        assert page.locator(".person").count() == 2
        page.get_by_label("Chercher une personne ou un rôle").fill("socialiste")                    # a role
        assert page.locator(".person").count() == 2
        page.get_by_label("Chercher une personne ou un rôle").fill("alice")
        expect(page.locator(".person")).to_have_count(1)
        page.get_by_label("Chercher une personne ou un rôle").fill("")
        page.get_by_label("Filtrer par rôle").select_option("Socialiste")
        assert page.locator(".person").count() == 2
        page.get_by_label("Filtrer par verdict").select_option("concordant")
        assert page.locator(".person").count() == 1
        page.get_by_role("button", name="Effacer les filtres").click()
        assert page.locator(".person").count() == 1

        # --- Vie privée: the register and the log
        page.get_by_role("button", name="Vie privée", exact=True).click()
        page.get_by_text("Personnes non enregistrées (4)").wait_for()
        page.get_by_label("Filtrer le registre par état").select_option("erased")
        page.get_by_text("Personnes non enregistrées (1 sur 4)").wait_for()
        page.get_by_label("Filtrer le registre par état").select_option("all")
        page.get_by_label("Chercher dans le registre").fill("111111")
        page.get_by_text("Personnes non enregistrées (1 sur 4)").wait_for()
        page.get_by_label("Chercher dans le registre").fill("")
        page.get_by_label("Filtrer le journal par acte").select_option("stop")
        page.get_by_text("2 sur 5").wait_for()

        # --- Système: the points to look at
        page.get_by_role("button", name="Système", exact=True).click()
        page.wait_for_selector("h1:has-text('Système')")
        if page.get_by_label("Filtrer les points à voir").count():
            page.get_by_label("Filtrer les points à voir").select_option("error")
        browser.close()
    assert errors == []


def test_the_map_keeps_its_search_and_filters(base):
    """The map had them first: the person search (accents ignored), the period, the kinds of links."""
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = open_page(browser, base, "Carte")
        page.fill("input[type=search]", "bo")
        page.wait_for_selector(".search li button")
        assert "Bobby" in page.locator(".search li button").first.inner_text()
        page.get_by_role("button", name="Filtres", exact=True).click()
        assert page.get_by_role("button", name="Réponses").count() == 1 and page.get_by_role("group", name="Période").count() == 1
        browser.close()


def test_bulk_topic_review_and_contradiction_evidence(base, ingest_db):
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = open_page(browser, base, "Thèmes")
        page.get_by_label("Sélectionner Économie et salaires").check()
        page.get_by_label("Sélectionner Écologie et énergie").check()
        page.get_by_role("button", name="Valider la sélection").click()
        expect(page.locator(".topic.isValidated")).to_have_count(3)
        assert ingest_db.execute("SELECT count(*) FROM topics WHERE status = 'validated'").fetchone()[0] == 3

        page.get_by_role("button", name="Contradictions", exact=True).click()
        page.get_by_role("button", name="Voir les citations").first.click()
        expect(page.locator(".said").first).to_be_visible()
        assert page.get_by_role("complementary", name="Fiche de la personne").count() == 0
        page.get_by_role("button", name="Analyse", exact=True).click()
        expect(page.get_by_role("heading", name="Contradictions", exact=True)).to_be_visible()
        browser.close()


def test_a_person_reviews_the_axes_that_the_ai_proposed_for_a_proposition(base, ingest_db):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = open_page(browser, base, "Positions")
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.wait_for_selector(".prop")
        page.get_by_label("Chercher une proposition ou une personne").fill("Taxer les très hauts revenus")
        expect(page.locator(".prop")).to_have_count(1)
        page.locator(".prop .row").click()
        page.get_by_text("Réviser la proposition et ses axes", exact=True).click()
        links = page.get_by_role("region", name="Axes de cette proposition")
        links.wait_for()
        assert "Propriété des moyens de production" in links.inner_text() and "proposé par l’IA" in links.inner_text()
        assert links.get_by_role("button", name="Valider ces liens").is_visible()              # nothing was reviewed yet
        links.get_by_role("button", name="Inverser").click()
        expect(links.get_by_text("Privé")).to_be_visible()                                   # the direction was turned: « vers Privé »
        expect(links.get_by_text("validé", exact=True)).to_be_visible()                      # and what a person decides is validated
        assert not links.get_by_role("button", name="Valider ces liens").is_visible()
        row = ingest_db.execute("SELECT pa.loading::float8, pa.is_validated FROM proposition_axis pa JOIN propositions p ON p.id = pa.proposition_id WHERE p.text = 'Taxer les très hauts revenus'").fetchone()
        assert row == (0.5, True)                                                            # what the person decided is what is kept
        links.get_by_label("Ajouter un axe").select_option("controle")
        links.get_by_role("button", name="Ajouter").click()
        expect(links.locator(".linkName", has_text="Contrôle de l'économie")).to_be_visible()
        links.get_by_role("button", name="Retirer").first.click()
        expect(links.locator(".link")).to_have_count(1)
        assert ingest_db.execute("SELECT count(*) FROM proposition_axis pa JOIN propositions p ON p.id = pa.proposition_id WHERE p.text = 'Taxer les très hauts revenus'").fetchone() == (1,)
        page.locator(".embedded").get_by_text("Analyse et réglages", exact=True).click()
        page.get_by_text("Options de lecture", exact=True).click()
        page.get_by_label("Ne compter dans les scores que les liens validés").check()
        for _ in range(30):                                                                  # (the request is on its way)
            if ingest_db.execute("SELECT value FROM scoring_settings WHERE key = 'only_validated_loadings'").fetchone()[0] == 1:
                break
            page.wait_for_timeout(100)
        assert ingest_db.execute("SELECT value FROM scoring_settings WHERE key = 'only_validated_loadings'").fetchone()[0] == 1
        browser.close()
    assert errors == []
