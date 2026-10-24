"""Feature registry. A feature is a function: one day of data/grid in, a DataFrame of columns out.

Add a feature:
    1. Write a function in a module under optpred/featurelib/groups/ (or make a new module and import it
       in groups/__init__.py).
    2. Put @feature(group="...", lookback_s=N) on it. N = the longest window it looks back, in seconds.
    3. Give it a docstring: it goes into the catalog.
That is all. tests/unit/test_featurelib.py checks every registered feature (no look-ahead, unique columns,
row count) and DVC rebuilds data/feat when the code changes.

Rules for a feature function:
  * Input: one day of the grid, rows in time order (one per second). Never mix days.
  * Use only the current and earlier rows (shift(n) with n >= 0, diff, trailing rolling). No shift(-n).
  * Return one row per input row, with the same index. NaN where the window is not full yet.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Feature:
    name: str
    group: str
    lookback_s: int
    fn: Callable[[pd.DataFrame], pd.DataFrame]
    doc: str


REGISTRY: dict[str, Feature] = {}
KEYS = ["day", "sod", "atm"]  # row keys written next to the features; no feature may use these names


def feature(group: str, lookback_s: int) -> Callable:
    def wrap(fn: Callable[[pd.DataFrame], pd.DataFrame]) -> Callable:
        if fn.__name__ in REGISTRY:
            raise ValueError(f"feature {fn.__name__!r} is registered twice")
        doc = inspect.getdoc(fn) or ""
        REGISTRY[fn.__name__] = Feature(fn.__name__, group, lookback_s, fn, doc)
        return fn

    return wrap


def load() -> dict[str, Feature]:
    """Import every group module so that all features register."""
    import optpred.featurelib.groups  # noqa: F401

    return REGISTRY


def select(groups: list[str] | str = "all") -> list[Feature]:
    feats = list(load().values())
    return feats if groups == "all" else [f for f in feats if f.group in groups]


def compute(day_grid: pd.DataFrame, feats: list[Feature]) -> pd.DataFrame:
    """Run the features on one day and join their columns. Fails on a duplicate column."""
    parts = []
    for f in feats:
        out = f.fn(day_grid)
        if len(out) != len(day_grid):
            raise ValueError(f"{f.name}: {len(out)} rows, expected {len(day_grid)}")
        parts.append(out)
    df = pd.concat(parts, axis=1).astype("float64")  # contract: every feature is a float (serving schema)
    dup = df.columns[df.columns.duplicated() | df.columns.isin(KEYS)].tolist()
    if dup:
        raise ValueError(f"duplicate or reserved feature columns: {dup}")
    return df
