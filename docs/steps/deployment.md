# Model Deployment

> Choose a deployment strategy; deploy to a serving infrastructure. AIOps: CI/CD, serving (MLflow Serve, REST),
> monitor in production, rollback for failed deployments.

**Strategy: online REST.** Ravion needs a decision every second, so the model is served live. Batch scoring
(`zoo_eval`) is used for backtests. Edge: not applicable (one VPS).

**Serving.** `docker-compose.yml`:
- `model`: `mlflow models serve` of the registry alias `nifty-signal@champion` ([serve_model.sh](../../scripts/serve_model.sh)).
- `api`: [signal_api.py](../../src/optpred/serving/signal_api.py) (FastAPI), the only public entry.
  `GET /signal?day&sod` → action, scores, and what happened after it. Also `/days`, `/model`, `/results`.

**CI/CD.**
- CI: the DVC DAG ends in `tests` (ruff + pytest) → `gate` (acceptance); `make ci` and the pre-push hook run `dvc repro gate` ([ci.md](ci.md)).
- CD: `dvc repro` → `zoo_eval` registers the champion → [promote.py](../../src/optpred/zoo/promote.py) smoke-tests it
  (loads it from the registry, predicts one full day) → only then aliases move (`champion`, old one → `previous`).
  The model server follows the alias, so promotion = deployment.

**Rollback.**
- Automatic: a new champion that is not healthy within `START_TIMEOUT` (180 s) is tagged `failed_start` and the
  alias goes back to `previous`.
- Manual: `POST /rollback` (admin token) swaps `champion` and `previous`.

**Production monitoring.** Prometheus metrics from the API: signals by action, served trades won/lost and net ₹,
latency, model version, model server up. See [monitoring.md](monitoring.md).
