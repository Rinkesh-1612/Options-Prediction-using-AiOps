"""Stage modelout: the output of every model at every minute of every recorded day.

The web page cannot run the deep models live, so this stage runs them once and stores the answers.
Each answer carries a `source` so that the page can say how fair it is:

  * oof    - the model never saw this day: walk-forward fold, trained only on earlier days.
  * test   - one of the unseen test days: trained on all dev days. Nothing is tuned on it.
  * train  - the first days: the model of the first fold saw them (in-sample, shown with a warning).

Direction models use the best setting of reports/zoo/cv.json. Volatility forecasters use params.yaml `vol`.
Outputs: data/modelout/direction/<day>.parquet (family, score_ce, score_pe, tau, source),
         data/modelout/vol/<day>.parquet (family, fc_300, fc_900, source), reports/modelout.json
Usage:   ./pipe python -m optpred.modelout.stage
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
from optpred.common.parallel import map_days
from optpred.vol.inputs import HORIZONS, inputs, targets
from optpred.vol.models import make as make_vol
from optpred.zoo.data import load_dataset, split_days
from optpred.zoo.models import make, predict

log = logging.getLogger("optpred.modelout")
OUT = Path("data/modelout")
FIRST_SOD = 33300  # 09:15:00; row i of a day is second 33300 + i


def sources(dev: list[str], test: list[str], folds) -> dict[str, tuple[str, list[str]]]:
    """Day -> (source, days the model that predicts it is trained on)."""
    out = {d: ("train", folds[0][0]) for d in folds[0][0]}
    for tr, va in folds:
        out |= {d: ("oof", tr) for d in va}
    out |= {d: ("train", dev) for d in dev if d not in out}  # days after the last fold (none by default)
    return out | {d: ("test", dev) for d in test}


def groups(plan: dict[str, tuple[str, list[str]]]) -> list[tuple[list[str], list[str], str]]:
    """Models to fit: (training days, days to predict, source), one per distinct training set and source."""
    g: dict[tuple, list[str]] = {}
    for d, (src, tr) in plan.items():
        g.setdefault((tuple(tr), src), []).append(d)
    return [(list(tr), days, src) for (tr, src), days in g.items()]


def direction(accepted, params, cv, plan) -> dict[str, list[pd.DataFrame]]:
    ds = load_dataset(accepted, Path(params["feat"]["out_dir"]), Path(params["labels"]["out_dir"]))
    z = params["zoo"]
    out: dict[str, list[pd.DataFrame]] = {d: [] for d in accepted}
    for fam, b in cv["best"].items():
        p = {k: v for k, v in b["params"].items() if k != "n_jobs"} | {"n_jobs": z["cpus"]}
        for tr, days, src in groups(plan):
            model = make(fam, p, ds.features).fit(ds, ds.rows(tr))
            sl = ds.day_slices(days)
            score = predict(model, ds, sl)
            for d, s in sl:
                sc = score[s]
                sod = FIRST_SOD + np.arange(len(sc))
                keep = sod % 60 == 0
                out[d].append(
                    pd.DataFrame(
                        {
                            "day": d,
                            "sod": sod[keep],
                            "family": fam,
                            "score_ce": sc[keep, 0].astype("float32"),
                            "score_pe": sc[keep, 1].astype("float32"),
                            "tau": float(b["tau"]),
                            "source": src,
                        }
                    )
                )
        log.info("direction %-11s done", fam)
    return out


def vol_day(day: str, grid_dir: str, feat_dir: str) -> pd.DataFrame:
    g = pd.read_parquet(Path(grid_dir) / f"{day}.parquet").sort_values("sod").reset_index(drop=True)
    f = pd.read_parquet(Path(feat_dir) / f"{day}.parquet").sort_values("sod").reset_index(drop=True)
    d = pd.concat([g[["sod"]], inputs(g), targets(g), f.drop(columns=["day", "sod", "atm"])], axis=1)
    return d.assign(day=day)


def volatility(accepted, params, plan) -> dict[str, list[pd.DataFrame]]:
    v = params["vol"]
    D = pd.concat(
        map_days(
            lambda d: vol_day(d, params["grid"]["out_dir"], params["feat"]["out_dir"]),
            accepted,
            params["eda"]["workers"],
        ),
        ignore_index=True,
    )
    ycols = [f"rv_fwd_{h}" for h in HORIZONS]
    X, Y = D.drop(columns=ycols + ["day", "sod"]), D[ycols]
    out: dict[str, list[pd.DataFrame]] = {d: [] for d in accepted}
    for name, p in v["models"].items():
        for tr, days, src in groups(plan):
            fit_m = D["day"].isin(tr) & (D["sod"] >= v["first_s"]) & (D["sod"] % v["stride_s"] == 0)
            model = make_vol(name, p).fit(X[fit_m], Y[fit_m])
            pr_m = D["day"].isin(days) & (D["sod"] % 60 == 0)
            fc = model.predict(X[pr_m]).astype("float32")
            part = pd.concat([D.loc[pr_m, ["day", "sod"]], fc], axis=1).assign(family=name, source=src)
            for d, q in part.groupby("day"):
                out[d].append(q.reset_index(drop=True))
        log.info("volatility %-8s done", name)
    return out


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    z = params["zoo"]
    cv = json.loads(Path("reports/zoo/cv.json").read_text())
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    dev, test, folds = split_days(accepted, z["n_test_days"], z["min_train_days"], z["val_days"])
    plan = sources(dev, test, folds)
    d_out, v_out = direction(accepted, params, cv, plan), volatility(accepted, params, plan)
    for sub, res in (("direction", d_out), ("vol", v_out)):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
        for d, parts in res.items():
            pd.concat(parts, ignore_index=True).to_parquet(OUT / sub / f"{d}.parquet", index=False)
    counts = pd.Series([s for s, _ in plan.values()]).value_counts().to_dict()
    Path("reports/modelout.json").write_text(
        json.dumps(
            {
                "days": len(accepted),
                "days_by_source": counts,
                "direction_families": list(cv["best"]),
                "vol_families": list(params["vol"]["models"]),
                "source": {d: s for d, (s, _) in plan.items()},
            },
            indent=1,
        )
    )
    summary.update(days=len(accepted), **{f"days_{k}": int(v) for k, v in counts.items()})
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("modelout", main))
