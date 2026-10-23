# Feature Engineering — DONE (open for more)

> Create new features from existing ones to improve model performance.

**Design: a feature library with CI.** [src/optpred/featurelib/](../../src/optpred/featurelib/)
- A feature = one function with `@feature(group, lookback_s)` in `groups/*.py`. One day of `data/grid` in, columns out.
- Stage `feat`: `data/grid` → `data/feat/<day>.parquet`. Groups are switched on in `params.yaml → feat.groups`.
- Generated: [reports/feature_catalog.md](../../reports/feature_catalog.md) (from the docstrings) and `reports/feat.json` (NaN share, mean, std).

**CI** (`tests/unit/test_featurelib.py`, run by the pre-push hook). Each registered feature is tested automatically:
no look-ahead (the value at t stays the same when the data after t is removed), docstring, row count, no inf,
values after the lookback, unique column names.

**Current set:** 10 features, 46 columns.

| Group | Features |
|---|---|
| time | minutes since open / to close, DTE, expiry day |
| spot | returns 5–300 s, realised vol 60/300 s, range position, distance to ATM |
| future | basis and its change, future lead over spot, future volume |
| book | ATM CE/PE: spread, L1 and 5-level imbalance, microprice offset |
| flow | ATM CE/PE: mid return, volume, OI change; call-vs-put volume and depth |
| chain | ATM IV, skew, IV change, straddle as bp of spot |

**Add a feature:** write a function in `groups/`, put `@feature` on it, run `dvc repro feat`.
