"""A synthetic day of data/grid (same columns), so feature tests run without the real data."""

from __future__ import annotations

import numpy as np
import pandas as pd

LEGS = [f"{s}_{'m' if k < 0 else 'p'}{abs(k)}" for s in ("ce", "pe") for k in range(-2, 3)]


def synth_grid(n: int = 1200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # About 0.3 bp per second, like real NIFTY: ATM moves a few times, not every second.
    spot = 25010 * np.exp(np.cumsum(rng.normal(0, 3e-5, n)))
    c = {"day": ["2026-10-15"] * n, "sod": 33300 + np.arange(n), "dte": 2, "expiry": 20746}
    c |= {"spot": spot, "spot_age_s": 0.1, "fut": spot + 40 + rng.normal(0, 1, n)}
    c |= {"fut_volume": np.cumsum(rng.integers(0, 500, n)).astype(float), "fut_oi": 1e7, "fut_age_s": 0.1}
    c["atm"] = np.round(spot / 50) * 50
    for leg in LEGS:
        m = 100 + rng.normal(0, 5, n).cumsum() * 0.1
        c[f"{leg}_bid"], c[f"{leg}_ask"], c[f"{leg}_ltp"] = m - 0.1, m + 0.1, m
        for f in ("bid_qty", "ask_qty", "bid_depth", "ask_depth"):
            c[f"{leg}_{f}"] = rng.integers(65, 6500, n).astype(float)
        c[f"{leg}_volume"] = np.cumsum(rng.integers(0, 3000, n)).astype(float)
        c[f"{leg}_oi"] = 1e6 + np.cumsum(rng.integers(-500, 500, n))
        c[f"{leg}_age_s"] = 0.2
    for side in ("ce", "pe"):
        c[f"{side}_iv"] = 12 + rng.normal(0, 0.1, n).cumsum() * 0.01
    c |= {"ce_delta": 0.5, "pe_delta": -0.5, "chain_age_s": 2.0}
    g = pd.DataFrame(c)
    g.loc[rng.choice(n, n // 50, replace=False), "ce_p0_bid"] = np.nan  # some gaps, as in the real grid
    return g
