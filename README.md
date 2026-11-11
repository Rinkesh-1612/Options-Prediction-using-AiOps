# Options-Prediction-using-AiOps

DA3408 course project. A full AIOps pipeline on my own NIFTY option data (Upstox → Ravion V2): data engineering,
tracking, gated deployment, monitoring and retraining. It forecasts **how much NIFTY will move** in the next 5 / 15
minutes (volatility), and tests whether **buying calls or puts after costs** pays (direction). It is also a signal
library for the author's trading system (Ravion V2).

**Results.**
- **Volatility: predictable.** A HAR forecaster beat the option market's implied forecast on **10 of 10** unseen test
  days (daily QLIKE −0.20, 95% interval −0.37 … −0.07) ([results](reports/vol/comparison.md)).
- **Direction: no edge.** A linear model and LightGBM against a "stay out" baseline, 39 training days, 10 later test
  days: neither beats "stay out" after costs ([results](reports/zoo/comparison.md)).

![Explore tab](docs/img/explore.png)

## Documents

| | |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | diagram, blocks, ports, versioning |
| [High-level design](docs/HLD.md) | problem, design rules, decisions, technology map |
| [Low-level design](docs/LLD.md) | every API endpoint and pipeline stage with its input and output |
| [Test plan](docs/TEST_PLAN.md) | levels, 111 test cases, acceptance criteria; report in `reports/test_report.md` |
| [User manual](docs/USER_MANUAL.md) | the web page for a non-technical user, with screenshots; operator commands |
| [Viva notes](docs/VIVA_NOTES.md) | short answers to likely questions |
| [Rubric map](docs/RUBRIC.md) | each evaluation item → where it is; results; what is not done |
| [CI with DVC](docs/steps/ci.md) | the DVC DAG as the CI pipeline, the acceptance gate |
| [Lifecycle steps](docs/steps/) | one short note per course step |

## Layout

```
dvc.yaml  params.yaml      the pipeline (13 stages) and every setting
src/optpred/
  data/                    stages export (ClickHouse → Parquet), check (Spark)
  eda/  transform/         stages clean, eda, grid (Ray, one task per day)
  featurelib/  labels/     stages feat (feature registry), labels (costs, triple barrier)
  zoo/                     direction models (baseline, linear, LightGBM): stages zoo_train, zoo_eval, deploy gate
  vol/                     volatility forecaster (option-market baseline, HAR, HAR + IV): stage vol
  drift/                   PSI drift: stage drift, and the online check in the API
  ci/                      stage gate (CI acceptance criteria)
  serving/                 FastAPI: the only thing the web page talks to
  common/                  session clock, run journal, Spark and Ray helpers
tests/                     unit, integration, api, e2e, ui (browser audit)
frontend/                  the web page (static, nginx)
monitoring/                Prometheus, alert rules, Alertmanager, Grafana dashboard
docker/  docker-compose.yml  pipe  stack     images, the serving stack, and the two entry scripts
scripts/                   what the system runs: retrain runner, model server start, demo replay, test report, backup
scripts/docs/              tools that make the diagrams, screenshots and the demo video
reports/                   metrics and plots written by the stages (in Git)
logs/                      one log per stage run + the run journal logs/runs.jsonl (in Git)
data/                      DVC data (not in Git); data/sample = one day in Git LFS
docs/                      the documents listed above; docs/steps = one short note per lifecycle step
MLproject                  the same stage commands as MLflow entry points
```

## Run it

```bash
./pipe build                 # pipeline image (Python, Java/Spark, Ray, LightGBM)
export CH_PASSWORD=...       # only for the export stage (Ravion ClickHouse, read-only)
./pipe dvc repro             # the whole pipeline; deploys a new champion only if it passes the gate
./stack up -d --build        # web 8080 · API 8000 · MLflow 5050 · Grafana 3001 · Prometheus 9091
make ci                      # CI = ./pipe dvc repro gate: reruns what changed, lint + tests, acceptance gate
make demo                    # replay the unseen days through the API: Grafana moves in near real time
make test                    # all tests; `make e2e` against the running stack; `make help` for the rest
git config core.hooksPath .githooks   # run the CI (dvc repro gate) before every push
```

Without the ClickHouse data: `data/sample/` (Git LFS) holds one test day of features and labels. On this server
`dvc pull` restores all data from the DVC remote (a folder on the same disk, `../dvc-remote`; it is not reachable
from another machine). All tests use synthetic data, so `make test` works on a fresh clone.

AI use: [AI_DISCLOSURE.md](AI_DISCLOSURE.md).
