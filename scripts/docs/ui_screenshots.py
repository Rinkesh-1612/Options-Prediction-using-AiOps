"""Take the screenshots used in the user manual with a real browser (Playwright, host Python).

Run:  UI_URL=http://127.0.0.1:8080 /usr/bin/python3 scripts/docs/ui_screenshots.py [outdir]
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
    seen = "try{localStorage.setItem('tour2_seen','1')}catch(e){}"  # skip the tour in the pictures
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(seen)
        page = ctx.new_page()
        page.goto(f"{URL}/#explore&day={DAY}&t={T}&iv=forecast", wait_until="networkidle")
        shot(page, "explore")
        for tab in ("works", "pipeline", "controls"):  # the other tabs
            page.click(f"[role=tab][data-tab='{tab}']")
            if tab == "works":
                page.click("summary:has-text('Forecasting how much')")
            shot(page, tab)
        page.click("#help-btn")
        shot(page, "help", full=False)
        ctx.close()
        for name, scheme in (("phone", "light"), ("phone-dark", "dark")):
            ctx = b.new_context(
                viewport={"width": 390, "height": 844}, color_scheme=scheme, device_scale_factor=2
            )
            ctx.add_init_script(seen)
            page = ctx.new_page()
            page.goto(f"{URL}/#explore&day={DAY}&t={T}", wait_until="networkidle")
            shot(page, name, full=False)
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
