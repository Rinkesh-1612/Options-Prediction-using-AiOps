# Web Page (UI): DONE (rebuilt 2026-10-25)

**Code.** [frontend/index.html](../../frontend/index.html): one static page, no libraries. Design, the seven UX questions and the
measured result: [UI_DESIGN.md](../UI_DESIGN.md). Manual: [USER_MANUAL.md](../USER_MANUAL.md).

- Built around the trader's question (how much will NIFTY move, and does it work?), with plain words and tap-to-explain terms.
- Designed with the UI/UX Pro Max skill (rules adopted and rejected are listed in UI_DESIGN.md).
- Browser audit `tests/ui/ui_audit.py`: first page 5 of 11 checks failed, this page passes 12 of 12.
- New API endpoint for the chart: `GET /vol/day`.
