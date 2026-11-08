# Architecture

One VPS, no cloud. Everything runs in Docker: the pipeline in one image (`./pipe`), the services with
Docker Compose (`./stack`). Ravion V2 (the author's live trading system) records the market data.

![Architecture diagram](architecture.svg)

*Left to right: the data source, the pipeline (DVC stages in the pipeline image), and the serving and monitoring stack (Docker Compose). Source of the picture: `scripts/make_diagrams.py`.*

| Block | What it does | Where |
|---|---|---|
| export | Copies the raw tables from ClickHouse to Parquet, read-only, row counts verified | `src/optpred/data/export.py` |
| check | Spark: accepts or rejects each day (coverage, frozen feed) | `src/optpred/data/check.py` |
| clean, eda | Ray tasks per day: outlier rules, missing values, profile and plots | `src/optpred/eda/` |
| grid | One aligned row per second: index, future, ATM ±2 option legs, ATM chain | `src/optpred/transform/` |
| feat | Feature library: registered, look-ahead-tested features | `src/optpred/featurelib/` |
| labels | Triple-barrier outcome of buying the ATM call / put each second | `src/optpred/labels/` |
| zoo_train | Walk-forward CV of 9 model families, Ray Tune, MLflow | `src/optpred/zoo/train.py` |
| zoo_eval | Test-day scores, champion chosen on CV, smoke test, deployment | `src/optpred/zoo/evaluate.py`, `promote.py` |
| vol | Second model: forecast of the NIFTY move over the next 5 / 15 min vs the implied move; registered `nifty-vol` | `src/optpred/vol/` |
| drift | PSI per day against the training days; reference for online drift | `src/optpred/drift/` |
| model | Serves the registry alias `nifty-signal@champion`; rolls back if a version does not start | `scripts/serve_model.sh` |
| api | The only public entry: signals, volatility forecasts (loads `nifty-vol`), results, pipeline, rollback, retrain, metrics | `src/optpred/serving/signal_api.py` |
| frontend | Static web page (4 tabs: Forecast, Does it work?, How it's built, Controls); knows only the API address | `frontend/` |
| Prometheus, Alertmanager, Grafana | Metrics every 5 s, 8 alert rules, one dashboard | `monitoring/` |
| runner | Runs `zoo_train` → `zoo_eval` when a retrain is requested (alert, button, schedule) | `scripts/runner.sh` |

**Ports** (bound to `127.0.0.1` unless `BIND` is set): web page 8080, API 8000, MLflow 5050, Grafana 3001,
Prometheus 9091.

**Versioning.** Git: code, configs, reports, run journal. Git LFS: one sample day. DVC: all data, local remote.
MLflow registry: models (aliases `champion`, `previous`; tag `deploy_check`). Encrypted backup of data and
models: `scripts/encrypt_snapshot.sh`.

## The pipeline as a DVC DAG (this is the CI pipeline)

`./pipe dvc dag` draws it from `dvc.yaml`. The "How it's built" tab of the web page draws the same graph from the live file.

```
export → check → clean → eda
                       → grid → feat, labels → zoo_train → zoo_eval ─┐
                              → vol ──────────────────────────────────┤
                              → drift, modelout                       │
tests (ruff + pytest + report) ───────────────────────────────────────┴→ gate
```

**CI and CD with DVC** ([steps/ci.md](steps/ci.md)). CI = `dvc repro gate`: a stage runs again only when its code, its
parameters or its input data changed; stage `tests` runs ruff and pytest; stage `gate` fails the run if an acceptance
criterion fails. The pre-push hook runs it. CD: `zoo_eval` registers a new model, the
smoke test checks it, and only then does the alias `champion` move. The model server follows the alias.

**Reproducibility.** Every MLflow run carries the Git commit, `git_dirty` and the DVC hash of its data. The run
journal (`runs/runs.jsonl`) records commit, parameters hash, duration and result of every stage run.
`MLproject` runs the same commands in the same image (`mlflow run . -e test`; log in `reports/mlproject_test_run.log`).
