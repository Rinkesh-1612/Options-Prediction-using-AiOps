"""Stage zoo_eval: score every family's best setting on the TEST days and register the champion.

  * Each family: train its best setting (reports/zoo/cv.json) on all dev days, score the test days with the
    tau chosen in cross-validation. Nothing is chosen on test days.
  * Champion = the non-baseline family with the best cross-validation net rupees per day. It is chosen
    BEFORE the test numbers are read; the test numbers only report how it does.
  * MLflow: one run per family (test metrics, 95% bootstrap interval over days); the champion is logged
    as a pyfunc model and registered. It is deployed (alias "champion") only if its smoke test passes
    (optpred.zoo.promote); the old champion becomes "previous", the rollback target.

Note: the test days were looked at by the old (deprecated) models. No model here trains or tunes on them.
Outputs: reports/zoo/test.json, reports/zoo/comparison.md
Usage:   ./pipe python -m optpred.zoo.evaluate
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.zoo import tracking
from optpred.zoo.data import load_dataset, split_days
from optpred.zoo.models import make, predict
from optpred.zoo.promote import promote
from optpred.zoo.pyfunc import SignalModel
from optpred.zoo.sim import bootstrap_ci, information_coef, simulate, trades_one_day

log = logging.getLogger("optpred.zoo.evaluate")


def signature(features: list[str]):
    """Explicit model signature: every feature is an OPTIONAL double (live rows can have NaN).
    Inferred from a few example rows, MLflow would make some columns required float32 and reject them."""
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, Schema

    out = Schema([ColSpec("double", "score_ce"), ColSpec("double", "score_pe"), ColSpec("string", "action")])
    return ModelSignature(Schema([ColSpec("double", f, required=False) for f in features]), out)


OUT = Path("reports/zoo")
BASELINES = {"stay_out", "random", "momentum"}


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    z = params["zoo"]
    cv = json.loads((OUT / "cv.json").read_text())
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    dev, test, _ = split_days(accepted, z["n_test_days"], z["min_train_days"], z["val_days"])
    ds = load_dataset(accepted, Path(params["feat"]["out_dir"]), Path(params["labels"]["out_dir"]))
    test_sl = ds.day_slices(test)
    test_rows = ds.rows(test)

    candidates = {f: b for f, b in cv["best"].items() if f not in BASELINES}
    champion = max(candidates, key=lambda f: candidates[f]["net_per_day"])
    log.info("champion (chosen on cross-validation): %s", champion)

    tracking.setup(z["mlflow"])
    tags = tracking.version_tags() | {"stage": "zoo_eval", "test_days": f"{test[0]}..{test[-1]}"}
    results = {}
    for fam, b in cv["best"].items():
        p = {k: v for k, v in b["params"].items() if k != "n_jobs"} | {"n_jobs": z["cpus"]}
        model = make(fam, p, ds.features).fit(ds, ds.rows(dev))
        score = predict(model, ds, test_sl)
        tau = float(b["tau"])
        m = simulate(score, ds, test_sl, tau)
        per_day = np.array(
            [trades_one_day(score[s], ds.valid[s], ds.net[s], ds.hold[s], tau)[2].sum() for _, s in test_sl]
        )
        lo, hi = bootstrap_ci(per_day, z["bootstrap"], z["seed"])
        r = {
            **m,
            **information_coef(score, ds, test_rows),
            "ci95_net_per_day": [lo, hi],
            "per_day": per_day.round(1).tolist(),
            "cv_net_per_day": b["net_per_day"],
            "tau": tau,
            "champion": fam == champion,
        }
        results[fam] = r
        log.info(
            "%-11s test net/day %8.1f [%7.1f, %7.1f]  trades %4d  hit %.2f",
            fam,
            m["net_per_day"],
            lo,
            hi,
            m["trades"],
            m["hit_rate"],
        )
        with mlflow.start_run(
            run_name=f"eval {fam}", tags=tags | {"family": fam, "champion": str(fam == champion)}
        ):
            mlflow.log_params(b["params"])
            mlflow.log_metrics(
                {f"test_{k}": v for k, v in r.items() if isinstance(v, int | float) and np.isfinite(v)}
                | {"test_ci95_lo": lo, "test_ci95_hi": hi}
            )
            if fam == champion:
                with tempfile.TemporaryDirectory() as tmp:
                    pkl = Path(tmp) / "model.pkl"
                    pkl.write_bytes(pickle.dumps({"model": model, "features": ds.features, "tau": tau}))
                    info = mlflow.pyfunc.log_model(
                        "model",
                        python_model=SignalModel(),
                        artifacts={"model": str(pkl)},
                        code_paths=["src/optpred"],
                        registered_model_name=z["mlflow"]["registered_model"],
                        signature=signature(ds.features),
                    )
                sample = pd.DataFrame(ds.X[test_sl[0][1]], columns=ds.features)  # one full test day
                r["deployment"] = promote(
                    mlflow.MlflowClient(),
                    z["mlflow"]["registered_model"],
                    info.registered_model_version,
                    sample,
                )
                r["registered_version"] = info.registered_model_version

    lines = [
        "| Family | CV net ₹/day | Test net ₹/day | 95% CI | Trades | Hit rate | IC CE / PE |",
        "|---|---|---|---|---|---|---|",
    ]
    for fam, r in sorted(results.items(), key=lambda kv: -kv[1]["cv_net_per_day"]):
        star = " (champion)" if r["champion"] else ""
        lines.append(
            f"| {fam}{star} | {r['cv_net_per_day']:.0f} | {r['net_per_day']:.0f} | "
            f"{r['ci95_net_per_day'][0]:.0f} … {r['ci95_net_per_day'][1]:.0f} | {r['trades']} | "
            f"{r['hit_rate']:.2f} | {r['ic_ce']:.3f} / {r['ic_pe']:.3f} |"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison.md").write_text("\n".join(lines) + "\n")
    (OUT / "test.json").write_text(
        json.dumps({"test_days": test, "champion": champion, "results": results}, indent=1, default=str)
    )
    summary.update(champion=champion, champion_test_net_per_day=results[champion]["net_per_day"])
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("zoo_eval", main))
