# Project Plan — Predicting Short-Term Direction of NIFTY Options (DA3408)

Living document. Every decision here has a reason next to it; change the decision,
change the reason. Course rubric: `DA3408/AI Application Evaluation Guideline.pdf`.

## 1. The question

At the end of each minute, choose one of **BUY_CE / BUY_PE / STAY_OUT** for the
ATM NIFTY option of the nearest expiry, where a trade is judged by its rupee result
**after the spread, taxes and slippage**, held for a fixed **2 minutes**.

If no reliable edge is found on unseen days, the project reports that. That is a
valid result.

## 2. The data (measured 2026-10-17 on the VPS)

| Table (ClickHouse, Ravion-V2) | What it is | Days | Rows/day | Total |
|---|---|---|---|---|
| `ravion.opt_tape` | Every NIFTY option tick, 5-level bid/ask, 2 expiries | 23-Jul → 16-Oct | ~1.0M before 11-Aug, ~1.8M after | ~85M |
| `ravion.option_chain_snap` | Chain snapshot every ~2.5 s: IV, delta, OI, ~25 strikes × 2 expiries | 03-Aug → 16-Oct | ~238k | ~13M |
| `ravion.depth_ticks` | 5-level book; ~99.99% of rows have an empty `symbol` — instrument not yet identified | 03-Aug → 16-Oct | ~650k | ~34M |

Facts found, and what we do about them:

| Fact | Evidence | Action |
|---|---|---|
| Chain table records on exchange holidays with frozen prices | 14-Sep, 02-Oct: tape ~68 rows, chain ~238k rows; 02-Oct has exactly 1 unique spot | Drop any day where the tape is near-empty (quality rule, Spark `check` stage) |
| Tape missing days | 25-Sep, 28-Sep, 29-Sep absent | Excluded |
| Partial chain days | 07-Sep (~165k), 16-Oct (~160k) | Flag; features must not depend on chain for those minutes or the day is dropped |
| Strike window widened on 11-Aug | 07-Aug: 11 strikes / 44 keys; 12-Aug: 21 strikes / 84 keys | Use ATM contract only; features per minute, never raw tick counts across strikes |
| Recorder runs 09:00–15:40 | min/max ts | Use 09:15–15:30 only; last entry at 15:28 so the 2-min exit is inside the session |
| One strike carries two expiries | 2 expiries every day | Key every series on `instrument_key`, never `strike` (Ravion rule) |

The statement's "22M snapshots / 27M order-book records" will be corrected to these
measured numbers in the report.

## 3. Train / validation / test split (by whole days, in time order)

| Part | Days | Count | Use |
|---|---|---|---|
| Train | 03-Aug → 18-Sep | 34 | Fit models |
| Validation | 21-Sep → 01-Oct | 6 | Choose settings and the decision threshold |
| Test (locked) | 05-Oct → 16-Oct | 10 | Opened **once**, at the end |
| Forward test | 19-Oct onwards | grows | Days recorded after the model was frozen |

Exact day list is produced by the `check` stage and committed as `data/days.yaml`;
the table above is provisional until then.

## 4. Label and P&L (the most important definitions)

For each minute *t* (decision made on data up to the end of *t*):

    entry   = best ask of the ATM option at the end of minute t
    exit    = best bid of the SAME instrument_key at the end of minute t+2
    gross   = (exit - entry) * 65                      # lot size 65
    cost    = statutory(entry, exit) + slippage        # statutory ~Rs18 (Ravion formula,
                                                        # zero brokerage); slippage 0.31 pt/leg
    net     = gross - cost

    label   = BUY_CE  if net_CE > 0 and net_CE >= net_PE
              BUY_PE  if net_PE > 0 and net_PE >  net_CE
              STAY_OUT otherwise

- ATM = strike nearest to spot at minute *t*, nearest expiry (Ravion convention).
- Cost formula copied from `Ravion-V2/common/ravion_quant.py::option_roundtrip_cost_rs`
  (brokerage zero per contract note 2026-08-06).
- **Open assumption:** the 0.31 pt/leg slippage may already include part of the spread
  (it was measured on 10 live legs; its reference price is not documented). Main result
  charges it on top of bid/ask (the harder hurdle); the result without it is reported
  alongside as a sensitivity.
- Horizon is fixed at 2 minutes **before** looking at results. 1 and 3 minutes are
  reported as side checks only, never chosen after the fact.

## 5. Evaluation (how we avoid fooling ourselves)

- **No overlapping trades in evaluation.** One position at a time; signals during an
  open trade are ignored. This is how it would actually be traded, and it stops one
  market move from being counted many times.
- **Unit of evidence is the day.** Report per-day net P&L, mean net per trade, hit rate,
  trade count, and a day-level bootstrap 95% interval. If the interval includes zero,
  the result is "not detected at this sample size", with the smallest effect the sample
  could resolve.
- **Baselines**, run through the same simulator and costs:
  1. Always STAY_OUT (P&L = 0 by definition)
  2. Momentum: sign of the last 2-min spot move → CE/PE
  3. Random, at the same trade frequency as the model
- **Independent route:** the final verdict is re-checked as a ravlab spec in Ravion-V2
  (Ravion CLAUDE.md rule) before it is used for any real trading decision.

## 6. Features (per minute, ATM CE and PE, data up to end of minute t only)

Order book: L1 imbalance, L1–L5 imbalance, total buy/sell qty ratio, spread (pts and %
of premium). Price: option mid return over 1/3/5 min, spot return over 1/3/5 min,
realised volatility last 5 min. Activity: traded volume last 1 min. Chain: ATM IV and
its 5-min change, OI change, put-call OI ratio near ATM. Time: minutes since open,
minutes to close, days to expiry, expiry-day flag.

## 7. Models

- LightGBM multiclass (gradient-boosted trees), class weights for the STAY_OUT-heavy
  label. Action taken only if its probability passes a threshold chosen on validation.
- Hyper-parameter search with Ray Tune, walk-forward folds by day inside the train set.
- Explanations: SHAP values per prediction, shown in the UI.

## 8. System (maps to the rubric)

| Component | Tool | Rubric line |
|---|---|---|
| `export` — ClickHouse → Parquet, read-only, partitioned by date | Python + `clickhouse-client FORMAT Parquet` | Data engineering |
| `check` — day-level quality rules, quality report JSON | Spark | Data engineering |
| `features` — ticks → 1-min ATM features + labels | Spark | Data engineering (throughput logged) |
| `train` / `tune` | LightGBM + Ray Tune | Experiment tracking |
| Tracking + registry, aliases `champion` / `previous` (rollback) | MLflow (server + registry) | Experiment tracking, packaging |
| Pipeline DAG: export → check → features → train → evaluate → register | DVC (`dvc repro`) | CI with DVC |
| CI | git pre-push hook: ruff, pytest, `dvc status` on a 1-day sample | CI |
| Model serving | `mlflow models serve` container | Packaging |
| Backend API | FastAPI: `/predict`, `/minute/{ts}`, `/pipeline/status`, `/retrain`, `/rollback`, `/metrics` | Packaging, LLD |
| Frontend | Static web app (nginx), talks to FastAPI only via configurable REST URL | UI, loose coupling |
| Pipeline screen | Page in frontend: DVC DAG, stage runs/failures, rows/sec, links to MLflow | Pipeline visualization |
| Replay | Feeds test / forward days minute by minute as if live | Monitoring demo |
| Monitoring | Prometheus (API, pipeline via pushgateway, node exporter), Grafana: prediction vs actual, P&L, latency, drift (PSI per feature) | Exporter + Grafana |
| Drift → retrain | Prometheus alert → webhook → `dvc repro`; new model registered as candidate, promoted only if validation not worse; rollback = move `champion` alias back | Monitoring & maintenance |
| Packaging | Docker Compose, own project name, network and ports (does not touch Ravion's stack); `MLproject` file | Packaging |
| Versioning | Git, Git LFS (1-day sample Parquet), DVC local remote on the VPS | Source control |
| Security | Full data snapshot encrypted (age/gpg); key never in repo | Best practices |

Documents (mandatory): architecture diagram, HLD, LLD (endpoint I/O), test plan + test
cases + test report, user manual.

## 9. Constraints

- Same VPS as live trading: Spark/Ray memory capped, heavy jobs after 15:30 IST,
  separate compose project, no writes to Ravion's ClickHouse.
- No managed cloud services.
- Solo project. Code is written here and pushed; it is run on the VPS by the operator.

## 10. Build order

1. Repo skeleton, `export` stage, data days list → verify: row counts match §2.
2. `check` (Spark) → verify: holidays and gap days are rejected, report written.
3. `features` + labels (Spark) → verify: hand-check 3 random minutes against raw ticks.
4. Baselines + simulator → verify: STAY_OUT = 0, momentum hand-computed on one day.
5. LightGBM + MLflow + Ray Tune → verify: runs tied to git commit and DVC data hash.
6. FastAPI + MLflow serve + frontend + Docker Compose.
7. Prometheus, Grafana, replay, drift → retrain, rollback.
8. Tests, CI hook, docs, final locked test, forward test, report.

## 11. Open questions

- Deadline.
- What `depth_ticks` rows with empty `symbol` are (likely NIFTY futures) — useful as an
  underlying order-book feature if so.
- VPS resources free for this project (CPU, RAM, disk).
- Slippage reference price (see §4).
