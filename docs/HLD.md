# High-level design

## 1. Problem

At the end of each minute, choose one action for the at-the-money (ATM) NIFTY option of the nearest expiry:

* `BUY_CE` – buy the call.
* `BUY_PE` – buy the put.
* `STAY_OUT` – do nothing.

We hold a trade for 2 minutes. We enter at the **ask**. We exit at the **bid**.
We then subtract taxes and slippage. A trade is good only if the result is above zero.

**Success metric (fixed before any model result):** mean net rupees per day on days the model never saw,
with a 95% interval from resampling days. We also report the mean per trade and the hit rate.
If the interval includes zero, the result is "no edge detected at this sample size". That is a valid result.

### 1.1 Label and profit (the most important definitions)

For each decision minute *t* (data up to the end of *t* only):

    entry  = best ask of the ATM option at the end of minute t
    exit   = best bid of the SAME contract (instrument_key) at the end of minute t+2
    gross  = (exit - entry) * 65                       # one lot
    cost   = statutory charges(entry, exit) + slippage # 0.31 points per leg
    net    = gross - cost

    label  = BUY_CE   if net_CE > 0 and net_CE >= net_PE
             BUY_PE   if net_PE > 0 and net_PE >  net_CE
             STAY_OUT otherwise

* The label is a **hindsight** answer. In hindsight one side often pays, because NIFTY options move more
  than the costs in two minutes. The question is whether the model can pick the side **before** the move.
  The "oracle" row in every result table shows this hindsight ceiling. It is not tradable.
* Statutory charges follow the author's broker contract notes (zero brokerage). Slippage of 0.31 points per leg
  was measured on the author's live trades. Results are also reported at 0 and 0.15 points.

### 1.2 Changes from the project proposal

| Proposal | Built | Reason |
|---|---|---|
| NIFTY and BANKNIFTY | NIFTY only | Measured in the source database: BANKNIFTY option ticks start on 11 Sep 2026 (about 25 sessions, half the window) and BANKNIFTY has **no** chain snapshots, so its IV and open-interest features cannot be built. Too few days for a train / validation / test split by whole days. |
| Hold of 1–3 minutes, not fixed | 2 minutes, fixed before any result | A horizon chosen after seeing results is a form of overfitting. |
| 22 M snapshots, 27 M order-book records | Measured counts in section 2 | The proposal used estimates. The report uses measured numbers. |
| Pipeline: collect, check, features, train, evaluate, register | Same, as DVC stages: `export`, `check`, `bars`, `features`, `baselines`, `tune`, `train`, `register`, `evaluate` | `bars` and `tune` were added. |

## 2. Data

"Ravion" below is the author's own live trading system on the same server. Its recorder stores the
Upstox websocket feed in a ClickHouse database. This project only **reads** a copy of that data.

| Item | Value |
|---|---|
| Source | The author's own recorded NSE data (Upstox websocket), in Ravion's ClickHouse |
| Window | 3 Aug 2026 – 16 Oct 2026 |
| Raw size | 86 M option ticks, 15 M index ticks, 12.9 M chain snapshots |
| Days kept | 49 of 55 (6 rejected by `check`) |
| Decision rows | 17,984 (one per minute per day) |
| Split | Whole days in time order: train 33, validation 6, locked test 10 |

Known data problems and what we do about them:

| Fact | Evidence | Action |
|---|---|---|
| The chain table records on exchange holidays, with frozen prices | 14 Sep and 2 Oct: tape ~68 rows, chain ~238k rows, one unique spot | `check` rejects any day with a near-empty tape |
| Recorder outages | 25, 28, 29 Sep missing | Rejected |
| Partial days | 7 Sep, 16 Oct | Flagged; a day needs data in 95% of session minutes |
| Strike window widened on 11 Aug | 11 strikes before, 21 after | Use the ATM contract only, never raw counts across strikes |
| One strike carries two expiries | Two expiries every day | Every series is keyed on `instrument_key`, never on `strike` |
| Recorder runs 09:00–15:40 | Timestamps | Use 09:15–15:30 only; last entry 15:28 so the exit is inside the session |
| The chain table has a 120-day retention | Table definition | Export once to a frozen Parquet snapshot |

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
| Chain the stages | `dvc.yaml`: export → check → bars → features → baselines, tune, train → register → evaluate. One command, `dvc repro`, runs all stages. `evaluate` is frozen after its single run. |
| CI | A pre-push hook runs ruff, pytest and `dvc dag`. |
| Track experiments | MLflow. We log more than autolog: day results, costs, baselines, quality report. |
| Serve | `mlflow models serve` behind FastAPI. |
| Same environment everywhere | Docker images. `MLproject` runs each stage in the pipeline image. |
| Monitor | Prometheus pulls metrics. Grafana shows them. Alert rules cover drift, failures and slow responses. |
| Maintain | Drift alert → retrain request → `train` + `register` → new candidate → promoted only if strictly better on validation. Roll back with one call. |
| Security | The data snapshot is encrypted with AES-256. The key is outside the repo. Admin calls need a token. |
| Drift window | PSI over the last ~2,000 served rows (about 5 sessions). On real data a single day already shows PSI above 0.25 on half the features, even a training day, so a one-day window gives false alarms. |
| Small serving image | Multi-stage `Dockerfile.serve` on a `-slim` base. `scripts/image_sizes.sh` builds the naive single-stage version too and prints the saving. |
| Test once | The locked test days are refused by every stage except `evaluate`, which runs once and is then frozen in DVC. The protocol was committed before the run (`docs/FINAL_TEST_PROTOCOL.md`). |

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
  The result on the locked test days is in `docs/RESULTS.md`.
