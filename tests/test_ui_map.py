"""The map in a real browser (Chromium through Playwright): a name can be hovered and clicked like its point.

Optional: skipped when Playwright or the built interface (make web) is missing. The map is a canvas, so the test asks the map where it
drew each name (`__map.labelBoxes`) and moves the real mouse there; how the highlight looks is checked on screenshots, not here.
"""
import os
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from test_ui_servers import WEB, open_page, running  # noqa: E402

pytestmark = pytest.mark.skipif(not (WEB / "index.html").exists(), reason="the interface is not built (make web)")


def settled_boxes(page, quiet=1.0, timeout=30):
    """The boxes of the names once they have not moved for `quiet` seconds (the layout of the map keeps moving the points for a while, longer on a busy machine)."""
    def read():
        return page.evaluate("document.querySelector('.canvas').__map.labelBoxes")

    last, since, deadline = read(), time.monotonic(), time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        now = read()
        if now != last:
            last, since = now, time.monotonic()
        elif time.monotonic() - since >= quiet:
            return now
    return last


def test_hovering_or_clicking_a_name_acts_on_its_person(ingest_db, ingest_url, tmp_path):
    with running(ingest_db, ingest_url, tmp_path, second=False) as base, sync_api.sync_playwright() as p:
        browser, page = open_page(p, base)
        page.wait_for_selector("footer span:has-text('2 personnes')", timeout=20000)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not page.evaluate("document.querySelector('.canvas').__map.labelBoxes.length"):
            time.sleep(0.2)
        boxes = settled_boxes(page)                                               # the points settle for a few seconds, the names with them
        assert len(boxes) == 2, boxes
        canvas = page.locator(".canvas").bounding_box()
        box = boxes[0]
        x, y = canvas["x"] + (box["left"] + box["right"]) / 2 + (box["right"] - box["left"]) / 4, canvas["y"] + (box["top"] + box["bottom"]) / 2
        page.mouse.move(canvas["x"] + 2, canvas["y"] + 2)                         # nobody under the mouse
        assert page.evaluate("document.querySelector('.canvas').__map.hoveredNow()") is None

        page.mouse.move(x, y)                                                     # on the name, not on the point
        assert page.evaluate("document.querySelector('.canvas').__map.hovered") is None
        assert page.evaluate("document.querySelector('.canvas').__map.hoveredNow()") == box["id"]
        assert page.evaluate("document.querySelector('.canvas').style.cursor") == "pointer"
        if os.environ.get("DINDON_SHOTS"):
            Path(os.environ["DINDON_SHOTS"]).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(os.environ["DINDON_SHOTS"]) / "name-hover.png"))

        now = next(b for b in page.evaluate("document.querySelector('.canvas').__map.labelBoxes") if b["id"] == box["id"])      # where the name is NOW (the map may still drift)
        page.mouse.move(canvas["x"] + now["right"] + 6, canvas["y"] + (now["top"] + now["bottom"]) / 2)         # still on the pill that opens around the name
        assert page.evaluate("document.querySelector('.canvas').__map.hoveredNow()") == box["id"]
        page.mouse.move(canvas["x"] + 2, canvas["y"] + 2)                         # away: nothing is lit any more
        assert page.evaluate("document.querySelector('.canvas').__map.hoveredNow()") is None
        assert page.evaluate("document.querySelector('.canvas').style.cursor") == "default"

        page.mouse.click(x, y)                                                    # a click on the name opens the person
        page.wait_for_selector("aside h2", timeout=10000)
        assert page.evaluate("document.querySelector('.canvas').__map.selected") == box["id"]
        browser.close()
