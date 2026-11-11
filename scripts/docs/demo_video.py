"""Record the demo video: a real browser walks through the running stack, with the explanation as subtitles.

Run (host Python with Playwright, stack up):   /usr/bin/python3 scripts/docs/demo_video.py [outdir]
Output: <outdir>/demo.webm (1280x720, subtitles in the picture). About 5 minutes. Nothing is simulated: every screen is the live system.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

UI = os.environ.get("UI_URL", "http://127.0.0.1:8080")
MLFLOW = os.environ.get("MLFLOW_URL", "http://127.0.0.1:5050")
GRAFANA = os.environ.get("GRAFANA_URL", "http://127.0.0.1:3001")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo")
DAY = "2026-10-13"  # an unseen expiry day with a big move

CAPTION_JS = """(text) => {
  let el = document.getElementById('demo-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'demo-cap';
    el.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2147483647;' +
      'max-width:1080px;padding:12px 22px;border-radius:10px;background:rgba(15,18,24,.93);color:#fff;' +
      'font:600 21px/1.4 system-ui,sans-serif;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.35);' +
      'pointer-events:none';
    document.body.appendChild(el);
  }
  el.textContent = text; el.style.display = text ? 'block' : 'none';
}"""


def say(page: Page, text: str, extra_s: float = 0.0) -> None:
    """Show a subtitle and hold it long enough to read (about 15 characters per second, at least 3.5 s)."""
    page.evaluate(CAPTION_JS, text)
    page.wait_for_timeout(int(max(3.5, len(text) / 15) * 1000 + extra_s * 1000))


def tab(page: Page, name: str) -> None:
    """Open a tab of the page; the subtitle of the scene before is cleared first."""
    page.evaluate(CAPTION_JS, "")
    page.click(f"[role=tab][data-tab={name}]")
    page.wait_for_timeout(2500)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")


def to(page: Page, selector: str, block: str = "center") -> None:
    """Scroll to an element. The page grows when new data arrives, so wait first and correct the position after."""
    js = "([s, b, how]) => document.querySelector(s)?.scrollIntoView({behavior: how, block: b})"
    page.wait_for_timeout(900)
    page.evaluate(js, [selector, block, "smooth"])
    page.wait_for_timeout(1200)
    page.evaluate(js, [selector, block, "instant"])
    page.wait_for_timeout(300)


def explore(page: Page) -> None:
    page.goto(f"{UI}/#explore&day={DAY}&t=39600", wait_until="networkidle")
    page.wait_for_timeout(1500)
    say(
        page,
        "NIFTY Signal: a full AIOps pipeline on my own recorded NIFTY options data. DA3408 course project.",
    )
    say(page, "On the first visit a guided tour opens. It is the user manual inside the page.")
    for _ in range(2):
        page.click("#tour-next")
        page.wait_for_timeout(1800)
    page.click("#tour-close")
    to(page, "#day-h", "start")
    say(
        page,
        "Step 1: pick a day. A star marks an unseen day: no model saw it in training, so it is the fair test.",
    )
    page.click(f"#cal button.day[data-day='{DAY}']")
    to(page, "#iv-h", "start")
    say(page, "Step 2: implied volatility, the option market's own guess of how much NIFTY will move.")
    page.click("[data-iv=forecast]")
    say(
        page,
        "Here it is against our forecast and what really happened. Our forecast is closer on 10 of 10 unseen days.",
    )
    page.click("[data-iv=smile]")
    say(page, "The smile: implied volatility by strike.")
    page.click("[data-iv=term]")
    say(page, "And the term structure: implied volatility by expiry.")
    page.click("[data-iv=time]")
    to(page, "#intra-h", "start")
    say(page, "Step 3: inside one day, minute by minute. A click on the chart chooses the moment.")
    box = page.locator("#ch-intra").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.45, box["y"] + 60, steps=25)
    page.wait_for_timeout(700)
    page.mouse.click(box["x"] + box["width"] * 0.6, box["y"] + 60)
    say(page, "The three boxes show the market's guess, our forecast, and what happened after that moment.")
    to(page, "#dir-h", "start")
    say(page, "Step 4: the second model answers a harder question: buy a call, buy a put, or stay out.")
    page.click("#dir-details summary")
    page.wait_for_timeout(800)
    to(page, "#dir-body")
    say(page, "It shows why it answered that (the inputs that moved the score) and what happened next.")
    to(page, "#verdict-h", "start")
    say(
        page,
        "Step 5, the honest verdict: the volatility forecast works. Call or put prediction shows no edge after costs.",
    )


def results(page: Page) -> None:
    tab(page, "works")
    say(
        page,
        "Results: all the numbers. Each question has 3 models: a baseline, a simple model and a better one.",
    )
    to(page, "#ch-cum")
    say(
        page, "The last 10 days were never used in training. The models are scored on them once, after costs."
    )


def pipeline(page: Page) -> None:
    tab(page, "pipeline")
    say(
        page,
        "How it's built: the DVC pipeline, drawn live from dvc.yaml. Green means the last run succeeded.",
    )
    say(
        page,
        "Data: export, check with Spark, clean, grid, features and labels with Ray. Then the two models.",
    )
    say(
        page,
        "The last two boxes are the CI: 'tests' runs lint and all tests, 'gate' checks the acceptance criteria.",
    )
    to(page, "#ch-thr")
    say(page, "Speed and throughput of each stage, in rows per second, from the last successful run.")
    to(page, "#runs")
    say(
        page,
        "Every run is in a journal: result, time and Git commit. This is the console for successes and failures.",
    )
    page.click("#runs-failed")
    page.wait_for_timeout(1200)
    page.locator("#runs tr").first.click()
    say(page, "'Failed only' lists the failures. A click on a run opens its log, with the full error.")
    page.click("#runs-failed")
    to(page, "#quality")
    say(page, "Data quality: which days were rejected and why, and what each cleaning rule removed.")


def controls(page: Page) -> None:
    tab(page, "controls")
    say(page, "Controls, for the operator: the health of each part, and the model version in service.")
    to(page, "#rollback")
    say(
        page,
        "Actions: go back to the previous model, retrain, or run the pipeline. A new model is served only after a smoke test.",
    )
    to(page, "#links")
    say(page, "The page talks to the backend only through the REST API. These links open MLflow and Grafana.")


def tools(page: Page) -> None:
    page.goto(f"{MLFLOW}/#/experiments", wait_until="domcontentloaded")
    page.wait_for_selector("text=nifty-zoo", timeout=60000)
    page.wait_for_timeout(1500)
    say(page, "MLflow: every training run with its parameters, metrics, artifacts and Git commit.")
    page.goto(f"{MLFLOW}/#/models", wait_until="domcontentloaded")
    page.wait_for_selector("text=nifty-signal", timeout=60000)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")  # MLflow may open a "what is new" window over the list
    page.wait_for_timeout(800)
    say(page, "The model registry. The alias 'champion' is the model in service; 'previous' is the way back.")
    page.goto(f"{GRAFANA}/d/optpred?from=now-15m&to=now&refresh=5s&kiosk", wait_until="domcontentloaded")
    page.wait_for_selector("text=Signals per minute", timeout=60000)
    page.wait_for_timeout(4000)
    say(
        page,
        "Grafana, fed by Prometheus every 5 seconds. A replay of the unseen days is running, so it moves.",
    )
    say(
        page,
        "Signals, served trades, drift, API time, the pipeline, and whether each component is up.",
        extra_s=3,
    )
    page.mouse.wheel(0, 900)
    page.wait_for_timeout(2500)
    say(
        page,
        "10 alert rules watch this. A drift alert or a losing model starts a retrain by itself.",
        extra_s=2,
    )
    say(
        page,
        "Result: the volatility forecast beats the option market. Direction shows no edge. Both are reported as measured.",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(OUT),
            record_video_size={"width": 1280, "height": 720},
        )
        page = ctx.new_page()
        for scene in (explore, results, pipeline, controls, tools):
            scene(page)
        video = page.video
        ctx.close()  # the video file is complete only after the context closes
        Path(video.path()).rename(OUT / "demo.webm")
        b.close()
    print("wrote", OUT / "demo.webm")


if __name__ == "__main__":
    main()
