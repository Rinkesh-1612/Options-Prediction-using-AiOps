# High-level design

## 1. Problem

At the end of each minute, choose one action for the at-the-money NIFTY option of the nearest expiry:

* `BUY_CE` – buy the call.
* `BUY_PE` – buy the put.
* `STAY_OUT` – do nothing.

We hold a trade for 2 minutes. We enter at the **ask**. We exit at the **bid**.
We then subtract taxes and slippage. A trade is good only if the result is above zero.

**Success metric (fixed before any model result):** mean net rupees per day on days the model never saw,
with a 95% interval from resampling days. We also report the mean per trade and the hit rate.
If the interval includes zero, the result is "no edge detected at this sample size". That is a valid result.

## 2. Data

| Item | Value |
|---|---|
| Source | The author's own recorded NSE data (Upstox websocket), in Ravion's ClickHouse |
| Window | 3 Aug 2026 – 16 Oct 2026 |
| Raw size | 86 M option ticks, 15 M index ticks, 12.9 M chain snapshots |
| Days kept | 49 of 55 (6 rejected by `check`) |
| Decision rows | 17,984 (one per minute per day) |
| Split | Whole days in time order: train, validation, locked test (10 days) |

Known data problems and what we do: see `PLAN.md` section 2.
The proposal quoted 22 M snapshots and 27 M order-book records. The report uses the measured numbers above.

## 3. Design choices and reasons

| Choice | Reason |
|---|---|
| Label = best action in hindsight after costs | It matches how we judge the trade. |
| Fixed 2-minute hold, set before results | A horizon chosen after the results is a form of cheating. |
| Split by whole days, locked test days | Rows from one day look alike. A row split leaks. |
| One position at a time in evaluation | One market move must not count many times. |
| Day is the unit of evidence | Minutes inside a day are not independent. |
| Reject bad days. Do not repair them. | Frozen prices are not market data. |
| Export once to Parquet | The result stays reproducible when Ravion's table expires (120-day TTL). |
| Spark for `check`, `bars` | Group-bys over 85 M rows. Spark fits. |
| Ray Tune for settings | It runs trials in parallel and handles the search loop. |
| LightGBM | A standard model for table data. It trains in seconds. |
| Trade threshold chosen on validation. "Never trade" is allowed. | If nothing beats the costs, the model stays out. |
| Decision rule inside the served model | The API never applies its own rule. Offline and online cannot differ. |
| Same feature code offline and online | It prevents training-serving skew. |

## 4. Paradigm

* The pipeline stages are **functional**. Each stage is a function from files to files.
  The core logic (labels, simulator, features, PSI) is in pure functions that tests call directly.
* The API and the registry client use a few small **classes** (`Settings`, `ModelServer`, `Metrics`, `DriftMonitor`).

## 5. AIOps design

| Need | Answer |
|---|---|
| Reproduce a run | Each run has a Git commit hash, a params hash and an MLflow run ID. The journal stores all three. |
| Version code, data, models | Git (code), Git LFS (one-day sample), DVC (data, models) with a local remote on the VPS. |
| Chain the stages | `dvc.yaml`. One command, `dvc repro`, runs all stages. |
| CI | A pre-push hook runs ruff, pytest and `dvc dag`. |
| Track experiments | MLflow. We log more than autolog: day results, costs, baselines, quality report. |
| Serve | `mlflow models serve` behind FastAPI. |
| Same environment everywhere | Docker images. `MLproject` runs each stage in the pipeline image. |
| Monitor | Prometheus pulls metrics. Grafana shows them. Alert rules cover drift, failures and slow responses. |
| Maintain | Drift alert → retrain request → new candidate → promote only if better. Roll back with one call. |
| Security | The data snapshot is encrypted with AES-256. The key is outside the repo. Admin calls need a token. |

## 6. Constraints

* One VPS. 8 cores. The live trading system shares it. Spark and Ray use at most 4 cores.
* Heavy jobs run after 15:30 IST.
* No managed cloud service.
* We never write to Ravion's ClickHouse.

## 7. Known limits (we state them before anyone asks)

* Ten test days resolve only large effects. The report shows the smallest effect the sample can detect.
* One market regime (Aug–Oct 2026).
* The slippage value (0.31 points per leg) may already include part of the spread. We report results with and without it.
* On validation, every simple rule loses money after costs. The trained model chose "never trade".
  This is the honest result so far.
