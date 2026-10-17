"""Shared Spark helpers: session setup and the one definition of a "clean" tick.

Time convention (single place it is defined):
  ts_ns is UTC epoch nanoseconds. IST = UTC + 5:30 (India has no DST), so the
  IST calendar day and minute are computed by plain arithmetic -- no timezone
  database, no Spark session-timezone surprises.
    sod         seconds since IST midnight
    minute      minutes since IST midnight; 09:15 -> 555, 15:29 -> 929
    day         IST calendar date
  A tick at 09:15:59.9 belongs to minute 555. "State at minute m" means the
  last tick with minute == m, i.e. the market as it stood at the END of m.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F

IST_OFFSET_S = 19800  # 5h30m
SESSION_FIRST_MIN = 9 * 60 + 15  # 555 = 09:15
SESSION_LAST_MIN = 15 * 60 + 29  # 929 = 15:29 (minute bar ending 15:30)
SESSION_MINUTES = SESSION_LAST_MIN - SESSION_FIRST_MIN + 1  # 375


def spark_session(app: str, cfg: dict) -> SparkSession:
    """Local Spark capped so it cannot starve the live trading stack on the VPS."""
    return (
        SparkSession.builder.appName(app)
        .master(f"local[{cfg['cores']}]")
        .config("spark.driver.memory", cfg["driver_memory"])
        .config("spark.sql.shuffle.partitions", cfg["shuffle_partitions"])
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def _ist_seconds(ts_ns: Column) -> Column:
    return F.floor(ts_ns / F.lit(1_000_000_000)) + F.lit(IST_OFFSET_S)


def with_time(df: DataFrame) -> DataFrame:
    """Add IST `day`, `sod` (seconds of day) and `minute` columns from ts_ns."""
    s = _ist_seconds(F.col("ts_ns"))
    return (
        df.withColumn("day", F.date_from_unix_date(F.floor(s / 86400).cast("int")))
        .withColumn("sod", (s % 86400).cast("int"))
        .withColumn("minute", F.floor(F.col("sod") / 60).cast("int"))
    )


def in_session(df: DataFrame) -> DataFrame:
    return df.where(F.col("minute").between(SESSION_FIRST_MIN, SESSION_LAST_MIN))


def read_raw(spark: SparkSession, raw_dir: str, table: str) -> DataFrame:
    return with_time(spark.read.parquet(f"{raw_dir}/{table}/*.parquet"))


def clean_opt_tape(df: DataFrame) -> DataFrame:
    """Session hours only, exact duplicates removed, crossed / one-sided books removed.

    A book with bid >= ask, or a zero on either side, cannot be traded at the
    quoted prices, so it must never become an entry or exit price.
    """
    return (
        in_session(df)
        .dropDuplicates(["instrument_key", "ts_ns"])
        .where((F.col("bid1_price") > 0) & (F.col("ask1_price") > 0))
        .where(F.col("bid1_price") < F.col("ask1_price"))
    )


def clean_index(df: DataFrame) -> DataFrame:
    """NIFTY index ticks (spot) in session, duplicates removed."""
    return (
        in_session(df)
        .where(F.col("kind") == "INDEX")
        .where(F.col("ltp") > 0)
        .dropDuplicates(["instrument_key", "ts_ns"])
    )
