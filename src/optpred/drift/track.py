"""Stage drift: drift over time. PSI of every accepted day against the dev (training) days.

Outputs:
  reports/drift/reference.json   bin edges + shares per feature (the API loads this for online drift)
  reports/drift/daily.json       per day: PSI per feature, share of features above the limit, drift flag
  reports/drift/daily.png        share of drifting features per day (dev vs test days)
  MLflow (experiment nifty-zoo, run "drift"): drift share per day as a metric series.

Per-feature limits: see optpred.drift.psi.
Usage:  ./pipe python -m optpred.drift.track
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402

from optpred.common import runlog  # noqa: E402
from optpred.drift.psi import psi_all, reference  # noqa: E402
from optpred.zoo import tracking  # noqa: E402
from optpred.zoo.data import feature_groups, load_dataset, split_days  # noqa: E402

log = logging.getLogger("optpred.drift.track")
OUT = Path("reports/drift")


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    z, d = params["zoo"], params["drift"]
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    dev, test, _ = split_days(accepted, z["n_test_days"], z["min_train_days"], z["val_days"])
    ds = load_dataset(accepted, Path(params["feat"]["out_dir"]), Path(params["labels"]["out_dir"]))

    # Schedule features (clock, DTE) are the calendar, not market data: never monitored for drift.
    skip = set(feature_groups(ds.features).get("time", []))
    cols = [j for j, f in enumerate(ds.features) if f not in skip]
    feats = [ds.features[j] for j in cols]
    X = ds.X[:, cols]
    dev_rows = ds.rows(dev)
    ref = reference(X[dev_rows], feats, d["n_bins"])
    psi_day = {day: psi_all(X[sl], feats, ref) for day, sl in ds.day_slices(accepted)}

    def q95(values):
        return {f: max(d["psi_limit"], float(np.quantile([v[f] for v in values], 0.95))) for f in feats}

    # Limits = normal variation on dev days: whole days (this stage) and windows of the online size (API).
    limits = q95([psi_day[x] for x in dev])
    rng = np.random.default_rng(d["seed"])
    starts = rng.choice(dev_rows[: -d["window"]], size=d["n_windows"], replace=False)
    win_limits = q95([psi_all(X[s : s + d["window"]], feats, ref) for s in starts])
    daily = {}
    for day, p in psi_day.items():
        share = float(np.mean([v > limits[f] for f, v in p.items()]))
        daily[day] = {
            "split": "test" if day in test else "dev",
            "share": round(share, 4),
            "drift": share > d["share_limit"],
            "psi": {k: round(v, 4) for k, v in p.items()},
        }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reference.json").write_text(
        json.dumps({"features": feats, "ref": ref, "limits": win_limits, "day_limits": limits, **d})
    )
    (OUT / "daily.json").write_text(json.dumps(daily, indent=1))
    days = list(daily)
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.bar(
        days,
        [daily[x]["share"] for x in days],
        color=["#C44E52" if daily[x]["split"] == "test" else "#4C72B0" for x in days],
    )
    ax.axhline(d["share_limit"], ls="--", c="grey")
    ax.set_ylabel("share of features above their limit")
    ax.set_title("Drift per day vs the training (dev) days (red = test days)")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "daily.png", dpi=110)
    plt.close(fig)

    tracking.setup(z["mlflow"])
    with mlflow.start_run(run_name="drift", tags=tracking.version_tags() | {"stage": "drift"}):
        for i, x in enumerate(days):
            mlflow.log_metric("drift_share", daily[x]["share"], step=i)
        mlflow.log_artifact(str(OUT / "daily.png"))
    drifting = [x for x in days if daily[x]["drift"]]
    log.info("%d of %d days drift (share > %.2f): %s", len(drifting), len(days), d["share_limit"], drifting)
    summary.update(days=len(days), drift_days=len(drifting))
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("drift", main))
