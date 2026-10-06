"""The performance panel of the page Système, in a real browser: a profile, a custom setting, saved for the bot and the AI. Optional: skipped without Playwright or the built interface."""
import dataclasses
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

from dindon import performance  # noqa: E402
from dindon.api.main import create_app  # noqa: E402
from synthetic import settings_for  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
PASSWORD = "correct horse"
pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


@pytest.fixture
def base(ingest_url, ingest_db, tmp_path):
    import uvicorn

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


def test_the_person_limits_the_machine_from_the_page_systeme(base, ingest_db):
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        page.get_by_role("button", name="Système", exact=True).click()
        panel = page.get_by_role("region", name="Performance")
        panel.wait_for()
        expect(panel.get_by_role("radio", name="Plein régime")).to_have_attribute("aria-checked", "true")           # the default: as before
        save = panel.get_by_role("button", name="Enregistrer")
        assert save.is_disabled()

        panel.get_by_role("radio", name="Économe").click()
        assert save.is_enabled()
        expect(panel.get_by_text("environ 4 fois plus lente")).to_be_visible()                                       # said in words what it costs
        save.click()
        panel.get_by_text("Enregistré.").wait_for()
        assert performance.load(ingest_db)["preset"] == "saver" and performance.load(ingest_db)["ai_max_load"] == 25

        panel.get_by_label("Part du temps où l’IA travaille").fill("50")                                           # a custom value: the profile becomes « Personnalisé »
        expect(panel.get_by_role("radio", name="Personnalisé")).to_have_attribute("aria-checked", "true")
        panel.get_by_role("button", name="Enregistrer").click()
        panel.get_by_text("Enregistré.").wait_for()
        assert performance.load(ingest_db)["ai_max_load"] == 50

        page.reload()                                                                                               # what was saved is what is shown again
        page.get_by_role("button", name="Système", exact=True).click()
        expect(page.get_by_role("region", name="Performance").get_by_label("Part du temps où l’IA travaille")).to_have_value("50")
        browser.close()
    assert errors == []


def test_the_discord_map_names_follow_the_chosen_person_limit(base, ingest_db):
    from dindon import discord_map

    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        page.get_by_role("button", name="Système", exact=True).click()
        panel = page.get_by_role("region", name="Carte sur Discord")
        people = panel.get_by_role("slider", name="Personnes sur l’image")
        names = panel.get_by_role("slider", name="Noms affichés")
        people.fill("350")
        expect(names).to_have_attribute("max", "350")
        names.fill("350")
        panel.get_by_role("button", name="Enregistrer").click()
        panel.get_by_text("Enregistré.").wait_for()
        assert discord_map.load(ingest_db)["max_people"] == discord_map.load(ingest_db)["names"] == 350
        people.fill("120")
        expect(names).to_have_value("120")
        expect(names).to_have_attribute("max", "120")
        browser.close()


def test_the_person_switches_on_the_automatic_reading_and_the_positions_ask_for_an_acknowledgement(base, ingest_db):
    from dindon import automation

    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(base)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_selector("nav", timeout=20000)
        page.get_by_role("button", name="Système", exact=True).click()
        panel = page.get_by_role("region", name="Lecture automatique")
        panel.wait_for()
        assert panel.get_by_text("Éteinte").is_visible() and panel.get_by_role("button", name="Enregistrer").is_disabled()
        panel.get_by_label("Activer la lecture automatique").check()
        panel.get_by_label("Fréquence de la lecture automatique").select_option("60")
        panel.get_by_label("Lire à partir de").select_option("22")
        panel.get_by_label("Lire jusqu’à").select_option("6")
        panel.get_by_text("Positions des personnes").click()                                      # the positions look at what people think
        save = panel.get_by_role("button", name="Enregistrer")
        assert panel.get_by_label("Les personnes sont informées").is_visible() and save.is_disabled()      # not without saying that the people are informed
        panel.get_by_label("Les personnes sont informées").check()
        assert save.is_enabled()
        save.click()
        panel.get_by_text("Enregistré.").wait_for()
        saved = automation.load(ingest_db)
        assert (saved["enabled"], saved["positions"], saved["positions_acknowledged"], saved["interval_minutes"], saved["window_from"], saved["window_to"]) == (True, True, True, 60, 22, 6)
        expect(panel.get_by_text("Activée", exact=True)).to_be_visible()
        panel.get_by_role("button", name="Lancer un cycle maintenant").click()
        panel.get_by_text("Un cycle va démarrer").wait_for()
        assert automation.state(ingest_db)["run_requested_at"]
        browser.close()
    assert errors == []
