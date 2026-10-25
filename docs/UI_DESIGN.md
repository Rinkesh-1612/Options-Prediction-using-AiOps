# UI / UX design

The page is [frontend/index.html](../frontend/index.html): one static file, no libraries, served by nginx. It talks to the
API only (address in `config.json`). Screenshots are in `docs/img/`; how to use the page is in
[USER_MANUAL.md](USER_MANUAL.md).

## How the design was made

The first version was organised around **our tools** (Signal, Results, Pipeline, Operations) and used model jargon on
the first screen. A browser audit (below) found 5 of 11 checks failing. I rebuilt it around the **trader's question**:
*"How much will NIFTY move next, and does this system work?"*

**Skill used:** [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (MIT licence, commit `d14efff`):
a design-rule base for AI coding agents (79 styles, 192 palettes, 74 font pairings, 119 UX rules, a pre-delivery
checklist). I did **not** run its installer. I cloned it into an isolated scratch folder, read `SKILL.md`, checked that its
search script has no network, subprocess or `eval` calls, and ran only `search.py` (`python3 -E -s`).

| Step | What the skill said | What I did |
|---|---|---|
| `--design-system "financial trading analytics dashboard non-technical user clear"` | Style *Minimalism & Swiss Style* (clean, grid-based, high contrast, "best for dashboards"); dark palette with green for positive; Fira Sans / Fira Code | **Adopted** the style, semantic colour tokens and light + dark. **Rejected** the suggested landing page ("Enterprise Gateway": hero video, "Contact Sales"): wrong for a dashboard. **Rejected** Google Fonts: an external request on a private server; I use the system font stack. |
| `--domain ux` for empty states, onboarding, errors, loading, help | Guide users when there is no content; onboarding must be skippable; errors need a recovery step and `role="alert"`; stable skeleton while loading with `aria-busy`; help in a consistent place | All five implemented (see the table below). |
| Checklist | no emoji icons, `cursor: pointer`, hover states, contrast 4.5:1, visible focus, `prefers-reduced-motion`, 375 / 768 / 1024 / 1440 px | All five implemented and **measured** by `tests/ui/ui_audit.py`. |

## The seven questions

| Question | What the page does | Evidence |
|---|---|---|
| **Is the UX intuitive for the problem statement?** | The first screen answers one question in one sentence: *"NIFTY is expected to move about 30 points over the next 15 minutes. The options market is pricing in about 74 points. Options look expensive."* Three numbered steps: **1 Pick a moment, 2 What to expect, 3 Should I buy a call or a put?** A chart of the whole day shows our forecast, the options market and what happened. Quick jumps ("Busiest moment", "Quietest moment", "Options priciest vs. forecast") open a meaningful example at once. The page opens on a real example, never on an empty screen. | `docs/img/forecast.png` |
| **How easy is it for a non-technical user?** | Plain words and index points instead of "bp", "IV", "QLIKE". Every technical word is a tap-to-explain term (`Options market`, `Unseen days`, `Spread`, `SHAP`, …) and the same **Help** button is in the same place on every screen (glossary + 3-step guide). A skippable first-visit banner offers the guide. Technical detail is folded into "Why did it say that?" and "All the numbers". The "Does it work?" tab gives two verdicts in words: **"Yes, it works"** and **"No, it does not"**. | `works.png`, `help.png`; audit check *jargon on the first screen is explained* |
| **Is it foolproof?** | Only real days and valid times can be chosen (a list and a bounded slider). Buttons that change something (roll back, retrain) ask for confirmation in a dialog. When the API fails, a readable alert (`role="alert"`) says what happened in plain words and offers **Try again**; the page never shows raw errors. Loading shows a stable skeleton, never a blank screen. The call/put model carries a clear "Not proven" notice. | audit checks *API down: readable alert + Try again* and *no error alert while everything works* |
| **Is it free of UI errors?** | A real browser (Chromium via Playwright) opens every tab at 4 widths and in light and dark mode, and fails on any console or page error, any "undefined", "NaN" or "null" text, and any control without an accessible name. | audit: `reports/ui_audit.md` |
| **Colours, shapes, geometry, look and feel?** | Swiss minimalism: one grid, 8 px spacing scale, one accent (blue), semantic colours for good / bad / warning, 10 px radius, no decoration. Light and dark follow the system. SVG icons only (no emoji). Colour is never the only signal: forecast / options / reality use three line styles (solid, dashed, dotted) and a legend and every verdict has an icon and a word. Contrast ≥ 4.5:1 for all text, measured. | audit check *contrast*; `forecast.png`, `phone-dark.png` |
| **How responsive is it?** | Mobile first. On a phone: one column and a bottom tab bar (thumb reach), 44 px touch targets, no horizontal scroll. Tablet and desktop: two-column cards and a top tab bar. Charts resize with the window. Checked at 375, 768, 1024 and 1440 px. | audit checks *no horizontal scroll* and *touch targets*; `phone.png` |
| **Is there a user manual?** | Yes: [USER_MANUAL.md](USER_MANUAL.md), written for a trader, with screenshots of every tab. The same help is inside the page. | |

## Measured result (browser audit)

`tests/ui/ui_audit.py` (Playwright). Before = the first page, after = this page.
Reports: [before](../reports/ui_audit_before_redesign.md), [after](../reports/ui_audit.md).

| Check | Before | After |
|---|---|---|
| no console or page errors | pass | pass |
| no horizontal scroll at 375 / 768 / 1024 / 1440 px | pass | pass |
| every control has an accessible name | pass | pass |
| touch targets ≥ 44 px on a phone | **13 fail** | pass |
| no text below 12 px | pass | pass |
| text contrast ≥ 4.5:1, light and dark | **60 fail** | pass |
| visible keyboard focus | **fail** | pass |
| no "undefined" / "NaN" / "null" text | pass | pass |
| jargon on the first screen is explained | **4 fail** | pass |
| no error alert while everything works | not tested | pass |
| API down: readable alert + Try again | **fail** | pass |
| tabs exist | pass | pass |

Two bugs that the screenshots caught and the checks did not (and then the check was made stricter): the error box and the
first-visit banner were visible all the time, because CSS `display: flex` overrode the HTML `hidden` attribute. The audit
now also fails when an alert is visible while everything works.

## Design tokens

Colours (light / dark): background `#f8fafc` / `#020617`, surface `#ffffff` / `#0f172a`, text `#0f172a` / `#f1f5f9`,
muted text `#475569` / `#a8b3c5`, primary `#1d4ed8` / `#60a5fa`, good `#15803d` / `#4ade80`, bad `#b91c1c` / `#f87171`,
warning `#92400e` / `#fbbf24`. Type: system font stack, 16 px body, 1.5 line height, headline 22–32 px, numbers use tabular
figures. Spacing: 4 / 8 / 12 / 16 / 24 px. Motion: none except a loading pulse, and none when the system asks for reduced motion.

## Run the checks

```bash
make ui                 # audit of the running page (needs Playwright on the host; writes reports/ui_audit.md)
UI_URL=http://127.0.0.1:8080 /usr/bin/python3 scripts/ui_screenshots.py   # redo the screenshots of the manual
```

## Charts

- Library: **Plotly.js 2.35.2 basic bundle** (MIT), self-hosted in `frontend/vendor/` (no CDN; checksum in `vendor/README.md`). If it fails to load, a plain SVG chart takes over (audited).
- Palette (checked with the `dataviz` skill validator, light and dark): forecast `#2a78d6` / `#3987e5`, options market `#eb6834` / `#d95926`, what happened `#1baf7a` / `#199e70`. Lines also differ in style (solid, dashed, dotted), so colour is never the only signal.
- Interaction: unified hover tooltip, click to select a time, drag to zoom, double-click to reset, zoom buttons, legend toggle. Each chart has a **table view** with the same numbers.
- Charts: forecast and NIFTY index (one day); error per unseen day; cumulative result of the call/put models; drift per day; speed per step.

## Explore page (rebuilt 2026-10-25 after the owner's feedback)

The page is for the examiner. One story page, top to bottom (the owner's order): guided tour (closable, reopen with a button) →
1 calendar → 2 implied volatility (four views: IV over the days, IV vs our forecast, smile, term structure) → 3 one day by the
minute → 4-7 (strategies, models, alpha test, verdict: next phases). Unseen days carry a star; training days carry a warning.
Data: `/explore/*` (docs/LLD.md); model answers are computed once by the DVC stage `modelout` (no model runs in the browser).
