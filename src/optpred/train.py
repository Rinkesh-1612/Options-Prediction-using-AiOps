"""Stage 6 -- train: LightGBM on the minute features, every run tracked in MLflow.

Learns, for each decision minute, which of STAY_OUT / BUY_CE / BUY_PE would have paid after costs
(labels.py, at the headline slippage). Then a rule turns probabilities into trades.

DISCIPLINE (all enforced here, not promised):
  * Only train and validation days are READ. The locked test rows are filtered out at the Parquet
    reader, so this stage cannot see them. Final scoring is a separate step that needs --final.
  * Validation is used twice: early stopping, and choosing the confidence threshold. So validation
    numbers are optimistic by construction. They are labelled `val_*_selected` in MLflow. Only the
    test days give a clean number.
  * The threshold grid includes "never trade". If every way of trading loses on validation, the
    chosen policy is to stay out, and the run says so instead of reporting a loss as a result.

Decision rule: take the most likely class; if it is a side (not STAY_OUT) and its probability is at
least tau, trade it, otherwise stay out. tau is picked on validation by mean net rupees per day,
among thresholds that give at least `min_val_trades` trades (or never trading).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import yaml
from mlflow import MlflowClient
from mlflow.models import infer_signature

from optpred import runlog
from optpred.baselines import evaluate as baseline_evaluate
from optpred.features import FEATURE_COLUMNS
from optpred.labels import ACTION_NAMES, label_actions
from optpred.serving_model import NEVER_TRADE, DirectionModel, decide, score_frame
from optpred.sim import simulate, summarize

log = logging.getLogger("optpred.train")


def fit_and_score(train: pd.DataFrame, val: pd.DataFrame, lgbm: dict, seed: int, p: dict, t: dict) -> dict:
    """Fit on train, early-stop and pick tau on val. Pure function: Ray Tune reuses it."""
    slip, qty, horizon = p["_slip"], p["qty"], p["horizon_min"]
    y_tr, y_va = label_actions(train, slip, qty), label_actions(val, slip, qty)
    model = lgb.LGBMClassifier(
        objective="multiclass", random_state=seed, n_jobs=t["n_jobs"], verbose=-1, **lgbm
    )
    model.fit(
        train[FEATURE_COLUMNS],
        y_tr,
        eval_set=[(val[FEATURE_COLUMNS], y_va)],
        eval_metric="multi_logloss",
        callbacks=[lgb.early_stopping(t["early_stopping_rounds"], verbose=False)],
    )
    proba = np.zeros((len(val), 3))
    proba[:, model.classes_] = model.predict_proba(val[FEATURE_COLUMNS])

    prior = np.bincount(y_tr, minlength=3) / len(y_tr)
    days = sorted(val["day"].unique())
    val = val.reset_index(drop=True)
    table = []
    for tau in t["threshold_grid"]:
        s = summarize(simulate(val, decide(proba, tau), slip, qty, horizon), days, 0, 0)
        table.append({"tau": tau, **s})
    ok = [r for r in table if r["trades"] >= t["min_val_trades"] or r["tau"] >= NEVER_TRADE]
    best = max(ok, key=lambda r: (r["mean_net_per_day_rs"], r["tau"]))
    return {
        "model": model,
        "proba": proba,
        "tau": best["tau"],
        "threshold_table": table,
        "val_logloss": float(-np.mean(np.log(np.clip(proba[np.arange(len(y_va)), y_va], 1e-12, None)))),
        "val_logloss_prior": float(-np.mean(np.log(prior[y_va]))),
        "val_accuracy": float((proba.argmax(axis=1) == y_va).mean()),
        "best_iteration": int(model.best_iteration_ or model.n_estimators),
    }


def contributions(model: lgb.LGBMClassifier, X: pd.DataFrame) -> pd.DataFrame:
    """Mean |SHAP-style contribution| per feature (LightGBM's own pred_contrib), per class."""
    c = model.booster_.predict(X, pred_contrib=True)
    k = c.shape[1] // (X.shape[1] + 1)
    c = np.abs(c.reshape(len(X), k, X.shape[1] + 1)[:, :, :-1]).mean(axis=0)
    df = pd.DataFrame(c.T, index=X.columns, columns=[ACTION_NAMES[i] for i in model.classes_])
    df["all_classes"] = df.mean(axis=1)
    return df.sort_values("all_classes", ascending=False)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def register(client: MlflowClient, name: str, run_id: str, val_net_per_day: float) -> dict:
    """Register the run's model. First version becomes champion; later ones only if better on val."""
    mv = next(v for v in client.search_model_versions(f"name='{name}'") if v.run_id == run_id)
    client.set_registered_model_alias(name, "candidate", mv.version)
    try:
        champ = client.get_model_version_by_alias(name, "champion")
        champ_val = client.get_run(champ.run_id).data.metrics.get("val_net_per_day_rs_selected", -np.inf)
        promoted = val_net_per_day > champ_val
    except mlflow.exceptions.MlflowException:
        champ, champ_val, promoted = None, None, True  # nothing deployed yet: initial deployment
    if promoted:
        if champ is not None:
            client.set_registered_model_alias(name, "previous", champ.version)  # rollback target
        client.set_registered_model_alias(name, "champion", mv.version)
    return {"version": int(mv.version), "promoted": promoted, "previous_champion_val": champ_val}


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--run-name", default=None)
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, t, m, b = params["features"], params["train"], params["mlflow"], params["baselines"]
    p["_slip"] = params["costs"]["slippage_pts_per_leg"]
    path = Path(p["out_dir"]) / "features.parquet"

    # the locked test days are filtered out inside the Parquet reader: they never reach memory
    df = pd.read_parquet(path, filters=[("split", "in", ["train", "val"])]).sort_values(["day", "minute"])
    assert set(df["split"]) <= {"train", "val"}
    train, val = df[df["split"] == "train"], df[df["split"] == "val"]
    log.info(
        "train %d rows / %d days, val %d rows / %d days",
        len(train),
        train["day"].nunique(),
        len(val),
        val["day"].nunique(),
    )

    out = fit_and_score(train, val, t["lgbm"], t["seed"], p, t)
    model, proba, tau = out["model"], out["proba"], out["tau"]
    val = val.reset_index(drop=True)
    days = sorted(val["day"].unique())
    chosen = summarize(
        simulate(val, decide(proba, tau), p["_slip"], p["qty"], p["horizon_min"]),
        days,
        b["bootstrap_resamples"],
        b["seed"],
    )
    base = baseline_evaluate(val, p["_slip"], p, b)
    imp = contributions(model, val[FEATURE_COLUMNS])

    uri = os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"])
    if uri.startswith("sqlite:///"):
        Path(uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(m["experiment"]) is None:
        mlflow.create_experiment(
            m["experiment"], artifact_location=Path(m["artifact_root"]).resolve().as_uri()
        )
    mlflow.set_experiment(m["experiment"])
    client = MlflowClient()

    with mlflow.start_run(run_name=args.run_name) as run:
        mlflow.log_params(
            {
                **{f"lgbm_{k}": v for k, v in t["lgbm"].items()},
                "seed": t["seed"],
                "horizon_min": p["horizon_min"],
                "qty": p["qty"],
                "slippage_pts_per_leg": p["_slip"],
                "tau": tau,
                "n_features": len(FEATURE_COLUMNS),
                "n_train_rows": len(train),
                "n_val_rows": len(val),
                "best_iteration": out["best_iteration"],
                "features_sha": file_sha(path),
                "days_sha": file_sha(Path("data/days.json")),
            }
        )
        mlflow.set_tags(
            {
                "git_commit": runlog._git("rev-parse", "HEAD"),
                "git_dirty": str(
                    runlog._git("status", "--porcelain", "--", *runlog.CODE_PATHS) not in ("", "unknown")
                ),
                "stage": "train",
                "splits_used": "train,val",
                "test_days_read": "no",
            }
        )
        mlflow.log_metrics(
            {
                "val_logloss": out["val_logloss"],
                "val_logloss_prior": out["val_logloss_prior"],
                "val_accuracy": out["val_accuracy"],
                "val_net_per_day_rs_selected": chosen["mean_net_per_day_rs"],
                "val_net_per_trade_rs_selected": chosen["mean_net_per_trade_rs"] or 0.0,
                "val_trades_per_day_selected": chosen["trades_per_day"],
                "val_hit_rate_selected": chosen["hit_rate"] or 0.0,
                "val_random_net_per_trade_rs": base["random"]["mean_net_per_trade_rs"],
                "val_random_net_per_day_rs": base["random"]["mean_net_per_day_rs"],
                "val_momentum_net_per_trade_rs": base["momentum"]["mean_net_per_trade_rs"] or 0.0,
                "val_momentum_net_per_day_rs": base["momentum"]["mean_net_per_day_rs"],
                "val_oracle_net_per_trade_rs": base["oracle_not_tradable"]["mean_net_per_trade_rs"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pd.DataFrame(out["threshold_table"]).to_csv(tmp / "threshold_table.csv", index=False)
            imp.to_csv(tmp / "feature_importance.csv")
            (tmp / "decision.json").write_text(
                json.dumps(
                    {
                        "tau": tau,
                        "classes": ACTION_NAMES,
                        "features": FEATURE_COLUMNS,
                        "horizon_min": p["horizon_min"],
                        "qty": p["qty"],
                        "slippage_pts_per_leg": p["_slip"],
                        "never_trade_tau": NEVER_TRADE,
                    },
                    indent=1,
                )
            )
            (tmp / "validation_summary.json").write_text(
                json.dumps({"selected": chosen, "baselines": base}, indent=1)
            )
            fig, ax = plt.subplots(figsize=(7, 6))
            imp["all_classes"].head(15)[::-1].plot.barh(ax=ax)
            ax.set_xlabel("mean |contribution| to the prediction (validation days)")
            fig.tight_layout()
            fig.savefig(tmp / "feature_importance.png", dpi=110)
            plt.close(fig)
            mlflow.log_artifacts(str(tmp))
        X = val[FEATURE_COLUMNS]
        with tempfile.TemporaryDirectory() as tmp:
            booster_file, meta_file = Path(tmp) / "booster.txt", Path(tmp) / "meta.json"
            model.booster_.save_model(str(booster_file))
            meta_file.write_text(json.dumps({"classes": [int(c) for c in model.classes_]}))
            served = score_frame(model.booster_, [int(c) for c in model.classes_], X, tau)
            if not np.allclose(served[["p_stay_out", "p_buy_ce", "p_buy_pe"]].to_numpy(), proba):
                raise RuntimeError("the served scoring function disagrees with the trained model")
            mlflow.pyfunc.log_model(
                name="model",
                python_model=DirectionModel(tau, FEATURE_COLUMNS),
                artifacts={"booster": str(booster_file), "meta": str(meta_file)},
                signature=infer_signature(X, served),
                input_example=X.head(3),
                registered_model_name=m["registered_model"],
                pip_requirements=[
                    f"lightgbm=={lgb.__version__}",
                    f"pandas=={pd.__version__}",
                    f"numpy=={np.__version__}",
                    f"mlflow=={mlflow.__version__}",
                ],
            )
        reg = register(client, m["registered_model"], run.info.run_id, chosen["mean_net_per_day_rs"])
        run_id = run.info.run_id

    log.info(
        "MLflow run %s  logloss %.4f (no-information prior %.4f)  tau %.2f%s",
        run_id,
        out["val_logloss"],
        out["val_logloss_prior"],
        tau,
        "  [never trade]" if tau >= NEVER_TRADE else "",
    )
    log.info(
        "validation, selected policy: %s trades/day, hit %s, net/trade Rs%s, net/day Rs%s, 95%% range/day %s",
        chosen["trades_per_day"],
        chosen["hit_rate"],
        chosen["mean_net_per_trade_rs"],
        chosen["mean_net_per_day_rs"],
        chosen.get("per_day_ci95_rs"),
    )
    log.info(
        "validation, same costs: random net/trade Rs%s, momentum Rs%s, oracle (hindsight) Rs%s",
        base["random"]["mean_net_per_trade_rs"],
        base["momentum"]["mean_net_per_trade_rs"],
        base["oracle_not_tradable"]["mean_net_per_trade_rs"],
    )
    log.info("top features: %s", ", ".join(imp.index[:6]))
    log.info("registry: version %d, champion=%s", reg["version"], reg["promoted"])
    summary.update(
        mlflow_run_id=run_id,
        tau=tau,
        registry=reg,
        val_selected=chosen,
        val_logloss=out["val_logloss"],
        val_logloss_prior=out["val_logloss_prior"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("train", main))
