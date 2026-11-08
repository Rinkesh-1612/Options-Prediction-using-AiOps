# Low-level design

## 1. API (`src/optpred/serving/signal_api.py`)

Base URL: `http://<host>:8000`. JSON unless stated. OpenAPI: `/docs`. Errors: `{"detail": "<text>"}`.
`tests/api/test_lld.py` checks that this list and the real routes are the same.

### GET /healthz
Out: `{"ok": true}`. 503 when the model server does not answer `/ping`.

### GET /days
Out: `[{"day": "2026-10-15", "split": "test" | "dev"}]`, every accepted day.

### GET /signal
In (query): `day` (an accepted day), `sod` (seconds since IST midnight, 33300–55799).
Out: `day, sod, time, atm, action (BUY_CE | BUY_PE | STAY_OUT), score_ce, score_pe, blocked,`
`outcome {net_rs, hold_s, barrier (1 take-profit, -1 stop-loss, 0 time limit), entry, exit} | null,`
`hindsight {ce, pe: {net_rs, hold_s, barrier} | null}`.
`drivers {side, unit, base, score, top[{feature, value, contribution}], other} | null`: exact SHAP values of the
champion's score for the better side (LightGBM `pred_contrib`). `base + sum(contribution) + other = score`; unit
`net_rs` = expected net rupees. `null` when the champion is not a LightGBM model.
The API sends the last 120 feature rows up to `sod` to the model server; nothing after `sod`.
`blocked` = the model wanted a side, but no entry was possible at `sod`. Errors: 404 unknown day, 422 bad `sod`,
503 model server down or data being rebuilt.

### GET /vol
In (query): `day`, `sod` (as `/signal`). Out: `{"day", "sod", "5min": V, "15min": V}`,
V = `{forecast_bp, implied_bp, ratio, realized_bp}`: the `nifty-vol` champion's forecast of the NIFTY move,
the move implied by the ATM IV, their ratio, and the realized move (known only after the fact).
Inputs use only rows up to `sod`. 503 when no `nifty-vol` champion is registered.

### GET /vol/day
In (query): `day`. Out: one value per minute from 09:30 to 15:00 (331 points):
`{day, sod[], spot[], forecast_300[], implied_300[], realized_300[], forecast_900[], implied_900[], realized_900[]}`.
Moves are in basis points (1 bp = 0.01% of NIFTY); `spot` converts them to index points. `realized_*` is the move
that happened after each minute (`null` where the data ends before the window does); it is hindsight. 404 unknown day, 503 as `/vol`.

### GET /vol/results
Out: `reports/vol/test.json` (`champion, verdict{300, 900: mean_daily_qlike_diff, ci95, days_better,`
`beats_implied}, results{forecaster: {300, 900: qlike, r2_log, corr_log}}`, `qlike_by_day{champion, implied:
{300, 900: {day: qlike}}}`) + `cv`.

### GET /explore/days
Out: one row per recorded day for the calendar: `{day, weekday, split (dev|test), source (train|oof|test), open, close, ret_pct, range_pct, dte, atm_iv, events[]}`.
`events` holds `expiry` (dte 0), `big_move` (move ≥ 1% or range ≥ 1.5%) and `drift` (drift stage alarm).

### GET /explore/iv/daily
Out: per day `{day, split, iv, forecast, realized, iv_rich_share}`. All three volatilities are annual percent, averages over the
minutes of the day; `realized` is hindsight; `forecast` is our champion volatility forecaster (`null` until stage `modelout` ran).
`iv_rich_share` = share of minutes where the option market's volatility was above what then happened.

### GET /explore/iv/day
In (query): `day`. Out: one point per minute 09:30-15:00: `{day, sod[], spot[], iv[], realized[], forecast[]}` (annual percent).

### GET /explore/iv/smile
In (query): `day`, `t` (seconds of day). Out: the chain snapshot nearest to `t`: `{day, sod, spot, expiries[{expiry, dte, strikes[], call_iv[], put_iv[]}]}`.

### GET /explore/iv/term
In (query): `day`, `t`. Out: `{day, sod, at[{expiry, dte, iv}], series{sod[], near[], next[]}}`: ATM IV of each expiry at `t`
and of the first two expiries through the day. 404 unknown day, 503 when the file is missing.

### GET /explore/strategies
In (query): `day`, `t` (second of day). Out: `{day, sod, lot, atm, strategies[]}`: every ready-made strategy (18: long and short
volatility, spreads, ratio spreads, backspreads, broken wing, jade lizard) entered at `t`: `{id, name, kind, legs_text, legs[{side,
action, lots, strike, price, k}], cost (₹; > 0 pay, < 0 receive), curve[] (net ₹ if closed after 1, 2, 3 ... minutes), at{m5, m15, m30,
m60}, best_exit{minute, net} (hindsight), barrier{hit (+1 take profit, -1 stop loss, 0 time cap), hold_s, net, sigma}|null,
max_profit, max_loss (at expiry, before charges; `null` = unlimited or very large: net long or short calls, or puts), breakevens[]}`. A strategy that cannot be priced has `error`.
Buy legs fill at the ask and exit at the bid, sell legs the other way; statutory charges, no brokerage; margin is not modelled.

### GET /explore/strategy
In (query): `day`, `t`, `legs` = `action:side:offset:lots,...` (1-4 legs, offset -2..2 strikes from ATM at entry, lots 1-10).
Out: the same fields for that strategy plus `payoff{spot[], pnl[], breakevens[], max_profit, max_loss}`. 422 bad legs, 409 cannot be priced
at that time (no quote, too close to the close), 404 unknown day.

### GET /explore/models
In (query): `day`, `t`. Out: what every model said at the minute of `t` (from stage `modelout`) and what happened:
`{day, sod, iv, realized, direction[{family, baseline, source (test|oof|train), action (BUY_CE|BUY_PE|STAY_OUT), score_ce, score_pe, tau,
ce_net, pe_net, result, ended_by}], vol[{family, kind (forecast|market), source, forecast}]}`. `source`: `test` = unseen day, `oof` = the model had not
seen the day (walk-forward), `train` = in-sample. Net rupees are for one lot, barrier exit (the labels). 503 until stage `modelout` ran.

### GET /explore/models/day
In (query): `day`. Out: `{day, direction[{family, baseline, source, trades, net, hit_rate}], vol[{family, source, qlike}]}`: each direction model
trades one position at a time at one-minute steps; `qlike` = error of the 15-minute volatility forecast (lower is better).

### GET /model
Out: `{"champion": V, "previous": V}`, V = `{version, family, git_commit, deploy_check, metrics}`.
Also `"vol": {version, family, deploy_check}`: the champion of the volatility forecaster `nifty-vol`.

### GET /results
Out: `reports/zoo/test.json` (`test_days, champion, results{family: net_per_day, ci95_net_per_day, trades,`
`hit_rate, ic_ce, ic_pe, cv_net_per_day, tau, per_day}`) + `cv {dev_days, folds, trials}`, `importance`
(top 15 gain share), `ablation`. Non-finite numbers are `null`. 404 before `zoo_eval` has run.

### POST /rollback
Header: `X-Admin-Token` (when `ADMIN_TOKEN` is set). Swaps the aliases `champion` and `previous`.
Out: `{"champion": int, "previous": int}`. 401 bad token, 409 no previous version.

### POST /retrain
Header: `X-Admin-Token`. In (query): `reason` (≤ 200 characters). Writes `state/retrain_request.json`.
Out (202): `{"accepted": true, "reason": str}`.

### GET /drift
Out: `{rows, ready, drift, share, psi{feature: value}}` for the last 1,000 served rows. 404 before the
`drift` stage has written its reference.

### POST /alerts/webhook
In: Alertmanager webhook body. `DriftDetected` or `ModelLosing` (firing) → retrain request, at most once per
`RETRAIN_COOLDOWN_S`. Out (202): `{"alerts": [names], "retrain_requested": bool}`.

### GET /drift/daily
Out: `[{day, split, share, drift}]` from `reports/drift/daily.json`.

### GET /pipeline
Out: `{"stages": [{name, cmd, last}], "edges": [[from, to]]}`. Edges: an output of one stage is a
dependency of the other (`dvc.yaml`). `last` = the newest run in the journal.

### GET /pipeline/runs
In (query): `limit` (1–500, default 50), `stage` (optional). Out: runs of current stages, newest first:
`{run_id, stage, started, status, duration_s, git_commit, git_dirty, exit_code, summary}`.

### GET /pipeline/runs/{run_id}/log
In: `run_id` (`[0-9T]+-[a-z_]+`), `tail` (1–5000 lines). Out: text. 400 bad id, 404 unknown run or no file.

### GET /quality
Out: `{accepted: [days], rejected: {day: [reasons]}, cleaning: {table: {rows_in, rows_out, drop_*, null_*}}}`.

### GET /metrics
Prometheus text. Main series: `signals_total{action}`, `signal_outcomes_total{result}`,
`signal_net_rupees_total`, `api_request_seconds`, `model_call_seconds`, `model_version`, `model_service_up`,
`drift_detected`, `drift_share`, `feature_psi{feature}`, `pipeline_last_run_ok{stage}`,
`data_rows_dropped_share{table}`, `retrain_requests_total{source}`.

## 2. Pipeline stages (`dvc.yaml`, settings in `params.yaml`)

| Stage | In | Out |
|---|---|---|
| export | ClickHouse (read-only) | `data/raw/<table>/<day>.parquet`, `manifest.json` |
| check | `data/raw` | `data/days.json`, `reports/quality.json` |
| clean | `data/raw`, `data/days.json` | `data/clean/<table>/<day>.parquet`, `reports/eda/cleaning.json` |
| eda | `data/clean` | `reports/eda/profile.json`, 4 plots |
| grid | `data/clean` | `data/grid/<day>.parquet` (22,500 rows × 116 columns per day), `reports/grid.json` |
| feat | `data/grid` | `data/feat/<day>.parquet` (46 float features + `day, sod, atm`), `reports/feat.json`, `reports/feature_catalog.md` |
| labels | `data/grid` | `data/labels/<day>.parquet` (per side: `valid, entry, sigma, hit, hold_s, exit, net_rs`), `reports/labels.json` |
| zoo_train | `data/feat`, `data/labels` (dev days) | `reports/zoo/cv.json`, `reports/zoo/importance.json`, MLflow runs |
| zoo_eval | + test days, `cv.json` | `reports/zoo/test.json`, `comparison.md`, registered + deployed model |
| vol | `data/grid`, `data/feat` | `reports/vol/cv.json`, `test.json`, `comparison.md`, `test_scatter.png`, model `nifty-vol` |
| drift | `data/feat` | `reports/drift/reference.json`, `daily.json`, `daily.png` |
| modelout | `data/grid`, `data/feat`, `data/labels`, `cv.json` | `data/modelout/<day>.parquet` (every model, every minute), `reports/modelout.json` |
| tests | `src/`, `tests/`, `scripts/`, `docs/LLD.md`, page | `reports/tests.json` (counts), `reports/test_report.md`; fails on a lint or test error |
| gate | `tests.json`, `days.json`, `vol/test.json`, `zoo/test.json` | `reports/gate.json` (4 criteria); fails when one fails |

## 3. Model interface (`src/optpred/zoo/models.py`)

`make(family, params, features)` → object with `fit(ds, rows)` and `predict_day(X) -> (n, 2)` scores (CE, PE).
The served pyfunc (`zoo/pyfunc.py`) returns `score_ce, score_pe, action` per row; the threshold `tau` is
inside the model.
