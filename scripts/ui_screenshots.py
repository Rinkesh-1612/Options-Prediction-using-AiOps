"""Take the screenshots used in the user manual with a real browser (Playwright, host Python).

Run:  UI_URL=http://127.0.0.1:8080 /usr/bin/python3 scripts/ui_screenshots.py [outdir]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("UI_URL", "http://127.0.0.1:8080")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
DAY, T = "2026-10-13", 35340  # a real moment: the options priced in far more movement than happened


def shot(page, name: str, full: bool = True) -> None:
    page.wait_for_timeout(2500)
    if (
        full
    ):  # grow the window to the page height: a full-page capture would show the sticky header in the middle
        width = page.viewport_size["width"]
        page.set_viewport_size({"width": width, "height": 700})  # shrink first: the page height can only fall
        page.wait_for_timeout(500)
        page.set_viewport_size(
            {"width": width, "height": page.evaluate("document.documentElement.scrollHeight")}
        )
        page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("wrote", OUT / f"{name}.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        # skip the first-visit banner so that it does not hide the page in the pictures
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script("try{localStorage.setItem('tour_seen','1')}catch(e){}")
        page = ctx.new_page()
        page.goto(f"{URL}/#forecast&day={DAY}&t={T}", wait_until="networkidle")
        page.click("#dir-details summary")
        shot(page, "forecast")
        for tab, name in (("works", "works"), ("pipeline", "pipeline"), ("controls", "controls")):
            page.click(f"[role=tab][data-tab='{tab}']")
            if tab == "works":
                page.click("summary:has-text('Forecasting how much')")
            shot(page, name)
        page.click("#help-btn")
        shot(page, "help", full=False)
        page.close()
        ctx.close()
        for width, height, name, scheme in ((390, 844, "phone", "light"), (390, 844, "phone-dark", "dark")):
            ctx = b.new_context(
                viewport={"width": width, "height": height}, color_scheme=scheme, device_scale_factor=2
            )
            ctx.add_init_script("try{localStorage.setItem('tour_seen','1')}catch(e){}")
            page = ctx.new_page()
            page.goto(f"{URL}/#forecast&day={DAY}&t={T}", wait_until="networkidle")
            shot(page, name)
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
