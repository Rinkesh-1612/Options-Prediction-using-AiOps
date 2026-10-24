# High-level design

## 1. Problem and goal

I trade NIFTY options. The question: at each second, should I buy the ATM call, buy the ATM put, or stay
out, after all costs? The system must answer this with a controlled AIOps pipeline, and it must become a
reusable signal library for Ravion V2. Success metric: **net ₹ per day after costs on test days that no
model was trained or tuned on**, with a 95% bootstrap interval over days, against baselines.

Results: **direction — no edge detected** (`reports/zoo/comparison.md`). **Volatility — predictable:** a second
model forecasts the NIFTY move over the next 5 / 15 min and beats the option market's implied forecast on 10 of 10
test days (`reports/vol/comparison.md`). A good volatility forecast did not make straddles profitable after the spread
(research branch `forward-data`: volatility, expiry-day and execution studies, with the forward days); for Ravion it is a filter and sizing input.

## 2. Design rules

1. **No look-ahead.** Every feature uses only data up to its second (tested for every feature). Gaps are
   filled forward with an age limit, never backward or by interpolation.
2. **One definition of a trade.** Entry at the ask, exit at the bid, statutory costs (checked against the
   author's contract note). The labels, the simulator and the API use the same code.
3. **Day is the unit.** Stages work per day (Ray tasks); splits are by whole day; a trade never crosses a day.
4. **Choose on validation, report on test.** Champion and threshold come from walk-forward CV on the dev days.
   The test days only report.
5. **Everything is a stage.** DVC runs it; the run journal (`runs/runs.jsonl`) records commit, parameters,
   duration and result; MLflow records models and metrics with the commit and the DVC data hashes.

## 3. Main decisions

| Decision | Why | Not chosen |
|---|---|---|
| 1-second ATM-relative grid | Keeps the order-flow detail; minute data can be made from it | Minute bars (loses detail) |
| Triple-barrier labels (σ-scaled take-profit / stop-loss, time cap) | The holding time follows the market; not fixed | One fixed horizon |
| Model zoo: baselines, ridge, LightGBM (reg / clf), meta-labelling, GRU, transformer | Fair comparison of all families on one label, one split, one simulator | One model |
| Feature library with a registry | Add a feature = one function; CI tests it automatically | Hand-written feature table |
| Deploy gate + alias-following server | Promotion = deployment; a bad version never serves; automatic rollback | Manual restarts |
| Drift limits from normal dev-day variation | Fixed PSI limits flagged 45 of 49 normal days | One global PSI limit |
| Second target: volatility (HAR vs implied IV, QLIKE) | Direction has no signal (corr ≈ 0.01); volatility clusters (corr ≈ 0.68) | More direction models |
| pandas + Ray per day; Spark for the day check | Per-day data fits in memory; Ray gives parallel days; Spark scans all 114 M raw rows | Spark for every stage |

## 4. Technology (course guideline → this project)

| Guideline | Used |
|---|---|
| Version control: Git, Git LFS, DVC | Git (code, reports, journal), LFS (sample day), DVC (data, remote) |
| Data engineering: Spark, Ray | Spark (`check`), Ray tasks (all per-day stages), Ray Tune (training) |
| Experiment tracking: MLflow | Experiment `nifty-zoo`, registry `nifty-signal` |
| Containerization: Docker, Compose | Pipeline image, serving image (multi-stage), frontend image, Compose stack |
| CI/CD: DVC | `dvc repro` = training + evaluation + gated deployment; pre-push hook = lint + tests |
| Serving: MLflow Serve, REST | `mlflow models serve` behind the FastAPI API |
| Monitoring: Prometheus, Grafana | Metrics, 8 alerts, dashboard; Alertmanager → retraining |
| No cloud | One self-managed VPS |

## 5. Best practices

- **Code quality:** ruff (PEP 8), docstrings in every module, one requirements file.
- **Testing:** unit, integration, API and end-to-end tests ([TEST_PLAN.md](TEST_PLAN.md)).
- **Security:** AES-256 encrypted backup of data and models; admin token for rollback and retraining;
  services bound to localhost by default; ClickHouse read-only.
- **Scalability:** the work grows with the number of days; days run in parallel on Ray (CPU limit in
  `params.yaml`, so live trading keeps its CPUs). New days = `dvc repro`.
- **Explainability:** global: gain importance and group ablation for the champion (Results tab, MLflow). Per signal:
  exact SHAP values of the score (`/signal` → `drivers`; Signal tab, "Why the put scored …"). They add up to the score.
- **Collaboration:** shared MLflow UI, Grafana, Git history, `docs/steps/` (one reviewed note per rubric item).
