"""Stage 6b -- micro_train: the v2 model, judged by walk-forward out-of-fold results (docs/V2_PROTOCOL.md).

Two LightGBM binary models per fold: P(the call trade wins) and P(the put trade wins), after costs at the
headline slippage. Rule at second t: take the side with the higher probability if it is at least tau.
One position at a time; the next entry is allowed the second after the exit.

DISCIPLINE (enforced here):
  * Only the 39 development days (split train or val) are read. Forward days and the v1 test days are
    filtered out at the Parquet reader.
  * Every number used to choose tau is out-of-fold: a fold's model never saw the days it scores.
  * The pass rule of the protocol is computed here and written to reports/micro_train.json.
  * Training rows are every `train_stride`-th second: neighbouring seconds share almost all their inputs,
    so this loses little information and cuts the time.
The final model is fitted on all 39 days with the chosen tau and registered as `nifty-option-micro`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import lightgbm as lgb
import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
import yaml
from mlflow import MlflowClient

from optpred import runlog
from optpred.labels import BUY_CE, BUY_PE, STAY_OUT, slippage_rs
from optpred.micro import MICRO_COLUMNS
from optpred.register import register
from optpred.sim import summarize
from optpred.tune import walk_forward_folds

log = logging.getLogger("optpred.micro_train")

NEVER = 1.01


def side_net(df: pd.DataFrame, side: str, slip: float, qty: int) -> np.ndarray:
    return (df[f"{side}_gross_rs"] - df[f"{side}_stat_rs"] - slippage_rs(slip, qty)).to_numpy(float)


def decide(p_ce: np.ndarray, p_pe: np.ndarray, tau: float) -> np.ndarray:
    """The side with the higher probability if it is at least tau, else stay out."""
    best = np.where(p_ce >= p_pe, BUY_CE, BUY_PE)
    return np.where(np.maximum(p_ce, p_pe) >= tau, best, STAY_OUT)


def simulate(df: pd.DataFrame, actions: np.ndarray, slip: float, qty: int) -> pd.DataFrame:
    """Barrier trades taken when following `actions`, one position at a time (rows sorted by day, sec)."""
    day, sec = df["day"].to_numpy(), df["sec"].to_numpy()
    hold = {BUY_CE: df["ce_hold_s"].to_numpy(), BUY_PE: df["pe_hold_s"].to_numpy()}
    net = {BUY_CE: side_net(df, "ce", slip, qty), BUY_PE: side_net(df, "pe", slip, qty)}
    taken, cur, free_at = [], None, -1.0
    for i in np.flatnonzero(actions != STAY_OUT):
        if day[i] != cur:
            cur, free_at = day[i], -1.0
        a = actions[i]
        if sec[i] >= free_at and np.isfinite(net[a][i]):
            taken.append(i)
            free_at = sec[i] + hold[a][i] + 1
    idx = np.array(taken, dtype=int)
    side = actions[idx]
    return pd.DataFrame(
        {
            "row": idx,
            "day": day[idx],
            "sec": sec[idx],
            "side": side,
            "net_rs": np.array([net[s][i] for s, i in zip(side, idx, strict=True)]),
        }
    )


def fit_pair(train: pd.DataFrame, lgbm: dict, slip: float, qty: int, seed: int) -> dict:
    out = {}
    for side in ("ce", "pe"):
        y = (side_net(train, side, slip, qty) > 0).astype(int)
        m = lgb.LGBMClassifier(objective="binary", random_state=seed, verbose=-1, **lgbm)
        m.fit(train[MICRO_COLUMNS], y)
        out[side] = m
    return out


def predict_pair(models: dict, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return tuple(models[s].predict_proba(df[MICRO_COLUMNS])[:, 1] for s in ("ce", "pe"))


def score(trades: pd.DataFrame, days: list[str], b: dict) -> dict:
    return summarize(trades[["day", "net_rs"]], days, b["bootstrap_resamples"], b["seed"])


def random_side_control(df: pd.DataFrame, trades: pd.DataFrame, days, slip, qty, b) -> dict:
    """Same entry seconds as the model, side by coin flip. Shows whether the model picks the side."""
    if trades.empty:
        return {"seeds": 0, "seeds_beaten": 0}
    net = {BUY_CE: side_net(df, "ce", slip, qty), BUY_PE: side_net(df, "pe", slip, qty)}
    rows = trades["row"].to_numpy()
    model_day = summarize(trades[["day", "net_rs"]], days, 0, 0)["mean_net_per_day_rs"]
    rng = np.random.default_rng(b["seed"])
    ctrl = []
    for _ in range(b["random_seeds"]):
        side = rng.choice([BUY_CE, BUY_PE], size=len(rows))
        n = np.where(side == BUY_CE, net[BUY_CE][rows], net[BUY_PE][rows])
        t = pd.DataFrame({"day": trades["day"].to_numpy(), "net_rs": n})
        ctrl.append(summarize(t, days, 0, 0)["mean_net_per_day_rs"])
    ctrl = np.array(ctrl)
    return {
        "seeds": len(ctrl),
        "seeds_beaten": int((model_day > ctrl).sum()),
        "control_per_day_mean": round(float(ctrl.mean()), 1),
        "control_per_day_p5_p95": [round(float(x), 1) for x in np.percentile(ctrl, [5, 95])],
    }


def rule_baselines(df: pd.DataFrame, days, slip, qty, b) -> dict:
    """Blind rules through the same barrier simulator: they have no free settings."""
    flow = np.where(
        (df["fut_ret5"] > 0) & (df["fut_sv5"] > 0.2),
        BUY_CE,
        np.where((df["fut_ret5"] < 0) & (df["fut_sv5"] < -0.2), BUY_PE, 0),
    )
    rules = {
        "always_ce": np.full(len(df), BUY_CE),
        "always_pe": np.full(len(df), BUY_PE),
        "futures_flow": flow,
    }
    return {k: score(simulate(df, a, slip, qty), days, b) for k, a in rules.items()}


class MicroModel(mlflow.pyfunc.PythonModel):
    """The v2 model as served: two boosters plus the decision rule (tau) inside it."""

    def __init__(self, tau: float, features: list[str]):
        self.tau, self.features = tau, list(features)

    def load_context(self, context):
        self.boosters = {s: lgb.Booster(model_file=context.artifacts[s]) for s in ("ce", "pe")}

    def predict(self, context, model_input, params=None):
        x = model_input[self.features].astype(float)
        p_ce, p_pe = (self.boosters[s].predict(x) for s in ("ce", "pe"))
        return pd.DataFrame(
            {"p_ce_wins": p_ce, "p_pe_wins": p_pe, "action": decide(p_ce, p_pe, self.tau), "tau": self.tau}
        )


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, mt, b, m = params["micro"], params["micro_train"], params["baselines"], params["mlflow"]
    slip, qty = params["costs"]["slippage_pts_per_leg"], p["qty"]

    path = Path(p["out_dir"]) / "micro.parquet"
    df = (
        pd.read_parquet(path, filters=[("split", "in", ["train", "val"])])
        .sort_values(["day", "sec"])
        .reset_index(drop=True)
    )
    days = sorted(df["day"].unique())
    folds = walk_forward_folds(days, mt["n_folds"], mt["min_train_days"])
    log.info("%d rows over %d development days; %d folds", len(df), len(days), len(folds))

    # ---- out-of-fold probabilities
    oof_parts = []
    for i, (tr_days, te_days) in enumerate(folds):
        tr = df[df["day"].isin(tr_days)]
        tr = tr[(tr["sec"] % mt["train_stride"]) == 0]
        models = fit_pair(tr, mt["lgbm"], slip, qty, mt["seed"])
        te = df[df["day"].isin(te_days)].copy()
        te["p_ce"], te["p_pe"] = predict_pair(models, te)
        oof_parts.append(te)
        log.info(
            "fold %d: %d train days (%d rows), scored %s..%s",
            i + 1,
            len(tr_days),
            len(tr),
            te_days[0],
            te_days[-1],
        )
    oof = pd.concat(oof_parts).sort_values(["day", "sec"]).reset_index(drop=True)
    oof_days = sorted(oof["day"].unique())

    # ---- tau from out-of-fold results only
    table = []
    for tau in mt["tau_grid"]:
        tr = simulate(oof, decide(oof["p_ce"].to_numpy(), oof["p_pe"].to_numpy(), tau), slip, qty)
        s = summarize(tr[["day", "net_rs"]], oof_days, 0, 0)
        table.append({"tau": tau, **s})
        log.info(
            "tau %.2f: trades/day %6s  hit %6s  net/trade Rs%8s  net/day Rs%9s",
            tau,
            s["trades_per_day"],
            s["hit_rate"],
            s["mean_net_per_trade_rs"],
            s["mean_net_per_day_rs"],
        )
    ok = [r for r in table if r["trades"] >= mt["min_oof_trades"] or r["tau"] >= NEVER]
    tau = max(ok, key=lambda r: (r["mean_net_per_day_rs"], r["tau"]))["tau"]

    chosen = simulate(oof, decide(oof["p_ce"].to_numpy(), oof["p_pe"].to_numpy(), tau), slip, qty)
    chosen_score = score(chosen, oof_days, b)
    control = random_side_control(oof, chosen, oof_days, slip, qty, b)
    ci = chosen_score.get("per_day_ci95_rs")
    pass_rule = {
        "1_oof_positive_and_interval_excludes_zero": bool(
            chosen_score["mean_net_per_day_rs"] > 0 and ci is not None and ci[0] > 0
        ),
        "2_beats_random_side_in_95_of_100": bool(control.get("seeds_beaten", 0) >= 95),
        "3_forward_days_positive": "scored later by micro_evaluate",
    }
    baselines = rule_baselines(oof, oof_days, slip, qty, b)

    # Diagnostics (not part of the pass rule, never used to choose tau): the cost table the protocol asks for,
    # and whether the model picks the side at each tau that trades.
    p_ce, p_pe = oof["p_ce"].to_numpy(), oof["p_pe"].to_numpy()
    diagnostics = {"by_slippage": {}, "side_picking_by_tau": {}}
    for s_ in params["costs"]["sensitivity_pts_per_leg"]:
        rows = []
        for t_ in mt["tau_grid"]:
            tr_ = simulate(oof, decide(p_ce, p_pe, t_), s_, qty)
            rows.append({"tau": t_, **score(tr_, oof_days, b)})
        diagnostics["by_slippage"][str(s_)] = rows
    for t_ in mt["tau_grid"]:
        tr_ = simulate(oof, decide(p_ce, p_pe, t_), slip, qty)
        if len(tr_) >= mt["min_oof_trades"]:
            diagnostics["side_picking_by_tau"][str(t_)] = random_side_control(
                oof, tr_, oof_days, slip, qty, b
            )
    for s_, rows in diagnostics["by_slippage"].items():
        best = max(rows, key=lambda r: r["mean_net_per_day_rs"])
        log.info(
            "diagnostic, slippage %s: best tau %s -> net/day Rs%s, interval %s",
            s_,
            best["tau"],
            best["mean_net_per_day_rs"],
            best.get("per_day_ci95_rs"),
        )
    log.info(
        "diagnostic, side picking: %s",
        {k: v.get("seeds_beaten") for k, v in diagnostics["side_picking_by_tau"].items()},
    )
    log.info("chosen tau %s; out-of-fold %s", tau, chosen_score)
    log.info("random side, same entries: %s", control)
    log.info("pass rule 1-2: %s", pass_rule)

    # ---- final model on all development days, tracked and registered
    full = df[(df["sec"] % mt["train_stride"]) == 0]
    models = fit_pair(full, mt["lgbm"], slip, qty, mt["seed"])
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"]))
    mlflow.set_experiment(m["experiment"])
    with mlflow.start_run(run_name="micro-train") as run:
        mlflow.set_tags(
            {
                "stage": "micro_train",
                "git_commit": runlog._git("rev-parse", "HEAD"),
                "model": "v2",
                "protocol": "docs/V2_PROTOCOL.md",
                "splits_used": "train,val",
                "test_days_read": "no",
            }
        )
        mlflow.log_params(
            {
                **{f"lgbm_{k}": v for k, v in mt["lgbm"].items()},
                "tau": tau,
                "train_stride": mt["train_stride"],
                "take_profit_pts": p["take_profit_pts"],
                "stop_loss_pts": p["stop_loss_pts"],
                "max_hold_s": p["max_hold_s"],
                "slippage_pts_per_leg": slip,
                "n_features": len(MICRO_COLUMNS),
            }
        )
        mlflow.log_metrics(
            {
                "oof_net_per_day_rs": chosen_score["mean_net_per_day_rs"],
                "oof_trades_per_day": chosen_score["trades_per_day"],
                "oof_hit_rate": chosen_score["hit_rate"] or 0.0,
                "oof_random_side_seeds_beaten": control.get("seeds_beaten", 0),
                # the register stage compares versions on this name
                "val_net_per_day_rs_selected": chosen_score["mean_net_per_day_rs"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            files = {}
            for s in ("ce", "pe"):
                files[s] = str(Path(tmp) / f"{s}.txt")
                models[s].booster_.save_model(files[s])
            pd.DataFrame(table).to_csv(Path(tmp) / "tau_table.csv", index=False)
            imp = pd.DataFrame(
                {s: models[s].booster_.feature_importance("gain") for s in ("ce", "pe")}, index=MICRO_COLUMNS
            )
            imp.sort_values("ce", ascending=False).to_csv(Path(tmp) / "feature_importance_gain.csv")
            mlflow.log_artifacts(tmp)
            mlflow.pyfunc.log_model(
                name="model",
                python_model=MicroModel(tau, MICRO_COLUMNS),
                artifacts=files,
                input_example=full[MICRO_COLUMNS].head(3).astype(float),
                registered_model_name=mt["registered_model"],
            )
        reg = register(
            MlflowClient(), mt["registered_model"], run.info.run_id, chosen_score["mean_net_per_day_rs"]
        )

    out = {
        "mlflow_run_id": run.info.run_id,
        "tau": tau,
        "oof_days": oof_days,
        "tau_table": table,
        "oof_chosen": chosen_score,
        "random_side_control": control,
        "baselines_oof": baselines,
        "pass_rule": pass_rule,
        "diagnostics_not_pass_rule": diagnostics,
        "registry": reg,
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/micro_train.json").write_text(json.dumps(out, indent=1, default=float))
    summary.update(
        mlflow_run_id=run.info.run_id,
        tau=tau,
        oof_net_per_day_rs=chosen_score["mean_net_per_day_rs"],
        pass_rule=pass_rule,
        registry=reg,
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("micro_train", main))
