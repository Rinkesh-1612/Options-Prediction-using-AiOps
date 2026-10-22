# Rubric tracker (28 marks)

Source: `DA3408/AI Application Evaluation Guideline.pdf`. Each line is a question the grader asks.
"Evidence" names the file or screen that answers it.
Status: DONE (built and checked), BUILT (written, not yet run end to end), TODO.
Last full update: 2026-10-19.

## Demonstration (5)

| Rubric question | What we do | Evidence | Status |
|---|---|---|---|
| UX intuitive; usable by a non-technical user | One page: pick a day and minute. A large answer card says call, put or stay out, with one plain sentence. | `frontend/index.html` | DONE |
| Foolproof; free of UI errors | Pickers offer only valid days and minutes. API errors show as readable banners. | `frontend/index.html`, `tests/test_frontend.py` | DONE |
| Colours, shapes, look and feel | One palette. Green, red, grey. Light and dark theme. | `frontend/index.html` | DONE |
| Responsive | Works at phone width. | `frontend/index.html` (grid and media query) | BUILT (no screenshot yet) |
| User manual | Written for a trader. | `docs/USER_MANUAL.md` | DONE (no screenshots yet) |
| Screen that shows the ML pipeline, incl. data engineering | "Pipeline" tab draws the DVC DAG from `dvc.yaml`. Colour = last run. | Pipeline tab | DONE |
| Pipeline console: errors, failures, successes | Same tab lists every run from `runs/runs.jsonl`. Tap a row for its log. Retrain and rollback buttons. | Pipeline tab, `/pipeline/runs` | DONE |
| Speed and throughput of the pipeline | Rows per second per Spark stage, in the Runs table and in Grafana. | `runs/runs.jsonl`, Grafana row 4 | DONE |
| Orchestration across tools | Links to MLflow and Grafana from the Pipeline tab. | Pipeline tab | DONE |

## Software engineering (5)

| Rubric question | What we do | Evidence | Status |
|---|---|---|---|
| Design document; OO or functional paradigm | HLD section 4: functional stages, a few small classes. | `docs/HLD.md` | DONE |
| LLD with every endpoint and its I/O | One heading per endpoint. A test compares the headings with the live OpenAPI. | `docs/LLD.md`, `test_openapi_matches_the_low_level_design` | DONE |
| Architecture diagram; HLD diagram | One SVG with all blocks, ports and flows. | `docs/architecture.svg`, `docs/ARCHITECTURE.md` | DONE |
| Frontend and backend loosely coupled over configurable REST | Static page in its own container. Address from `config.json`. | `docker-compose.yml`, `tests/test_frontend.py` | DONE |
| Python style standard | `ruff`, line length 110. Runs in the pre-push hook. | `pyproject.toml`, `.githooks/pre-push` | DONE |
| Logging | Every stage writes a log file and a journal line. The API logs to the console. | `logs/`, `runlog.py` | DONE |
| Exception handling | Typed errors per module (`ExportError`, `FeatureError`, `TuneError`, `ReplayError`). Stages return non-zero and still journal. The API returns structured errors. | `src/optpred/` | DONE |
| Inline documentation | Each module starts with what it does and the rules it keeps. | all modules | DONE |
| APIs follow the design doc | Test compares OpenAPI with the LLD. | `tests/test_api.py` | DONE |
| Unit tests | pytest, 67 cases, all passing (`reports/test_report.md`). | `tests/` | DONE |
| Test plan, cases, report with counts, acceptance criteria | Plan with 26 named cases and 7 acceptance criteria. The report is generated from pytest output. | `docs/TEST_PLAN.md`, `reports/test_report.md` | DONE |

## AIOps implementation (10)

| Rubric question | What we do | Evidence | Status |
|---|---|---|---|
| Data pipeline on Ray, Spark or K8s | Spark for `check` and `bars`. Ray Tune for the settings search. | `check.py`, `bars.py`, `tune.py` | DONE (real runs in the journal) |
| Throughput and speed | `check` and `bars` log rows per second. | `runs/runs.jsonl` | DONE |
| CI with DVC; DVC DAG | `dvc.yaml` has seven stages. The pre-push hook runs ruff, pytest, `dvc dag`, `dvc status`. | `dvc.yaml`, `.githooks/pre-push` | DONE (hook not yet exercised by a real push) |
| Git, Git LFS and DVC | Git: code. LFS: one-day sample. DVC: data and models, local remote `/home/trader/dvc-remote`. | `.gitattributes`, `.dvc/config`, `dvc.lock` | BUILT (first LFS push pending) |
| Experiments tracked: metrics, params, artifacts | Params, seed, git commit, data hashes, metrics, plots, model. | MLflow | DONE |
| Beyond autolog | Manual logging of day-level results, costs, baselines, tuning trials. | `train.py`, `tune.py` | DONE |
| Prometheus: what is monitored; are all components monitored | API, MLflow, host, Prometheus, pipeline journal, model service (via the API), drift. | `monitoring/prometheus.yml`, `docs/LLD.md` | DONE (all four targets UP) |
| Grafana in near real time | 5 s scrape and refresh. Replay feeds a moving stream. | `monitoring/grafana/dashboards/optpred.json` | DONE (checked through the API; look at it once by eye) |
| MLflow exposes the model | `mlflow models serve` behind the API. Follows the `champion` alias. | `docker-compose.yml`, `scripts/serve_model.sh` | DONE |
| MLproject | `MLproject` runs every stage in the pipeline image. `environment.yml` rebuilds without Docker. | `MLproject`, `environment.yml` | BUILT (not run with `mlflow run`) |
| FastAPI exposes what the UI needs | 13 endpoints. | `docs/LLD.md` | DONE |
| Backend and frontend in two Compose services | `api` and `frontend`, plus 8 more services. | `docker-compose.yml` | DONE |
| Drift, retrain, rollback | PSI on served rows → `DriftDetected` → Alertmanager → API → runner → candidate. Rollback swaps aliases. | `drift.py`, `monitoring/alerts.yml` | DONE (chain ran once for real: registry version 2 was trained and not promoted) |
| Encrypted data snapshot | AES-256 with GnuPG. Verified by decrypting and comparing the checksum. | `scripts/encrypt_snapshot.sh` | DONE |

## Viva (5)

| Rubric line | Preparation | Status |
|---|---|---|
| Explain the entire project | One-minute summary in `docs/VIVA.md`. Put it in your own words. | YOURS |
| Answer questions from Assignments 1-10 | Review the Mod1 and Mod3 assignments and TA solutions. | YOURS |
| MLOps tools and use cases | Table in `docs/VIVA.md`. | YOURS |
| Design and implementation choices | `PLAN.md` section 14, `docs/HLD.md` section 3. | YOURS |
| Defend choices when challenged | Known limits are in `docs/HLD.md` section 7. | YOURS |

## Mandatory documents

| Document | File | Status |
|---|---|---|
| Architecture diagram with explanation | `docs/ARCHITECTURE.md`, `docs/architecture.svg` | DONE |
| High-level design | `docs/HLD.md` | DONE |
| Low-level design | `docs/LLD.md` | DONE |
| Test plan and test cases | `docs/TEST_PLAN.md`, `reports/test_report.md` | DONE |
| User manual | `docs/USER_MANUAL.md` | DONE |
| AI disclosure | `AI_DISCLOSURE.md` | DONE (update the tool list for this session's work) |

## Still open

1. Locked test run (`--final`). Do it once, at the end. It is your decision. See `PLAN.md` section 3.
2. Commit the new work and push. Runs journaled before the commit show `git_dirty: true`.
3. Screenshots for the manual and the test report (phone width, Grafana).
4. Run `mlflow run . -e test` once to prove `MLproject`.

## Deliberate choices that cost marks

* **Kubernetes is not used.** The rubric says "Ray or Spark or Kubernetes". Spark and Ray cover it. A cluster on the live-trading server adds risk and no mark.
* **No GPU, no cloud.** Not allowed or not needed.
* **No edge found.** The rubric grades the system and the honesty of the measurement.
