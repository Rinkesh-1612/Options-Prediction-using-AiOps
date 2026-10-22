# Low-level design

This document lists every endpoint of the API with its input and output.
A test (`test_openapi_matches_the_low_level_design`) reads the headings below.
It fails if an endpoint exists in the API but not here, or the reverse.

Base URL: `API_URL` (default `http://127.0.0.1:8000`). Format: JSON. Time zone: IST.
`minute` is the minute since midnight. 09:20 is 560. 15:29 is 929.

**Errors.** Every error has an HTTP status and a JSON body.
`{"detail": "<text>"}` is the standard FastAPI form.
`{"error": "model_unavailable", "detail": "<text>"}` is used when the model service is down (status 503).

**Admin calls** (`/rollback`, `/retrain`) need the header `X-Admin-Token: <ADMIN_TOKEN>`.
When `ADMIN_TOKEN` is empty, no token is needed (local development only).
A wrong or missing token gives `401`.

## Prediction

### `GET /healthz`
Returns 200 only when the model service answers.

| | |
|---|---|
| Input | none |
| 200 | `{"status": "ok", "rows": <int>}` – `rows` is the number of decision rows loaded |
| 503 | `{"detail": "model service not ready"}` |

### `GET /days`
Lists the days a person may pick. Locked test days are not listed until `reports/final.json` exists.

| | |
|---|---|
| Input | none |
| 200 | list of `{day, split, in_sample, minutes, first_time, last_time}` |

`split` is `train`, `val` or `test`. `in_sample` is true for train days (the model learned from them).
Times are `HH:MM`.

### `GET /minutes`
Lists the decision minutes of one day.

| | |
|---|---|
| Input | query `day` (`YYYY-MM-DD`), required |
| 200 | list of `{minute: int, time: "HH:MM"}` |
| 404 | the day has no minutes, or it is a locked test day |
| 422 | `day` is missing |

### `POST /predict`
Asks the model what it would have said at one past minute. Also returns what happened next.

| | |
|---|---|
| Input | body `{"day": "2026-09-30", "minute": 600}`; `minute` 0–1439 |
| 200 | `PredictResponse` (below) |
| 403 | the day is a locked test day and the final evaluation is not done |
| 404 | no decision row for that day and minute |
| 422 | wrong type or range |
| 503 | model service down |

`PredictResponse`:

| Field | Type | Meaning |
|---|---|---|
| `day`, `minute`, `decision_time` | str, int, str | the minute asked |
| `split`, `in_sample` | str, bool | which part of the data the day is in |
| `spot` | float | NIFTY index value |
| `probabilities` | `{STAY_OUT, BUY_CE, BUY_PE}` → float | model probabilities, sum to 1 |
| `action` | str | `STAY_OUT`, `BUY_CE` or `BUY_PE`, after the decision rule |
| `headline` | str | one short sentence, for example "Buy the 22900 call (CE)" |
| `reason` | str | one plain sentence that says why |
| `drivers` | list of `{feature, value, push}` | the three inputs that moved the answer most |
| `call`, `put` | `Contract` | `{instrument_key, strike, entry_ask, spread_pts}` |
| `outcome` | `Outcome` | `{horizon_min, call_net_rs, put_net_rs, best_in_hindsight, result_of_model_action_rs}` |

Side effects: increments `predictions_total`, `predictions_vs_actual_total`, `model_result_rs_total`.
Adds the feature row to the drift window.

## Model management

### `GET /model`
Shows the registry versions behind the aliases.

| | |
|---|---|
| Input | none |
| 200 | `{registered_model, champion: V, previous?: V, candidate?: V}` where `V = {version, run_id, tau, git_commit, val_metrics}` |
| 404 | no champion yet |
| 503 | registry unreachable |

### `POST /rollback`
Swaps the `champion` and `previous` aliases. The model service restarts on the new champion within 10 seconds.

| | |
|---|---|
| Input | none. Header `X-Admin-Token` |
| 200 | `{"champion": <int>, "previous": <int>}` |
| 401 | token missing or wrong |
| 409 | there is no previous model |

### `POST /retrain`
Writes `state/retrain_request.json`. The runner trains a new model. The new model becomes champion only if it validates better.

| | |
|---|---|
| Input | query `reason` (text, up to 200 characters, default `manual`). Header `X-Admin-Token` |
| 202 | `{"accepted": true, "reason": "<text>"}` |
| 401 | token missing or wrong |

### `GET /results`
The one-time score on the locked test days, as written by the `evaluate` stage (`reports/final.json`).
The rules are in `docs/FINAL_TEST_PROTOCOL.md`.

| | |
|---|---|
| Input | none |
| 200 | `{days, rows, tau, model: {name, version, run_id}, by_slippage: {"<slip>": {champion: S, baselines: {stay_out, always_ce, always_pe, momentum, random, oracle_not_tradable}: S, side_picking: {forced_policy: S, coin_flip_same_minutes_per_day_mean, coin_flip_same_minutes_per_day_p5_p95, seeds, seeds_beaten, detected}}}, information: {model_logloss, prior_logloss, gain_per_day_mean, gain_per_day_ci95, days_with_gain, accuracy, detected}, verdict: {...}, protocol, evaluated_at_commit, mlflow_run_id}` where `S = {days, trades, trades_per_day, hit_rate, mean_net_per_trade_rs, mean_net_per_day_rs, positive_days, per_day_ci95_rs?}` |
| 404 | the test days have not been scored yet |
| 500 | the results file cannot be read |

## Monitoring

### `GET /drift`
Shows input drift. Compares the last served rows (up to 2000, about 5 sessions) with the training rows. Calendar and price-level features are left out (see `drift.py`).

| | |
|---|---|
| Input | none |
| 200 | `{ready, rows, drifted, features_drifted, max_psi?, psi: {feature: float}}` |

`ready` is false until 1000 rows are in the window (env `DRIFT_MIN_ROWS`). PSI above 0.25 is drift for one feature.
`drifted` is true when more than 30% of the monitored features drift.

### `POST /alerts/webhook`
Alertmanager calls this. It acts on a firing `DriftDetected` alert only.

| | |
|---|---|
| Input | Alertmanager webhook body `{"alerts": [{"status", "labels": {"alertname"}}]}` |
| 202 | `{"accepted": true}` – a retrain request was written |
| 202 | `{"accepted": false, "reason": "<text>"}` – no firing `DriftDetected`, or the cooldown (default 1 hour) is active |

### `GET /metrics`
Prometheus text format. Metric names:

| Name | Type | Labels | Meaning |
|---|---|---|---|
| `api_requests_total` | counter | path, method, status | requests |
| `api_request_seconds` | histogram | path | request time |
| `model_call_seconds` | histogram | – | time in the model service |
| `model_service_up` | gauge | – | 1 if the model answered |
| `predictions_total` | counter | action | predictions served |
| `predictions_vs_actual_total` | counter | predicted, actual | prediction against hindsight |
| `model_result_rs_total` | counter | sign (`gain`, `loss`) | rupees after costs |
| `champion_model_version` | gauge | – | registry version served |
| `feature_psi` | gauge | feature | drift score |
| `drift_detected` | gauge | – | 1 when drift rule is met |
| `drift_window_rows` | gauge | – | rows in the window |
| `retrain_requests_total` | counter | source | retrain requests |
| `pipeline_last_run_ok` | gauge | stage | 1 if the last run succeeded |
| `pipeline_last_duration_seconds` | gauge | stage | duration of the last run |
| `pipeline_last_rows_per_second` | gauge | stage | throughput of the last run |
| `pipeline_last_run_timestamp_seconds` | gauge | stage | start of the last run |
| `pipeline_runs` | gauge | stage, status | runs in the journal |

## Pipeline console

### `GET /pipeline/dag`
The DVC graph read from `dvc.yaml`.

| | |
|---|---|
| Input | none |
| 200 | `{nodes: [{id, cmd, deps, outs}], edges: [{from, to}]}` |

### `GET /pipeline/runs`
The newest runs from `runs/runs.jsonl`.

| | |
|---|---|
| Input | query `limit` (1–500, default 50) |
| 200 | list of `{run_id, stage, status, started, duration_s, git_commit, git_dirty, rows_per_s, summary}` |

### `GET /pipeline/runs/{run_id}/log`
The last lines of one run log, as plain text. The API serves only files under `logs/`.

| | |
|---|---|
| Input | path `run_id`; query `lines` (1–2000, default 200) |
| 200 | text |
| 404 | unknown run, file missing, or file outside `logs/` |

## Pipeline stages (command line)

| Stage | Command | Reads | Writes |
|---|---|---|---|
| export | `python -m optpred.export` | ClickHouse | `data/raw/`, `data/raw/manifest.json` |
| check | `python -m optpred.check` | `data/raw/` | `data/days.json`, `reports/quality.json` |
| bars | `python -m optpred.bars` | `data/raw/`, `data/days.json` | `data/bars/` |
| features | `python -m optpred.features` | `data/bars/` | `data/features/`, `data/splits.json`, `reports/features.json` |
| baselines | `python -m optpred.baselines` | `data/features/` | `reports/baselines.json` |
| tune | `python -m optpred.tune` | train days of `data/features/` | `reports/tune.json`, MLflow run |
| train | `python -m optpred.train` | train and validation days | MLflow run, new model version, `reports/train.json` |
| register | `python -m optpred.register` | `reports/train.json`, registry | registry aliases, `reports/register.json` |
| evaluate | `python -m optpred.evaluate --final` (once; frozen in DVC) | test days, registry `champion` | `reports/final.json`, MLflow run `final-evaluation` |
| replay | `python -m optpred.replay --api URL` | API | none (calls `/predict`) |

Every stage returns exit code 0 on success. A failure returns non-zero and still writes a journal line.
All tunable numbers are in `params.yaml`.

## Frontend configuration

The page reads `config.json` when it loads: `{"api_url", "mlflow_url", "grafana_url"}`.
The container writes this file from the environment variables `API_URL`, `MLFLOW_URL`, `GRAFANA_URL`.
No other link exists between the page and the back end.
