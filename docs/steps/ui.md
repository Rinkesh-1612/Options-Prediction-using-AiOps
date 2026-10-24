# Web Page (UI) — DONE

**Code.** [frontend/index.html](../../frontend/index.html): one static page, no libraries, served by nginx
(`frontend/Dockerfile`). It talks only to the signal API; the API address comes from `config.json`
(set by environment variables at container start). Light / dark mode, works at phone width.

| Tab | Shows |
|---|---|
| Signal | Pick a day (test or dev) and a second (09:20–15:15), or **Play** it like a live feed. Action, expected ₹ per side against the threshold, what happened next (entry, exit, barrier, hold, net ₹), hindsight for both sides, session total. |
| Results | Verdict, every model: CV vs test ₹/day with 95% interval, trades, hit rate; drift per day; feature importance; group ablation. |
| Pipeline | DVC stage graph coloured by the last run, run history (duration, commit, dirty flag), log of each run, data quality (rejected days with reasons, rows removed per rule). |
| Operations | Champion and previous version (deploy check, commit, test metrics), rollback and retrain (admin token), online drift, links to MLflow, Grafana, OpenAPI. |

**Foolproof.** Only accepted days and valid seconds can be picked; buttons are disabled during a call;
every API error shows as a readable message; rollback asks for confirmation.

**API added for the page:** `/pipeline`, `/pipeline/runs`, `/pipeline/runs/{id}/log`, `/quality`, `/drift/daily`,
`/signal` → `hindsight`, `/results` → CV summary, importance, ablation. Tests: `tests/api/test_signal_api.py`.
