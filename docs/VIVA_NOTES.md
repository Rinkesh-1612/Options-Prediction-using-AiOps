# Viva notes

Short answers to the questions a grader is likely to ask. Numbers come from the committed reports.

## The project in one minute
I trade NIFTY options and have my own recorded tick data (Upstox → Ravion V2 → ClickHouse). I built a full AIOps
pipeline on it: export → check (Spark) → clean / grid / features / labels (Ray) → model training and evaluation
(Ray Tune, MLflow) → gated deployment (MLflow Serve + FastAPI) → monitoring (Prometheus, Grafana, drift,
alerts) → automatic retraining. Two questions, three models each (baseline, simple, better). Result: **direction is not predictable after costs,
volatility is.**

## Design choices and how I defend them
| Question | Answer |
|---|---|
| Why no good strategy? | Direction correlation ≈ 0.01. The spread of one leg is ≈ ₹25; a 15-min edge must beat it. A linear model and LightGBM, 39 dev days, 10 test days: neither beats "stay out" (−₹1,376/day for the champion). I report this instead of hiding it. |
| Why only 3 models per question? | A baseline, a simple model, a better model: enough to answer "does ML beat the baseline?". I tried 6 more direction families first (GRU, Transformer, meta-labelling and others). None beat "stay out", so I removed them: more models added work to explain, not information. They are in Git history. |
| Why volatility? | Volatility clusters (corr 0.68). A HAR forecast beats the option market's implied move on 10 of 10 test days (QLIKE −0.20, 95% CI [−0.37, −0.07]). It is a filter / sizing input for Ravion, not a trade. |
| Why walk-forward by day, test once? | Prices are a time series; shuffling leaks the future. Whole days avoid overlap. The champion and threshold are chosen on validation; the test days are scored once. The old test days were seen by a first version (disclosed); no model trained or tuned on them. |
| Why triple-barrier labels? | The holding time should follow the market, not be fixed. Take-profit and stop-loss scale with the option's own volatility; a time cap is only a safety. |
| Why a 1-second grid and a feature registry? | Keeps order-flow detail. A new feature = one function; the tests check every feature for look-ahead automatically. |
| Why Ray and Spark? | Spark scans all 114 M raw rows (`check`, ≈ 350 k option ticks per second). Per-day stages are independent, so Ray tasks run days in parallel and Ray Tune searches settings. |
| Why DVC as CI/CD? | Course stack (lecture 11). `dvc.yaml` is the DAG; `dvc repro` reruns only stale stages. Stage `tests` = ruff + pytest; stage `gate` fails the run if a criterion fails. The pre-push hook runs `dvc repro gate`. |
| Why MLflow Serve behind FastAPI? | Loose coupling: the page only knows the API address; the API is the only public entry; the model server follows the registry alias. |
| How is a bad model stopped? | Deploy gate: load from the registry and predict a full day before `champion` moves. If a version does not start in 180 s, the server rolls back to `previous` (tested with a broken version). Manual rollback: `POST /rollback`. |
| How do you detect drift? | PSI per feature against the training days. Limits come from normal day-to-day variation (a fixed 0.25 flagged 45 of 49 normal days). Online: last 1,000 served rows. |
| Why is the explanation (SHAP) useful? | It showed the champion mostly uses ATM IV, skew and the clock — regime features, not order flow. That is why it fails out of sample. |

## The web page

| Question | Answer |
|---|---|
| Is the UX intuitive for your problem? | One story page, five numbered steps top to bottom: pick a day → implied volatility → inside the day → call or put? → verdict. A guided tour opens on the first visit. Unseen days carry a ★ so the fair test is visible. It opens on real data, never on an empty screen. |
| How did you design it? | With the UI/UX Pro Max skill (design rules for AI agents): Swiss minimalism, semantic colour tokens, light and dark, mobile first. I audited the skill's code before running it, used its rules, and rejected two of its suggestions (a marketing landing page and Google Fonts). |
| How do you know it is free of UI errors and responsive? | A real-browser audit (Playwright): 13 checks at 375 / 768 / 1024 / 1440 px, light and dark. The first page failed 5 of 11; this one passes 13 of 13 (`reports/ui_audit.md`). CI also parses the page script (`node --check`): a quote inside a string once stopped the whole page, and the old audit report did not show it. |
| Is it foolproof? | Only valid days and times can be chosen; destructive actions ask for confirmation; when the API fails the page shows a readable alert and a Try again button, never a raw error. |
| Loose coupling? | The page is a static file that knows one address (`config.json`). A test checks that every path it calls is in the LLD. |

## Likely challenges
- **"Your result is negative — what did you deliver?"** A reproducible, monitored system plus an honest measurement.
  Every stage, test, gate and alert works; the data science result is "no edge", backed by intervals over days.
- **"Isn't picking the best of 8 settings overfitting?"** Yes, which is why the champion is chosen on validation and
  the test is scored once. The test number (−₹1,376) is the honest one; the CV number (+₹246) was optimistic.
- **"Why does the volatility model not trade?"** I tested it: straddles lose after the ≈ ₹51 spread; expiry-day and
  strategy studies (research branches, not in this submission) found nothing that pays after costs.
- **"What would you do with more time / data?"** 20+ more expiries for the expiry-day question; a rising market for
  the short-volatility carry lead; strike-level volatility.

## Tools (use cases)
Git (code), Git LFS (sample day), DVC (data, DAG, CI), Spark / Ray (data engineering, tuning), MLflow (tracking,
registry, serving, MLproject), FastAPI (REST), Docker + Compose (identical environments, two services), Prometheus
(metrics), Alertmanager (alerts → retrain), Grafana (near-real-time dashboard), LightGBM / scikit-learn (models), SHAP
(explanations).

## Straight answers about the tools (checked 2026-10-26)

| Question | Answer |
|---|---|
| Git LFS? | Yes, narrowly: one rule for `*.parquet`; two sample files (one test day of features and labels, 6 MB). The large data is in DVC. |
| DVC? | Yes: 13 stages (11 data/model + `tests` + `gate`), `dvc.lock` in git, cache 9.5 GB, `dvc status` clean. The remote is a folder on the same disk, so it is not an off-machine backup. |
| Spark? Ray? | Both used. Spark: stage `check` (day-quality rules). Ray: per-day parallel jobs in 7 stages and Ray Tune in `zoo_train`. |
| Ray Serve? | No. Only Ray Core and Tune. Serving is MLflow Serve behind a FastAPI layer. |
| Kubernetes? Swarm? | No. Docker Compose is the orchestrator. Swarm is a possible next step. |
| MLflow? | Yes: tracking (263 runs, 2 experiments), registry with aliases champion / previous, deploy gate, MLflow Serve, MLproject. |
| Docker Hub? | Not pushed. Images are built locally. |
| Prometheus, Grafana? | Yes: 8 scrape targets (api, mlflow, host, Prometheus, Alertmanager, Grafana, blackbox probes of the page and the model server) plus a runner heartbeat, 10 alert rules, one dashboard; DriftDetected and ModelLosing start a retrain (ran live once). |
