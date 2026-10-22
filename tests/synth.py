"""Synthetic raw snapshot in the exact export schema, for tests and the CI smoke run."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
BOOK = [f"{s}{i}_{k}" for s in ("bid", "ask") for i in range(1, 6) for k in ("price", "qty")]


def _ts(day: date, sod: np.ndarray) -> np.ndarray:
    base = int(datetime(day.year, day.month, day.day, tzinfo=IST).timestamp()) * 1_000_000_000
    return base + (sod * 1e9).astype("int64")


def write_day(root: Path, day: date, frozen: bool = False, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    sod = np.arange(9 * 3600, 15 * 3600 + 40 * 60, 2.0)  # a tick every 2 s, 09:00-15:40
    spot = 22900 + (0 if frozen else 1) * np.cumsum(rng.normal(0, 0.3, len(sod)))
    expiry = day + timedelta(days=(1 - day.weekday()) % 7 or 7)
    for t in ("opt_tape", "und_tape", "option_chain_snap"):
        (root / t).mkdir(parents=True, exist_ok=True)

    und = pd.DataFrame(
        {
            "ts_ns": _ts(day, sod),
            "kind": "INDEX",
            "expiry": None,
            "instrument_key": "NSE_INDEX|Nifty 50",
            "trading_symbol": "NIFTY",
            "ltp": spot,
            "ltq": 0.0,
            "volume": 0.0,
            "oi": 0.0,
        }
    )
    fut = und.assign(  # NIFTY futures: a premium over spot, traded every tick (tick-rule flow)
        kind="FUT",
        instrument_key="NSE_FO|NIFTYFUT",
        trading_symbol="NIFTY FUT",
        ltp=spot + 40.0,
        ltq=75.0,
        volume=np.arange(len(sod)) * 75.0,
    )
    pd.concat([und, fut]).to_parquet(root / "und_tape" / f"{day}.parquet")

    rows = []
    for k, strike in enumerate(range(22700, 23101, 50)):
        for side, sign in (("CE", 1), ("PE", -1)):
            mid = np.maximum(5, 100 + sign * (spot - strike) * 0.5)
            df = pd.DataFrame(
                {
                    "ts_ns": _ts(day, sod + 0.1 * k),
                    # ClickHouse exports its Date type to Parquet as a uint16 day count, not a date
                    "expiry": np.uint16((expiry - date(1970, 1, 1)).days),
                    "dte": (expiry - day).days,
                    "strike": float(strike),
                    "side": side,
                    "instrument_key": f"NSE_FO|{strike}{side}",
                    "lot_size": 65,
                    "ltp": mid,
                    "ltq": 65.0,
                    "ltt": 0.0,
                    "volume": np.arange(len(sod)) * 65.0,
                    "avg_price": mid,
                    "oi": 1e5,
                    "total_buy_qty": 5e4,
                    "total_sell_qty": 6e4,
                }
            )
            for i in range(1, 6):
                df[f"bid{i}_price"], df[f"ask{i}_price"] = mid - 0.05 * i, mid + 0.05 * i
                df[f"bid{i}_qty"], df[f"ask{i}_qty"] = 650.0 * i, 520.0 * i
            rows.append(df)
    tape = pd.concat(rows)
    tape = pd.concat([tape, tape.iloc[5000:5010]])  # 10 in-session exact duplicates the check must count
    tape.to_parquet(root / "opt_tape" / f"{day}.parquet")

    snap = sod[::2]
    parts = []
    for strike in range(22700, 23101, 50):
        parts.append(
            pd.DataFrame(
                {
                    "ts_ns": _ts(day, snap),
                    "expiry": str(expiry),
                    "expiry_rank": 0,
                    "dte": (expiry - day).days,
                    "strike": float(strike),
                    "spot": spot[::2],
                    "ce_key": "c",
                    "ce_ltp": 100.0,
                    "ce_bid": 99.9,
                    "ce_ask": 100.1,
                    "ce_oi": 1e5,
                    "ce_volume": 1e4,
                    "ce_iv": 12.0 + (strike - 22900) / 1e4,
                    "ce_delta": 0.5,
                    "pe_key": "p",
                    "pe_ltp": 100.0,
                    "pe_bid": 99.9,
                    "pe_ask": 100.1,
                    "pe_oi": 1.2e5,
                    "pe_volume": 1e4,
                    "pe_iv": 12.5 + (strike - 22900) / 1e4,
                    "pe_delta": -0.5,
                }
            )
        )
    pd.concat(parts).to_parquet(root / "option_chain_snap" / f"{day}.parquet")


def write_holiday(root: Path, day: date) -> None:
    """A holiday as recorded: chain rows with one frozen spot, tape and spot almost empty."""
    write_day(root, day, frozen=True)
    for t in ("opt_tape", "und_tape"):
        p = root / t / f"{day}.parquet"
        pd.read_parquet(p).iloc[:30].to_parquet(p)
