"""Stage vol: forecast the NIFTY move over the next 5 and 15 min; compare with the option market's forecast.

  * Rows: one every `stride_s` seconds from 09:20, while the target window ends before the close.
  * Forecasters (optpred.vol.models): implied (the option market's IV, scale fitted) = the baseline,
    har (past moves), har_iv (past moves + IV).
  * Walk-forward CV on the dev days (same folds as the zoo). Champion = lowest CV QLIKE at the main horizon.
  * Test days: every forecaster trained on all dev days. Success rule (fixed before any test result):
    the champion's daily QLIKE is lower than the implied forecast's, and the 95% bootstrap interval of the
    daily difference is below zero.
  * MLflow: experiment nifty-vol (one run per forecaster); the champion is registered as `nifty-vol` and gets
    the alias `champion` only after a smoke test (load from the registry, predict one test day).

Outputs: reports/vol/cv.json, reports/vol/test.json, reports/vol/comparison.md, reports/vol/test_scatter.png
Usage:   ./pipe python -m optpred.vol.stage
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from optpred.common import runlog  # noqa: E402
from optpred.common.parallel import map_days  # noqa: E402
from optpred.vol.inputs import HORIZONS, inputs, targets  # noqa: E402
from optpred.vol.models import make, qlike  # noqa: E402
from optpred.vol.pyfunc import VolModel  # noqa: E402
from optpred.zoo import tracking  # noqa: E402
from optpred.zoo.data import split_days  # noqa: E402

log = logging.getLogger("optpred.vol.stage")
OUT = Path("reports/vol")


def day_rows(day: str, grid_dir: str, stride: int, first_s: int) -> pd.DataFrame:
    g = pd.read_parquet(Path(grid_dir) / f"{day}.parquet").sort_values("sod").reset_index(drop=True)
    d = pd.concat([g[["sod"]], inputs(g), targets(g)], axis=1).assign(day=day)
    keep = (
        (d["sod"] >= first_s)
        & (d["sod"] % stride == 0)
        & d[[f"rv_fwd_{h}" for h in HORIZONS]].notna().all(axis=1)
    )
    return d[keep].reset_index(drop=True)


def metrics(df: pd.DataFrame, fc: pd.DataFrame) -> dict:
    out = {}
    for h in HORIZONS:
        y, p = df[f"rv_fwd_{h}"].to_numpy(), fc[f"fc_{h}"].to_numpy()
        ok = (y > 0) & (p > 0)
        ly, lp = np.log(y[ok]), np.log(p[ok])
        out[h] = {
            "qlike": qlike(y, p),
            "r2_log": float(1 - np.mean((ly - lp) ** 2) / np.var(ly)),
            "corr_log": float(np.corrcoef(ly, lp)[0, 1]),
            "qlike_by_day": {
                d: qlike(df.loc[m, f"rv_fwd_{h}"], fc.loc[m, f"fc_{h}"])
                for d, m in df.groupby("day").groups.items()
            },
        }
    return out


def scatter(df: pd.DataFrame, fc: pd.DataFrame, implied: pd.DataFrame, h: int, path: Path) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(10, 4.2), sharex=True, sharey=True)
    for a, (name, p) in zip(ax, (("champion", fc), ("implied (IV)", implied)), strict=True):
        a.scatter(p[f"fc_{h}"], df[f"rv_fwd_{h}"], s=3, alpha=0.25)
        lim = [1, float(df[f"rv_fwd_{h}"].quantile(0.995))]
        a.plot(lim, lim, c="grey", lw=1)
        a.set(
            xscale="log",
            yscale="log",
            title=f"{name}: forecast vs realized, next {h // 60} min (test)",
            xlabel="forecast move (bp)",
            ylabel="realized move (bp)",
        )
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    v, z = params["vol"], params["zoo"]
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    dev, test, folds = split_days(accepted, z["n_test_days"], z["min_train_days"], z["val_days"])
    rows = map_days(
        lambda d: day_rows(d, params["grid"]["out_dir"], v["stride_s"], v["first_s"]),
        accepted,
        params["eda"]["workers"],
    )
    D = pd.concat(rows, ignore_index=True)
    ycols = [f"rv_fwd_{h}" for h in HORIZONS]
    X, Y = D.drop(columns=ycols + ["day", "sod"]), D[ycols]
    main_h = v["main_horizon_s"]

    cv, oof_all = {}, {}
    for name, p in v["models"].items():
        oof = pd.DataFrame(index=D.index, columns=[f"fc_{h}" for h in HORIZONS], dtype=float)
        for tr_days, va_days in folds:
            tr, va = D["day"].isin(tr_days), D["day"].isin(va_days)
            oof.loc[va] = make(name, p).fit(X[tr], Y[tr]).predict(X[va]).to_numpy()
        va_all = D["day"].isin([d for _, vd in folds for d in vd])
        cv[name] = metrics(D[va_all], oof[va_all])
        oof_all[name] = oof
        log.info(
            "CV %-8s " + "  ".join(f"{h // 60}min qlike %.4f corr %.3f" for h in HORIZONS),
            name,
            *[x for h in HORIZONS for x in (cv[name][h]["qlike"], cv[name][h]["corr_log"])],
        )
    champion = min(cv, key=lambda n: cv[n][main_h]["qlike"])
    log.info("champion (CV QLIKE, %d min): %s", main_h // 60, champion)

    dev_m, test_m = D["day"].isin(dev), D["day"].isin(test)
    fitted, test_res, test_fc = {}, {}, {}
    for name, p in v["models"].items():
        fitted[name] = make(name, p).fit(X[dev_m], Y[dev_m])
        test_fc[name] = fitted[name].predict(X[test_m])
        test_res[name] = metrics(D[test_m], test_fc[name])
    rng = np.random.default_rng(v["seed"])
    verdict = {}
    for h in HORIZONS:
        diff = np.array(
            [
                test_res[champion][h]["qlike_by_day"][d] - test_res["implied"][h]["qlike_by_day"][d]
                for d in test
            ]
        )
        boot = rng.choice(diff, (v["bootstrap"], len(diff))).mean(axis=1)
        lo, hi = float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))
        verdict[h] = {
            "mean_daily_qlike_diff": float(diff.mean()),
            "ci95": [lo, hi],
            "days_better": int((diff < 0).sum()),
            "beats_implied": bool(hi < 0),
        }
        log.info(
            "test %d min: champion - implied daily QLIKE %.4f [%.4f, %.4f], better on %d/%d days -> %s",
            h // 60,
            diff.mean(),
            lo,
            hi,
            (diff < 0).sum(),
            len(diff),
            "PASS" if hi < 0 else "FAIL",
        )

    OUT.mkdir(parents=True, exist_ok=True)
    scatter(D[test_m], test_fc[champion], test_fc["implied"], main_h, OUT / "test_scatter.png")
    head = [
        "Forecaster",
        "CV QLIKE 15m",
        "CV corr 15m",
        "Test QLIKE 15m",
        "Test corr 15m",
        "Test QLIKE 5m",
        "Test corr 5m",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for n in sorted(cv, key=lambda n: cv[n][main_h]["qlike"]):
        cells = [
            f"{n} (champion)" if n == champion else n,
            f"{cv[n][900]['qlike']:.4f}",
            f"{cv[n][900]['corr_log']:.3f}",
        ]
        cells += [
            f"{test_res[n][h][k]:.4f}" if k == "qlike" else f"{test_res[n][h][k]:.3f}"
            for h in (900, 300)
            for k in ("qlike", "corr_log")
        ]
        lines.append("| " + " | ".join(cells) + " |")
    (OUT / "comparison.md").write_text("\n".join(lines) + "\n")

    def strip(m):
        return {h: {k: x for k, x in r.items() if k != "qlike_by_day"} for h, r in m.items()}

    (OUT / "cv.json").write_text(
        json.dumps(
            {
                "dev_days": dev,
                "folds": len(folds),
                "rows": int(len(D)),
                "results": {n: strip(m) for n, m in cv.items()},
            },
            indent=1,
        )
    )
    test_out = {
        "test_days": test,
        "champion": champion,
        "main_horizon_s": main_h,
        "verdict": verdict,
        "results": {n: strip(m) for n, m in test_res.items()},
        "qlike_by_day": {n: {h: m[h]["qlike_by_day"] for h in HORIZONS} for n, m in test_res.items()},
    }

    tracking.setup(v["mlflow"])
    tags = tracking.version_tags(("data/grid",)) | {"stage": "vol"}
    reg = v["mlflow"]["registered_model"]
    for name in v["models"]:
        with mlflow.start_run(
            run_name=f"vol {name}", tags=tags | {"family": name, "champion": str(name == champion)}
        ):
            mlflow.log_params({"family": name, **v["models"][name]})
            for h in HORIZONS:
                for k in ("qlike", "r2_log", "corr_log"):
                    mlflow.log_metric(f"cv_{k}_{h}", cv[name][h][k])
                    mlflow.log_metric(f"test_{k}_{h}", test_res[name][h][k])
            if name == champion:
                sample = X[test_m & D["day"].eq(test[0])]
                with tempfile.TemporaryDirectory() as tmp:
                    pkl = Path(tmp) / "model.pkl"
                    pkl.write_bytes(pickle.dumps({"model": fitted[name]}))
                    info = mlflow.pyfunc.log_model(
                        "model",
                        python_model=VolModel(),
                        artifacts={"model": str(pkl)},
                        code_paths=["src/optpred"],
                        registered_model_name=reg,
                        input_example=sample.head(3),
                    )
                test_out["deployment"] = deploy(reg, info.registered_model_version, sample)
    (OUT / "test.json").write_text(json.dumps(test_out, indent=1))
    summary.update(
        champion=champion,
        test_pass_15min=verdict[900]["beats_implied"],
        test_pass_5min=verdict[300]["beats_implied"],
    )
    return 0


def deploy(name: str, version: str, sample: pd.DataFrame) -> dict:
    """Smoke test (load from the registry, predict) -> aliases champion / previous."""
    c = mlflow.MlflowClient()
    try:
        out = mlflow.pyfunc.load_model(f"models:/{name}/{version}").predict(sample)
        assert len(out) == len(sample) and np.isfinite(out.to_numpy()).all() and (out.to_numpy() > 0).all()
    except Exception as e:  # noqa: BLE001 -- any failure blocks the deployment
        c.set_model_version_tag(name, version, "deploy_check", "failed")
        log.error("vol model v%s NOT deployed: %r", version, e)
        return {"deployed": False, "version": version, "reason": repr(e)[:300]}
    c.set_model_version_tag(name, version, "deploy_check", "passed")
    try:
        old = c.get_model_version_by_alias(name, "champion").version
    except mlflow.exceptions.MlflowException:
        old = None
    if old and old != version:
        c.set_registered_model_alias(name, "previous", old)
    c.set_registered_model_alias(name, "champion", version)
    return {"deployed": True, "version": version, "previous": old}


if __name__ == "__main__":
    sys.exit(runlog.run("vol", main))
