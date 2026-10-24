"""Stage eda: profile data/clean -- coverage, missing values, patterns. Reads only clean data.

Outputs (reports/eda/):
  profile.json        per-day coverage, NaN rate per column, missing share after the fill policy,
                      intraday and premium patterns
  coverage.png        rows and covered minutes per day
  intraday.png        spread, tick rate and index move by time of day
  spread_premium.png  relative spread by option premium
  index_returns.png   1-minute NIFTY returns against a normal curve (fat tails)

Usage:  ./pipe python -m optpred.eda.profile
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from functools import partial
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from optpred.common import runlog  # noqa: E402
from optpred.common.clock import (  # noqa: E402
    IST_OFFSET_S,
    SESSION_FIRST_MIN,
    SESSION_LAST_MIN,
    SESSION_MINUTES,
)
from optpred.common.parallel import map_days  # noqa: E402
from optpred.eda.fill import asof  # noqa: E402

log = logging.getLogger("optpred.eda.profile")
OUT = Path("reports/eda")
PREMIUM_BINS = [0, 1, 5, 20, 100, 1e9]
PREMIUM_LABELS = ["<1", "1-5", "5-20", "20-100", ">100"]


def minute_ends_ns(day: str) -> np.ndarray:
    """Last nanosecond of each session minute of `day` (the 'state at the end of minute m' grid)."""
    ist_midnight = pd.Timestamp(day, tz="UTC").value - IST_OFFSET_S * 1_000_000_000
    minutes = np.arange(SESSION_FIRST_MIN, SESSION_LAST_MIN + 1)
    return ist_midnight + (minutes + 1) * 60 * 1_000_000_000 - 1


def missing_after_fill(ticks: pd.DataFrame, grid: np.ndarray, max_age_s: float, by: str | None) -> float:
    """Share of grid points still empty after forward fill (within each key's first..last tick)."""
    if ticks.empty:
        return 1.0
    f = asof(ticks[["ts_ns"] + ([by] if by else [])], grid, max_age_s, by=by)
    if by:
        span = ticks.groupby(by)["ts_ns"].agg(["min", "max"])
        f = f.join(span, on=by)
        f = f[(f["grid_ns"] >= f["min"]) & (f["grid_ns"] <= f["max"])]
    return float(f["tick_ns"].isna().mean())


def profile_day(day: str, clean: Path, max_age: dict) -> dict:
    opt = pd.read_parquet(clean / "opt_tape" / f"{day}.parquet")
    und = pd.read_parquet(clean / "und_tape" / f"{day}.parquet")
    chain = pd.read_parquet(clean / "option_chain_snap" / f"{day}.parquet")
    idx, fut = und[und["kind"] == "INDEX"], und[und["kind"] == "FUT"]
    grid = minute_ends_ns(day)
    chain = chain.assign(key=chain["expiry"].astype(str) + "|" + chain["strike"].astype(str))

    r = {
        "rows": {"opt_tape": len(opt), "index": len(idx), "future": len(fut), "option_chain_snap": len(chain)}
    }
    r["minutes"] = {
        n: int((t["sod"] // 60).nunique())
        for n, t in (("opt_tape", opt), ("index", idx), ("future", fut), ("option_chain_snap", chain))
    }
    r["missing_after_fill"] = {
        "opt_tape": missing_after_fill(opt, grid, max_age["opt_tape"], "instrument_key"),
        "index": missing_after_fill(idx, grid, max_age["index"], None),
        "future": missing_after_fill(fut, grid, max_age["future"], None),
        "option_chain_snap": missing_after_fill(chain, grid, max_age["option_chain_snap"], "key"),
    }
    r["nan_count"] = {
        "opt_tape": opt.isna().sum()[lambda s: s > 0].astype(int).to_dict(),
        "option_chain_snap": chain.isna().sum()[lambda s: s > 0].astype(int).to_dict(),
    }

    # Patterns. Spread on options that a trader would buy (premium >= Rs5).
    mid = (opt["bid1_price"] + opt["ask1_price"]) / 2
    rel = (opt["ask1_price"] - opt["bid1_price"]) / mid
    bucket15 = (opt["sod"] // 900) * 15  # minutes since midnight, 15-minute buckets
    liquid = mid >= 5
    r["spread_by_15min"] = rel[liquid].groupby(bucket15[liquid]).median().to_dict()
    r["ticks_per_min_by_15min"] = (opt.groupby(bucket15).size() / 15).to_dict()
    prem = pd.cut(mid, PREMIUM_BINS, labels=PREMIUM_LABELS)
    r["spread_by_premium"] = rel.groupby(prem, observed=False).median().to_dict()
    r["spread_by_dte"] = {int(opt["dte"].min()): float(rel[liquid].median())}  # one front expiry per day

    last = idx.groupby(idx["sod"] // 60)["ltp"].last()
    ret = np.log(last).diff().dropna()
    r["index_ret_1m"] = ret.tolist()
    r["index_absret_by_15min"] = ret.abs().groupby((ret.index // 15) * 15).mean().to_dict()
    return r


def fmt_bucket(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def plots(days: list[str], res: dict) -> None:
    fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    ax[0].bar(days, [res[d]["rows"]["opt_tape"] / 1e6 for d in days], color="#4C72B0")
    ax[0].set_ylabel("option rows (M)")
    for n, c in (("opt_tape", "#4C72B0"), ("index", "#55A868"), ("option_chain_snap", "#C44E52")):
        ax[1].plot(days, [res[d]["minutes"][n] for d in days], marker=".", label=n, color=c)
    ax[1].axhline(SESSION_MINUTES, ls="--", c="grey")
    ax[1].set_ylabel(f"minutes covered / {SESSION_MINUTES}")
    ax[1].legend()
    ax[1].tick_params(axis="x", rotation=90, labelsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "coverage.png", dpi=110)
    plt.close(fig)

    def avg(key: str) -> pd.Series:
        return pd.DataFrame([res[d][key] for d in days]).median().sort_index()

    sp, tk, mv = avg("spread_by_15min"), avg("ticks_per_min_by_15min"), avg("index_absret_by_15min")
    fig, ax = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    for a, s, lab in (
        (ax[0], sp * 100, "median spread (% of mid)"),
        (ax[1], tk, "option updates / min"),
        (ax[2], mv * 1e4, "mean |1-min index move| (bp)"),
    ):
        a.plot([fmt_bucket(int(m)) for m in s.index], s.values, marker="o")
        a.set_ylabel(lab, fontsize=8)
    ax[2].tick_params(axis="x", rotation=90, labelsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "intraday.png", dpi=110)
    plt.close(fig)

    pr = avg("spread_by_premium").reindex(PREMIUM_LABELS)
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar(PREMIUM_LABELS, pr.values * 100, color="#8172B2")
    ax.set_yscale("log")
    ax.set_xlabel("option premium (Rs)")
    ax.set_ylabel("median spread (% of mid, log)")
    fig.tight_layout()
    fig.savefig(OUT / "spread_premium.png", dpi=110)
    plt.close(fig)

    ret = np.concatenate([res[d]["index_ret_1m"] for d in days]) * 1e4
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.hist(ret, bins=120, density=True, alpha=0.7, label="NIFTY 1-min return")
    x = np.linspace(ret.min(), ret.max(), 400)
    ax.plot(
        x,
        np.exp(-0.5 * ((x - ret.mean()) / ret.std()) ** 2) / (ret.std() * np.sqrt(2 * np.pi)),
        label="normal",
    )
    ax.set_yscale("log")
    ax.set_xlabel("basis points")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "index_returns.png", dpi=110)
    plt.close(fig)


def summarise(days: list[str], res: dict) -> dict:
    ret = pd.Series(np.concatenate([res[d]["index_ret_1m"] for d in days]))
    nan = {}
    for t in ("opt_tape", "option_chain_snap"):
        total = sum(res[d]["rows"][t] for d in days)
        cols = {c for d in days for c in res[d]["nan_count"][t]}
        nan[t] = {
            c: round(sum(res[d]["nan_count"][t].get(c, 0) for d in days) / total, 5) for c in sorted(cols)
        }
    return {
        "days": len(days),
        "partial_days": {d: m for d in days for n, m in res[d]["minutes"].items() if m < SESSION_MINUTES - 1},
        "nan_rate": nan,
        "missing_after_fill_mean": {
            t: round(float(np.mean([res[d]["missing_after_fill"][t] for d in days])), 5)
            for t in res[days[0]]["missing_after_fill"]
        },
        "spread_by_premium_median": pd.DataFrame([res[d]["spread_by_premium"] for d in days])
        .median()
        .to_dict(),
        "index_ret_1m": {
            "std_bp": round(ret.std() * 1e4, 2),
            "excess_kurtosis": round(float(ret.kurt()), 2),
            "lag1_autocorr": round(float(ret.autocorr(1)), 3),
        },
    }


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        p = yaml.safe_load(f)["eda"]
    clean = Path(p["clean_dir"])
    days = json.loads(Path("data/days.json").read_text())["accepted"]

    res = dict(
        zip(
            days,
            map_days(partial(profile_day, clean=clean, max_age=p["max_age_s"]), days, p["workers"]),
            strict=True,
        )
    )

    OUT.mkdir(parents=True, exist_ok=True)
    plots(days, res)
    s = summarise(days, res)
    per_day = {d: {k: v for k, v in r.items() if k != "index_ret_1m"} for d, r in res.items()}
    (OUT / "profile.json").write_text(json.dumps({"summary": s, "days": per_day}, indent=1, default=str))
    log.info("summary: %s", json.dumps(s, default=str))
    summary.update(days=len(days), **s["index_ret_1m"])
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("eda", main))
