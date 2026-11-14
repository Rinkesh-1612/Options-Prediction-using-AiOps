# Data Exploration & Analysis (EDA)

> Perform EDA to understand data characteristics, identify patterns, and detect potential issues
> (e.g., missing values, outliers).

**Code.** [src/optpred/eda/](../../src/optpred/eda/): two DVC stages, `clean` (raw → `data/clean`) and `eda` (profile + plots).
`rules.py` = outlier rules, `fill.py` = missing-value policy. Thresholds in `params.yaml → eda`. Tests: `tests/unit/test_eda_rules.py`.

**Missing values.**
- Missing days (5 frozen, 1 partial): dropped by `check`. A day is never invented.
- Gaps inside a day: forward fill with an age limit (options 20 s, index 5 s, chain 30 s), then NaN.
  No backfill, interpolation or KNN: they use future values (look-ahead).
- After the fill rule, 0.2% of index minutes and about 5% of option minutes are missing. 2026-09-07 has a partial chain (266/375 min).

**Outliers (financial rules), over 49 days.**

| Rule | Rows |
|---|---|
| Outside 09:15–15:30 | 2.29 M dropped |
| One-sided book (bid or ask = 0) | 4,501 dropped |
| Spread > 25% of mid (premium ≥ ₹1) | 1,500 dropped |
| Index closing print (jump > 0.15% after 15:28) | 12,412 dropped |
| Cumulative volume above a later value (yesterday's total at 09:15) | 1,238 → NaN |
| OI ≤ 0 | 2,711 → NaN |
| Chain IV = 0 / delta = ±1 (Upstox placeholder) | 1.3 M → NaN |
| Chain spot > 25 pts from index (open / close print) | 10,950 → NaN |

**Patterns** (`reports/eda/*.png`).
- Activity, spread and index moves form a U-shape over the day. The largest values are at the open and the close.
- The median spread is 0.27% of mid above ₹100, and 8% below ₹1. Cheap options cannot be traded at a profit.
- NIFTY 1-minute returns: std 2.35 bp, excess kurtosis 9.9 (fat tails), lag-1 autocorrelation 0.02 (almost none).
