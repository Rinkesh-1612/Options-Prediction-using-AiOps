# Data Cleaning & Transformation

> Clean and transform the data to prepare it for model training. Handle missing values, outliers, and inconsistencies.

**Cleaning.** Stage `clean` ([eda.md](eda.md)): session filter, broken books, wide spreads, closing print,
bad volume/OI, chain placeholders. `data/raw` → `data/clean`.

**Transformation.** Stage `grid` ([grid.py](../../src/optpred/transform/grid.py)): `data/clean` → `data/grid/<day>.parquet`.
- One row per second, 09:15:00–15:29:59: 22,500 rows/day, 1.1 M rows in total, 116 columns.
- Columns: index, future, the front-expiry option legs ATM±2 (CE and PE: bid/ask, size, 5-level depth, LTP, volume,
  OI, age), and the ATM chain IV/delta.
- Each value = the last tick at or before the end of the second, with the same age limit as the EDA (`fill.asof`).
  No look-ahead.
- After the fill, the empty values are below 0.1% for option legs and 0.8% for the chain (most of them on 2026-09-07).

**Checks.** On every row, call prices fall as the strike goes up, put prices rise, and ask > bid.
Test: `tests/unit/test_grid.py` (ATM roll, no future quote).
