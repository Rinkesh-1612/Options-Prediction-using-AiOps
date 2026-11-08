# Data Identification & Acquisition — DONE

> Identify and collect relevant data from various sources. Document data sources, formats, and potential biases.

**Source.** My own NIFTY options recording from Ravion V2 (Upstox websocket and REST option chain → ClickHouse).
The `export` stage ([export.py](../../src/optpred/data/export.py)) copies it once, read-only, into Parquet.
Each file's row count is checked against the server.

**Data.** 2026-08-03 to 2026-10-16: 55 days, 49 accepted, about 114 M rows, 4.1 GB.

| Table | One row | Rate |
|---|---|---|
| `opt_tape` | one option contract: LTP, volume, OI, 5-level book | ~0.75 s |
| `und_tape` | NIFTY index or future | ~10 ms (index) |
| `option_chain_snap` | one strike, CE + PE: bid/ask/IV/delta | ~2–5 s |

Format: one Parquet file per table per day, `ts_ns` = UTC nanoseconds.

**Layout.**
```
data/raw/<table>/YYYY-MM-DD.parquet   source snapshot (DVC)
data/raw/manifest.json                rows per file
data/days.json                        accepted / rejected days
data/clean, grid, feat, labels, modelout   derived by DVC stages
```

**Biases.**
- NIFTY only, near-ATM strikes only (by design).
- About 2.5 months, one regime (an edge is expected to last 2–3 months).
- Broker feed updates, not exchange ticks.
- 6 bad days and some placeholder chain values (handled in EDA).
- Snapshot frozen at 2026-10-16 (for reproducibility).
