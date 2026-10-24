"""Volatility forecast inputs (HAR-style) and targets, from one day of data/grid.

Inputs at second t use only data up to t (tested like the features):
  rv_past_{w}   realized NIFTY move over the last w seconds, scaled to 15 minutes, in bp
                (sqrt of the sum of squared 1-second log returns), w = 60, 300, 900, 1800
  rv_day        realized move since the open, scaled to 15 minutes, bp
  iv_move_{h}   move over the next h seconds implied by the ATM IV (mean of call and put), bp
  tod           time of day, 0 at 09:15 and 1 at 15:30
Targets (forward-looking by design, never inputs):
  rv_fwd_{h}    realized move over (t, t+h], bp, h = 300, 900
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from optpred.common.clock import SESSION_FIRST_MIN, SESSION_LAST_MIN

YEAR_S = 252 * 22500  # trading seconds in a year (252 days of 6 h 15 min)
WINDOWS = (60, 300, 900, 1800)
HORIZONS = (300, 900)
OPEN_S, CLOSE_S = SESSION_FIRST_MIN * 60, (SESSION_LAST_MIN + 1) * 60


def sq_returns(g: pd.DataFrame) -> pd.Series:
    s = g["spot"].ffill().to_numpy()
    return pd.Series(np.r_[np.nan, np.diff(np.log(s))] ** 2, index=g.index)


def inputs(g: pd.DataFrame) -> pd.DataFrame:
    """One day of the grid (time order) -> HAR inputs, one row per second."""
    r2 = sq_returns(g)
    out = pd.DataFrame(index=g.index)
    for w in WINDOWS:
        out[f"rv_past_{w}"] = np.sqrt(r2.rolling(w, min_periods=w // 2).sum() * (900 / w)) * 1e4
    out["rv_day"] = np.sqrt(r2.expanding(60).mean() * 900) * 1e4
    iv = ((g["ce_iv"] + g["pe_iv"]) / 2).ffill()
    for h in HORIZONS:
        out[f"iv_move_{h}"] = iv / 100 * np.sqrt(h / YEAR_S) * 1e4
    out["tod"] = (g["sod"] - OPEN_S) / (CLOSE_S - OPEN_S)
    return out


def targets(g: pd.DataFrame) -> pd.DataFrame:
    r2 = sq_returns(g)
    return pd.DataFrame(
        {
            f"rv_fwd_{h}": np.sqrt(r2[::-1].rolling(h, min_periods=h).sum()[::-1].shift(-1)) * 1e4
            for h in HORIZONS
        },
        index=g.index,
    )


def design(X: pd.DataFrame, h: int, with_iv: bool) -> pd.DataFrame:
    """Model matrix of the linear forecasters: logs of the moves, time of day and its square."""
    cols = [f"rv_past_{w}" for w in WINDOWS] + ["rv_day"] + ([f"iv_move_{h}"] if with_iv else [])
    M = np.log(X[cols].clip(lower=1e-3)).fillna(0.0)
    return M.assign(tod=X["tod"], tod2=X["tod"] ** 2)
