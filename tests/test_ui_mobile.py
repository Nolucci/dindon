"""The interface on a phone (390 px wide), in a real browser: the pages are one tap away at the bottom, the map has buttons for a finger, and the card of a person is a sheet at the bottom
that leaves the map visible. Optional: skipped when Playwright or the built interface (make web) is missing."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from test_ui_servers import PASSWORD, WEB, running  # noqa: E402

pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def phone(playwright, base, width=390, height=800):
    browser = playwright.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": width, "height": height}, has_touch=True, is_mobile=True)
    page.goto(base)
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    return browser, page


def test_on_a_phone_the_pages_are_at_the_bottom_and_the_map_has_buttons_for_a_finger(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = phone(p, base)
        page.wait_for_selector("footer span:has-text('personnes')", timeout=20000)
        bar = page.locator(".tabBar")
        assert bar.is_visible() and [b.inner_text().strip() for b in bar.locator("button").all()] == ["Carte", "Débats", "Analyse", "Système", "Plus"]
        box = bar.bounding_box()
        assert box["y"] + box["height"] >= 799 and all(b.bounding_box()["height"] >= 44 for b in bar.locator("button").all())     # at the bottom, big enough for a thumb
        for name in ("Zoomer", "Dézoomer", "Recentrer la carte"):
            button = page.get_by_role("button", name=name, exact=True)
            assert button.is_visible() and button.bounding_box()["width"] >= 44
        page.get_by_role("button", name="Zoomer", exact=True).click()
        page.locator(".tabBar button", has_text="Système").click()
        page.get_by_role("button", name="Discord", exact=True).click()
        page.wait_for_selector("text=Fiche sur Discord")
        page.locator(".tabBar button", has_text="Carte").click()
        page.screenshot(path=str(tmp_path / "phone.png"))
        browser.close()


def test_on_a_computer_there_is_no_bottom_bar_and_no_zoom_buttons(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = phone(p, base, 1440, 900)
        page.wait_for_selector("footer span:has-text('personnes')", timeout=20000)
        assert not page.locator(".tabBar").is_visible() and not page.get_by_role("button", name="Zoomer", exact=True).is_visible()
        browser.close()
