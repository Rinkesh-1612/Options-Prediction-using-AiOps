"""UI audit in a real browser (Playwright). Answers the rubric questions about the front end with measurements:

  Is the front end free of UI errors?      console / page errors, "undefined" / "NaN" text, broken layout
  How responsive is the UI?                no horizontal scroll at 375 / 768 / 1024 / 1440 px
  Is the UX foolproof?                     a failing API gives a readable alert with a retry button
  Is it usable by non-technical users?     jargon on the first screen is explained, controls have names,
                                           touch targets >= 44 px, text >= 12 px, contrast >= 4.5:1, visible focus

Run (needs Playwright; the host Python has it):
    UI_URL=http://127.0.0.1:8080 /usr/bin/python3 tests/ui/ui_audit.py [--md reports/ui_audit.md]
Exit code 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from playwright.sync_api import sync_playwright

VIEWPORTS = [(375, 800), (768, 1000), (1024, 800), (1440, 900)]
JARGON = [
    "QLIKE",
    "SHAP",
    "PSI",
    "champion",
    "drift",
    "ablation",
    "triple-barrier",
    "walk-forward",
    "pyfunc",
    "alias",
]

JS_COLLECT = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.01; };
  const inClosed = (el) => !!el.closest('details:not([open]) > :not(summary)') || !!el.closest('dialog:not([open])') || !!el.closest('[hidden]');
  const out = {names: [], small: [], tiny: [], contrast: [], jargon: [], text: ''};
  const name = (el) => (el.getAttribute('aria-label') || '') ||
    (el.getAttribute('aria-labelledby') ? [...el.getAttribute('aria-labelledby').split(' ')].map(i => (document.getElementById(i)||{}).innerText||'').join(' ') : '') ||
    (el.labels && el.labels.length ? [...el.labels].map(l => l.innerText).join(' ') : '') ||
    (el.innerText || '').trim() || el.getAttribute('title') || el.getAttribute('placeholder') || '';
  const label = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : '');
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea, [role=button], [role=tab], summary')) {
    if (!vis(el) || inClosed(el)) continue;
    if (!name(el).trim()) out.names.push(label(el));
    const r = el.getBoundingClientRect();
    if (!el.classList.contains('term') && (r.width < 44 - 0.5 || r.height < 44 - 0.5) && el.type !== 'range')
      out.small.push(label(el) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  }
  const rgb = (c) => { const m = c.match(/[\d.]+/g).map(Number); return {r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1}; };
  const lum = ({r, g, b}) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (el) => { let layers = []; for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
    let base = {r: 255, g: 255, b: 255}; for (const c of layers.reverse()) base = {r: c.r * c.a + base.r * (1 - c.a), g: c.g * c.a + base.g * (1 - c.a), b: c.b * c.a + base.b * (1 - c.a)}; return base; };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set(); let n;
  while ((n = walker.nextNode())) {
    const t = n.textContent.trim(); const el = n.parentElement;
    if (!t || !el || !vis(el) || inClosed(el) || el.closest(':disabled') || ['SCRIPT', 'STYLE', 'OPTION'].includes(el.tagName)) continue;
    out.text += t + ' ';
    const s = getComputedStyle(el), px = parseFloat(s.fontSize);
    if (px < 12 && !seen.has(el)) { out.tiny.push(label(el) + ' ' + px + 'px "' + t.slice(0, 24) + '"'); seen.add(el); }
    const fg = rgb(s.color), bg = bgOf(el), fa = fg.a;
    const f2 = {r: fg.r * fa + bg.r * (1 - fa), g: fg.g * fa + bg.g * (1 - fa), b: fg.b * fa + bg.b * (1 - fa)};
    const L1 = lum(f2), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const large = px >= 24 || (px >= 18.66 && +s.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5) && !seen.has(el)) { out.contrast.push(label(el) + ' ' + ratio.toFixed(2) + ' "' + t.slice(0, 24) + '"'); seen.add(el); }
    if (!el.closest('.term, .keep-term, summary')) for (const j of %JARGON%) if (new RegExp('\\b' + j + '\\b', 'i').test(t)) out.jargon.push(j + ' in "' + t.slice(0, 40) + '"');
  }
  return out;
}
"""

JS_FOCUS = r"""
(el) => { const s = getComputedStyle(el); const o = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
  return o || (s.boxShadow && s.boxShadow !== 'none'); }
"""


def run(url: str) -> dict:
    results: dict[str, list[str]] = {}

    def fail(key: str, msg: str) -> None:
        results.setdefault(key, []).append(msg)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w, h in VIEWPORTS:
            for scheme in ("light", "dark") if w == 1440 else ("light",):
                ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m, e=errors: m.type == "error" and e.append(m.text[:120]))
                page.on("pageerror", lambda x, e=errors: e.append("pageerror: " + str(x)[:120]))
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1500)
                tabs = page.eval_on_selector_all("[role=tab]", "els => els.map(e => e.dataset.tab || e.id)")
                if not tabs:
                    fail("tabs", f"{w}px: no [role=tab] found")
                for tab in tabs:
                    page.click(f"[role=tab][data-tab='{tab}']")
                    page.wait_for_timeout(1800)
                    where = f"{w}px/{scheme}/{tab}"
                    shown = page.eval_on_selector_all(
                        "[role=alert]",
                        "els => els.filter(e => e.getBoundingClientRect().height > 0).map(e => e.innerText.slice(0, 40))",
                    )
                    if shown:
                        fail("false_alarm", f"{where}: error alert visible while the API works: {shown[0]!r}")
                    if page.evaluate("document.documentElement.scrollWidth") > w + 1:
                        fail(
                            "overflow",
                            f"{where}: horizontal scroll ({page.evaluate('document.documentElement.scrollWidth')} > {w})",
                        )
                    c = page.evaluate(JS_COLLECT.replace("%JARGON%", json.dumps(JARGON)))
                    for k in ("names", "tiny", "contrast"):
                        for item in c[k][:5]:
                            fail(k, f"{where}: {item}")
                    if w == 375 and scheme == "light":
                        for item in c["small"][:6]:
                            fail("touch", f"{where}: {item}")
                    if tab == tabs[0] and w in (375, 1440) and scheme == "light":
                        for item in sorted(set(c["jargon"]))[:6]:
                            fail("jargon", f"{where}: {item}")
                    import re

                    if re.search(r"\b(undefined|NaN|\[object|Infinity)\b|\bnull\b", c["text"]):
                        fail(
                            "bad_text",
                            f"{where}: {re.search(r'.{0,20}(undefined|NaN|null|Infinity).{0,20}', c['text']).group(0)}",
                        )
                # keyboard focus visibility on the first tab
                if w == 1440 and scheme == "light":
                    page.click(f"[role=tab][data-tab='{tabs[0]}']")
                    page.mouse.click(5, 5)
                    bad = 0
                    for _ in range(20):
                        page.keyboard.press("Tab")
                        if not page.evaluate_handle("document.activeElement").evaluate(JS_FOCUS):
                            bad += 1
                            fail(
                                "focus",
                                f"no visible focus ring on {page.evaluate('document.activeElement.tagName + (document.activeElement.id ? \"#\" + document.activeElement.id : \"\")')}",
                            )
                for e in errors[:5]:
                    fail("console", f"{w}px/{scheme}: {e}")
                ctx.close()

        # explore page: calendar, interactive charts, fallback
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script("try{localStorage.setItem('tour2_seen','1')}catch(e){}")
        page = ctx.new_page()
        page.goto(url + "#explore&day=2026-10-13&t=39600", wait_until="networkidle")
        page.wait_for_timeout(2500)
        if not page.locator("#cal button.day:not([disabled])").count():
            fail("charts", "calendar shows no selectable day")
        else:
            page.locator("#cal button.day:not([disabled])").first.click()
            page.wait_for_timeout(600)
            if "13 Oct" in page.inner_text("#dayinfo"):
                fail("charts", "clicking a calendar day did not change the day")
        for mode in ("time", "forecast", "smile", "term"):
            page.click(f"[data-iv={mode}]")
            page.wait_for_timeout(900)
            if not page.locator("#ch-iv .main-svg").count():
                fail("charts", f"IV view '{mode}' was not drawn")
        page.click("[data-iv=time]")
        page.click("#cal button.day[data-day='2026-10-13']") if page.locator(
            "#cal button.day[data-day='2026-10-13']"
        ).count() else None
        page.wait_for_timeout(1500)
        if not page.locator("#ch-intra .main-svg").count():
            fail("charts", "intraday chart was not drawn")
        else:
            page.locator("#ch-intra").scroll_into_view_if_needed()
            box = page.locator("#ch-intra").bounding_box()
            box = {"x": box["x"] + 70, "y": box["y"] + 20, "width": box["width"] - 90}
            for k in range(4):
                page.mouse.move(box["x"] + box["width"] * (0.5 + k * 0.01), box["y"] + 40)
                page.wait_for_timeout(100)
            page.wait_for_timeout(400)
            if not page.locator(".hoverlayer text").count():
                fail("charts", "no tooltip when the pointer is over the intraday chart")
            before = page.inner_text("#clock-intra")
            page.mouse.click(box["x"] + box["width"] * 0.8, box["y"] + 40)
            page.wait_for_timeout(600)
            if page.inner_text("#clock-intra") == before:
                fail("charts", "clicking the intraday chart did not move the selected time")
        page.wait_for_timeout(800)
        if page.locator("#strat-body tr").count() < 10:
            fail("charts", "the strategies table has fewer than 10 rows")
        else:
            page.locator("#strat-body [data-pick]").first.click()
            page.wait_for_timeout(1200)
            if not (
                page.locator("#ch-exit .main-svg").count() and page.locator("#ch-payoff .main-svg").count()
            ):
                fail("charts", "exit-time and payoff charts were not drawn for a chosen strategy")
            page.click("[data-exit=barrier]")
            page.wait_for_timeout(300)
            if "Result" not in page.inner_text("#strat-head"):
                fail("charts", "the barrier-rule view did not change the table")
            page.click("#builder summary")
            page.select_option("#la0", "sell")
            page.click("#leg-add")
            page.click("#leg-run")
            page.wait_for_timeout(1200)
            if "Your strategy" not in page.inner_text("#sd-title"):
                fail("charts", "a strategy built from legs was not priced")
        if page.locator("#m-dir tr").count() < 5 or not page.locator("#ch-dirday .main-svg").count():
            fail("charts", "the models section (tables and chart) was not drawn")
        if not page.locator("#ch-intra-t table").count() or not page.locator("#ch-iv-t table").count():
            fail("charts", "no table twin for a chart")
        page.click("#tour-again")
        page.wait_for_timeout(300)
        steps = 1
        while page.inner_text("#tour-next") != "Finish" and steps < 12:
            page.click("#tour-next")
            steps += 1
        page.click("#tour-close")
        if page.locator("#tour").is_visible():
            fail("charts", "the guided tour did not close")
        ctx.close()
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900}
        )  # library blocked: SVG fallback must work
        ctx.add_init_script("try{localStorage.setItem('tour2_seen','1')}catch(e){}")
        ctx.route("**/vendor/**", lambda r: r.abort())
        page = ctx.new_page()
        page.goto(url + "#explore&day=2026-10-13&t=39600", wait_until="networkidle")
        page.wait_for_timeout(1500)
        if not page.locator("#ch-intra p.hint, #ch-iv p.hint, #ch-iv svg").count():
            fail("charts", "no readable fallback when the chart library is missing")
        ctx.close()

        # foolproof: API down -> readable alert with a way to retry
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        for pat in ("**/vol*", "**/vol/**", "**/signal*", "**/days*", "**/results*", "**/model*"):
            ctx.route(pat, lambda r: r.abort())
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(2500)
        alerts = page.eval_on_selector_all(
            "[role=alert]",
            "els => els.filter(e => e.getBoundingClientRect().height > 0).map(e => e.innerText)",
        )
        if not alerts:
            fail("api_down", "no visible [role=alert] when the API is unreachable")
        elif any(re.search(r"failed to fetch|TypeError|NetworkError", a, re.I) for a in alerts):
            fail("api_down", f"raw browser error shown: {alerts[0][:60]}")
        if not page.get_by_role("button", name=re.compile("try again|retry", re.I)).count():
            fail("api_down", "no 'Try again' button when the API is unreachable")
        ctx.close()
        browser.close()
    return results


CHECKS = {
    "console": "no console or page errors",
    "overflow": "no horizontal scroll (responsive)",
    "names": "every control has an accessible name",
    "touch": "touch targets >= 44 px on a phone",
    "tiny": "no text below 12 px",
    "contrast": "text contrast >= 4.5:1 (3:1 for large text), light and dark",
    "focus": "visible keyboard focus",
    "bad_text": "no 'undefined' / 'NaN' / 'null' text",
    "jargon": "jargon on the first screen is explained (term button) or folded away",
    "false_alarm": "no error alert while everything works",
    "charts": "explore page: calendar, four IV views, intraday chart (tooltip, click), tour, table twins, fallback",
    "api_down": "API down: readable alert + Try again button",
    "tabs": "tabs exist",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("UI_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--md", help="write a markdown report")
    a = ap.parse_args()
    res = run(a.url)
    lines = [f"# UI audit of {a.url}", "", "| Check | Result | Findings |", "|---|---|---|"]
    bad = 0
    for k, desc in CHECKS.items():
        f = res.get(k, [])
        bad += bool(f)
        lines.append(f"| {desc} | {'FAIL' if f else 'pass'} | {len(f) if f else ''} |")
    lines.append("")
    for k, f in res.items():
        lines += (
            [f"## {CHECKS.get(k, k)}"]
            + [f"- {x}" for x in f[:12]]
            + ([f"- … {len(f) - 12} more"] if len(f) > 12 else [])
            + [""]
        )
    text = "\n".join(lines)
    print(text)
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(text + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
