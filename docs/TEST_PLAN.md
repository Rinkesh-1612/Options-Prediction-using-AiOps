# Test plan

## 1. Scope and levels

| Level | Folder | What it proves | Runs |
|---|---|---|---|
| Unit | `tests/unit/` | Each rule and function alone: cleaning rules, fill policy, grid, every feature, labels and costs, simulator, every model family, deploy gate, PSI, Ray map | every push |
| Integration | `tests/integration/` | Real stage `main`s on synthetic raw data: check (Spark) → clean → grid → feat → labels | every push |
| API | `tests/api/` | Every endpoint with a fake model server and registry (and a fake volatility model); LLD = real routes; page calls only documented paths | every push |
| End-to-end | `tests/e2e/` | The running stack: API → model server → registry, web page, Prometheus | `make e2e` with the stack up |
| UI audit | `tests/ui/ui_audit.py` | The web page in a real browser (Playwright): 13 checks at 4 screen widths, light and dark (incl. charts: drawn, tooltip, click, zoom, table twin, fallback) | `make ui` with the stack up |

Synthetic data: `tests/helpers/synth.py` (raw tables in the export schema), `tests/helpers/grid_synth.py`
(one grid day). No test needs the real data.

## 2. Test cases (110: 105 pass, 5 e2e skipped without the stack; e2e 5/5 with the stack)

| ID | Area | Cases | File |
|---|---|---|---|
| T1 | Export | TSV counts, row-count check rejects a short file, run journal on success and failure | `unit/test_export.py` (4) |
| T2 | Cleaning | outlier rules counted; index closing print; forward fill respects the age limit; never uses the future | `unit/test_eda_rules.py` (4) |
| T3 | Grid | legs follow ATM; no future quote | `unit/test_grid.py` (1) |
| T4 | Features | for each of the 10 features: docstring and rows, **no look-ahead**, values after the lookback; unique columns; all float | `unit/test_featurelib.py` (33) |
| T5 | Labels | cost = contract note (₹18.13); take-profit, stop-loss, time limit; follows the bought contract when ATM moves | `unit/test_barrier.py` (3) |
| T6 | Models and simulator | each of 3 families fits and scores; trees find a planted signal; one position at a time; NaN never trades; walk-forward folds; no-score model never trades | `unit/test_zoo.py` (8) |
| T7 | Deployment | failed smoke test is not deployed; passed version → champion, old → previous; first deployment | `unit/test_promote.py` (3) |
| T8 | Drift | same distribution low PSI, shift high; NaN share change; monitor waits for rows, then flags | `unit/test_psi.py` (3) |
| T9 | Ray | day results keep their order | `unit/test_parallel.py` (1) |
| T10 | Data pipeline | holiday rejected, duplicates counted; session rows only; 22,500 grid rows with legs, ask > bid; float features; labels aligned | `integration/test_data_pipeline.py` (5) |
| T11 | API | signal without future rows; volatility forecast uses only rows up to the second; hindsight; blocked entry; losing trade metric; 404 / 503; rollback token and swap; alert → one retrain then cooldown; drift and gauges; data-quality gauges; pipeline graph, runs, log (path attack refused), throughput from the last successful run; inf → null; drivers passed through; runner heartbeat gauge; failed requests logged; pipeline run needs the token, one waiting run | `api/test_signal_api.py` (18) |
| T12 | Contract | LLD = routes; page uses documented paths only | `api/test_lld.py` (2) |
| T14 | Volatility model | inputs have no look-ahead; targets look only forward; QLIKE zero for a perfect forecast; each of 3 forecasters fits and predicts positive; HAR beats a noise IV on clustered volatility | `unit/test_vol.py` (7) |
| T15 | Explanations | SHAP contributions add up to the score and name the planted driver; non-LightGBM models give none; served model explains only the last row; API passes `drivers` through (or null) | `unit/test_explain.py` (3) |
| T18 | CI gate | all criteria pass; each broken criterion fails | `unit/test_gate.py` (2) |
| T19 | Web page | the page script parses (`node --check`; a syntax error once broke the whole page) | `unit/test_page_script.py` (1) |
| T20 | Demo replay | calls `/signal` and `/vol` for every step of the unseen days; counts answers and refusals | `unit/test_replay.py` (1) |
| T17 | Explore API | calendar and events; IV by minute with and without a volatility model; forecast of the model in service; smile and term structure (expiries sent in separate seconds are merged); 404 / 503 | `api/test_explore.py` (6) |
| T13 | End-to-end | served model passed the gate; test-day signal round trip; reports, pipeline, metrics; web page and config; Prometheus scrapes the API | `e2e/test_stack.py` (5) |

### UI audit (13 checks, now on the Explore page: calendar, four IV views, intraday chart, call/put answer, verdict, guided tour, fallback without the chart library, report `reports/ui_audit.md`)

console and page errors; horizontal scroll at 375 / 768 / 1024 / 1440 px; accessible name of every control; touch
targets ≥ 44 px on a phone; no text under 12 px; text contrast ≥ 4.5:1 in light and dark; visible keyboard focus; no
"undefined" / "NaN" / "null" text; jargon on the first screen explained; no error alert while everything works; readable
alert and **Try again** when the API is down; tabs exist. Result: **13 of 13 pass** (the first page failed 5 of 11).

## 3. How to run

```bash
make test        # unit + integration + API (e2e is skipped without the stack)
make e2e         # end-to-end, after ./stack up -d
make ui          # browser audit of the page, after ./stack up -d (needs Playwright on the host)
mlflow run . -e test   # the same tests through the MLproject (log: reports/mlproject_test_run.log)
make report      # all tests -> reports/test_report.md (numbers copied from pytest's JUnit file)
./pipe bash -c "E2E_API_URL=http://127.0.0.1:8000 python scripts/test_report.py"   # report incl. e2e
```
CI: `make ci` (= `dvc repro gate`) runs ruff and all tests as the DVC stage `tests`, then checks the acceptance
criteria in the stage `gate`. The pre-push hook runs the same before every push ([steps/ci.md](steps/ci.md)).

## 4. Acceptance criteria

1. All tests pass and lint is clean, and the DVC stage `gate` passes (`make ci`; result in `reports/gate.json`).
2. `make e2e` passes against the running stack, and `make ui` passes all 13 checks.
3. `dvc status` = up to date: every output comes from the committed code.
4. Every MLflow run of the final model stages has `git_dirty = False`.
5. A broken model version is never served: the gate refuses it, or the server rolls back (both observed: v3, v6).

## 5. Report

`reports/test_report.md` (written by `scripts/test_report.py`), with the commit and the result of each case.
The committed report comes from the CI stage `tests`, which has no running stack, so it shows the 5 end-to-end
tests as skipped. `make e2e` runs them against the stack: 5 of 5 pass.
