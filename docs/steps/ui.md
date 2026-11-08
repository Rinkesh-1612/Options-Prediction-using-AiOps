# Web Page (UI): DONE (rebuilt 2026-10-25)

**Code.** [frontend/index.html](../../frontend/index.html): one static page (Plotly.js vendored in `frontend/vendor/`). Manual: [USER_MANUAL.md](../USER_MANUAL.md).

- Built around the trader's question (how much will NIFTY move, and does it work?), with plain words and tap-to-explain terms.
- Designed with the UI/UX Pro Max skill (Swiss minimal style, semantic colours, light + dark).
- Browser audit `tests/ui/ui_audit.py`: first page 5 of 11 checks failed, this page passes 13 of 13 (`reports/ui_audit.md`).
- New API endpoint for the chart: `GET /vol/day`.
