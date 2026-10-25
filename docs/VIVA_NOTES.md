# Viva notes

Short answers to the questions a grader is likely to ask. Numbers come from the committed reports.

## The project in one minute
I trade NIFTY options and have my own recorded tick data (Upstox → Ravion V2 → ClickHouse). I built a full AIOps
pipeline on it: export → check (Spark) → clean / grid / features / labels (Ray) → model training and evaluation
(Ray Tune, MLflow) → gated deployment (MLflow Serve + FastAPI) → monitoring (Prometheus, Grafana, drift,
alerts) → automatic retraining. Result: **direction is not predictable after costs, volatility is.**

## Design choices and how I defend them
| Question | Answer |
|---|---|
| Why no good strategy? | Direction correlation ≈ 0.01. The spread of one leg is ≈ ₹25; a 15-min edge must beat it. 9 model families, 39 dev days, 10 test days: none beats "stay out" (−₹1,376/day for the champion). I report this instead of hiding it. |
| Why volatility? | Volatility clusters (corr 0.68). A HAR forecast beats the option market's implied move on 10 of 10 test days (QLIKE −0.20, 95% CI [−0.37, −0.07]). It is a filter / sizing input for Ravion, not a trade. |
| Why walk-forward by day, test once? | Prices are a time series; shuffling leaks the future. Whole days avoid overlap. The champion and threshold are chosen on validation; the test days are scored once. The old test days were seen by a first version (disclosed); no model trained or tuned on them. |
| Why triple-barrier labels? | The holding time should follow the market, not be fixed. Take-profit and stop-loss scale with the option's own volatility; a time cap is only a safety. |
| Why a 1-second grid and a feature registry? | Keeps order-flow detail. A new feature = one function; the tests check every feature for look-ahead automatically. |
| Why Ray and Spark? | Spark scans all 114 M raw rows (`check`, ≈ 350 k option ticks per second). Per-day stages are independent, so Ray tasks run days in parallel and Ray Tune searches settings. |
| Why DVC as CI/CD? | Course stack. `dvc.yaml` is the DAG; `dvc repro` reruns only stale stages; the pre-push hook runs lint, tests and `dvc dag`. |
| Why MLflow Serve behind FastAPI? | Loose coupling: the page only knows the API address; the API is the only public entry; the model server follows the registry alias. |
| How is a bad model stopped? | Deploy gate: load from the registry and predict a full day before `champion` moves. If a version does not start in 180 s, the server rolls back to `previous` (tested with a broken version). Manual rollback: `POST /rollback`. |
| How do you detect drift? | PSI per feature against the training days. Limits come from normal day-to-day variation (a fixed 0.25 flagged 45 of 49 normal days). Online: last 1,000 served rows. |
| Why is the explanation (SHAP) useful? | It showed the champion mostly uses ATM IV, skew and the clock — regime features, not order flow. That is why it fails out of sample. |

## Likely challenges
- **"Your result is negative — what did you deliver?"** A reproducible, monitored system plus an honest measurement.
  Every stage, test, gate and alert works; the data science result is "no edge", backed by intervals over days.
- **"Isn't picking the best of 22 settings overfitting?"** Yes, which is why the champion is chosen on validation and
  the test is scored once. The test number (−₹1,376) is the honest one; the CV number (+₹246) was optimistic.
- **"Why does the volatility model not trade?"** I tested it: straddles lose after the ≈ ₹51 spread; expiry-day and
  strategy-search studies (branches `forward-data`, `strategy-search`) found nothing that pays after costs.
- **"What would you do with more time / data?"** 20+ more expiries for the expiry-day question; a rising market for
  the short-volatility carry lead; strike-level volatility.

## Tools (use cases)
Git (code), Git LFS (sample day), DVC (data, DAG, CI), Spark / Ray (data engineering, tuning), MLflow (tracking,
registry, serving, MLproject), FastAPI (REST), Docker + Compose (identical environments, two services), Prometheus
(metrics), Alertmanager (alerts → retrain), Grafana (near-real-time dashboard), LightGBM / PyTorch (models), SHAP
(explanations).
