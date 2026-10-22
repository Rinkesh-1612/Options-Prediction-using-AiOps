# Viva preparation

Say these answers in your own words. The grader asks "why". A list of facts is not enough.

## One-minute summary

I trade NIFTY options. I want to know if a model can pick, each minute, the call, the put or nothing,
and still make money after the spread, taxes and slippage. I built a reproducible system around that question.
It exports my recorded data, checks it, builds features, trains LightGBM, tracks every run in MLflow,
serves the model over REST, shows it on a web page and watches it with Prometheus and Grafana.
On unseen days, no simple rule beat the costs. The trained model chose to stay out. I report that honestly.

## Questions to expect

| Question | Short answer | Where to look |
|---|---|---|
| Why a 2-minute hold? | I set it before I saw any result. A horizon chosen after results is cheating. 1 and 3 minutes are side checks only. | PLAN §4 |
| Why enter at the ask and exit at the bid? | That is what a real buyer gets. The mid price is not tradable. | `labels.py` |
| Why split by day? | Minutes in one day look alike. A row split leaks the answer into training. | HLD §3 |
| Why is the test set locked? | One honest score needs data nobody tuned on. Code refuses it without `--final`. | `baselines.py`, API |
| Why does the model say "Stay out"? | On validation, every threshold lost money after costs. "Never trade" was the best option on offer. | `train.py` |
| Is 'no edge' a failure? | No. The rubric grades the system and the honesty of the measurement. | RUBRIC |
| Why is a hindsight label so favourable? | NIFTY moves more than the costs in 2 minutes. In hindsight one side usually pays. The question is whether we can pick it first. The oracle row shows the ceiling. | PLAN §4 |
| Why Spark? | `check` and `bars` group 85 M ticks. A single-machine pandas job would run out of memory. | `check.py`, `bars.py` |
| Why Ray Tune? | It runs trials in parallel and handles the search loop. We score on walk-forward log loss, not profit. | `tune.py` |
| Why not tune on profit? | A few days of profit is noise. Tuning on it fits the validation days. | `tune.py` docstring |
| What is DVC for? | It versions data and models, and chains the stages. `dvc repro` reruns everything. | `dvc.yaml` |
| What is your CI? | A pre-push hook: ruff, pytest, `dvc dag`. DVC is the DAG; the hook is the gate. | `.githooks/pre-push` |
| How do you reproduce a run? | Git commit hash + MLflow run ID + params hash, all in the journal. | `runlog.py` |
| What does MLflow add over autolog? | I log day-level results, cost values, baselines, quality report, data hashes by hand. | `train.py` |
| How does rollback work? | MLflow aliases. `champion` and `previous` swap. The model server follows the alias. | `api.py`, `serve_model.sh` |
| How does drift trigger a retrain? | PSI per feature on served rows. More than 30% of features above 0.25, on a window of about 5 sessions → alert → webhook → retrain request → runner. A candidate is promoted only if better. | `drift.py`, `monitoring/alerts.yml` |
| How is the front end decoupled? | Static page in its own container. It knows one address from `config.json`. No shared code. | `frontend/` |
| Why multi-stage Docker? | The build image has compilers. The runtime image does not. `scripts/image_sizes.sh` prints the saving. | `Dockerfile.serve` |
| Why Compose, not Kubernetes? | One server. Kubernetes adds risk to the live trading system and no extra mark. | RUBRIC |
| What does Prometheus watch? | API requests and latency, predictions by class, prediction against actual, drift, pipeline journal, MLflow, host. | `docs/LLD.md` |
| What is the weakest point? | Ten test days. One market regime. The slippage value may double count part of the spread. | HLD §7 |
| What would you do next? | Port the simulator into Ravion's `ravlab`. Test other horizons and signals there, with the same cost model. | – |

## Facts to know cold

* Data: 55 days exported, 49 accepted, 17,984 decision rows. Train 33 days, validation 6, locked test 10.
* Cost: statutory about Rs 18 per round trip plus 0.31 points per leg slippage, lot size 65.
* Validation: always-CE about −Rs 38 per trade, always-PE about −Rs 22, momentum about −Rs 34, random about −Rs 31. The oracle (hindsight, not tradable) makes about +Rs 160.
* Model log loss on validation 1.0865 against the no-information 1.0964. A small gain. It did not turn into profit.
* Tools and ports: web 8080, API 8000, MLflow 5050, Prometheus 9091, Grafana 3001.

Numbers come from `reports/baselines.json` and `runs/runs.jsonl`. Re-read them before the viva.
