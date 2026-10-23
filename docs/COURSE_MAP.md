# Course map

Each line of `docs/AI Application Evaluation Guideline.pdf` → the part of the project that answers it → the evidence.
Code paths are under `src/optpred/`. Commands assume the repository root (`make help` lists them).

## Repository layout

| Folder | Course component | Contents |
|---|---|---|
| `src/optpred/common/` | Logging, reproducibility | run journal (`runlog`), session clock, Spark session |
| `src/optpred/data/` | Data engineering (Spark) | `export`, `check`, `bars`, `ticks` |
| `src/optpred/features/` | Feature engineering | `labels` (costs), `minute` (v1), `micro` (v2) |
| `src/optpred/models/` | Experiment tracking (MLflow, Ray Tune) | `sim`, `baselines`, `tune`, `train`, `register`, `evaluate`, `micro_train`, `micro_evaluate`, `sprint` |
| `src/optpred/serving/` | Packaging (MLflow serve, FastAPI) | `serving_model` (pyfunc), `api` |
| `src/optpred/monitoring/` | Monitoring code | `drift` (PSI), `replay` |
| `monitoring/` | Prometheus, Alertmanager, Grafana | scrape config, alert rules, dashboard |
| `frontend/` | Web UI | static page, nginx, its own Dockerfile |
| `docker/` | Containers | pipeline image, serving image (multi-stage), naive image for the size comparison |
| `dvc.yaml`, `params.yaml` | CI with DVC | the pipeline graph and every setting |
| `tests/` | Testing | `unit/`, `integration/`, `api/`, `helpers/` |
| `docs/` | Mandatory documents | architecture, HLD, LLD, test plan, user manual, results, protocols |

## Demonstration (5)

| Rubric line | Answer | Evidence |
|---|---|---|
| UX intuitive, usable by a non-technical user | Three tabs: Pick a minute, Results, Pipeline. Plain sentences, no jargon on the main card. | `frontend/index.html`, `docs/img/*.png` |
| Foolproof, free of UI errors | Pickers offer only valid values. API errors show as readable banners. | `tests/api/test_frontend.py` |
| Colours, look and feel; responsive | One palette, light and dark. Phone layout hides secondary columns. | `docs/img/predict-phone.png`, `docs/img/results-phone.png` |
| User manual | Written for a trader, with screenshots. | `docs/USER_MANUAL.md` |
| Screen for the ML pipeline incl. data engineering | Pipeline tab draws the DVC graph from `dvc.yaml`; colour = last run. | `docs/img/pipeline-desktop.png` |
| Pipeline management console; errors, failures, successes | Runs table from the journal; tap a row for its log; Retrain and Roll back buttons. | `runs/runs.jsonl`, `logs/` |
| Speed and throughput | Rows per second per Spark stage, in the console and in Grafana. | journal lines of `check`, `bars`, `ticks` |

## Software engineering (5)

| Rubric line | Answer | Evidence |
|---|---|---|
| Design document; OO or functional | Functional stages (files in, files out); small classes in the API and models. | `docs/HLD.md` section 4 |
| LLD with endpoint I/O | One heading per endpoint. A test compares it with the live OpenAPI. | `docs/LLD.md`, `tests/api/test_api.py` |
| Architecture and HLD diagrams | One diagram, every block explained. | `docs/architecture.svg`, `docs/ARCHITECTURE.md` |
| Loose coupling over configurable REST | The page knows only `config.json`; a test checks every path it calls is in the LLD. | `frontend/config.json`, `tests/api/test_frontend.py` |
| Coding style | ruff, PEP 8 rules declared in `pyproject.toml`; formatter applied. | `make lint` |
| Logging | Every stage writes a log file and a journal line (commit, params hash, status, duration). | `src/optpred/common/runlog.py` |
| Exception handling | Typed errors per stage; non-zero exit still journals; the API returns readable 4xx/5xx. | `src/optpred/serving/api.py` |
| Inline documentation | Each module states what it does and the rules it keeps. | module docstrings |
| Unit tests | 87 tests in `unit/`, `integration/`, `api/`. | `reports/test_report.md` |
| Test plan, cases, report, acceptance | Plan with 42 named cases and 8 criteria; acceptance record. | `docs/TEST_PLAN.md` |

## AIOps implementation (10)

| Rubric line | Answer | Evidence |
|---|---|---|
| Data pipeline on Spark / Ray | Spark: `check`, `bars` (86 M ticks), `ticks` (32 M ticks → 20.6 M contract-seconds with window functions). Ray Tune: `tune`. | `src/optpred/data/`, `src/optpred/models/tune.py` |
| Throughput | `ticks`: about 27,000 ticks/s; `check`: about 363,000 rows/s. | `runs/runs.jsonl` |
| CI with DVC, DVC DAG | `dvc.yaml` chains 14 stages; the pre-push hook runs lint, tests, `dvc dag`. | `make dag`, `.githooks/pre-push` |
| Git, Git LFS, DVC versioning | Git: code. LFS: one-day sample. DVC: data, local remote. MLflow registry: models. | `.gitattributes`, `.dvc/config`, `dvc.lock` |
| Experiment tracking beyond autolog | Params, seed, commit, data hashes, day-level results, baselines, threshold tables, feature importance. | MLflow experiment `nifty-option-direction` |
| Prometheus instrumentation | API requests, latency, predictions vs outcome, drift (PSI), pipeline journal, MLflow, host. | `monitoring/prometheus.yml` |
| Grafana in near real time | 5 s refresh; replay feed for demos; drift and retrain visible. | `docs/img/grafana.png`, `docs/img/grafana-drift.png` |
| MLflow to expose the model | `mlflow models serve` of the `champion` alias behind the API. | `docker-compose.yml` service `model` |
| MLproject | Entry points run in the pipeline image; `mlflow run . -e test` passes. | `MLproject`, `reports/mlproject_test_run.log` |
| FastAPI for the UI | 15 endpoints, all in the LLD. | `src/optpred/serving/api.py` |
| Dockerised front end and back end, Compose | Separate services `frontend` and `api`, plus model, MLflow, runner, monitoring. | `docker-compose.yml`, `docker/` |
| Drift → retrain, rollback | PSI → `DriftDetected` → Alertmanager → API → runner (`dvc repro train register`). Observed end to end. | `docs/TEST_PLAN.md` section 9 |
| Encryption | AES-256 snapshot, key outside the repo. | `scripts/encrypt_snapshot.sh` |

## Results and honesty

| Item | Where |
|---|---|
| v1 one-time test on locked days | `docs/RESULTS.md`, `docs/FINAL_TEST_PROTOCOL.md` |
| v2 second-level model | `docs/V2_PROTOCOL.md`, `reports/micro_train.json`, `reports/micro_final.json` (held-out, one look) |
| Alpha sprint (six trials, 99% bar) | `docs/ALPHA_SPRINT.md`, `reports/sprint.json` |
