"""Input drift: has the market the model sees now moved away from the market it learned from?

Method: Population Stability Index (PSI) per feature. Bin edges come from the training rows
(deciles). The PSI compares the share of recent rows in each bin with the share of training rows.
Rule of thumb used in industry (and by the course): PSI < 0.10 stable, 0.10-0.25 watch, > 0.25 drift.

WINDOW SIZE MATTERS. Market conditions change from day to day: on real data one single day already
shows PSI above 0.25 on about half of the features against the training days, even a training day.
So the window must span several sessions (default 2000 rows, about 5 sessions), never one day.

`DriftMonitor` keeps a rolling window of the feature rows the API served. It needs no labels, so it
can warn before the model's results get worse. Pure numpy: the serving image has no Spark.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

# Features that differ by construction between any two stretches of time, so PSI on them is not drift:
# time of day, days to expiry and the expiry flag follow the calendar; option prices follow the index
# level. The model sees them, but a drift alarm on them would fire every day.
CALENDAR_AND_LEVEL = frozenset({"minute", "dte", "is_expiry_day", "ce_mid", "pe_mid"})

PSI_WATCH = 0.10
PSI_DRIFT = 0.25
EPS = 1e-4  # share floor, so an empty bin does not give log(0)


def monitored(columns: list[str]) -> list[str]:
    """The features worth a drift check: all except calendar and price-level ones."""
    return [c for c in columns if c not in CALENDAR_AND_LEVEL]


def bin_edges(reference: pd.Series, bins: int = 10) -> np.ndarray:
    """Interior bin edges from the reference values (unique, so constant features give no edges)."""
    q = np.quantile(reference.dropna().to_numpy(float), np.linspace(0, 1, bins + 1)[1:-1])
    return np.unique(q)


def shares(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(edges, values, side="right")
    counts = np.bincount(idx, minlength=len(edges) + 1).astype(float)
    return np.clip(counts / max(counts.sum(), 1.0), EPS, None)


def psi(reference: pd.Series, recent: pd.Series, bins: int = 10) -> float:
    """PSI of `recent` against `reference`. 0 means identical distributions."""
    edges = bin_edges(reference, bins)
    if len(edges) == 0:  # constant reference: any change is a change, but there is no scale for it
        return 0.0
    ref, cur = (
        shares(reference.dropna().to_numpy(float), edges),
        shares(recent.dropna().to_numpy(float), edges),
    )
    return float(np.sum((cur - ref) * np.log(cur / ref)))


class DriftMonitor:
    """Rolling window of served feature rows, compared with the training rows."""

    def __init__(
        self,
        reference: pd.DataFrame,
        columns: list[str],
        window: int = 300,
        min_rows: int = 100,
        psi_limit: float = PSI_DRIFT,
        max_share: float = 0.2,
    ):
        self.columns, self.min_rows = list(columns), min_rows
        self.psi_limit, self.max_share = psi_limit, max_share
        self.reference = reference[self.columns].astype(float).reset_index(drop=True)
        self.rows: deque[np.ndarray] = deque(maxlen=window)

    def add(self, row: pd.Series | pd.DataFrame) -> None:
        self.rows.append(np.asarray(row[self.columns], dtype=float).reshape(-1))

    def ready(self) -> bool:
        return len(self.rows) >= self.min_rows

    def scores(self) -> dict[str, float]:
        """PSI per feature; empty until the window holds `min_rows` rows."""
        if not self.ready():
            return {}
        recent = pd.DataFrame(np.vstack(self.rows), columns=self.columns)
        return {c: psi(self.reference[c], recent[c]) for c in self.columns}

    def summary(self) -> dict:
        """`drifted` is true when more than `max_share` of the features are above the drift limit.

        One noisy feature must not trigger a retrain, so the rule needs several features to move.
        """
        s = self.scores()
        if not s:
            return {"ready": False, "rows": len(self.rows), "drifted": False, "features_drifted": 0}
        n = sum(v > self.psi_limit for v in s.values())
        return {
            "ready": True,
            "rows": len(self.rows),
            "max_psi": max(s.values()),
            "features_drifted": n,
            "drifted": n / len(s) > self.max_share,
        }
