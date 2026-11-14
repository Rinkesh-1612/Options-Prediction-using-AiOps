# Course guidelines → where to find it

Course: DA3408. First the "AI Application Evaluation Guideline", one row per item; then the "AI Application
Development Guidelines". Short notes per lifecycle step are in
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
| Design, OO / functional | [HLD.md](HLD.md) §2 and §3; functional stages + small classes (models, API) |
| Loose coupling | page ↔ API only by REST; address in `frontend/config.json` |
| Coding style, logging, exceptions, comments | ruff (PEP 8) in CI; run journal `logs/runs.jsonl` + `logs/<stage>/`; docstrings per module |
| Unit tests, test report | 110 cases (105 pass, 5 e2e skip without the stack; e2e 5/5 with it); `make e2e` with the stack |
| Data engineering (Spark / Ray) | Spark: stage `check`. Ray: per-day stages, Ray Tune. Speed: [HLD.md](HLD.md) §8 |
| CI with DVC, DVC DAG, Git / LFS / DVC | [steps/ci.md](steps/ci.md): DAG ends in `tests` → `gate`; `make ci` = `dvc repro gate` |
| Experiment tracking | MLflow experiments `nifty-zoo`, `nifty-vol`; params, metrics, artifacts, git commit tags ([HLD.md](HLD.md) §6) |
| Prometheus + Grafana | 8 scrape targets (api, mlflow, host, Prometheus, Alertmanager, Grafana, blackbox probes of page + model) + runner heartbeat; 10 alert rules; one dashboard, 5 s refresh; `make demo` replays the unseen days through the API so it moves ([HLD.md](HLD.md) §7) |
| Packaging | MLflow Serve (model), [MLproject](../MLproject), FastAPI (API), Docker images, Compose with separate `frontend` and `api` services |

## Development guidelines

| Guideline | Where |
|---|---|
| I. Automation | `dvc repro` runs ingest → check → clean → features → train → evaluate → deploy; alerts start retraining ([steps/monitoring.md](steps/monitoring.md)) |
| I. Reproducibility (Git commit + MLflow run ID) | every MLflow run has the tags `git_commit`, `git_dirty` and the DVC data hashes; the final model runs are on a clean commit; run journal `logs/runs.jsonl` |
| I. Continuous integration | [steps/ci.md](steps/ci.md) |
| I. Monitoring and logging | [HLD.md](HLD.md) §7; one log per stage run in `logs/`; the API logs failed requests |
| I. Collaboration | shared MLflow UI, Grafana and the web page; Git history; these documents |
| I. Version control | Git (code, params, reports), Git LFS (sample day), DVC (data), MLflow registry (models) |
| I. Environment parity | every stage runs in the pipeline image (`./pipe`); services in Docker Compose; one `requirements.txt` |
| II.A Problem definition, data collection, EDA | [steps/business_understanding.md](steps/business_understanding.md), [steps/data_identification.md](steps/data_identification.md), [steps/eda.md](steps/eda.md) |
| II.B Preprocessing, feature engineering | [steps/cleaning_transformation.md](steps/cleaning_transformation.md), [steps/feature_engineering.md](steps/feature_engineering.md); feature importance in `reports/zoo/importance.json` |
| II.C Model selection, training, evaluation | [steps/model_selection.md](steps/model_selection.md), [steps/model_training.md](steps/model_training.md), [steps/vol_model.md](steps/vol_model.md) |
| II.D Deployment, serving, rollback | [steps/deployment.md](steps/deployment.md) |
| II.E Monitoring, drift, retraining, model versions | [steps/monitoring.md](steps/monitoring.md) |
| IV. Code quality, testing | ruff in CI; unit, integration, API, end-to-end tests ([TEST_PLAN.md](TEST_PLAN.md)) |
| IV. Security (encryption) | `scripts/encrypt_snapshot.sh` (AES-256 backup of data and models); admin token; localhost by default |
| IV. Scalability, explainability, documentation | [HLD.md](HLD.md) §5; SHAP per signal on the page (Explore step 4) |
| AI fair-use code of conduct | [AI_DISCLOSURE.md](../AI_DISCLOSURE.md): tools, how they were used, impact |

## Results

- Volatility forecast: beats the option market on 10 of 10 unseen days (QLIKE −0.20, 95% CI below 0).
- Call/put direction: no edge after costs (about −₹1,376 a day on unseen days).

## Not done or not used

- Not used: Ray Serve, Kubernetes, Swarm, Docker Hub push, cloud CI (cloud is not allowed).
- DVC remote is a folder on the same disk, not off-machine.
- Removed on 2026-11-11 to keep the project simple (in Git history): 6 direction model families (GRU, Transformer, meta-label, LightGBM classifier, momentum, random), the LightGBM volatility model, the option strategy simulator, the `modelout` stage.
