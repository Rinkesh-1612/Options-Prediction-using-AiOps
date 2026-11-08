# Options-Prediction-using-AiOps

DA3408 course project. A full AIOps pipeline on my own NIFTY option data (Upstox → Ravion V2): data engineering,
tracking, gated deployment, monitoring and retraining. It forecasts **how much NIFTY will move** in the next 5 / 15
minutes (volatility), and tests whether **buying calls or puts after costs** pays (direction). It is also a signal
library for the author's trading system (Ravion V2).

**Results.**
- **Volatility: predictable.** A HAR forecaster beat the option market's implied forecast on **10 of 10** unseen test
  days (daily QLIKE −0.20, 95% interval −0.37 … −0.07) ([results](reports/vol/comparison.md)).
- **Direction: no edge.** Nine model families, 39 training days, 10 later test days: none beats "stay out" after costs
  ([results](reports/zoo/comparison.md)). Option structures, expiries and strikes chosen by ML found nothing either
  (research branches).

![Forecast tab](docs/img/forecast.png)

## Documents

| | |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | diagram, blocks, ports, versioning |
| [High-level design](docs/HLD.md) | problem, design rules, decisions, technology map |
| [Low-level design](docs/LLD.md) | every API endpoint and pipeline stage with its input and output |
| [Test plan](docs/TEST_PLAN.md) | levels, 126 test cases, acceptance criteria; report in `reports/test_report.md` |
| [User manual](docs/USER_MANUAL.md) | the web page for a non-technical user, with screenshots; operator commands |
| [Viva notes](docs/VIVA_NOTES.md) | short answers to likely questions |
| [Rubric map](docs/RUBRIC.md) | each evaluation item → where it is; results; what is not done |
| [CI with DVC](docs/steps/ci.md) | the DVC DAG as the CI pipeline, the acceptance gate |
| [Lifecycle steps](docs/steps/) | one short note per course step |

## Layout

| Path | What |
|---|---|
| `src/optpred/data/` | `export` (ClickHouse → Parquet), `check` (Spark day check) |
| `src/optpred/eda/`, `transform/` | `clean`, `eda`, `grid` (Ray per day) |
| `src/optpred/featurelib/` | feature library (registry; every feature tested) |
| `src/optpred/labels/` | costs, triple-barrier labels |
| `src/optpred/zoo/` | model families, simulator, training (Ray Tune, MLflow), evaluation, deploy gate |
| `src/optpred/vol/` | volatility forecaster (second model, `nifty-vol`) |
| `src/optpred/drift/` | PSI drift (per day and online) |
| `src/optpred/serving/` | FastAPI signal API |
| `src/optpred/ci/` | CI acceptance gate (last DVC stage) |
| `frontend/`, `monitoring/`, `docker/` | web page (plain-language, responsive, light + dark); Prometheus, Alertmanager, Grafana; images |
| `dvc.yaml`, `params.yaml`, `MLproject` | the pipeline, every setting, the same commands as MLflow entry points |
| `tests/` | unit, integration, API, end-to-end; `tests/ui/` browser audit of the page |

## Run it

```bash
./pipe build                 # pipeline image (Python, Java/Spark, Ray, LightGBM, PyTorch)
export CH_PASSWORD=...       # only for the export stage (Ravion ClickHouse, read-only)
./pipe dvc repro             # the whole pipeline; deploys a new champion only if it passes the gate
./stack up -d --build        # web 8080 · API 8000 · MLflow 5050 · Grafana 3001 · Prometheus 9091
make ci                      # CI = ./pipe dvc repro gate: reruns what changed, lint + tests, acceptance gate
make test                    # all tests; `make e2e` against the running stack; `make help` for the rest
git config core.hooksPath .githooks   # run the CI (dvc repro gate) before every push
```

Without the ClickHouse data, `data/sample/` (Git LFS) holds one test day of features and labels, and
`dvc pull` restores all data from the DVC remote.

AI use: [AI_DISCLOSURE.md](AI_DISCLOSURE.md).
