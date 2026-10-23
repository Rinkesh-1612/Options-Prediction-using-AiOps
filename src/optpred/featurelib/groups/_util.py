"""Small helpers shared by feature groups. All of them look only backwards."""

from __future__ import annotations

import numpy as np
import pandas as pd

BP = 1e4


def mid(g: pd.DataFrame, leg: str) -> pd.Series:
    return (g[f"{leg}_bid"] + g[f"{leg}_ask"]) / 2


def same_contract(g: pd.DataFrame, n: int) -> pd.Series:
    """True where ATM did not move in the last n seconds, so a leg is the same contract over the window."""
    moved = g["atm"].diff().fillna(0).ne(0).astype(int)
    return moved.rolling(n, min_periods=1).sum().eq(0)


def log_ret(x: pd.Series, n: int) -> pd.Series:
    return np.log(x).diff(n)


def safe_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a / b.where(b != 0)).replace([np.inf, -np.inf], np.nan)
