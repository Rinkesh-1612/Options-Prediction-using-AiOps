"""Data drift by PSI (population stability index), per feature, against the training data.

Reference: per feature, decile edges and the share of training rows in each bin (+ a NaN bin).
PSI = sum over bins of (p_now - p_ref) * ln(p_now / p_ref). Rule of thumb: < 0.10 stable, > 0.25 drift.
Per-feature limits: some features are almost constant inside one day (DTE, ATM IV), so one day never looks
like the pooled reference. Each feature's limit = max(psi_limit, 95th percentile of its PSI on the normal
training days). A window "drifts" when more than `share_limit` of the features are above their limit.
"""

from __future__ import annotations

from collections import deque

import numpy as np

EPS = 1e-4


def reference(X: np.ndarray, features: list[str], n_bins: int = 10) -> dict:
    """Bin edges (inner deciles) and reference shares per feature, from training rows."""
    ref = {}
    for j, f in enumerate(features):
        x = X[:, j]
        fin = x[np.isfinite(x)]
        edges = np.unique(np.quantile(fin, np.linspace(0, 1, n_bins + 1)[1:-1])) if len(fin) else np.array([])
        ref[f] = {"edges": edges.tolist(), "shares": shares(x, edges).tolist()}
    return ref


def shares(x: np.ndarray, edges) -> np.ndarray:
    """Share of rows per bin; the last bin holds NaN."""
    edges = np.asarray(edges, float)
    fin = np.isfinite(x)
    counts = np.bincount(np.searchsorted(edges, x[fin], side="right"), minlength=len(edges) + 1)
    out = np.append(counts, (~fin).sum()).astype(float)
    return out / max(len(x), 1)


def psi(p_now: np.ndarray, p_ref: np.ndarray) -> float:
    a, b = np.clip(p_now, EPS, None), np.clip(np.asarray(p_ref), EPS, None)
    return float(((a - b) * np.log(a / b)).sum())


def psi_all(X: np.ndarray, features: list[str], ref: dict) -> dict[str, float]:
    return {
        f: psi(shares(X[:, j], ref[f]["edges"]), ref[f]["shares"]) for j, f in enumerate(features) if f in ref
    }


class DriftMonitor:
    """Rolling window of the rows the API served (online drift)."""

    def __init__(self, ref: dict, window=1000, min_rows=300, psi_limit=0.25, share_limit=0.3, limits=None):
        self.ref, self.features = ref, list(ref)
        self.limits = {f: (limits or {}).get(f, psi_limit) for f in self.features}
        self.rows: deque = deque(maxlen=window)
        self.min_rows, self.psi_limit, self.share_limit = min_rows, psi_limit, share_limit

    def add(self, row: dict) -> None:
        self.rows.append([row.get(f, np.nan) for f in self.features])

    def status(self) -> dict:
        n = len(self.rows)
        if n < self.min_rows:
            return {"rows": n, "ready": False, "drift": False, "share": 0.0, "psi": {}}
        p = psi_all(np.asarray(self.rows, float), self.features, self.ref)
        share = float(np.mean([v > self.limits[f] for f, v in p.items()]))
        return {"rows": n, "ready": True, "drift": share > self.share_limit, "share": share, "psi": p}
