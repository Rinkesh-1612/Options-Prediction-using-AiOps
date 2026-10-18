"""Trade simulator and day-level scoring. The one yardstick for baselines and the model.

RULES (stated so a number can be checked against them):
  * One position at a time. A signal while a trade is open is ignored. A trade entered at
    minute t is open until the end of t+horizon; the next entry may be decided at t+horizon.
  * Every trade is the same trade the labels describe: buy at the ask, sell at the bid of the
    same contract `horizon` minutes later, statutory costs, plus slippage (labels.py).
  * The unit of evidence is the DAY. Trades inside a day share the market's mood, so 5,000
    trades are not 5,000 independent answers. Intervals come from resampling whole days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from optpred.labels import BUY_CE, STAY_OUT, net_rs


def simulate(df: pd.DataFrame, actions, slippage_pts_per_leg: float, qty: int, horizon: int) -> pd.DataFrame:
    """Trades taken when following `actions` (0 stay out, 1 buy CE, 2 buy PE), one position at a time."""
    day, minute = df["day"].to_numpy(), df["minute"].to_numpy()
    if (
        len(df) > 1
        and not ((day[1:] > day[:-1]) | ((day[1:] == day[:-1]) & (minute[1:] > minute[:-1]))).all()
    ):
        raise ValueError("rows must be sorted by (day, minute) with no duplicates")
    act = np.asarray(actions)
    net = {
        1: net_rs(df, "ce", slippage_pts_per_leg, qty).to_numpy(),
        2: net_rs(df, "pe", slippage_pts_per_leg, qty).to_numpy(),
    }
    gross = {1: df["ce_gross_rs"].to_numpy(), 2: df["pe_gross_rs"].to_numpy()}
    taken, free_at, cur = [], -1, None
    for i in np.flatnonzero(act != STAY_OUT):
        if day[i] != cur:
            cur, free_at = day[i], -1
        if minute[i] >= free_at:
            taken.append(i)
            free_at = minute[i] + horizon
    idx = np.array(taken, dtype=int)
    side = act[idx]
    return pd.DataFrame(
        {
            "day": day[idx],
            "minute": minute[idx],
            "side": side,
            "net_rs": [net[s][i] for s, i in zip(side, idx, strict=True)],
            "gross_rs": [gross[s][i] for s, i in zip(side, idx, strict=True)],
        }
    )


def summarize(trades: pd.DataFrame, days: list[str], resamples: int, seed: int) -> dict:
    """Score a set of trades over `days` (days with no trade count as Rs0, not as missing)."""
    net_by_day = trades.groupby("day")["net_rs"].sum().reindex(days, fill_value=0.0).to_numpy()
    n_by_day = trades.groupby("day").size().reindex(days, fill_value=0).to_numpy()
    n_days, n_trades = len(days), int(n_by_day.sum())
    out = {
        "days": n_days,
        "trades": n_trades,
        "trades_per_day": round(n_trades / n_days, 1) if n_days else None,
        "hit_rate": round(float((trades["net_rs"] > 0).mean()), 4) if n_trades else None,
        "mean_net_per_trade_rs": round(float(trades["net_rs"].mean()), 2) if n_trades else None,
        "mean_net_per_day_rs": round(float(net_by_day.mean()), 1) if n_days else None,
        "positive_days": int((net_by_day > 0).sum()),
    }
    if resamples > 0 and n_days >= 2 and n_trades:
        rng = np.random.default_rng(seed)
        pick = rng.integers(0, n_days, size=(resamples, n_days))
        sums, counts = net_by_day[pick].sum(axis=1), n_by_day[pick].sum(axis=1)
        per_day = sums / n_days
        per_trade = sums[counts > 0] / counts[counts > 0]
        out["per_day_ci95_rs"] = [round(float(x), 1) for x in np.percentile(per_day, [2.5, 97.5])]
        out["per_trade_ci95_rs"] = [round(float(x), 2) for x in np.percentile(per_trade, [2.5, 97.5])]
        # the smallest daily average this many days could tell apart from zero (about 2 standard errors)
        out["resolvable_per_day_rs"] = round(float(1.96 * net_by_day.std(ddof=1) / np.sqrt(n_days)), 1)
    return out


def oracle_actions(df: pd.DataFrame, slippage_pts_per_leg: float, qty: int) -> np.ndarray:
    """Perfect hindsight: the better side if it pays after costs. NOT tradable -- a yardstick only."""
    from optpred.labels import label_actions

    return label_actions(df, slippage_pts_per_leg, qty)


__all__ = ["BUY_CE", "oracle_actions", "simulate", "summarize"]
