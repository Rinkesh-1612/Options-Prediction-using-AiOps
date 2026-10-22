"""Stage 3b -- ticks (Spark): raw ticks -> one row per instrument per SECOND, with order-flow measures.

This is the v2 data-engineering step (docs/V2_PROTOCOL.md). Each output row is the market as it stood
at the END of that second (the last clean tick inside it), plus what happened during the second:

  order-flow imbalance (OFI)   Cont, Kukanov and Stoikov (2014), computed tick by tick on the best level:
                               e = 1{bid >= prev bid} * bid_qty - 1{bid <= prev bid} * prev bid_qty
                                   - 1{ask <= prev ask} * ask_qty + 1{ask >= prev ask} * prev ask_qty
  traded volume                increase of the cumulative day volume since the previous tick
  signed volume                that volume times the trade sign: at or above the previous ask = buy (+1),
                               at or below the previous bid = sell (-1), else the tick rule on the last price

Only contracts that can be at the money are kept: the nearest expiry of the day, strikes within
`ticks.strike_margin` points of the day's NIFTY range. That keeps ~10-20 contracts per day instead of ~80.

Outputs (Parquet, partitioned by day, accepted days only):
  data/ticks/opt    day, sec, instrument_key, expiry, strike, side, 5-level book, ltp, ofi, vol, signed_vol,
                    ticks, last_ts_ns
  data/ticks/fut    day, sec, ltp, vol, signed_vol, ticks       (NIFTY futures, tick rule)
  data/ticks/spot   day, sec, ltp, ticks                         (NIFTY index)
`sec` is seconds since IST midnight. A tick at 10:00:00.7 belongs to sec 36000.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import yaml
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from optpred import runlog
from optpred.spark_common import clean_index, clean_opt_tape, in_session, read_raw, spark_session

log = logging.getLogger("optpred.ticks")

BOOK_COLS = [f"{s}{i}_{k}" for s in ("bid", "ask") for i in range(1, 6) for k in ("price", "qty")]


def tick_flow(df: DataFrame, keys: list[str], with_book: bool) -> DataFrame:
    """Per-tick OFI (book only), traded volume and signed volume, from each tick and the one before it."""
    w = Window.partitionBy(*keys).orderBy("ts_ns")
    prev = {c: F.lag(c).over(w) for c in ("ltp", "volume")}
    vol = F.greatest(F.col("volume") - prev["volume"], F.lit(0.0))
    tick_rule = F.signum(F.col("ltp") - prev["ltp"])
    if with_book:
        pb, pa = F.lag("bid1_price").over(w), F.lag("ask1_price").over(w)
        pbq, paq = F.lag("bid1_qty").over(w), F.lag("ask1_qty").over(w)
        ofi = (
            F.when(F.col("bid1_price") >= pb, F.col("bid1_qty")).otherwise(0)
            - F.when(F.col("bid1_price") <= pb, pbq).otherwise(0)
            - F.when(F.col("ask1_price") <= pa, F.col("ask1_qty")).otherwise(0)
            + F.when(F.col("ask1_price") >= pa, paq).otherwise(0)
        )
        sign = F.when(F.col("ltp") >= pa, 1).when(F.col("ltp") <= pb, -1).otherwise(tick_rule)
        df = df.withColumn("ofi", F.coalesce(ofi, F.lit(0.0)))
    else:
        sign = tick_rule
    return df.withColumn("vol", F.coalesce(vol, F.lit(0.0))).withColumn(
        "signed_vol", F.coalesce(F.col("vol") * sign, F.lit(0.0))
    )


def expiry_as_date(df: DataFrame) -> DataFrame:
    """ClickHouse writes its Date type to Parquet as days since 1970 (a number); tests write real dates."""
    if dict(df.dtypes)["expiry"] == "date":
        return df
    return df.withColumn("expiry", F.date_from_unix_date(F.col("expiry").cast("int")))


def atm_candidates(tape: DataFrame, spot: DataFrame, margin: float) -> DataFrame:
    """Nearest-expiry contracts whose strike can be at the money at some moment of the day."""
    tape = expiry_as_date(tape)
    rng = spot.groupBy("day").agg(F.min("ltp").alias("lo"), F.max("ltp").alias("hi"))
    near = tape.where(F.col("expiry") >= F.col("day")).groupBy("day").agg(F.min("expiry").alias("near"))
    keys = (
        tape.select("day", "instrument_key", "expiry", "strike", "side")
        .distinct()
        .join(near, "day")
        .join(rng, "day")
        .where(
            (F.col("expiry") == F.col("near"))
            & F.col("strike").between(F.col("lo") - margin, F.col("hi") + margin)
        )
        .select("day", "instrument_key")
    )
    return tape.join(F.broadcast(keys), ["day", "instrument_key"])


def opt_seconds(tape: DataFrame) -> DataFrame:
    keys = ["day", "instrument_key"]
    t = tick_flow(tape, keys, with_book=True).withColumn("sec", F.col("sod"))
    last = [F.max_by(c, "ts_ns").alias(c) for c in BOOK_COLS + ["ltp", "expiry", "strike", "side"]]
    return t.groupBy(*keys, "sec").agg(
        *last,
        F.sum("ofi").alias("ofi"),
        F.sum("vol").alias("vol"),
        F.sum("signed_vol").alias("signed_vol"),
        F.count("*").alias("ticks"),
        F.max("ts_ns").alias("last_ts_ns"),
    )


def fut_seconds(und: DataFrame) -> DataFrame:
    fut = (
        in_session(und)
        .where(F.col("kind") == "FUT")
        .where(F.col("ltp") > 0)
        .dropDuplicates(["instrument_key", "ts_ns"])
    )
    # one futures contract per day in this data; if there were two, keep the most traded one
    top = (
        fut.groupBy("day", "instrument_key")
        .count()
        .withColumn("r", F.row_number().over(Window.partitionBy("day").orderBy(F.desc("count"))))
    )
    fut = fut.join(top.where("r = 1").select("day", "instrument_key"), ["day", "instrument_key"])
    t = tick_flow(fut, ["day", "instrument_key"], with_book=False).withColumn("sec", F.col("sod"))
    return t.groupBy("day", "sec").agg(
        F.max_by("ltp", "ts_ns").alias("ltp"),
        F.sum("vol").alias("vol"),
        F.sum("signed_vol").alias("signed_vol"),
        F.count("*").alias("ticks"),
    )


def spot_seconds(und: DataFrame) -> DataFrame:
    return (
        clean_index(und)
        .withColumn("sec", F.col("sod"))
        .groupBy("day", "sec")
        .agg(F.max_by("ltp", "ts_ns").alias("ltp"), F.count("*").alias("ticks"))
    )


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    raw_dir, p = params["export"]["out_dir"], params["ticks"]
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    if not accepted:
        log.error("no accepted days in data/days.json -- run the check stage first")
        return 1

    spark = spark_session("optpred-ticks", params["spark"])
    keep = F.col("day").isin(accepted)
    tape = clean_opt_tape(read_raw(spark, raw_dir, "opt_tape").where(keep))
    und = read_raw(spark, raw_dir, "und_tape").where(keep)
    spot = spot_seconds(und)
    tape = atm_candidates(tape, spot, p["strike_margin"])

    t0 = time.monotonic()
    counts = {}
    for name, df in (("spot", spot), ("fut", fut_seconds(und)), ("opt", opt_seconds(tape))):
        df.write.mode("overwrite").partitionBy("day").parquet(f"{p['out_dir']}/{name}")
        counts[name] = spark.read.parquet(f"{p['out_dir']}/{name}").count()
        log.info("wrote %-4s seconds: %d rows", name, counts[name])
    elapsed = time.monotonic() - t0
    tape_rows = tape.count()
    spark.stop()

    summary.update(
        days=len(accepted),
        tape_rows_in=tape_rows,
        rows_out=counts,
        seconds=round(elapsed, 1),
        tape_rows_per_s=round(tape_rows / elapsed),
    )
    log.info(
        "%d option ticks (ATM candidates) in %.0fs = %.0f rows/s",
        tape_rows,
        elapsed,
        summary["tape_rows_per_s"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("ticks", main))
