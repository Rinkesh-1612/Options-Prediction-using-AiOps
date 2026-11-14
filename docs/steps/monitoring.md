# Model Monitoring & Maintenance

> Monitor performance in production; detect data drift; retrain periodically or on degradation.
> AIOps: automated monitoring and alerting, automated retraining, drift and performance over time, model versioning.

**Performance.** API metrics → Prometheus (5 s) → Grafana dashboard `NIFTY signal: production`
(`monitoring/grafana/dashboards/optpred.json`): signals per minute, cumulative net ₹ of served trades, hit rate,
net ₹ distribution, model version, latency, pipeline stage status, components up, host. `make demo` replays the unseen
days through the API, so the dashboard moves in near real time.

**Drift.** PSI per feature against the dev (training) days ([src/optpred/drift/](../../src/optpred/drift/)).
- Online: the API keeps the last 1,000 served rows; gauges `feature_psi`, `drift_share`, `drift_detected`.
- Over time: stage `drift` → `reports/drift/daily.json` + `daily.png`, and an MLflow metric series.
  Result: mean share of drifting features 2.9% on dev days, 15.5% on test days; no day above the 30% limit.

**Alerts** (`monitoring/alerts.yml`): DriftDetected, ModelLosing (running net ₹ of served trades fell by ₹2,000 in 1 h), LowHitRate,
ModelServiceDown, TargetDown, ComponentDown, RunnerDown, PipelineStageFailed, SlowApi, BadDataRate (10 rules).

**Every component is watched.** Prometheus scrapes the API, MLflow, the host, Alertmanager, Grafana and itself; a
blackbox probe checks the web page and the model server; the retrain runner writes a heartbeat (table in [HLD](../HLD.md) section 7).

**Data quality.** Gauges `data_days{verdict}`, `data_rows_dropped_share{table}`, `data_rule_rows{table,rule}` from the
`check` and `clean` reports; Grafana row "Data quality"; alert BadDataRate (more than 1% of in-session rows dropped).

**Retraining.**
- On alert: Alertmanager → `POST /alerts/webhook` → `state/retrain_request.json` (1 h cooldown) → `runner`
  → `zoo_train` → `zoo_eval` → smoke test → deploy.
- On schedule: `RETRAIN_EVERY_S` in the runner. Manual: `POST /retrain`.

**Versioning.** MLflow registry `nifty-signal`: every version has its run (git commit, DVC data hashes, metrics),
the tag `deploy_check`, and the aliases `champion` / `previous`. `GET /model` shows both.
