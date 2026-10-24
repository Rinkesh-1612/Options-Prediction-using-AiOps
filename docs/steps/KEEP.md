# Keep list

Files and folders used by the reviewed work. Everything else is a candidate for deletion after review.
Updated at each step.

## Reviewed (keep)

| Path | Why |
|---|---|
| `docs/steps/` | reviewed write-ups, progress, this list |
| `docs/ARCHITECTURE.md`, `HLD.md`, `LLD.md`, `TEST_PLAN.md`, `USER_MANUAL.md`, `docs/img/`, `README.md`, `AI_DISCLOSURE.md` | documents |
| `src/optpred/common/clock.py`, `runlog.py`, `spark.py`, `parallel.py` | session clock, run journal, Spark (`check`), Ray per-day tasks |
| `src/optpred/data/export.py`, `check.py` | stages export, check |
| `src/optpred/eda/` | stages clean, eda (rules, fill policy) |
| `src/optpred/transform/` | stage grid |
| `src/optpred/featurelib/` | stage feat (feature library) |
| `src/optpred/labels/` | stage labels (costs, triple barrier) |
| `src/optpred/zoo/` | stages zoo_train, zoo_eval (data, simulator, models, seqnets, MLflow tracking, pyfunc, promote/deploy gate) |
| `src/optpred/vol/` | stage vol, second model `nifty-vol` (inputs, forecasters, pyfunc) |
| `src/optpred/drift/` | stage drift + online drift (PSI) |
| `src/optpred/serving/signal_api.py` | the API (signal, model, rollback, retrain, drift, webhook, metrics) |
| `monitoring/` (prometheus, alerts, alertmanager, grafana dashboard) | monitoring and alerting |
| `frontend/` (index.html, nginx.conf, Dockerfile, config.json, 40-config.sh) | the web page |
| `docker-compose.yml`, `stack`, `scripts/serve_model.sh`, `scripts/runner.sh` | serving stack, CD, rollback, retraining |
| `scripts/encrypt_snapshot.sh` | AES-256 encryption of data + models (`--verify` checks a backup) |
| `tests/unit/test_export.py`, `test_eda_rules.py`, `test_grid.py`, `test_featurelib.py`, `test_barrier.py`, `test_zoo.py`, `test_promote.py`, `test_psi.py`, `test_parallel.py`, `tests/api/test_signal_api.py`, `tests/integration/test_data_pipeline.py`, `tests/api/test_lld.py`, `tests/e2e/`, `tests/unit/test_vol.py`, `tests/unit/test_explain.py` | tests |
| `scripts/test_report.py`, `reports/test_report.md` | test report |
| `tests/helpers/grid_synth.py`, `tests/helpers/synth.py` | synthetic data for the tests |
| `dvc.yaml` stages `export`, `check`, `clean`, `eda`, `grid`, `feat`, `labels`, `zoo_train`, `zoo_eval`, `drift`, `vol` | pipeline |
| `params.yaml` sections `export`, `spark`, `check`, `eda`, `grid`, `feat`, `labels`, `zoo`, `drift`, `vol` | settings |
| `dvc.lock`, `.dvc/`, `.dvcignore`, `.gitignore`, `.gitattributes`, `data/.gitignore` | versioning |
| `pipe`, `docker/Dockerfile.pipeline`, `docker/Dockerfile.serve`, `requirements.txt` (the only one), `Makefile`, `pyproject.toml`, `.githooks/pre-push` | run environment, CI |
| `data/sample/` (Git LFS: one test day of feat + labels), `data/raw`, `data/days.json`, `data/clean`, `data/grid`, `data/feat`, `data/labels` | data (DVC) |
| `reports/quality.json`, `reports/eda/`, `reports/grid.json`, `reports/feat.json`, `reports/feature_catalog.md`, `reports/labels.json`, `reports/zoo/`, `reports/drift/`, `reports/vol/` | stage outputs |
| `runs/runs.jsonl`, `logs/{export,check,clean,eda,grid,feat,labels,zoo_train,zoo_eval,drift}/` | run journal |
| `mlflow/` (experiment `nifty-zoo`, model `nifty-signal`) | experiment tracking, registry |

## Not reviewed yet (decide in a later step)

`docker/Dockerfile.serve.naive` + `scripts/image_sizes.sh`
(image size comparison).

## Deleted on 2026-10-23 (in Git history before this date)

Old v1/v2 code, tests, docs, reports, logs, `MLproject`, `requirements-serve.txt`, data `bars/ticks/features/micro`.
