"""Stage 5 -- baselines: what blind rules earn through the same simulator and costs.

The model has to beat these. If it does not, it has found nothing.

  stay_out    never trade (Rs0 by definition)
  always_ce   buy the call every chance
  always_pe   buy the put every chance
  momentum    follow the last 2 minutes of NIFTY: up -> call, down -> put (rule fixed in advance)
  random      call or put by coin flip at every chance, averaged over many seeds
  oracle      perfect hindsight (NOT tradable). It shows how big the moves are against the costs.

The locked test days are refused unless --final is given: nothing here has free settings, but
looking at test results while building the model would still tune the model to them.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.features.labels import BUY_CE, BUY_PE, STAY_OUT
from optpred.models.sim import oracle_actions, simulate, summarize

log = logging.getLogger("optpred.models.baselines")


def rule_actions(df: pd.DataFrame, name: str, rng: np.random.Generator | None = None) -> np.ndarray:
    n = len(df)
    if name == "stay_out":
        return np.full(n, STAY_OUT)
    if name == "always_ce":
        return np.full(n, BUY_CE)
    if name == "always_pe":
        return np.full(n, BUY_PE)
    if name == "momentum":
        r = df["spot_ret2"].to_numpy()
        return np.where(r > 0, BUY_CE, np.where(r < 0, BUY_PE, STAY_OUT))
    if name == "random":
        return rng.choice([BUY_CE, BUY_PE], size=n)
    raise ValueError(name)


def evaluate(df: pd.DataFrame, slip: float, p: dict, b: dict) -> dict:
    """Every baseline on `df` at one slippage setting."""
    days = sorted(df["day"].unique())
    args = (slip, p["qty"], p["horizon_min"])
    res = {}
    for name in ("stay_out", "always_ce", "always_pe", "momentum"):
        res[name] = summarize(
            simulate(df, rule_actions(df, name), *args), days, b["bootstrap_resamples"], b["seed"]
        )
    rng = np.random.default_rng(b["seed"])
    seeds = [
        summarize(simulate(df, rule_actions(df, "random", rng), *args), days, 0, 0)
        for _ in range(b["random_seeds"])
    ]
    per_trade = np.array([s["mean_net_per_trade_rs"] for s in seeds])
    per_day = np.array([s["mean_net_per_day_rs"] for s in seeds])
    res["random"] = {
        "days": len(days),
        "trades_per_day": seeds[0]["trades_per_day"],
        "hit_rate": round(float(np.mean([s["hit_rate"] for s in seeds])), 4),
        "mean_net_per_trade_rs": round(float(per_trade.mean()), 2),
        "mean_net_per_day_rs": round(float(per_day.mean()), 1),
        "across_seeds_per_trade_p5_p95": [round(float(x), 2) for x in np.percentile(per_trade, [5, 95])],
        "seeds": len(seeds),
    }
    res["oracle_not_tradable"] = summarize(
        simulate(df, oracle_actions(df, slip, p["qty"]), *args), days, b["bootstrap_resamples"], b["seed"]
    )
    return res


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--splits", nargs="+", default=["train", "val"])
    ap.add_argument("--final", action="store_true", help="allow the locked test days")
    args = ap.parse_args(argv)
    if "test" in args.splits and not args.final:
        log.error("refusing to touch the locked test days without --final")
        return 2
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, costs, b = params["features"], params["costs"], params["baselines"]

    df = (
        pd.read_parquet(Path(p["out_dir"]) / "features.parquet")
        .sort_values(["day", "minute"])
        .reset_index(drop=True)
    )
    out: dict = {"splits": args.splits, "results": {}}
    groups = [[s] for s in args.splits] + ([args.splits] if len(args.splits) > 1 else [])
    for group in groups:
        name = "+".join(group)
        sub = df[df["split"].isin(group)].reset_index(drop=True)
        out["results"][name] = {}
        for slip in costs["sensitivity_pts_per_leg"]:
            res = evaluate(sub, slip, p, b)
            out["results"][name][str(slip)] = res
            if group is groups[-1]:  # the headline group is printed; all of them go to the JSON
                for strat, r in res.items():
                    log.info(
                        "%-14s slip %-4s %-20s trades/day %5s  hit %5s  net/trade Rs%7s  net/day Rs%8s  %s",
                        name,
                        slip,
                        strat,
                        r["trades_per_day"],
                        r["hit_rate"],
                        r["mean_net_per_trade_rs"],
                        r["mean_net_per_day_rs"],
                        r.get("per_day_ci95_rs", ""),
                    )
    Path("reports").mkdir(exist_ok=True)
    Path("reports/baselines.json").write_text(json.dumps(out, indent=1))
    summary.update(splits=args.splits, rows=len(df))
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("baselines", main))
