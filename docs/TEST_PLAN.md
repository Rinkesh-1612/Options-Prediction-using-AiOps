# Test plan

## 1. Scope and levels

| Level | Folder | What it proves | Runs |
|---|---|---|---|
| Unit | `tests/unit/` | Each rule and function alone: cleaning rules, fill policy, grid, every feature, labels and costs, simulator, every model family, deploy gate, PSI, Ray map | every push |
| Integration | `tests/integration/` | Real stage `main`s on synthetic raw data: check (Spark) → clean → grid → feat → labels | every push |
| API | `tests/api/` | Every endpoint with a fake model server and registry; LLD = real routes; page calls only documented paths | every push |
| End-to-end | `tests/e2e/` | The running stack: API → model server → registry, web page, Prometheus | `make e2e` with the stack up |

Synthetic data: `tests/helpers/synth.py` (raw tables in the export schema), `tests/helpers/grid_synth.py`
(one grid day). No test needs the real data.

## 2. Test cases (90)

| ID | Area | Cases | File |
|---|---|---|---|
| T1 | Export | TSV counts, row-count check rejects a short file, run journal on success and failure | `unit/test_export.py` (4) |
| T2 | Cleaning | outlier rules counted; index closing print; forward fill respects the age limit; never uses the future | `unit/test_eda_rules.py` (4) |
| T3 | Grid | legs follow ATM; no future quote | `unit/test_grid.py` (1) |
| T4 | Features | for each of the 10 features: docstring and rows, **no look-ahead**, values after the lookback; unique columns; all float | `unit/test_featurelib.py` (33) |
| T5 | Labels | cost = contract note (₹18.13); take-profit, stop-loss, time limit; follows the bought contract when ATM moves | `unit/test_barrier.py` (3) |
| T6 | Models and simulator | each of 9 families fits and scores; trees find a planted signal; one position at a time; NaN never trades; walk-forward folds; no-score model never trades | `unit/test_zoo.py` (14) |
| T7 | Deployment | failed smoke test is not deployed; passed version → champion, old → previous; first deployment | `unit/test_promote.py` (3) |
| T8 | Drift | same distribution low PSI, shift high; NaN share change; monitor waits for rows, then flags | `unit/test_psi.py` (3) |
| T9 | Ray | day results keep their order | `unit/test_parallel.py` (1) |
| T10 | Data pipeline | holiday rejected, duplicates counted; session rows only; 22,500 grid rows with legs, ask > bid; float features; labels aligned | `integration/test_data_pipeline.py` (5) |
| T11 | API | signal without future rows; hindsight; blocked entry; losing trade metric; 404 / 503; rollback token and swap; alert → one retrain then cooldown; drift and gauges; data-quality gauges; pipeline graph, runs, log (path attack refused); inf → null | `api/test_signal_api.py` (12) |
| T12 | Contract | LLD = routes; page uses documented paths only | `api/test_lld.py` (2) |
| T13 | End-to-end | served model passed the gate; test-day signal round trip; reports, pipeline, metrics; web page and config; Prometheus scrapes the API | `e2e/test_stack.py` (5) |

## 3. How to run

```bash
make test        # unit + integration + API (e2e is skipped without the stack)
make e2e         # end-to-end, after ./stack up -d
make report      # all tests -> reports/test_report.md (numbers copied from pytest's JUnit file)
./pipe bash -c "E2E_API_URL=http://127.0.0.1:8000 python scripts/test_report.py"   # report incl. e2e
```
The pre-push hook (`.githooks/pre-push`) runs ruff, all tests and `dvc dag` before every push.

## 4. Acceptance criteria

1. All tests pass (`make test` exit 0) and lint is clean (`make lint`).
2. `make e2e` passes against the running stack.
3. `dvc status` = up to date: every output comes from the committed code.
4. Every MLflow run of the final model stages has `git_dirty = False`.
5. A broken model version is never served: the gate refuses it, or the server rolls back (both observed: v3, v6).

## 5. Report

`reports/test_report.md` (written by `scripts/test_report.py`), with the commit and the result of each case.
Last report: 90 of 90 passed, including the 5 end-to-end tests against the running stack.
