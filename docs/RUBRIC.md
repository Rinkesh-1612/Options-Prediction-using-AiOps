# Evaluation guideline → where to find it

Course: DA3408 "AI Application Evaluation Guideline". One row per item. Short notes per lifecycle step are in
[docs/steps/](steps/).

## Mandatory documents

| Document | File |
|---|---|
| Architecture diagram + blocks | [ARCHITECTURE.md](ARCHITECTURE.md), [architecture.svg](architecture.svg) |
| High-level design (choices, rationale) | [HLD.md](HLD.md), [hld.svg](hld.svg) |
| Low-level design (endpoints, I/O) | [LLD.md](LLD.md) (a test checks it equals the real routes) |
| Test plan + test cases | [TEST_PLAN.md](TEST_PLAN.md), report [reports/test_report.md](../reports/test_report.md) |
| User manual (non-technical) | [USER_MANUAL.md](USER_MANUAL.md) |

## Items

| Item | Evidence |
|---|---|
| UI/UX, user manual | `frontend/` (one page, light + dark, phone width), guided tour, [USER_MANUAL.md](USER_MANUAL.md); browser audit `make ui` 13/13 ([reports/ui_audit.md](../reports/ui_audit.md)) |
| ML pipeline visualization | "How it's built" tab: live DVC DAG, speed per stage, runs with totals and a "Failed only" filter, run logs, data quality; Controls tab (management console): run the pipeline (`dvc repro gate`), retrain, rollback, links to MLflow (5050) and Grafana (3001) |
| Design, OO / functional | [HLD.md](HLD.md) §2–3; functional stages + small classes (models, API) |
| Loose coupling | page ↔ API only by REST; address in `frontend/config.json` |
| Coding style, logging, exceptions, comments | ruff (PEP 8) in CI; run journal `runs/runs.jsonl` + `logs/<stage>/`; docstrings per module |
| Unit tests, test report | 129 cases (124 pass, 5 e2e skip without the stack; e2e 5/5 with it); `make e2e` with the stack |
| Data engineering (Spark / Ray) | Spark: stage `check`. Ray: per-day stages, Ray Tune. Speed: [HLD.md](HLD.md) §8 |
| CI with DVC, DVC DAG, Git / LFS / DVC | [steps/ci.md](steps/ci.md): DAG ends in `tests` → `gate`; `make ci` = `dvc repro gate` |
| Experiment tracking | MLflow experiments `nifty-zoo`, `nifty-vol`; params, metrics, artifacts, git commit tags ([HLD.md](HLD.md) §6) |
| Prometheus + Grafana | 8 scrape targets (api, mlflow, host, Prometheus, Alertmanager, Grafana, blackbox probes of page + model) + runner heartbeat; 10 alert rules; one dashboard ([HLD.md](HLD.md) §7) |
| Packaging | MLflow Serve (model), [MLproject](../MLproject), FastAPI (API), Docker images, Compose with separate `frontend` and `api` services |

## Results (honest)

- Volatility forecast: beats the option market on 10 of 10 unseen days (QLIKE −0.20, 95% CI below 0).
- Call/put direction: no edge after costs (about −₹1,376 a day on unseen days).
- Vol-gate strategy study ([steps/strategy_search.md](steps/strategy_search.md)): no structure pays after costs.

## Not done or not used (say so in the viva)

- Not used: Ray Serve, Kubernetes, Swarm, Docker Hub push, cloud CI (cloud is not allowed).
- DVC remote is a folder on the same disk, not off-machine.
- No strategy-picking rule or equity curve on the page. Margin for short strategies is not modelled.
