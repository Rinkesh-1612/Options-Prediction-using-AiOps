"""Data-quality rules for the raw NIFTY tables. Pure functions: DataFrame in, DataFrame + counts out.

Two kinds of rule:
  DROP  the row cannot be a real, tradable market state (outside session, broken book, bad print).
  NULL  one field is a placeholder or stale; the rest of the row is valid, so only that field becomes NaN.

Every rule is counted, so the cleaning report shows exactly what was removed and why.
Thresholds come from params.yaml -> eda. They were chosen from the measured data (docs/steps/eda.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from optpred.common.clock import IST_OFFSET_S, SESSION_FIRST_MIN, SESSION_LAST_MIN

SESSION_START_S = SESSION_FIRST_MIN * 60  # 09:15:00
SESSION_END_S = (SESSION_LAST_MIN + 1) * 60  # 15:30:00 (exclusive)


def add_sod(df: pd.DataFrame) -> pd.DataFrame:
    """Add `sod` = seconds since IST midnight (see optpred.common.clock)."""
    return df.assign(sod=((df["ts_ns"] // 1_000_000_000 + IST_OFFSET_S) % 86400).astype("int32"))


def later_min(values: pd.Series, key: pd.Series) -> pd.Series:
    """Smallest value among the LATER rows of the same key (NaN for the last row). Sorted input."""
    rev = values[::-1].groupby(key[::-1]).cummin()
    return rev.groupby(key[::-1]).shift()[::-1]


class Counter:
    """Applies rules in order and counts what each one did."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df
        self.counts: dict[str, int] = {"rows_in": len(df)}

    def drop(self, name: str, mask: pd.Series) -> None:
        mask = mask.fillna(False).astype(bool)
        self.counts[f"drop_{name}"] = int(mask.sum())
        self.df = self.df[~mask]

    def null(self, name: str, mask: pd.Series, cols: list[str]) -> None:
        mask = mask.fillna(False).astype(bool)
        self.counts[f"null_{name}"] = int(mask.sum())
        self.df = self.df.copy()
        self.df.loc[mask, cols] = np.nan

    def result(self) -> tuple[pd.DataFrame, dict[str, int]]:
        self.counts["rows_out"] = len(self.df)
        return self.df.reset_index(drop=True), self.counts


def outside_session(df: pd.DataFrame) -> pd.Series:
    return (df["sod"] < SESSION_START_S) | (df["sod"] >= SESSION_END_S)


def isolated_spike(price: pd.Series, key: pd.Series, max_jump: float) -> pd.Series:
    """True where a price jumps by more than `max_jump` (log) and the next tick jumps straight back.

    A real move stays; a bad print reverts at once. Input must be sorted by key, then time.
    """
    lp = np.log(price)
    r_in = lp.groupby(key).diff()
    r_out = -lp.groupby(key).diff(-1)  # move from this tick to the next
    return (r_in.abs() > max_jump) & (r_out.abs() > max_jump) & (np.sign(r_in) != np.sign(r_out))


# Rules for opt_tape


def clean_opt_tape(df: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, dict[str, int]]:
    c = Counter(add_sod(df).sort_values(["instrument_key", "ts_ns"], kind="stable"))
    c.drop("outside_session", outside_session(c.df))
    bid, ask = c.df["bid1_price"], c.df["ask1_price"]
    c.drop("one_sided_book", (bid <= 0) | (ask <= 0))
    bid, ask = c.df["bid1_price"], c.df["ask1_price"]
    c.drop("crossed_book", bid >= ask)

    mid = (c.df["bid1_price"] + c.df["ask1_price"]) / 2
    rel = (c.df["ask1_price"] - c.df["bid1_price"]) / mid
    # Below Rs1 the 0.05 tick alone makes the relative spread large, so the rule starts at spread_min_mid.
    c.drop("wide_spread", (mid >= p["spread_min_mid"]) & (rel > p["max_rel_spread"]))

    mid = (c.df["bid1_price"] + c.df["ask1_price"]) / 2
    c.drop("mid_spike", isolated_spike(mid, c.df["instrument_key"], p["max_mid_jump"]))

    # Cumulative day volume can never be above a LATER value of the same contract. The usual case:
    # at 09:15:00 the feed repeats yesterday's total (e.g. 60.8 M) once, then restarts from today's.
    c.null(
        "volume_above_later", c.df["volume"] > later_min(c.df["volume"], c.df["instrument_key"]), ["volume"]
    )
    c.null("oi_not_positive", c.df["oi"] <= 0, ["oi"])
    out, counts = c.result()
    return out.sort_values("ts_ns", kind="stable").reset_index(drop=True), counts


# Rules for und_tape


def closing_print(df: pd.DataFrame, from_s: int, max_jump: float) -> pd.Series:
    """True from the first index tick after `from_s` that jumps by more than `max_jump` (log).

    NSE computes the index close as an average of the last 30 minutes and publishes it in the last
    1-2 minutes. That print is not a traded level, and everything after it repeats it.
    """
    late = df["sod"] >= from_s
    jump = np.log(df["ltp"]).diff().abs() > max_jump
    return (late & jump).cummax()


def clean_und_tape(df: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, dict[str, int]]:
    c = Counter(add_sod(df).sort_values(["kind", "ts_ns"], kind="stable"))
    c.drop("outside_session", outside_session(c.df))
    c.drop("not_positive_price", c.df["ltp"] <= 0)
    c.drop("duplicate", c.df.duplicated(["instrument_key", "ts_ns"]))
    idx = c.df["kind"] == "INDEX"
    close = pd.Series(False, index=c.df.index)
    close[idx] = closing_print(c.df[idx], p["close_from_s"], p["close_max_jump"])
    c.drop("index_closing_print", close)
    out, counts = c.result()
    return out.sort_values("ts_ns", kind="stable").reset_index(drop=True), counts


# Rules for option_chain_snap


def clean_chain(df: pd.DataFrame, index: pd.DataFrame, p: dict) -> tuple[pd.DataFrame, dict[str, int]]:
    """`index` = cleaned INDEX rows of und_tape (ts_ns, ltp), used to check the chain's spot."""
    c = Counter(add_sod(df).sort_values("ts_ns", kind="stable"))
    c.drop("outside_session", outside_session(c.df))
    for s in ("ce", "pe"):
        # Upstox sends iv=0 and delta=+-1 when it cannot compute them (mostly deep ITM).
        c.null(f"{s}_iv_placeholder", c.df[f"{s}_iv"] <= 0, [f"{s}_iv", f"{s}_delta"])
        b, a = c.df[f"{s}_bid"], c.df[f"{s}_ask"]
        c.null(f"{s}_bad_book", (b <= 0) | (a <= 0) | (b >= a), [f"{s}_bid", f"{s}_ask"])
    ref = pd.merge_asof(
        c.df[["ts_ns"]], index[["ts_ns", "ltp"]].sort_values("ts_ns"), on="ts_ns", direction="backward"
    )["ltp"].to_numpy()
    c.null("spot_off_index", (c.df["spot"] - ref).abs() > p["max_spot_gap_pts"], ["spot"])
    return c.result()
