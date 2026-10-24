"""Stage labels: triple-barrier outcome of buying the ATM call / put at every second.

For each second t and side (CE, PE):
  contract   the ATM contract at t: (front expiry, atm_t, side). It is FOLLOWED even when ATM moves later.
  entry      its ask at t
  sigma      std of its 1-second mid changes over the last `sigma_window_s`, times sqrt(sigma_horizon_s),
             in points (only data up to t)
  barriers   take-profit: bid >= entry + k_tp * sigma      stop-loss: bid <= entry - k_sl * sigma
             time cap: max_hold_s, or the forced exit at force_exit_s
  exit       the bid when the first barrier is touched (time cap: the last known bid)
  net_rs     rupees after statutory costs and slippage (optpred.labels.costs)

Outputs data/labels/<day>.parquet: day, sod, and per side {side}_valid, entry, sigma, hit (+1 take-profit,
-1 stop-loss, 0 time cap), hold_s, exit, net_rs. Labels look forward by design: they are targets,
never features.

Usage:  ./pipe python -m optpred.labels.barrier
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.common.parallel import map_days
from optpred.labels.costs import net_rs

log = logging.getLogger("optpred.labels.barrier")
SIDES = ("ce", "pe")


def contract_matrix(g: pd.DataFrame, side: str, field: str, step: int, n_strikes: int):
    """(strikes, M): M[t, j] = `field` of contract (side, strikes[j]) at second t (from the ATM legs)."""
    ks = range(-n_strikes, n_strikes + 1)
    atm = g["atm"].to_numpy()
    strikes = np.unique(np.concatenate([atm + k * step for k in ks]))
    strikes = strikes[np.isfinite(strikes)]
    m = np.full((len(g), len(strikes)), np.nan)
    rows = np.arange(len(g))
    for k in ks:
        col = np.searchsorted(strikes, atm + k * step)
        ok = np.isfinite(atm)
        m[rows[ok], col[ok]] = g[f"{side}_{'m' if k < 0 else 'p'}{abs(k)}_{field}"].to_numpy()[ok]
    return strikes, m


def contract_sigma(mid: np.ndarray, j: np.ndarray, window: int) -> np.ndarray:
    """Rolling std of 1-second mid changes of the contract held at each t (only data up to t)."""
    n = len(j)
    rows = np.arange(n)
    ok = j >= 0
    jj = np.where(ok, j, 0)
    d = np.full(n, np.nan)
    d[1:] = mid[rows[1:], jj[1:]] - mid[rows[1:] - 1, jj[1:]]
    # The change at t uses the contract held at t, so a roll of ATM does not create a fake jump.
    d[~ok] = np.nan
    return pd.Series(d).rolling(window, min_periods=window // 2).std().to_numpy()


def barrier_side(g: pd.DataFrame, side: str, p: dict) -> pd.DataFrame:
    step, n_str = p["strike_step"], p["n_strikes"]
    strikes, bid = contract_matrix(g, side, "bid", step, n_str)
    _, ask = contract_matrix(g, side, "ask", step, n_str)
    n = len(g)
    rows = np.arange(n)
    atm = g["atm"].to_numpy()
    j = np.where(np.isfinite(atm), np.searchsorted(strikes, np.nan_to_num(atm)), -1)
    jj = np.where(j >= 0, j, 0)
    mid = (bid + ask) / 2

    entry = np.where(j >= 0, ask[rows, jj], np.nan)
    bid0 = np.where(j >= 0, bid[rows, jj], np.nan)
    sigma = contract_sigma(mid, j, p["sigma_window_s"]) * np.sqrt(p["sigma_horizon_s"])
    sod = g["sod"].to_numpy()
    age = g[f"{side}_p0_age_s"].to_numpy()
    valid = (
        np.isfinite(entry)
        & np.isfinite(bid0)
        & np.isfinite(sigma)
        & (sigma > 0)
        & (entry >= p["min_entry_premium"])
        & (age <= p["max_entry_age_s"])
        & (sod >= p["first_entry_s"])
        & (sod <= p["last_entry_s"])
    )
    tp, sl = entry + p["k_tp"] * sigma, entry - p["k_sl"] * sigma

    hit = np.zeros(n, dtype=np.int8)
    hold = np.full(n, np.nan)
    exit_ = np.full(n, np.nan)
    last_bid = bid0.copy()
    open_ = valid.copy()
    last_s = np.searchsorted(sod, p["force_exit_s"])  # index of the forced-exit second
    for h in range(1, p["max_hold_s"] + 1):
        if not open_.any():
            break
        s = np.minimum(rows + h, min(n, last_s) - 1)
        b = bid[s, jj]
        last_bid = np.where(open_ & np.isfinite(b), b, last_bid)
        up, down = open_ & (b >= tp), open_ & (b <= sl)
        for mask, code in ((up, 1), (down & ~up, -1)):
            hit[mask], hold[mask], exit_[mask] = code, h, b[mask]
        open_ &= ~(up | down)
        cap = open_ & ((h == p["max_hold_s"]) | (rows + h >= last_s - 1))
        hold[cap], exit_[cap] = h, last_bid[cap]
        open_ &= ~cap
    exit_[~valid] = np.nan
    hold[~valid] = np.nan
    net = net_rs(entry, exit_, p["qty"], p["slippage_pts_per_leg"])
    return pd.DataFrame(
        {
            f"{side}_valid": valid,
            f"{side}_entry": entry,
            f"{side}_sigma": sigma,
            f"{side}_hit": hit,
            f"{side}_hold_s": hold,
            f"{side}_exit": exit_,
            f"{side}_net_rs": np.where(valid, net, np.nan),
        }
    )


def label_day(day: str, grid_dir: Path, out_dir: Path, p: dict) -> dict:
    g = pd.read_parquet(grid_dir / f"{day}.parquet").sort_values("sod").reset_index(drop=True)
    out = pd.concat([g[["day", "sod"]], *(barrier_side(g, s, p) for s in SIDES)], axis=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_dir / f"{day}.parquet", index=False)
    r = {}
    for s in SIDES:
        v = out[out[f"{s}_valid"]]
        r[s] = {
            "valid": len(v),
            "tp": int((v[f"{s}_hit"] == 1).sum()),
            "sl": int((v[f"{s}_hit"] == -1).sum()),
            "cap": int((v[f"{s}_hit"] == 0).sum()),
            "net_sum": float(v[f"{s}_net_rs"].sum()),
            "hold_median": float(v[f"{s}_hold_s"].median()) if len(v) else None,
        }
    return r


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p = params["labels"] | {k: params["grid"][k] for k in ("strike_step", "n_strikes")}
    days = json.loads(Path("data/days.json").read_text())["accepted"]

    work = partial(label_day, grid_dir=Path(params["grid"]["out_dir"]), out_dir=Path(p["out_dir"]), p=p)
    res = dict(zip(days, map_days(work, days, params["eda"]["workers"]), strict=True))

    tot = {}
    for s in SIDES:
        v = sum(r[s]["valid"] for r in res.values())
        tot[s] = {
            "valid": v,
            **{k: round(sum(r[s][k] for r in res.values()) / v, 4) for k in ("tp", "sl", "cap")},
            "mean_net_rs": round(sum(r[s]["net_sum"] for r in res.values()) / v, 2),
            "median_hold_s": float(
                np.median([r[s]["hold_median"] for r in res.values() if r[s]["hold_median"]])
            ),
        }
        log.info("%s: %s", s, tot[s])
    Path("reports").mkdir(exist_ok=True)
    Path("reports/labels.json").write_text(json.dumps({"total": tot, "days": res}, indent=1))
    summary.update(days=len(days), **{f"{s}_{k}": tot[s][k] for s in SIDES for k in ("tp", "mean_net_rs")})
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("labels", main))
