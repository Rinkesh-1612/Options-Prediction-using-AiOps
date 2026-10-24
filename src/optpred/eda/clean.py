"""Stage clean: data/raw -> data/clean, one accepted day at a time, with every rule counted.

Rules: optpred.eda.rules. Thresholds: params.yaml -> eda.
Outputs:
  data/clean/<table>/<day>.parquet   same columns as raw, plus `sod` (seconds since IST midnight)
  reports/eda/cleaning.json          per day, per table: rows in/out and the count of each rule

Usage:  ./pipe python -m optpred.eda.clean
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from functools import partial
from pathlib import Path

import pandas as pd
import yaml

from optpred.common import runlog
from optpred.common.parallel import map_days
from optpred.eda import rules

log = logging.getLogger("optpred.eda.clean")
TABLES = ("opt_tape", "und_tape", "option_chain_snap")


def clean_day(day: str, raw: Path, out: Path, p: dict) -> dict:
    """Clean the three tables of one day and write them. Returns the rule counts."""
    und, c_und = rules.clean_und_tape(pd.read_parquet(raw / "und_tape" / f"{day}.parquet"), p)
    opt, c_opt = rules.clean_opt_tape(pd.read_parquet(raw / "opt_tape" / f"{day}.parquet"), p)
    index = und[und["kind"] == "INDEX"]
    chain, c_chain = rules.clean_chain(
        pd.read_parquet(raw / "option_chain_snap" / f"{day}.parquet"), index, p
    )
    for table, df in (("opt_tape", opt), ("und_tape", und), ("option_chain_snap", chain)):
        (out / table).mkdir(parents=True, exist_ok=True)
        df.to_parquet(out / table / f"{day}.parquet", index=False)
    return {"opt_tape": c_opt, "und_tape": c_und, "option_chain_snap": c_chain}


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p = params["eda"]
    raw, out = Path(params["export"]["out_dir"]), Path(p["clean_dir"])
    days = json.loads(Path("data/days.json").read_text())["accepted"]

    results = dict(
        zip(days, map_days(partial(clean_day, raw=raw, out=out, p=p), days, p["workers"]), strict=True)
    )

    totals = {t: {} for t in TABLES}
    for day, per_table in results.items():
        for t, counts in per_table.items():
            for k, v in counts.items():
                totals[t][k] = totals[t].get(k, 0) + v
        log.info(
            "%s  opt %d -> %d rows", day, per_table["opt_tape"]["rows_in"], per_table["opt_tape"]["rows_out"]
        )
    for t in TABLES:
        log.info("%s: %s", t, totals[t])

    Path("reports/eda").mkdir(parents=True, exist_ok=True)
    Path("reports/eda/cleaning.json").write_text(json.dumps({"total": totals, "days": results}, indent=1))
    summary.update(days=len(days), **{f"{t}_rows_out": totals[t]["rows_out"] for t in TABLES})
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("clean", main))
