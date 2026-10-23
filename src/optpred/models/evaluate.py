"""Stage 9 -- evaluate: the one-time score of the champion model on the locked test days.

Follows docs/FINAL_TEST_PROTOCOL.md, which was committed before this file existed.

DISCIPLINE (enforced here):
  * Refuses to run without --final, and refuses to run twice: once reports/final.json exists the test
    days have been seen, and a second run would be a second look. The DVC stage is also frozen.
  * Scores the model exactly as it is served: it is loaded from the MLflow registry by its `champion`
    alias and called through the same pyfunc `predict` the model server uses, with the rule inside it.
  * Nothing is fitted here. The only thing taken from the train days is the class shares (the
    no-information prior of S1), which use train labels only.

Results (all on the test days, unit of evidence = the day):
  primary  the champion's own policy against the baselines (baselines.evaluate)
  S1       log loss gain over the no-information prior, with a day-bootstrap interval
  S2       forced policy (tau = 0) against coin-flip sides at the SAME entry minutes
  S3       S2 and primary at every slippage in costs.sensitivity_pts_per_leg

Writing reports/final.json also unlocks the test days in the web page (api.py checks for it).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.features.labels import BUY_CE, BUY_PE, STAY_OUT, label_actions
from optpred.features.minute import FEATURE_COLUMNS
from optpred.models.baselines import evaluate as baseline_evaluate
from optpred.models.sim import simulate, summarize
from optpred.serving.serving_model import decide

log = logging.getLogger("optpred.models.evaluate")

PROTOCOL = "docs/FINAL_TEST_PROTOCOL.md"
PROBA_COLUMNS = ["p_stay_out", "p_buy_ce", "p_buy_pe"]


class EvaluateError(RuntimeError):
    """The final evaluation cannot run (already done, no champion, no test days)."""


def logloss_gain_by_day(test: pd.DataFrame, proba: np.ndarray, y: np.ndarray, prior: np.ndarray) -> pd.Series:
    """Per test day: prior log loss minus model log loss (> 0 means the model knows more than the shares)."""
    p_model = np.clip(proba[np.arange(len(y)), y], 1e-12, None)
    p_prior = np.clip(prior[y], 1e-12, None)
    gain = -np.log(p_prior) + np.log(p_model)
    return pd.Series(gain).groupby(test["day"].to_numpy()).mean()


def bootstrap_mean(values: np.ndarray, resamples: int, seed: int) -> list[float]:
    """95% interval of the mean, resampling whole days."""
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(resamples, len(values)))].mean(axis=1)
    return [round(float(x), 5) for x in np.percentile(means, [2.5, 97.5])]


def information_test(
    test: pd.DataFrame, proba: np.ndarray, y: np.ndarray, prior: np.ndarray, b: dict
) -> dict:
    """S1: does the model carry information on unseen days?"""
    by_day = logloss_gain_by_day(test, proba, y, prior)
    ci = bootstrap_mean(by_day.to_numpy(), b["bootstrap_resamples"], b["seed"])
    p_model = np.clip(proba[np.arange(len(y)), y], 1e-12, None)
    return {
        "model_logloss": round(float(-np.mean(np.log(p_model))), 5),
        "prior_logloss": round(float(-np.mean(np.log(prior[y]))), 5),
        "gain_per_day_mean": round(float(by_day.mean()), 5),
        "gain_per_day_ci95": ci,
        "days_with_gain": int((by_day > 0).sum()),
        "accuracy": round(float((proba.argmax(axis=1) == y).mean()), 4),
        "detected": bool(ci[0] > 0),
    }


def side_picking_test(test: pd.DataFrame, proba: np.ndarray, slip: float, p: dict, b: dict) -> dict:
    """S2: the forced policy (tau = 0) against coin-flip sides at the same entry minutes."""
    days = sorted(test["day"].unique())
    args = (slip, p["qty"], p["horizon_min"])
    forced = decide(proba, 0.0)
    model = summarize(simulate(test, forced, *args), days, b["bootstrap_resamples"], b["seed"])
    trades = forced != STAY_OUT
    rng = np.random.default_rng(b["seed"])
    control = []
    for _ in range(b["random_seeds"]):
        sides = rng.choice([BUY_CE, BUY_PE], size=len(test))
        control.append(
            summarize(simulate(test, np.where(trades, sides, STAY_OUT), *args), days, 0, 0)[
                "mean_net_per_day_rs"
            ]
        )
    control = np.array(control)
    beaten = int((model["mean_net_per_day_rs"] > control).sum())
    return {
        "forced_policy": model,
        "coin_flip_same_minutes_per_day_mean": round(float(control.mean()), 1),
        "coin_flip_same_minutes_per_day_p5_p95": [
            round(float(x), 1) for x in np.percentile(control, [5, 95])
        ],
        "seeds": len(control),
        "seeds_beaten": beaten,
        "detected": beaten >= int(0.95 * len(control)),
    }


def score_test(
    test: pd.DataFrame, served: pd.DataFrame, tau: float, prior: np.ndarray, p: dict, costs: dict, b: dict
) -> dict:
    """Every number of the protocol, from the served model's output on the test rows. Pure: tests call it."""
    days = sorted(test["day"].unique())
    proba = served[PROBA_COLUMNS].to_numpy()
    actions = served["action"].to_numpy()
    headline = costs["slippage_pts_per_leg"]
    out: dict = {"days": days, "rows": len(test), "tau": tau, "by_slippage": {}}
    for slip in costs["sensitivity_pts_per_leg"]:
        args = (slip, p["qty"], p["horizon_min"])
        out["by_slippage"][str(slip)] = {
            "champion": summarize(simulate(test, actions, *args), days, b["bootstrap_resamples"], b["seed"]),
            "baselines": baseline_evaluate(test, slip, p, b),
            "side_picking": side_picking_test(test, proba, slip, p, b),
        }
    y = label_actions(test, headline, p["qty"])
    out["information"] = information_test(test, proba, y, prior, b)
    main = out["by_slippage"][str(headline)]
    trading = {k: v for k, v in main["baselines"].items() if k not in ("stay_out", "oracle_not_tradable")}
    out["verdict"] = {
        "headline_slippage": headline,
        "champion_net_per_day_rs": main["champion"]["mean_net_per_day_rs"],
        "every_trading_baseline_lost": all(v["mean_net_per_day_rs"] < 0 for v in trading.values()),
        "information_detected": out["information"]["detected"],
        "side_picking_detected": main["side_picking"]["detected"],
    }
    return out


def load_champion(name: str):
    """The registry's champion, exactly as the model server loads it."""
    client = mlflow.MlflowClient()
    try:
        mv = client.get_model_version_by_alias(name, "champion")
    except mlflow.exceptions.MlflowException as e:
        raise EvaluateError(f"no champion registered for {name}") from e
    model = mlflow.pyfunc.load_model(f"models:/{name}@champion")
    return model, mv


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--final", action="store_true", help="open the locked test days (once)")
    ap.add_argument("--out", default="reports/final.json")
    args = ap.parse_args(argv)
    out_path = Path(args.out)
    if not args.final:
        log.error("refusing to open the locked test days without --final (%s)", PROTOCOL)
        return 2
    if out_path.exists():
        log.error("%s exists: the test days were already scored once; a second look is not allowed", out_path)
        return 3
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, costs, b, m = params["features"], params["costs"], params["baselines"], params["mlflow"]

    df = pd.read_parquet(Path(p["out_dir"]) / "features.parquet").sort_values(["day", "minute"])
    test = df[df["split"] == "test"].reset_index(drop=True)
    train = df[df["split"] == "train"]
    if test.empty:
        raise EvaluateError("no test rows in the features file")
    y_train = label_actions(train, costs["slippage_pts_per_leg"], p["qty"])
    prior = np.bincount(y_train, minlength=3) / len(y_train)

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"]))
    model, mv = load_champion(m["registered_model"])
    served = model.predict(test[FEATURE_COLUMNS].astype(float))
    tau = float(served["tau"].iloc[0])
    log.info(
        "champion v%s (run %s), tau %.2f; %d test rows over %d days",
        mv.version,
        mv.run_id,
        tau,
        len(test),
        test["day"].nunique(),
    )

    res = score_test(test, served, tau, prior, p, costs, b)
    res.update(
        protocol=PROTOCOL,
        model={"name": m["registered_model"], "version": int(mv.version), "run_id": mv.run_id},
        evaluated_at_commit=runlog._git("rev-parse", "HEAD"),
    )
    v, main_res = res["verdict"], res["by_slippage"][str(costs["slippage_pts_per_leg"])]

    mlflow.set_experiment(m["experiment"])
    with mlflow.start_run(run_name="final-evaluation") as run:
        mlflow.set_tags(
            {
                "stage": "evaluate",
                "git_commit": res["evaluated_at_commit"],
                "champion_run_id": mv.run_id,
                "champion_version": mv.version,
                "test_days_read": "yes",
                "protocol": PROTOCOL,
            }
        )
        forced = main_res["side_picking"]["forced_policy"]
        mlflow.log_metrics(
            {
                "test_champion_net_per_day_rs": v["champion_net_per_day_rs"],
                "test_logloss": res["information"]["model_logloss"],
                "test_logloss_prior": res["information"]["prior_logloss"],
                "test_logloss_gain_per_day": res["information"]["gain_per_day_mean"],
                "test_forced_net_per_day_rs": forced["mean_net_per_day_rs"],
                "test_forced_hit_rate": forced["hit_rate"] or 0.0,
                "test_forced_seeds_beaten": main_res["side_picking"]["seeds_beaten"],
                **{
                    f"test_{k}_net_per_day_rs": r["mean_net_per_day_rs"]
                    for k, r in main_res["baselines"].items()
                },
            }
        )
        res["mlflow_run_id"] = run.info.run_id
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "final.json"
            f.write_text(json.dumps(res, indent=1, default=float))
            mlflow.log_artifact(str(f))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=1, default=float))  # last: this file is the "done" marker
    for name, r in main_res["baselines"].items():
        log.info(
            "test  %-20s net/day Rs%9s  net/trade Rs%7s",
            name,
            r["mean_net_per_day_rs"],
            r["mean_net_per_trade_rs"],
        )
    log.info("test  champion             net/day Rs%9s", v["champion_net_per_day_rs"])
    log.info("S1 information: %s", res["information"])
    log.info(
        "S2 forced policy net/day Rs%s, beats %d/%d coin-flip seeds",
        forced["mean_net_per_day_rs"],
        main_res["side_picking"]["seeds_beaten"],
        main_res["side_picking"]["seeds"],
    )
    log.info("verdict: %s", v)
    summary.update(mlflow_run_id=run.info.run_id, model_version=int(mv.version), verdict=v)
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("evaluate", main))
