# Rubric tracker (28 marks)

Source: `DA3408/AI Application Evaluation Guideline.pdf`. Every line of the rubric is
a question the grader asks; the "Evidence" column is the file or screen that answers it.
Status: DONE / PARTIAL / TODO. Updated whenever something lands.

## Demonstration (5)

| Rubric question | What we do | Evidence | Status |
|---|---|---|---|
| UX intuitive for the problem; usable by a non-technical user | One page: pick a past date + minute, big BUY CALL / BUY PUT / STAY OUT card, one plain sentence saying why, expected result after costs | `frontend/` | TODO |
| Foolproof; free of UI errors | Date/minute pickers only offer accepted days and valid minutes; every API failure shows a readable message, never a blank page | `tests/test_ui_*` | TODO |
| Colours, shapes, look and feel | One palette, green/red/grey for call/put/stay out, consistent in light and dark | `frontend/` | TODO |
| Responsive | Works at phone width (the operator uses a phone) | screenshot in test report | TODO |
| User manual exists | Written for a trader, not an engineer, with screenshots | `docs/USER_MANUAL.md` | TODO |
| Separate screen visualising the ML pipeline incl. data engineering | "Pipeline" tab: the DVC DAG drawn from `dvc.yaml`, each stage's last run, status, duration, rows/sec | `frontend/` Pipeline tab | TODO |
| Pipeline management console: errors, failures, successes | Same tab: table of every run from `runs/runs.jsonl` (green/red), log viewer, retrain and rollback buttons | `runs/runs.jsonl` (already written) | PARTIAL |
| Speed and throughput of the pipeline | Each Spark stage logs rows/sec; shown on the tab | `reports/quality.json`, run summaries | PARTIAL |
| Orchestration across tools | Links from the tab to the MLflow and Grafana UIs | `frontend/` | TODO |

## Software engineering (5)

| Rubric question | What we do | Evidence | Status |
|---|---|---|---|
| Design document; OO or functional paradigm stated | HLD states: functional pipeline stages (pure functions over DataFrames) + small classes for API and registry client | `docs/HLD.md` | TODO |
| LLD with every endpoint and its I/O | Table per endpoint: method, path, request schema, response schema, errors; generated check that FastAPI's OpenAPI matches the document | `docs/LLD.md` + `tests/test_openapi_matches_lld` | TODO |
| Architecture diagram; HLD diagram | Two diagrams: components (containers and ports) and data flow | `docs/architecture.svg`, `docs/HLD.md` | TODO |
| Frontend / backend loosely coupled over configurable REST | Frontend is static files in its own container; backend URL read from `config.json` at load time; no shared code | `docker-compose.yml` | TODO |
| Python style standard | `ruff` with line length 110; runs in the pre-push hook | `pyproject.toml` | DONE |
| Logging | Every stage logs to file and console; journal per run | `logs/`, `src/optpred/runlog.py` | DONE |
| Comprehensive exception handling | Typed errors (`ExportError`, ...), stages return non-zero codes, API returns structured errors, crashes are journaled | `export.py`, `runlog.py` | PARTIAL |
| Inline documentation | Each module starts with what it does and the conventions it relies on | all modules | DONE so far |
| APIs follow the design doc | Test compares live OpenAPI to LLD | `tests/` | TODO |
| Unit tests | pytest; currently 6 | `tests/` | PARTIAL |
| Test plan; list of test cases; report with counts of passed and failed; acceptance criteria met | Acceptance criteria written **before** the final run; report generated from pytest's own output, not typed by hand | `docs/TEST_PLAN.md`, `reports/test_report.md` | TODO |

## AIOps implementation (10)

| Rubric question | What we do | Evidence | Status |
|---|---|---|---|
| Data ingestion / transformation pipeline on Ray, Spark or K8s | Spark `check` and `bars`; Ray Tune for the model search. Two of the three named tools | `check.py`, `bars.py` | DONE (code), first real run pending |
| Throughput and speed | rows/sec logged for each Spark stage, compared at 2 and 4 cores | run summaries | PARTIAL |
| CI implemented with DVC; DVC DAG shown | `dvc.yaml` with all stages; `dvc dag` output in the manual; pre-push hook runs ruff, pytest and `dvc status` | `dvc.yaml`, `.githooks/pre-push` | PARTIAL |
| Git, Git LFS and DVC all used | Git for code, **Git LFS for a one-day sample Parquet**, DVC for data and models with a local remote on the VPS | `.gitattributes`, `.dvc/config` | TODO |
| Experiments tracked: metrics, params, artifacts | Every model run: params, seed, git commit, data hash, per-day P&L, confusion table, SHAP plot, model | MLflow | TODO |
| Beyond autolog | Manual logging of per-day results, cost parameters, baseline comparisons, data-quality report, run journal entry | MLflow | TODO |
| Prometheus instrumentation: what is monitored, are **all** components monitored | API (requests, latency, predictions by class), pipeline (stage duration, rows, failures via pushgateway), MLflow, host (node exporter), model (drift score per feature) | `monitoring/prometheus.yml` | TODO |
| Grafana in near real time | 5-second scrape; replay mode feeds a past day minute by minute so the dashboard moves live during the demo | `monitoring/grafana/` | TODO |
| MLflow used to expose the model | `mlflow models serve` container behind the FastAPI service | `docker-compose.yml` | TODO |
| MLproject used for identical dev/test environments | `MLproject` + `environment.yml` | repo root | TODO |
| FastAPI exposes what the UI needs | `/predict`, `/minutes`, `/pipeline/runs`, `/retrain`, `/rollback`, `/healthz`, `/metrics` | `api/` | TODO |
| Backend and frontend dockerised, **two separate Compose services** | `api`, `frontend` (plus mlflow, prometheus, grafana) | `docker-compose.yml` | TODO |

## Viva (5)

| Rubric line | Preparation | Status |
|---|---|---|
| Explain the entire project | One-page summary in plain words, in the operator's own wording | TODO |
| Answer questions from Assignments 1-10 | Review `Mod1`, `Mod3` assignments and TA solutions; know DVC rollback, MLflow comparison, multi-stage Docker, Compose vs Kubernetes | TODO |
| MLOps tools and use cases | Why each tool is here and what it replaced | TODO |
| Design and implementation choices | PLAN.md §14 | PARTIAL |
| Defend choices when challenged | Known weaknesses stated up front: 10 test days is small, slippage assumption, one market regime | TODO |

## Mandatory documents

| Document | File | Status |
|---|---|---|
| Architecture diagram with explanation of blocks | `docs/ARCHITECTURE.md` | TODO |
| High-level design | `docs/HLD.md` | TODO |
| Low-level design (endpoints and I/O) | `docs/LLD.md` | TODO |
| Test plan and test cases | `docs/TEST_PLAN.md` | TODO |
| User manual for a non-technical user | `docs/USER_MANUAL.md` | TODO |
| AI disclosure (code of conduct) | `AI_DISCLOSURE.md` | DONE |

## Deliberate choices that cost marks, so we know them

- **Kubernetes is not used.** The rubric names "Ray or Spark or Kubernetes", so Spark and Ray cover the line. On a shared VPS, adding a cluster adds risk to live trading for no extra mark.
- **No GPU, no cloud.** Not allowed or not needed.
- **If the model finds no edge**, the demo still scores fully on this rubric: it grades the system and the honesty of the measurement, not the profit.
