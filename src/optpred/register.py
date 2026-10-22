"""Stage 8 -- register: decide which model version the registry serves.

The train stage logs a new model version to the MLflow registry and writes reports/train.json.
This stage reads that file and moves the registry aliases:
  * `candidate` always points at the newest version, so it can be inspected.
  * `champion` (what the model server loads) moves to it only if its validation result is strictly
    better than the current champion's. The first version ever becomes champion.
  * `previous` keeps the old champion. Rolling back = swapping `champion` and `previous`.

Validation is the only data used to decide. The locked test days are never read here.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import mlflow
import numpy as np
import yaml
from mlflow import MlflowClient

from optpred import runlog

log = logging.getLogger("optpred.register")


def register(client: MlflowClient, name: str, run_id: str, val_net_per_day: float) -> dict:
    """Point `candidate` at the run's model version; promote it to `champion` only if better on val."""
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
    return {
        "version": int(mv.version),
        "promoted": promoted,
        "champion_version": int(mv.version) if promoted else int(champ.version),
        "previous_champion_val_net_per_day_rs": champ_val,
    }


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--train-report", default="reports/train.json")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        m = yaml.safe_load(f)["mlflow"]
    report = Path(args.train_report)
    if not report.exists():
        log.error("%s is missing: run the train stage first", report)
        return 2
    trained = json.loads(report.read_text())
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"]))
    reg = register(
        MlflowClient(),
        m["registered_model"],
        trained["mlflow_run_id"],
        trained["val_net_per_day_rs_selected"],
    )
    log.info(
        "version %d registered as candidate; promoted to champion: %s (champion is now v%d)",
        reg["version"],
        reg["promoted"],
        reg["champion_version"],
    )
    Path("reports/register.json").write_text(
        json.dumps({"mlflow_run_id": trained["mlflow_run_id"], **reg}, indent=1)
    )
    summary.update(**reg)
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("register", main))
