"""One trade simulator and one set of metrics for every model.

Policy: at each second with no open position, take the side with the higher score if that score > tau and an
entry is possible. Hold until the triple-barrier exit of that trade (its label), then look again.
One position at a time. The trade result is the label's net rupees (entry ask, exit bid, all costs).
"""

from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr


def trades_one_day(score: np.ndarray, valid: np.ndarray, net: np.ndarray, hold: np.ndarray, tau: float):
    """Indices, sides and net rupees of the trades of one day. Inputs are (n, 2) arrays in time order."""
    s = np.where(valid & np.isfinite(score), score, -np.inf)
    side = np.argmax(s, axis=1)
    best = s[np.arange(len(s)), side]
    cand = np.flatnonzero(best > tau)
    out_t, out_side, out_net = [], [], []
    free_at = 0
    k = 0
    while k < len(cand):
        k = np.searchsorted(cand, free_at)
        if k >= len(cand):
            break
        t = cand[k]
        sd = side[t]
        out_t.append(t)
        out_side.append(sd)
        out_net.append(net[t, sd])
        free_at = t + max(int(hold[t, sd]), 1)
    return np.array(out_t, int), np.array(out_side, int), np.array(out_net, float)


def simulate(score, ds, day_slices, tau: float) -> dict:
    """Run the policy on each day. `score` is (N, 2) aligned with ds rows."""
    per_day, nets, sides = [], [], []
    for _, sl in day_slices:
        _, sd, nt = trades_one_day(score[sl], ds.valid[sl], ds.net[sl], ds.hold[sl], tau)
        per_day.append(nt.sum())
        nets.append(nt)
        sides.append(sd)
    return metrics(np.array(per_day), np.concatenate(nets) if nets else np.array([]), np.concatenate(sides))


def metrics(per_day: np.ndarray, nets: np.ndarray, sides: np.ndarray) -> dict:
    cum = np.cumsum(per_day)
    sd = per_day.std(ddof=1) if len(per_day) > 1 else 0.0
    return {
        "days": len(per_day),
        "trades": int(len(nets)),
        "net_total": float(nets.sum()),
        "net_per_day": float(per_day.mean()) if len(per_day) else 0.0,
        "net_per_trade": float(nets.mean()) if len(nets) else 0.0,
        "hit_rate": float((nets > 0).mean()) if len(nets) else 0.0,
        "daily_sharpe": float(per_day.mean() / sd) if sd > 0 else 0.0,
        "max_drawdown": float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max()),
        "share_ce": float((sides == 0).mean()) if len(sides) else 0.0,
    }


def information_coef(score: np.ndarray, ds, rows: np.ndarray) -> dict:
    """Spearman rank correlation between score and net rupees, per side (rows where an entry is possible)."""
    out = {}
    for j, s in enumerate(("ce", "pe")):
        r = rows[ds.valid[rows, j] & np.isfinite(score[rows, j])]
        out[f"ic_{s}"] = float(spearmanr(score[r, j], ds.net[r, j]).statistic) if len(r) > 100 else 0.0
    return out


def choose_tau(score, ds, day_slices, quantiles: list[float], min_trades: int) -> tuple[float, float, dict]:
    """Pick tau from quantiles of the best score, by net rupees per day. Returns (tau, quantile, metrics)."""
    best_s = np.where(ds.valid & np.isfinite(score), score, -np.inf).max(axis=1)
    pool = np.concatenate([best_s[sl] for _, sl in day_slices])
    pool = pool[np.isfinite(pool)]
    best = (np.inf, 1.0, simulate(score, ds, day_slices, np.inf))  # "never trade"
    if len(pool) == 0:  # a model that never scores a trade (stay_out)
        return best
    for q in quantiles:
        tau = float(np.quantile(pool, q))
        m = simulate(score, ds, day_slices, tau)
        if m["trades"] >= min_trades and m["net_per_day"] > best[2]["net_per_day"]:
            best = (tau, q, m)
    return best


def bootstrap_ci(per_day: np.ndarray, n: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(per_day, size=(n, len(per_day)), replace=True).mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
