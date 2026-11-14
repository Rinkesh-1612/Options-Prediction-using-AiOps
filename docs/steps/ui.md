# Web Page (UI)

**Code.** [frontend/index.html](../../frontend/index.html): one static page (Plotly.js vendored in `frontend/vendor/`). Manual: [USER_MANUAL.md](../USER_MANUAL.md).

- Built around the trader's question (how much will NIFTY move, and does it work?), with plain words and tap-to-explain terms.
- Swiss minimal style, semantic colours, light and dark themes.
- Browser audit `tests/ui/ui_audit.py`: first page 5 of 11 checks failed, this page passes 13 of 13 (`reports/ui_audit.md`).
- Four tabs: **Explore** (5 steps: day → implied volatility → inside one day → call or put? → verdict), **Results**,
  **How it's built** (live pipeline, speed, runs, logs, data quality) and **Controls** (health, rollback, retrain, run the pipeline).
- A guided tour opens on the first visit: it is the user manual inside the page.
