"""Pictures for the guided tour of the web page (frontend/img/tour-*.png), taken with a real browser.

Run:  UI_URL=http://127.0.0.1:8080 /usr/bin/python3 scripts/docs/tour_images.py
Then rebuild the frontend image (./stack up -d --build frontend).
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("UI_URL", "http://127.0.0.1:8080")
OUT = Path("frontend/img")
DAY = "2026-10-13"
SHOTS = [
    ("tour-1.png", None),
    ("tour-2.png", "#s-day"),
    ("tour-3.png", "#s-iv"),
    ("tour-4.png", "#s-intra"),
    ("tour-5.png", "#s-dir"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1100, "height": 900})
        ctx.add_init_script("try{localStorage.setItem('tour2_seen','1')}catch(e){}")
        page = ctx.new_page()
        page.goto(f"{URL}/#explore&day={DAY}&t=39600", wait_until="networkidle")
        page.wait_for_timeout(3000)
        for name, sel in SHOTS:
            if sel:
                page.locator(sel).screenshot(path=str(OUT / name))
            else:
                page.screenshot(path=str(OUT / name))
            print("wrote", OUT / name)
        b.close()


if __name__ == "__main__":
    main()
