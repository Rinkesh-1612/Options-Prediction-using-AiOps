# Options-Prediction-using-AiOps

DA3408 course project. Every second of the NIFTY session: buy the ATM call, buy the ATM put, or stay out —
judged **after costs**, with a holding time set by the market (triple barrier). Built as a controlled AIOps
pipeline, and as a signal library for the author's trading system (Ravion V2).

**Result: no edge detected.** Nine model families were trained on 39 days and scored on 10 later test days.
None beats "stay out" with confidence after costs ([Results](reports/zoo/comparison.md)).

![Signal tab](docs/img/signal.png)

## Documents

| | |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | diagram, blocks, ports, versioning |
| [High-level design](docs/HLD.md) | problem, design rules, decisions, technology map |
| [Low-level design](docs/LLD.md) | every API endpoint and pipeline stage with its input and output |
| [Test plan](docs/TEST_PLAN.md) | levels, 90 test cases, acceptance criteria; report in `reports/test_report.md` |
| [User manual](docs/USER_MANUAL.md) | the web page, tab by tab; operator commands |
| [Rubric steps](docs/steps/PROGRESS.md) | one short note per course item |

## Layout

| Path | What |
|---|---|
| `src/optpred/data/` | `export` (ClickHouse → Parquet), `check` (Spark day check) |
| `src/optpred/eda/`, `transform/` | `clean`, `eda`, `grid` (Ray per day) |
| `src/optpred/featurelib/` | feature library (registry + CI) |
| `src/optpred/labels/` | costs, triple-barrier labels |
| `src/optpred/zoo/` | model families, simulator, training (Ray Tune, MLflow), evaluation, deploy gate |
| `src/optpred/drift/` | PSI drift (per day and online) |
| `src/optpred/serving/` | FastAPI signal API |
| `frontend/`, `monitoring/`, `docker/` | web page; Prometheus, Alertmanager, Grafana; images |
| `dvc.yaml`, `params.yaml` | the pipeline and every setting |
| `tests/` | unit, integration, API, end-to-end |

## Run it

```bash
./pipe build                 # pipeline image (Python, Java/Spark, Ray, LightGBM, PyTorch)
export CH_PASSWORD=...       # only for the export stage (Ravion ClickHouse, read-only)
./pipe dvc repro             # the whole pipeline; deploys a new champion only if it passes the gate
./stack up -d --build        # web 8080 · API 8000 · MLflow 5050 · Grafana 3001 · Prometheus 9091
make test                    # all tests; `make e2e` against the running stack; `make help` for the rest
git config core.hooksPath .githooks   # CI: lint + tests + dvc dag before every push
```

Without the ClickHouse data, `data/sample/` (Git LFS) holds one test day of features and labels, and
`dvc pull` restores all data from the DVC remote.

AI use: [AI_DISCLOSURE.md](AI_DISCLOSURE.md).
