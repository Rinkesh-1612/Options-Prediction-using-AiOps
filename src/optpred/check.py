"""Stage 2 -- check (Spark): data-quality rules per trading day.

Reads the raw snapshot, measures every day, and decides which days are fit to
train and test on. Nothing is silently dropped: every rejected day and every
removed row is counted in reports/quality.json.

Day rules (thresholds in params.yaml -> check):
  REJECT  tape covers < min_coverage of the 375 session minutes
          (holidays with frozen recordings, outages: 14-Sep, 25/28/29-Sep, 02-Oct)
  REJECT  spot (NIFTY index) covers < min_coverage of the session minutes
  REJECT  tape last-traded price never changes (a frozen feed)
  FLAG    chain covers < min_coverage, or its spot never changes
          (day kept; chain features are left empty for missing minutes)

Outputs:
  data/days.json         accepted days, rejected days with the reason
  reports/quality.json   per-day measurements and row-level removals
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import yaml
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from optpred import runlog
from optpred.spark_common import (
    SESSION_MINUTES,
    clean_index,
    clean_opt_tape,
    in_session,
    read_raw,
    spark_session,
)

log = logging.getLogger("optpred.check")


def _per_day(df: DataFrame, **aggs) -> dict[str, dict]:
    """Per-day aggregates. The "" entry lists the measurement names even when no day has rows."""
    rows = df.groupBy("day").agg(*[a.alias(k) for k, a in aggs.items()]).collect()
    return {"": dict.fromkeys(aggs, 0)} | {str(r["day"]): {k: r[k] for k in aggs} for r in rows}


def measure(spark, raw_dir: str) -> dict[str, dict]:
    """All per-day measurements, keyed by day then by measurement name."""
    tape = read_raw(spark, raw_dir, "opt_tape")
    und = read_raw(spark, raw_dir, "und_tape")
    chain = read_raw(spark, raw_dir, "option_chain_snap")
    tape_s = in_session(tape)

    parts = [
        _per_day(tape, tape_rows_raw=F.count("*")),
        _per_day(
            tape_s,
            tape_rows_session=F.count("*"),
            tape_minutes=F.countDistinct("minute"),
            tape_distinct_ltp=F.countDistinct("ltp"),
            tape_crossed=F.sum(
                ((F.col("bid1_price") >= F.col("ask1_price")) & (F.col("ask1_price") > 0)).cast("int")
            ),
            tape_one_sided=F.sum(((F.col("bid1_price") <= 0) | (F.col("ask1_price") <= 0)).cast("int")),
            tape_instruments=F.countDistinct("instrument_key"),
            tape_expiries=F.countDistinct("expiry"),
        ),
        _per_day(
            tape_s.groupBy("day", "instrument_key", "ts_ns").count().where("count > 1"),
            tape_duplicate_keys=F.count("*"),
        ),
        _per_day(clean_opt_tape(tape), tape_rows_clean=F.count("*")),
        _per_day(
            clean_index(und),
            spot_ticks=F.count("*"),
            spot_minutes=F.countDistinct("minute"),
            spot_distinct=F.countDistinct("ltp"),
        ),
        _per_day(
            in_session(chain),
            chain_rows=F.count("*"),
            chain_minutes=F.countDistinct("minute"),
            chain_distinct_spot=F.countDistinct("spot"),
        ),
    ]
    # A day absent from a part had zero matching rows: record 0, never a missing key.
    names = {k for part in parts for m in part.values() for k in m}
    days = {d: dict.fromkeys(names, 0) for part in parts for d in part if d}
    for part in parts:
        for d, m in part.items():
            if d:
                days[d].update({k: (v or 0) for k, v in m.items()})
    return dict(sorted(days.items()))


def decide(m: dict, min_coverage: float) -> tuple[str, list[str]]:
    """Return ("accept" | "reject", reasons) for one day's measurements."""
    need = min_coverage * SESSION_MINUTES
    reasons, flags = [], []
    if m.get("tape_minutes", 0) < need:
        reasons.append(f"tape covers {m.get('tape_minutes', 0)}/{SESSION_MINUTES} minutes")
    if m.get("spot_minutes", 0) < need:
        reasons.append(f"spot covers {m.get('spot_minutes', 0)}/{SESSION_MINUTES} minutes")
    if 0 < m.get("tape_distinct_ltp", 0) <= 1:  # 0 means no in-session rows: already reported above
        reasons.append("tape prices never change (frozen feed)")
    if m.get("chain_minutes", 0) < need:
        flags.append(f"chain partial: {m.get('chain_minutes', 0)}/{SESSION_MINUTES} minutes")
    elif m.get("chain_distinct_spot", 0) <= 1:
        flags.append("chain spot never changes (frozen recording)")
    return ("reject" if reasons else "accept"), reasons + flags


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, raw_dir = params["check"], params["export"]["out_dir"]

    spark = spark_session("optpred-check", params["spark"])
    t0 = time.monotonic()
    days = measure(spark, raw_dir)
    elapsed = time.monotonic() - t0
    spark.stop()

    accepted, rejected = [], {}
    for d, m in days.items():
        verdict, reasons = decide(m, p["min_coverage"])
        m["verdict"], m["reasons"] = verdict, reasons
        if verdict == "accept":
            accepted.append(d)
        else:
            rejected[d] = reasons
        log.info("%s %-6s %s", d, verdict, "; ".join(reasons))

    raw_rows = sum(m.get("tape_rows_raw", 0) for m in days.values())
    Path("data").mkdir(exist_ok=True)
    Path("reports").mkdir(exist_ok=True)
    Path("data/days.json").write_text(json.dumps({"accepted": accepted, "rejected": rejected}, indent=1))
    Path("reports/quality.json").write_text(json.dumps(days, indent=1, default=str))

    summary.update(
        days_seen=len(days),
        days_accepted=len(accepted),
        days_rejected=len(rejected),
        tape_rows_raw=raw_rows,
        tape_rows_clean=sum(m.get("tape_rows_clean", 0) for m in days.values()),
        seconds=round(elapsed, 1),
        rows_per_s=round(raw_rows / elapsed) if elapsed else None,
    )
    log.info("accepted %d / %d days; %.0f tape rows/s", len(accepted), len(days), summary["rows_per_s"] or 0)
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("check", main))
