"""Stage 9b -- micro_evaluate: the one-time score of the v2 model (docs/V2_PROTOCOL.md sections 3 and 7).

  clean test     the forward days (split "forward"): recorded after v1 was frozen, never seen by anyone
  second look    the v1 test days (split "test"): already opened for v1, so reported apart and never used
                 to choose anything

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

from optpred import runlog
from optpred.micro import MICRO_COLUMNS
from optpred.micro_train import random_side_control, rule_baselines, score, simulate

log = logging.getLogger("optpred.micro_evaluate")


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
    ap.add_argument("--final", action="store_true", help="open the forward days (once)")
    ap.add_argument("--out", default="reports/micro_final.json")
    args = ap.parse_args(argv)
    out_path = Path(args.out)
    if not args.final:
        log.error("refusing to score the forward days without --final (docs/V2_PROTOCOL.md)")
        return 2
    if out_path.exists():
        log.error("%s exists: v2 was already scored once; a second look is not allowed", out_path)
        return 3
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, mt, b, m = params["micro"], params["micro_train"], params["baselines"], params["mlflow"]
    costs = params["costs"]

    df = pd.read_parquet(Path(p["out_dir"]) / "micro.parquet", filters=[("split", "in", ["forward", "test"])])
    df = df.sort_values(["day", "sec"]).reset_index(drop=True)
    forward = df[df["split"] == "forward"].reset_index(drop=True)
    if forward.empty:
        log.error("no forward days in the micro table: export and process them first")
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
    for name, part in (
        ("clean_forward", forward),
        ("second_look_v1_test", df[df["split"] == "test"].reset_index(drop=True)),
    ):
        if part.empty:
            continue
        served = model.predict(part[MICRO_COLUMNS].astype(float))
        res[name] = score_split(part, served, slips, p["qty"], b)
        head = res[name]["by_slippage"][str(p["slippage_pts_per_leg"])]["model"]
        log.info("%s: %d days, model %s", name, len(res[name]["days"]), head)
    head = res["clean_forward"]["by_slippage"][str(p["slippage_pts_per_leg"])]["model"]
    res["pass_rule_3_forward_days_positive"] = bool(head["mean_net_per_day_rs"] > 0 and head["trades"] > 0)

    mlflow.set_experiment(m["experiment"])
    with mlflow.start_run(run_name="micro-final-evaluation") as run:
        mlflow.set_tags(
            {
                "stage": "micro_evaluate",
                "git_commit": res["evaluated_at_commit"],
                "model": "v2",
                "champion_run_id": mv.run_id,
                "champion_version": mv.version,
                "forward_days_read": "yes",
                "protocol": "docs/V2_PROTOCOL.md",
            }
        )
        mlflow.log_metrics(
            {"forward_net_per_day_rs": head["mean_net_per_day_rs"], "forward_trades": head["trades"]}
        )
        res["mlflow_run_id"] = run.info.run_id
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=1, default=float))
    summary.update(
        mlflow_run_id=run.info.run_id, forward=head, pass_rule_3=res["pass_rule_3_forward_days_positive"]
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("micro_evaluate", main))
