"""Time of day, NIFTY spot and NIFTY future."""

from __future__ import annotations

import numpy as np
import pandas as pd

from optpred.common.clock import SESSION_FIRST_MIN, SESSION_LAST_MIN
from optpred.featurelib.groups._util import BP, log_ret
from optpred.featurelib.registry import feature

OPEN_S, CLOSE_S = SESSION_FIRST_MIN * 60, (SESSION_LAST_MIN + 1) * 60
SPOT_WINDOWS = (5, 15, 30, 60, 120, 300)


@feature(group="time", lookback_s=0)
def clock(g: pd.DataFrame) -> pd.DataFrame:
    """Minutes since 09:15, minutes to 15:30, days to expiry, expiry-day flag."""
    return pd.DataFrame(
        {
            "min_since_open": (g["sod"] - OPEN_S) / 60,
            "min_to_close": (CLOSE_S - g["sod"]) / 60,
            "dte": g["dte"],
            "is_expiry_day": (g["dte"] == 0).astype(int),
        },
        index=g.index,
    )


@feature(group="spot", lookback_s=max(SPOT_WINDOWS))
def spot_returns(g: pd.DataFrame) -> pd.DataFrame:
    """NIFTY log return over the last 5, 15, 30, 60, 120, 300 s, in basis points."""
    return pd.DataFrame({f"spot_ret_{n}s": log_ret(g["spot"], n) * BP for n in SPOT_WINDOWS}, index=g.index)


@feature(group="spot", lookback_s=300)
def spot_volatility(g: pd.DataFrame) -> pd.DataFrame:
    """Realised volatility: std of 1-second NIFTY returns over the last 60 and 300 s, in bp."""
    r1 = log_ret(g["spot"], 1) * BP
    return pd.DataFrame({f"spot_vol_{n}s": r1.rolling(n).std() for n in (60, 300)}, index=g.index)


@feature(group="spot", lookback_s=300)
def spot_range_position(g: pd.DataFrame) -> pd.DataFrame:
    """Where spot sits in its 300 s high-low range (0 = low, 1 = high); and spot - ATM in strikes."""
    hi, lo = g["spot"].rolling(300).max(), g["spot"].rolling(300).min()
    pos = ((g["spot"] - lo) / (hi - lo)).where(hi > lo)
    return pd.DataFrame(
        {"spot_range_pos_300s": pos, "spot_atm_offset": (g["spot"] - g["atm"]) / 50}, index=g.index
    )


@feature(group="future", lookback_s=300)
def future_basis(g: pd.DataFrame) -> pd.DataFrame:
    """Future minus spot (points), its change over 60 and 300 s, and the future's 15 s lead over spot (bp)."""
    basis = g["fut"] - g["spot"]
    lead = (log_ret(g["fut"], 15) - log_ret(g["spot"], 15)) * BP
    return pd.DataFrame(
        {
            "basis": basis,
            "basis_chg_60s": basis.diff(60),
            "basis_chg_300s": basis.diff(300),
            "fut_lead_15s": lead,
        },
        index=g.index,
    )


@feature(group="future", lookback_s=60)
def future_volume(g: pd.DataFrame) -> pd.DataFrame:
    """NIFTY future contracts traded in the last 10 and 60 s (log1p)."""
    v = g["fut_volume"]
    return pd.DataFrame({f"fut_vol_{n}s": np.log1p(v.diff(n).clip(lower=0)) for n in (10, 60)}, index=g.index)
