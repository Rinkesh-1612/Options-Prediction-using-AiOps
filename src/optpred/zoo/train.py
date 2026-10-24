"""Stage zoo_train: walk-forward cross-validation of every model family and setting, on DEV days only.

  * Ray Tune runs the settings of params.yaml -> zoo.grid in parallel (one trial = one family + one setting).
  * Each trial trains on the folds, scores the validation days, and picks tau on the pooled validation
    (out-of-fold) scores. Its result: net rupees per day, trades, hit rate, IC, per-fold numbers.
  * MLflow: one parent run per family, one child run per setting (params, metrics, data and code versions).
  * The best LightGBM regressor also gets feature importance (gain) and a group ablation
    (cross-validation again without one feature group at a time).

Outputs: reports/zoo/cv.json (best setting and tau per family), reports/zoo/importance.json.
Usage:   ./pipe python -m optpred.zoo.train
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import mlflow
import numpy as np
import yaml

from optpred.common import runlog
from optpred.zoo import tracking
from optpred.zoo.data import feature_groups, load_dataset, split_days
from optpred.zoo.models import make, predict
from optpred.zoo.sim import choose_tau, information_coef, simulate

log = logging.getLogger("optpred.zoo.train")
OUT = Path("reports/zoo")


def run_cv(ds, family: str, params: dict, folds, z: dict) -> dict:
    """Out-of-fold scores of one setting -> tau, pooled metrics, per-fold metrics."""
    score = np.full((len(ds.X), 2), np.nan)
    val_slices = []
    for train_days, val_days in folds:
        model = make(family, params, ds.features).fit(ds, ds.rows(train_days))
        sl = ds.day_slices(val_days)
        score_f = predict(model, ds, sl)
        for _, s in sl:
            score[s] = score_f[s]
        val_slices += sl
    tau, q, m = choose_tau(score, ds, val_slices, z["tau_quantiles"], z["min_trades"])
    oof_rows = np.concatenate([np.arange(s.start, s.stop) for _, s in val_slices])
    folds_m = [simulate(score, ds, ds.day_slices(v), tau) for _, v in folds]
    return {
        "tau": tau,
        "tau_q": q,
        **m,
        **information_coef(score, ds, oof_rows),
        "fold_net_per_day": [f["net_per_day"] for f in folds_m],
    }


def trial(config: dict, ds, folds, z: dict) -> dict:
    t = config["trial"]
    return {"family": t["family"], "params": t["params"], **run_cv(ds, t["family"], t["params"], folds, z)}


def run_grid(ds, folds, z: dict) -> list[dict]:
    import ray
    from ray import tune
    from ray.train import RunConfig

    trials = [{"family": f, "params": p | {"n_jobs": 1}} for f, ps in z["grid"].items() for p in ps]
    ray.init(num_cpus=z["cpus"], include_dashboard=False, logging_level=logging.WARNING)
    fn = tune.with_resources(tune.with_parameters(trial, ds=ds, folds=folds, z=z), {"cpu": 1})
    tuner = tune.Tuner(
        fn,
        param_space={"trial": tune.grid_search(trials)},
        run_config=RunConfig(storage_path=str(Path("state/ray").resolve()), name="zoo", verbose=0),
    )
    results = tuner.fit()
    ray.shutdown()
    out = []
    for r in results:
        if r.error:
            log.error("trial failed: %s", r.error)
            continue
        out.append(
            {
                k: r.metrics[k]
                for k in (
                    "family",
                    "params",
                    "tau",
                    "tau_q",
                    "trades",
                    "net_per_day",
                    "net_per_trade",
                    "hit_rate",
                    "daily_sharpe",
                    "max_drawdown",
                    "ic_ce",
                    "ic_pe",
                    "fold_net_per_day",
                )
            }
        )
    if len(out) != len(trials):
        raise RuntimeError(f"{len(trials) - len(out)} of {len(trials)} trials failed")
    return out


def importance_and_ablation(ds, folds, dev: list[str], params: dict, z: dict) -> dict:
    model = make("lgbm_reg", params | {"n_jobs": z["cpus"]}, ds.features).fit(ds, ds.rows(dev))
    full = run_cv(ds, "lgbm_reg", params | {"n_jobs": z["cpus"]}, folds, z)
    abl = {}
    for group, cols in feature_groups(ds.features).items():
        r = run_cv(ds, "lgbm_reg", params | {"n_jobs": z["cpus"], "drop_columns": cols}, folds, z)
        abl[group] = {k: round(r[k] - full[k], 4) for k in ("net_per_day", "ic_ce", "ic_pe")}
        log.info("ablation without %-7s: %s", group, abl[group])
    imp = dict(sorted(model.importance().items(), key=lambda kv: -kv[1]))
    return {
        "gain_share": imp,
        "ablation_delta_vs_full": abl,
        "full": {k: full[k] for k in ("net_per_day", "ic_ce", "ic_pe")},
    }


def num(v):
    return float(v) if np.isfinite(v) else 1e12


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    z = params["zoo"]
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    dev, test, folds = split_days(accepted, z["n_test_days"], z["min_train_days"], z["val_days"])
    log.info("dev %d days (%d folds), test %d days (not read here)", len(dev), len(folds), len(test))
    ds = load_dataset(dev, Path(params["feat"]["out_dir"]), Path(params["labels"]["out_dir"]))

    results = run_grid(ds, folds, z)
    best = {}
    for r in results:
        b = best.get(r["family"])
        if b is None or (r["net_per_day"], r["daily_sharpe"]) > (b["net_per_day"], b["daily_sharpe"]):
            best[r["family"]] = r
    lgbm = best["lgbm_reg"]["params"]
    imp = importance_and_ablation(ds, folds, dev, {k: v for k, v in lgbm.items() if k != "n_jobs"}, z)

    tracking.setup(z["mlflow"])
    tags = tracking.version_tags() | {"stage": "zoo_train", "dev_days": f"{dev[0]}..{dev[-1]}"}
    metric_keys = (
        "trades",
        "net_per_day",
        "net_per_trade",
        "hit_rate",
        "daily_sharpe",
        "max_drawdown",
        "ic_ce",
        "ic_pe",
        "tau_q",
    )
    for fam in best:
        with mlflow.start_run(run_name=fam, tags=tags | {"family": fam}):
            for r in (x for x in results if x["family"] == fam):
                with mlflow.start_run(
                    run_name=f"{fam} {r['params']}", nested=True, tags=tags | {"family": fam}
                ):
                    mlflow.log_params(r["params"])
                    mlflow.log_metrics({f"cv_{k}": r[k] for k in metric_keys} | {"cv_tau": num(r["tau"])})
                    for i, v in enumerate(r["fold_net_per_day"]):
                        mlflow.log_metric("cv_fold_net_per_day", v, step=i)
            b = best[fam]
            mlflow.log_params(b["params"])
            mlflow.log_metrics({f"cv_{k}": b[k] for k in metric_keys} | {"cv_tau": num(b["tau"])})
            if fam == "lgbm_reg":
                mlflow.log_dict(imp, "importance.json")
                mlflow.log_metrics({f"gain_{k}": v for k, v in list(imp["gain_share"].items())[:20]})
                mlflow.log_metrics(
                    {
                        f"ablation_{g}_net_per_day": d["net_per_day"]
                        for g, d in imp["ablation_delta_vs_full"].items()
                    }
                )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cv.json").write_text(
        json.dumps(
            {"dev_days": dev, "folds": [v for _, v in folds], "best": best, "all": results},
            indent=1,
            default=str,
        )
    )
    (OUT / "importance.json").write_text(json.dumps(imp, indent=1))
    for fam, b in sorted(best.items(), key=lambda kv: -kv[1]["net_per_day"]):
        log.info(
            "%-11s net/day %8.1f  trades %5d  hit %.2f  ic %.3f/%.3f  %s",
            fam,
            b["net_per_day"],
            b["trades"],
            b["hit_rate"],
            b["ic_ce"],
            b["ic_pe"],
            b["params"],
        )
    summary.update(
        trials=len(results), families=len(best), best_family=max(best, key=lambda f: best[f]["net_per_day"])
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("zoo_train", main))
