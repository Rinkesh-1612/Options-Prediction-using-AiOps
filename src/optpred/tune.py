"""Stage 5b -- tune: Ray Tune searches LightGBM settings with walk-forward folds by day.

Why walk-forward: the model will always predict days AFTER the ones it learned from. So each fold
trains on the earlier days and scores on the next block of days. Rows from one day never sit on
both sides of a split.

What it scores: mean multi-class log loss on the folds. It does not score profit. Profit on a few
days is too noisy to rank settings, and ranking on it would tune the model to the validation days.

DISCIPLINE: only train-split days are read. Validation and test days stay untouched here, so the
validation numbers in `train` stay honest. The best settings go to reports/tune.json; `train` uses
them only when params.yaml sets `train.use_tuned: true`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
import yaml

from optpred import runlog
from optpred.features import FEATURE_COLUMNS
from optpred.labels import label_actions

log = logging.getLogger("optpred.tune")


class TuneError(RuntimeError):
    """Raised when the data cannot support the requested folds."""


def walk_forward_folds(
    days: list[str], n_folds: int, min_train_days: int = 10
) -> list[tuple[list[str], list[str]]]:
    """Expanding-window folds: train on days[:k], score on the next block. Days stay in time order."""
    days = sorted(days)
    block = (len(days) - min_train_days) // n_folds
    if block < 1:
        raise TuneError(f"{len(days)} days cannot give {n_folds} folds with {min_train_days} training days")
    folds = []
    for i in range(n_folds):
        cut = min_train_days + i * block
        folds.append((days[:cut], days[cut : cut + block]))
    return folds


def cv_logloss(
    df: pd.DataFrame, lgbm: dict, folds, slip: float, qty: int, seed: int, n_jobs: int, rounds: int
) -> dict:
    """Mean multi-class log loss over the folds, and the mean best iteration."""
    losses, iters = [], []
    for tr_days, va_days in folds:
        tr, va = df[df["day"].isin(tr_days)], df[df["day"].isin(va_days)]
        y_tr, y_va = label_actions(tr, slip, qty), label_actions(va, slip, qty)
        model = lgb.LGBMClassifier(
            objective="multiclass", random_state=seed, n_jobs=n_jobs, verbose=-1, **lgbm
        )
        model.fit(
            tr[FEATURE_COLUMNS],
            y_tr,
            eval_set=[(va[FEATURE_COLUMNS], y_va)],
            eval_metric="multi_logloss",
            callbacks=[lgb.early_stopping(rounds, verbose=False)],
        )
        proba = np.zeros((len(va), 3))
        proba[:, model.classes_] = model.predict_proba(va[FEATURE_COLUMNS])
        losses.append(float(-np.mean(np.log(np.clip(proba[np.arange(len(y_va)), y_va], 1e-12, None)))))
        iters.append(int(model.best_iteration_ or model.n_estimators))
    return {
        "logloss": float(np.mean(losses)),
        "fold_logloss": losses,
        "mean_best_iteration": float(np.mean(iters)),
    }


def trial(config: dict, df: pd.DataFrame, folds, base_lgbm: dict, slip, qty, seed, n_jobs, rounds) -> None:
    """One Ray Tune trial: score one setting on all folds."""
    from ray import train as ray_train

    lgbm = {**base_lgbm, **config}
    ray_train.report(cv_logloss(df, lgbm, folds, slip, qty, seed, n_jobs, rounds))


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, t, tu, m = params["features"], params["train"], params["tune"], params["mlflow"]
    slip = params["costs"]["slippage_pts_per_leg"]

    path = Path(p["out_dir"]) / "features.parquet"
    df = pd.read_parquet(path, filters=[("split", "==", "train")]).sort_values(["day", "minute"])
    assert set(df["split"]) == {"train"}
    folds = walk_forward_folds(sorted(df["day"].unique()), tu["n_folds"], tu["min_train_days"])
    log.info("%d train rows, %d days, %d walk-forward folds", len(df), df["day"].nunique(), len(folds))

    import ray
    from ray import tune
    from ray.train import RunConfig

    ray.init(num_cpus=tu["cpus"], include_dashboard=False, logging_level=logging.WARNING)
    space = {
        "num_leaves": tune.choice(tu["space"]["num_leaves"]),
        "min_child_samples": tune.choice(tu["space"]["min_child_samples"]),
        "learning_rate": tune.loguniform(*tu["space"]["learning_rate"]),
        "colsample_bytree": tune.uniform(*tu["space"]["colsample_bytree"]),
        "reg_lambda": tune.loguniform(*tu["space"]["reg_lambda"]),
        "n_estimators": t["lgbm"]["n_estimators"],
    }
    base = {k: v for k, v in t["lgbm"].items() if k not in space}
    objective = tune.with_parameters(
        trial,
        df=df,
        folds=folds,
        base_lgbm=base,
        slip=slip,
        qty=p["qty"],
        seed=t["seed"],
        n_jobs=tu["cpus_per_trial"],
        rounds=t["early_stopping_rounds"],
    )
    objective = tune.with_resources(objective, {"cpu": tu["cpus_per_trial"]})
    tuner = tune.Tuner(
        objective,
        param_space=space,
        tune_config=tune.TuneConfig(
            metric="logloss",
            mode="min",
            num_samples=tu["num_samples"],
            max_concurrent_trials=tu["concurrent"],
            search_alg=tune.search.BasicVariantGenerator(random_state=t["seed"]),
        ),
        run_config=RunConfig(storage_path=str(Path("state/ray").resolve()), verbose=0, name="tune"),
    )
    grid = tuner.fit()
    ray.shutdown()
    results = [r for r in grid if r.metrics and "logloss" in r.metrics]
    if not results:
        raise TuneError("no Ray Tune trial finished")
    best = min(results, key=lambda r: r.metrics["logloss"])
    default = cv_logloss(
        df, t["lgbm"], folds, slip, p["qty"], t["seed"], tu["cpus"], t["early_stopping_rounds"]
    )
    best_cfg = {k: (float(v) if isinstance(v, float) else v) for k, v in best.config.items()}
    out = {
        "objective": "mean walk-forward multi_logloss on train days",
        "n_trials": len(results),
        "n_folds": len(folds),
        "default_logloss": default["logloss"],
        "best_logloss": best.metrics["logloss"],
        "best_params": best_cfg,
        "trials": sorted(
            (
                {
                    **{k: (float(v) if isinstance(v, float) else v) for k, v in r.config.items()},
                    "logloss": r.metrics["logloss"],
                }
                for r in results
            ),
            key=lambda d: d["logloss"],
        ),
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/tune.json").write_text(json.dumps(out, indent=1))

    uri = __import__("os").environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"])
    if uri.startswith("sqlite:///"):
        Path(uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(m["experiment"]) is None:
        mlflow.create_experiment(
            m["experiment"], artifact_location=Path(m["artifact_root"]).resolve().as_uri()
        )
    mlflow.set_experiment(m["experiment"])
    with mlflow.start_run(run_name="ray-tune") as run:
        mlflow.set_tags(
            {"git_commit": runlog._git("rev-parse", "HEAD"), "stage": "tune", "splits_used": "train"}
        )
        mlflow.log_params(
            {
                "n_trials": len(results),
                "n_folds": len(folds),
                "seed": t["seed"],
                **{f"best_{k}": v for k, v in best_cfg.items()},
            }
        )
        mlflow.log_metrics(
            {"cv_logloss_best": out["best_logloss"], "cv_logloss_default": out["default_logloss"]}
        )
        for i, tr in enumerate(out["trials"]):
            mlflow.log_metric("trial_logloss", tr["logloss"], step=i)
        mlflow.log_artifact("reports/tune.json")
    log.info(
        "default cv logloss %.4f, best %.4f (%d trials)",
        out["default_logloss"],
        out["best_logloss"],
        len(results),
    )
    summary.update(
        mlflow_run_id=run.info.run_id,
        n_trials=len(results),
        default_logloss=out["default_logloss"],
        best_logloss=out["best_logloss"],
        best_params=best_cfg,
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("tune", main))
