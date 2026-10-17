"""Stage 3 -- bars (Spark): ~85M option ticks -> one row per instrument per minute.

This is the heavy data-engineering step. Each output row is the market AS IT
STOOD AT THE END of that minute (the last clean tick inside the minute), plus
how many ticks the minute had and how old that last tick was.

Outputs (Parquet, partitioned by day, accepted days only):
  data/bars/opt     day, minute, instrument_key, expiry, strike, side, last book (5 levels),
                    ltp, cumulative volume, oi, ticks, last_sod
  data/bars/spot    day, minute, NIFTY index open/high/low/close, ticks, last_sod
  data/bars/chain   day, minute, expiry, strike, spot, ce/pe iv, delta, oi (last snapshot of the minute)

Instruments are keyed by instrument_key, never by strike: one strike carries
two expiries.
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
from optpred.spark_common import clean_index, clean_opt_tape, in_session, read_raw, spark_session

log = logging.getLogger("optpred.bars")

BOOK_COLS = [f"{s}{i}_{k}" for s in ("bid", "ask") for i in range(1, 6) for k in ("price", "qty")]
OPT_LAST = BOOK_COLS + ["ltp", "volume", "oi", "total_buy_qty", "total_sell_qty", "sod"]


def last_of_minute(df: DataFrame, keys: list[str], cols: list[str]) -> DataFrame:
    """For each (keys, minute) take every column from the latest tick (max ts_ns)."""
    aggs = [F.max_by(c, "ts_ns").alias(c) for c in cols] + [F.count("*").alias("ticks")]
    return df.groupBy(*keys).agg(*aggs).withColumnRenamed("sod", "last_sod")


def opt_bars(tape: DataFrame) -> DataFrame:
    return last_of_minute(
        clean_opt_tape(tape), ["day", "minute", "instrument_key", "expiry", "strike", "side"], OPT_LAST
    )


def spot_bars(und: DataFrame) -> DataFrame:
    idx = clean_index(und)
    return idx.groupBy("day", "minute").agg(
        F.min_by("ltp", "ts_ns").alias("open"),
        F.max("ltp").alias("high"),
        F.min("ltp").alias("low"),
        F.max_by("ltp", "ts_ns").alias("close"),
        F.count("*").alias("ticks"),
        F.max("sod").alias("last_sod"),
    )


def chain_bars(chain: DataFrame) -> DataFrame:
    """Rows of the last chain snapshot inside each minute, per expiry."""
    c = in_session(chain)
    last_ts = c.groupBy("day", "minute", "expiry").agg(F.max("ts_ns").alias("ts_ns"))
    cols = ["spot", "ce_iv", "pe_iv", "ce_delta", "pe_delta", "ce_oi", "pe_oi", "ce_volume", "pe_volume"]
    return c.join(last_ts, ["day", "minute", "expiry", "ts_ns"]).select(
        "day", "minute", "expiry", "expiry_rank", "strike", *cols
    )


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    raw_dir, out = params["export"]["out_dir"], params["bars"]["out_dir"]
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    if not accepted:
        log.error("no accepted days in data/days.json -- run the check stage first")
        return 1

    spark = spark_session("optpred-bars", params["spark"])
    keep = F.col("day").isin(accepted)
    tape = read_raw(spark, raw_dir, "opt_tape").where(keep)
    und = read_raw(spark, raw_dir, "und_tape").where(keep)
    chain = read_raw(spark, raw_dir, "option_chain_snap").where(keep)

    t0 = time.monotonic()
    counts = {}
    for name, df in (("opt", opt_bars(tape)), ("spot", spot_bars(und)), ("chain", chain_bars(chain))):
        df.write.mode("overwrite").partitionBy("day").parquet(f"{out}/{name}")
        counts[name] = spark.read.parquet(f"{out}/{name}").count()
        log.info("wrote %-5s bars: %d rows", name, counts[name])
    elapsed = time.monotonic() - t0
    tape_rows = tape.count()
    spark.stop()

    summary.update(
        days=len(accepted),
        tape_rows_in=tape_rows,
        bars_out=counts,
        seconds=round(elapsed, 1),
        tape_rows_per_s=round(tape_rows / elapsed),
    )
    log.info("%d tape rows in %.0fs = %.0f rows/s", tape_rows, elapsed, summary["tape_rows_per_s"])
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("bars", main))
