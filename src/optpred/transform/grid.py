"""Stage grid: data/clean -> data/grid, one model-ready row per second per day.

Each row is the market as it stood at the END of second `sod` (seconds since IST midnight), 09:15:00-15:29:59.
Every value is the last tick at or before that time (optpred.eda.fill.asof), or NaN if that tick is older
than eda.max_age_s. Nothing from a later second is used.

Columns:
  day, sod, expiry (front weekly, days since 1970-01-01), dte, atm (strike nearest to spot)
  spot, spot_age_s                          NIFTY index
  fut, fut_volume, fut_oi, fut_age_s        NIFTY future
  {leg}_{field}  for leg in ce_m2..ce_p2, pe_m2..pe_p2 (m2 = ATM-2 strikes, p2 = ATM+2 strikes)
                 field: bid, ask, bid_qty, ask_qty, bid_depth, ask_depth (5 levels), ltp, volume, oi, age_s
  ce_iv, pe_iv, ce_delta, pe_delta, chain_age_s   ATM row of the front-expiry chain

A leg is a POSITION relative to ATM, so its contract changes when ATM moves. The contract is always
(expiry, atm + k * strike_step, side). Features that use differences over time must check that atm
did not move.

Usage:  ./pipe python -m optpred.transform.grid
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.common.clock import IST_OFFSET_S, SESSION_FIRST_MIN, SESSION_LAST_MIN
from optpred.eda.fill import asof

log = logging.getLogger("optpred.transform.grid")
NS = 1_000_000_000
LEG_FIELDS = ["bid", "ask", "bid_qty", "ask_qty", "bid_depth", "ask_depth", "ltp", "volume", "oi"]


def second_ends(day: str) -> tuple[np.ndarray, np.ndarray]:
    """(sod, last nanosecond of that second) for every session second of `day`."""
    sod = np.arange(SESSION_FIRST_MIN * 60, (SESSION_LAST_MIN + 1) * 60)
    ist_midnight = pd.Timestamp(day, tz="UTC").value - IST_OFFSET_S * NS
    return sod, ist_midnight + (sod + 1) * NS - 1


def leg_name(side: str, k: int) -> str:
    return f"{side.lower()}_{'m' if k < 0 else 'p'}{abs(k)}"


def option_legs(opt: pd.DataFrame, grid: pd.DataFrame, p: dict, max_age_s: float) -> pd.DataFrame:
    """Add the ATM-relative option legs to `grid` (needs grid_ns and atm)."""
    q = opt.assign(
        bid=opt["bid1_price"],
        ask=opt["ask1_price"],
        bid_qty=opt["bid1_qty"],
        ask_qty=opt["ask1_qty"],
        bid_depth=opt[[f"bid{i}_qty" for i in range(1, 6)]].sum(axis=1),
        ask_depth=opt[[f"ask{i}_qty" for i in range(1, 6)]].sum(axis=1),
    )[["ts_ns", "instrument_key", *LEG_FIELDS]]
    ident = opt.drop_duplicates("instrument_key").set_index("instrument_key")[["strike", "side"]]
    long = asof(q, grid["grid_ns"], max_age_s, by="instrument_key").join(ident, on="instrument_key")
    long = long.set_index(["grid_ns", "strike", "side"])[[*LEG_FIELDS, "age_s"]]

    out = grid
    for side in ("CE", "PE"):
        for k in range(-p["n_strikes"], p["n_strikes"] + 1):
            want = pd.MultiIndex.from_arrays(
                [grid["grid_ns"], grid["atm"] + k * p["strike_step"], np.full(len(grid), side)]
            )
            leg = long.reindex(want).reset_index(drop=True)
            leg.columns = [f"{leg_name(side, k)}_{c}" for c in leg.columns]
            out = pd.concat([out.reset_index(drop=True), leg], axis=1)
    return out


def build_day(day: str, clean: Path, out_dir: Path, p: dict, max_age: dict) -> dict:
    opt = pd.read_parquet(clean / "opt_tape" / f"{day}.parquet")
    und = pd.read_parquet(clean / "und_tape" / f"{day}.parquet")
    chain = pd.read_parquet(clean / "option_chain_snap" / f"{day}.parquet")
    opt = opt[opt["dte"] == opt["dte"].min()]  # front weekly expiry only
    chain = chain[chain["expiry_rank"] == 0]

    sod, grid_ns = second_ends(day)
    g = pd.DataFrame({"day": day, "sod": sod.astype("int32"), "grid_ns": grid_ns})
    g["expiry"] = int(opt["expiry"].iloc[0])
    g["dte"] = int(opt["dte"].iloc[0])

    idx = asof(und.loc[und["kind"] == "INDEX", ["ts_ns", "ltp"]], grid_ns, max_age["index"])
    g["spot"], g["spot_age_s"] = idx["ltp"].to_numpy(), idx["age_s"].to_numpy()
    fut = asof(und.loc[und["kind"] == "FUT", ["ts_ns", "ltp", "volume", "oi"]], grid_ns, max_age["future"])
    g["fut"], g["fut_volume"], g["fut_oi"] = (
        fut["ltp"].to_numpy(),
        fut["volume"].to_numpy(),
        fut["oi"].to_numpy(),
    )
    g["fut_age_s"] = fut["age_s"].to_numpy()
    # ATM = nearest listed strike to spot; carried forward while spot is missing.
    g["atm"] = (np.round(g["spot"] / p["strike_step"]) * p["strike_step"]).ffill()

    g = option_legs(opt, g, p, max_age["opt_tape"])

    ch = asof(
        chain[["ts_ns", "strike", "ce_iv", "pe_iv", "ce_delta", "pe_delta"]],
        grid_ns,
        max_age["option_chain_snap"],
        by="strike",
    )
    ch = ch.set_index(["grid_ns", "strike"])[["ce_iv", "pe_iv", "ce_delta", "pe_delta", "age_s"]]
    ch = ch.reindex(pd.MultiIndex.from_arrays([g["grid_ns"], g["atm"]])).reset_index(drop=True)
    g[["ce_iv", "pe_iv", "ce_delta", "pe_delta", "chain_age_s"]] = ch.to_numpy()

    g = g.drop(columns="grid_ns")
    out_dir.mkdir(parents=True, exist_ok=True)
    g.to_parquet(out_dir / f"{day}.parquet", index=False)
    return {"rows": len(g), "nan_share": g.isna().mean().round(4)[lambda s: s > 0].to_dict()}


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, eda = params["grid"], params["eda"]
    days = json.loads(Path("data/days.json").read_text())["accepted"]

    work = partial(
        build_day, clean=Path(eda["clean_dir"]), out_dir=Path(p["out_dir"]), p=p, max_age=eda["max_age_s"]
    )
    with ProcessPoolExecutor(eda["workers"]) as ex:
        res = dict(zip(days, ex.map(work, days), strict=True))

    nan = pd.DataFrame([r["nan_share"] for r in res.values()]).fillna(0).mean().round(4).sort_values()
    report = {
        "days": len(days),
        "rows": sum(r["rows"] for r in res.values()),
        "nan_share_mean": nan.to_dict(),
        "per_day": res,
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/grid.json").write_text(json.dumps(report, indent=1))
    log.info("%d days, %d rows; highest NaN share: %s", len(days), report["rows"], nan.tail(5).to_dict())
    summary.update(days=len(days), rows=report["rows"])
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("grid", main))
