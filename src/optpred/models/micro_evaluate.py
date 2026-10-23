"""Stage 9b -- micro_evaluate: the one-time score of the v2 model (docs/V2_PROTOCOL.md, amendment 2).

  held-out days  the v1 test days (split "test"). No v2 choice used them. They were opened once for v1
                 (aggregate v1 results only), so every v2 number on them is labelled "second look".
  forward days   not used: the author decided to work only with the data already exported.

Same discipline as the v1 evaluate stage: --final is required, a second run is refused, the model is the
registry's `champion` of `nifty-option-micro`, scored through its pyfunc exactly as it would be served.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import mlflow
import pandas as pd
import yaml

from optpred.common import runlog
from optpred.features.micro import MICRO_COLUMNS
from optpred.models.micro_train import random_side_control, rule_baselines, score, simulate

log = logging.getLogger("optpred.models.micro_evaluate")


def score_split(df: pd.DataFrame, served: pd.DataFrame, slips: list[float], qty: int, b: dict) -> dict:
    days = sorted(df["day"].unique())
    actions = served["action"].to_numpy()
    out = {"days": days, "rows": len(df), "by_slippage": {}}
    for slip in slips:
        trades = simulate(df, actions, slip, qty)
        out["by_slippage"][str(slip)] = {
            "model": score(trades, days, b),
            "random_side_same_entries": random_side_control(df, trades, days, slip, qty, b),
            "baselines": rule_baselines(df, days, slip, qty, b),
        }
    return out


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--final", action="store_true", help="score the held-out days (once)")
    ap.add_argument("--out", default="reports/micro_final.json")
    args = ap.parse_args(argv)
    out_path = Path(args.out)
    if not args.final:
        log.error("refusing to score the held-out days without --final (docs/V2_PROTOCOL.md)")
        return 2
    if out_path.exists():
        log.error("%s exists: v2 was already scored once; a second look is not allowed", out_path)
        return 3
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, mt, b, m = params["micro"], params["micro_train"], params["baselines"], params["mlflow"]
    costs = params["costs"]

    df = pd.read_parquet(Path(p["out_dir"]) / "micro.parquet", filters=[("split", "==", "test")])
    held_out = df.sort_values(["day", "sec"]).reset_index(drop=True)
    if held_out.empty:
        log.error("no held-out (v1 test) days in the micro table")
        return 4

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"]))
    client = mlflow.MlflowClient()
    mv = client.get_model_version_by_alias(mt["registered_model"], "champion")
    model = mlflow.pyfunc.load_model(f"models:/{mt['registered_model']}@champion")
    slips = costs["sensitivity_pts_per_leg"]

    res = {
        "protocol": "docs/V2_PROTOCOL.md",
        "model": {"name": mt["registered_model"], "version": int(mv.version), "run_id": mv.run_id},
        "evaluated_at_commit": runlog._git("rev-parse", "HEAD"),
    }
    served = model.predict(held_out[MICRO_COLUMNS].astype(float))
    res["second_look_v1_test"] = score_split(held_out, served, slips, p["qty"], b)
    main_ = res["second_look_v1_test"]["by_slippage"][str(p["slippage_pts_per_leg"])]
    head = main_["model"]
    for k, v in main_.items():
        log.info("held-out %s: %s", k, v)
    res["pass_rule_3_held_out_positive"] = bool(head["mean_net_per_day_rs"] > 0 and head["trades"] > 0)

    mlflow.set_experiment(m["experiment"])
    with mlflow.start_run(run_name="micro-final-evaluation") as run:
        mlflow.set_tags(
            {
                "stage": "micro_evaluate",
                "git_commit": res["evaluated_at_commit"],
                "model": "v2",
                "champion_run_id": mv.run_id,
                "champion_version": mv.version,
                "held_out_days_read": "yes (v1 test days, second look)",
                "protocol": "docs/V2_PROTOCOL.md",
            }
        )
        mlflow.log_metrics(
            {"held_out_net_per_day_rs": head["mean_net_per_day_rs"], "held_out_trades": head["trades"]}
        )
        res["mlflow_run_id"] = run.info.run_id
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=1, default=float))
    summary.update(
        mlflow_run_id=run.info.run_id, held_out=head, pass_rule_3=res["pass_rule_3_held_out_positive"]
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("micro_evaluate", main))
