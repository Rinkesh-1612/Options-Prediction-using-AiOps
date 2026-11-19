# Model Training & Evaluation

> Train models, experiment with hyperparameters and architectures. Evaluate with appropriate metrics,
> compare models, select the best. AIOps: automate, track versions / hyperparameters / metrics (MLflow), Docker.

**Code.** [src/optpred/zoo/](../../src/optpred/zoo/): stages `zoo_train` and `zoo_eval`. Settings: `params.yaml → zoo`.

**Training (`zoo_train`).** 3 families (stay-out baseline, linear, LightGBM), 8 settings (`zoo.grid`), on the 39 dev days only.
- Walk-forward by day: 4 folds (train on the first 19, 24, 29, 34 days, validate on the next 5).
- Ray Tune runs the settings in parallel (4 CPUs). For each setting, tau (the trade threshold) is chosen on
  the pooled validation scores.
- MLflow (experiment `nifty-zoo`): one parent run per family, one child run per setting, with params, metrics
  per fold, git commit and DVC data hashes.
- The best LightGBM model also gets gain importance and a group ablation (`reports/zoo/importance.json`).

**Metrics.** One simulator scores every model: one position at a time, entry at the ask, exit at the bid at
the triple barrier, net ₹ after costs. Reported: net ₹/day (main), trades, hit rate, daily Sharpe, max drawdown,
IC (rank correlation of score vs net ₹), and on the test days a 95% bootstrap interval over days.

**Selection (`zoo_eval`).** Champion = the best non-baseline family by cross-validation, chosen before the test
numbers are read. All families are scored on the 10 test days (`reports/zoo/comparison.md`).

| Family | CV ₹/day | Test ₹/day | 95% CI | Trades | Hit |
|---|---|---|---|---|---|
| lgbm_reg (champion) | 246 | −1,376 | −2,936 … 0 | 132 | 0.41 |
| linear | 98 | −137 | −686 … 275 | 9 | 0.56 |
| stay_out (baseline) | 0 | 0 | n/a | 0 | n/a |

**Result: no edge.** No model beats "stay out" on the test days. The CV edge was weak (IC ≈ ±0.01). Without the spot, future or
chain features, the CV result falls to ₹0 a day, because the model stops trading. The edge did not hold on the test days. The test days were seen by the old
models (not trained or tuned on).

**Reproducibility.** The final runs of `zoo_train`, `zoo_eval`, `vol` and `drift` were made on the clean commit
`972f975` (in the runs: `d864f63`, see [commit_map.md](../commit_map.md)) (MLflow tags `git_commit`, `git_dirty = False`, DVC data hashes; journal `logs/runs.jsonl`).

**Docker.** Every stage runs in the pipeline image (`./pipe`, `docker/Dockerfile.pipeline`, one `requirements.txt`).
