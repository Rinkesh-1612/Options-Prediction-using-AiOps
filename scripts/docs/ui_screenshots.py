"""Take the screenshots used in the README and the user manual with a real browser (Playwright, host Python).

Each picture waits for its real content, and the script stops when the page shows an error.

Run:  UI_URL=http://127.0.0.1:8080 /usr/bin/python3 scripts/docs/ui_screenshots.py [outdir]
Grafana window (default: the last 30 minutes): GRAFANA_FROM and GRAFANA_TO, epoch ms or now-30m form.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("UI_URL", "http://127.0.0.1:8080")
MLFLOW = os.environ.get("MLFLOW_LOCAL_URL", "http://127.0.0.1:5050")
GRAFANA = os.environ.get("GRAFANA_LOCAL_URL", "http://127.0.0.1:3001")
G_FROM, G_TO = os.environ.get("GRAFANA_FROM", "now-30m"), os.environ.get("GRAFANA_TO", "now")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
DAY, T = "2026-10-13", 39600  # an unseen expiry day with a big move, at 11:00
SEEN = "try{localStorage.setItem('tour2_seen','1')}catch(e){}"  # skip the tour in the pictures
EXPLORE = (
    "#cal button.day:not([disabled])",
    "#ch-iv .main-svg",
    "#ch-intra .main-svg",
    "#dir-main .action",
    "#verdict-box .big",
)
TOOL_LEFT = 198  # MLflow: the width of its side menu, left out of the pictures


def ready(page, selectors) -> None:
    """Wait for the real content. A page that shows an error box must not become a picture."""
    for sel in selectors:
        page.wait_for_selector(sel, timeout=120000)
    page.wait_for_timeout(1500)
    if page.locator("#alert").is_visible():
        raise SystemExit(f"the page shows an error: {page.inner_text('#alert')[:120]}")


def shot(page, name: str, full: bool = True) -> None:
    if full:  # grow the window to the page height, so that the sticky header stays at the top
        width = page.viewport_size["width"]
        page.set_viewport_size({"width": width, "height": 700})  # shrink first: the height can only fall
        page.wait_for_timeout(500)
        height = page.evaluate("document.documentElement.scrollHeight")
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("wrote", OUT / f"{name}.png")


def clip(page, name: str, x: int, width: int, height: int) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), clip={"x": x, "y": 0, "width": width, "height": height})
    print("wrote", OUT / f"{name}.png")


def web_pages(b) -> None:
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light")
    ctx.add_init_script(SEEN)
    page = ctx.new_page()
    page.goto(f"{URL}/#explore&day={DAY}&t={T}&iv=forecast")
    ready(page, EXPLORE)
    shot(page, "explore")
    page.add_style_tag(content=".top, #story { position: static !important; }")
    page.locator("#s-intra").screenshot(path=str(OUT / "explore-day.png"))
    print("wrote", OUT / "explore-day.png")
    for tab, sel in (("works", "#ch-cum .main-svg"), ("pipeline", "#dag .node"), ("controls", "#health li")):
        page.click(f"[role=tab][data-tab='{tab}']")
        ready(page, [sel])
        if tab == "works":
            page.click("summary:has-text('Forecasting how much')")
        shot(page, tab)
    page.click("#help-btn")
    page.wait_for_timeout(500)
    shot(page, "help", full=False)
    ctx.close()
    for name, scheme in (("phone", "light"), ("phone-dark", "dark")):
        ctx = b.new_context(
            viewport={"width": 390, "height": 844}, color_scheme=scheme, device_scale_factor=2
        )
        ctx.add_init_script(SEEN)
        page = ctx.new_page()
        page.goto(f"{URL}/#explore&day={DAY}&t={T}")
        ready(page, EXPLORE)
        page.evaluate("window.scrollTo(0, 0)")
        shot(page, name, full=False)
        ctx.close()


def close_assistant(page) -> None:
    """MLflow opens an assistant panel on the right. It only takes space from the table."""
    if page.get_by_text("MLflow Assistant").count():
        page.mouse.click(1465, 35)
        page.wait_for_timeout(1000)


def tools(b) -> None:
    ctx = b.new_context(
        viewport={"width": 1500, "height": 950}, color_scheme="light", device_scale_factor=1.5
    )
    page = ctx.new_page()
    page.goto(f"{MLFLOW}/#/experiments/3/runs", wait_until="domcontentloaded")  # nifty-zoo: training runs
    page.wait_for_selector("text=Run Name", timeout=60000)
    page.wait_for_timeout(3000)
    close_assistant(page)
    clip(page, "mlflow-runs", TOOL_LEFT, 1296, 640)
    page.goto(f"{MLFLOW}/#/models/nifty-signal", wait_until="domcontentloaded")
    page.wait_for_selector("text=Version 14", timeout=60000)
    page.wait_for_timeout(2500)
    close_assistant(page)
    clip(page, "mlflow-registry", TOOL_LEFT, 1296, 575)
    ctx.close()
    ctx = b.new_context(
        viewport={"width": 1500, "height": 1000}, color_scheme="light", device_scale_factor=1.5
    )
    page = ctx.new_page()
    page.goto(
        f"{GRAFANA}/d/optpred?orgId=1&from={G_FROM}&to={G_TO}&theme=light&kiosk",
        wait_until="domcontentloaded",
    )
    page.wait_for_selector("text=Signals per minute", timeout=60000)
    page.wait_for_timeout(9000)
    clip(page, "grafana", 0, 1500, 840)
    ctx.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        web_pages(b)
        tools(b)
        b.close()


if __name__ == "__main__":
    main()
