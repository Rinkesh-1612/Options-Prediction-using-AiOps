"""Stage 6c -- sprint: the six pre-registered alpha-sprint trials (docs/ALPHA_SPRINT.md), out of fold.

Every trial is scored on the same 24 out-of-fold development days as v2, with the same simulator and costs.
The pass rule uses a 99% day-bootstrap interval because six more trials are tested.

  v2   reference: the v2 rule (two side models, tau)
  A    magnitude gate: P(big move in 120 s) >= tau, on the side the side models prefer
  C    trailing exit: the entry rule of the better of v2 and A, side models retrained on trailing-exit labels
  D1   best of v2 / A / C, 09:20-09:45 only
  D2   best of v2 / A / C, expiry day after 13:00 only
  D3   best of v2 / A / C, only when realised volatility (60 s, annualised) > ATM implied volatility
  E    liquidity sweep rule, no model

Only the development days are read. Writes reports/sprint.json and one MLflow run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.features.labels import BUY_CE, BUY_PE, STAY_OUT
from optpred.features.micro import MICRO_COLUMNS
from optpred.models.micro_train import decide, fit_pair, predict_pair, random_side_control, simulate
from optpred.models.sim import summarize
from optpred.models.tune import walk_forward_folds

log = logging.getLogger("optpred.models.sprint")

SECONDS_PER_YEAR = 252 * 375 * 60  # trading seconds


def trailing_view(df: pd.DataFrame) -> pd.DataFrame:
    """The same rows with the trailing-exit trade in place of the barrier trade (for the simulator)."""
    v = df.copy()
    for s in ("ce", "pe"):
        v[f"{s}_hold_s"], v[f"{s}_gross_rs"], v[f"{s}_stat_rs"] = (
            df[f"{s}_tr_hold_s"],
            df[f"{s}_tr_gross_rs"],
            df[f"{s}_tr_stat_rs"],
        )
    return v


def score99(trades: pd.DataFrame, days: list[str], b: dict) -> dict:
    """The usual summary plus a 99% day-bootstrap interval of the mean net per day."""
    s = summarize(trades[["day", "net_rs"]], days, b["bootstrap_resamples"], b["seed"])
    by_day = trades.groupby("day")["net_rs"].sum().reindex(days, fill_value=0.0).to_numpy()
    rng = np.random.default_rng(b["seed"])
    means = by_day[rng.integers(0, len(days), size=(b["bootstrap_resamples"], len(days)))].mean(axis=1)
    s["per_day_ci99_rs"] = [round(float(x), 1) for x in np.percentile(means, [0.5, 99.5])]
    return s


def best_tau(view, actions_for, grid, days, slip, qty, min_trades, mask=None):
    """tau with the highest out-of-fold net per day (at least `min_trades` trades, or never trade)."""
    table = []
    for tau in grid:
        a = actions_for(tau)
        if mask is not None:
            a = np.where(mask, a, STAY_OUT)
        s = summarize(simulate(view, a, slip, qty)[["day", "net_rs"]], days, 0, 0)
        table.append({"tau": tau, **s})
    ok = [r for r in table if r["trades"] >= min_trades or r["tau"] >= 1.0]
    return max(ok, key=lambda r: (r["mean_net_per_day_rs"], r["tau"]))["tau"], table


def random_entry_control(view, trades, days, slip, qty, b) -> dict:
    """Trial E control: random entry seconds on the same days, same count, random side."""
    if trades.empty:
        return {"seeds": 0, "seeds_beaten": 0}
    model_day = summarize(trades[["day", "net_rs"]], days, 0, 0)["mean_net_per_day_rs"]
    per_day = trades.groupby("day").size()
    rows_by_day = {d: np.flatnonzero(view["day"].to_numpy() == d) for d in per_day.index}
    rng = np.random.default_rng(b["seed"])
    ctrl = []
    for _ in range(b["random_seeds"]):
        a = np.zeros(len(view), dtype=int)
        for d, n in per_day.items():
            pick = rng.choice(rows_by_day[d], size=min(n, len(rows_by_day[d])), replace=False)
            a[pick] = rng.choice([BUY_CE, BUY_PE], size=len(pick))
        ctrl.append(
            summarize(simulate(view, a, slip, qty)[["day", "net_rs"]], days, 0, 0)["mean_net_per_day_rs"]
        )
    ctrl = np.array(ctrl)
    return {
        "seeds": len(ctrl),
        "seeds_beaten": int((model_day > ctrl).sum()),
        "control_per_day_mean": round(float(ctrl.mean()), 1),
    }


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, mt, b, m = params["micro"], params["micro_train"], params["baselines"], params["mlflow"]
    slip, qty, grid = p["slippage_pts_per_leg"], p["qty"], mt["tau_grid"]

    df = pd.read_parquet(Path(p["out_dir"]) / "micro.parquet", filters=[("split", "in", ["train", "val"])])
    df = df.sort_values(["day", "sec"]).reset_index(drop=True)
    days = sorted(df["day"].unique())
    folds = walk_forward_folds(days, mt["n_folds"], mt["min_train_days"])

    # ---- out-of-fold probabilities: side models (barrier and trailing labels) and the big-move model
    parts = []
    for tr_days, te_days in folds:
        tr = df[df["day"].isin(tr_days) & ((df["sec"] % mt["train_stride"]) == 0)]
        te = df[df["day"].isin(te_days)].copy()
        te["p_ce"], te["p_pe"] = predict_pair(fit_pair(tr, mt["lgbm"], slip, qty, mt["seed"]), te)
        te["p_ce_tr"], te["p_pe_tr"] = predict_pair(
            fit_pair(trailing_view(tr), mt["lgbm"], slip, qty, mt["seed"]), te
        )
        cut = np.nanpercentile(tr["spot_mfe120"], 80)  # the fold's own train days define "big"
        ok = np.isfinite(tr["spot_mfe120"])
        big = lgb.LGBMClassifier(objective="binary", random_state=mt["seed"], verbose=-1, **mt["lgbm"])
        big.fit(tr.loc[ok, MICRO_COLUMNS], (tr.loc[ok, "spot_mfe120"] >= cut).astype(int))
        te["p_big"] = big.predict_proba(te[MICRO_COLUMNS])[:, 1]
        parts.append(te)
        log.info("fold scored %s..%s (big move >= %.1f spot points)", te_days[0], te_days[-1], cut)
    oof = pd.concat(parts).sort_values(["day", "sec"]).reset_index(drop=True)
    oof_tr = trailing_view(oof)
    oof_days = sorted(oof["day"].unique())
    p_ce, p_pe, p_big = oof["p_ce"].to_numpy(), oof["p_pe"].to_numpy(), oof["p_big"].to_numpy()
    p_ce_tr, p_pe_tr = oof["p_ce_tr"].to_numpy(), oof["p_pe_tr"].to_numpy()
    side, side_tr = np.where(p_ce >= p_pe, BUY_CE, BUY_PE), np.where(p_ce_tr >= p_pe_tr, BUY_CE, BUY_PE)

    rules = {
        "v2": (oof, lambda t: decide(p_ce, p_pe, t)),
        "A": (oof, lambda t: np.where(p_big >= t, side, STAY_OUT)),
    }
    results, tables = {}, {}

    def run(name, view, actions_for, mask=None, model=True):
        tau, table = best_tau(view, actions_for, grid, oof_days, slip, qty, mt["min_oof_trades"], mask)
        a = actions_for(tau)
        if mask is not None:
            a = np.where(mask, a, STAY_OUT)
        trades = simulate(view, a, slip, qty)
        s = score99(trades, oof_days, b)
        ctrl = (random_side_control if model else random_entry_control)(view, trades, oof_days, slip, qty, b)
        ci = s.get("per_day_ci99_rs")
        results[name] = {
            "tau": tau,
            "oof": s,
            "control": ctrl,
            "rule_1_positive_and_99pct_interval_above_zero": bool(
                s["mean_net_per_day_rs"] > 0 and ci is not None and ci[0] > 0
            ),
            "rule_2_beats_control_95_of_100": bool(ctrl.get("seeds_beaten", 0) >= 95),
        }
        tables[name] = table
        log.info(
            "%-3s tau %s: %s trades, hit %s, net/day Rs%s, 99%% %s, control beaten %s/100",
            name,
            tau,
            s["trades"],
            s["hit_rate"],
            s["mean_net_per_day_rs"],
            ci,
            ctrl.get("seeds_beaten"),
        )

    for name, (view, fn) in rules.items():
        run(name, view, fn)
    # C: the entry rule of the better of v2 and A, with trailing exits and trailing-label side models
    base = max(("v2", "A"), key=lambda k: results[k]["oof"]["mean_net_per_day_rs"])
    if base == "v2":
        rules["C"] = (oof_tr, lambda t: decide(p_ce_tr, p_pe_tr, t))
    else:
        rules["C"] = (oof_tr, lambda t: np.where(p_big >= t, side_tr, STAY_OUT))
    run("C", *rules["C"])
    best = max(("v2", "A", "C"), key=lambda k: results[k]["oof"]["mean_net_per_day_rs"])
    view, fn = rules[best]

    sec, dte = oof["sec"].to_numpy(), oof["dte"].to_numpy()
    rv_ann = oof["spot_rv60"].to_numpy() * np.sqrt(SECONDS_PER_YEAR / 60) * 100  # percent, like the IV column
    masks = {
        "D1": sec <= 9 * 3600 + 45 * 60,
        "D2": (dte == 0) & (sec >= 13 * 3600),
        "D3": rv_ann > oof["atm_iv"].to_numpy(),
    }
    for name, mask in masks.items():
        run(name, view, fn, mask=mask)
    ce_sweep, pe_sweep = oof["ce_sweep"].to_numpy() > 0, oof["pe_sweep"].to_numpy() > 0
    sweep = np.where(ce_sweep & ~pe_sweep, BUY_CE, np.where(pe_sweep & ~ce_sweep, BUY_PE, STAY_OUT))
    run("E", oof, lambda t: sweep, model=False)

    out = {
        "protocol": "docs/ALPHA_SPRINT.md",
        "oof_days": oof_days,
        "base_for_C": base,
        "best_for_D": best,
        "share_of_seconds_in_filter": {k: round(float(v.mean()), 4) for k, v in masks.items()},
        "results": results,
        "tau_tables": tables,
        "passed_rules_1_and_2": [
            k
            for k, r in results.items()
            if r["rule_1_positive_and_99pct_interval_above_zero"] and r["rule_2_beats_control_95_of_100"]
        ],
    }
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"]))
    mlflow.set_experiment(m["experiment"])
    with mlflow.start_run(run_name="alpha-sprint") as run_:
        mlflow.set_tags(
            {
                "stage": "sprint",
                "git_commit": runlog._git("rev-parse", "HEAD"),
                "protocol": "docs/ALPHA_SPRINT.md",
                "splits_used": "train,val",
                "test_days_read": "no",
            }
        )
        for k, r in results.items():
            mlflow.log_metric(f"{k}_oof_net_per_day_rs", r["oof"]["mean_net_per_day_rs"])
            mlflow.log_metric(f"{k}_oof_trades", r["oof"]["trades"])
        out["mlflow_run_id"] = run_.info.run_id
    Path("reports/sprint.json").write_text(json.dumps(out, indent=1, default=float))
    log.info("passed rules 1 and 2: %s", out["passed_rules_1_and_2"] or "none")
    summary.update(passed=out["passed_rules_1_and_2"], best_for_D=best, mlflow_run_id=out["mlflow_run_id"])
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("sprint", main))
