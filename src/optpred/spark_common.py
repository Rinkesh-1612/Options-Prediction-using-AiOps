"""Shared Spark helpers: session setup and the one definition of a "clean" tick.

Time columns added by with_time(): day (IST date), sod (seconds since IST midnight), minute.
The clock conventions are defined in optpred.clock.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F

from optpred.clock import IST_OFFSET_S, SESSION_FIRST_MIN, SESSION_LAST_MIN


def spark_session(app: str, cfg: dict) -> SparkSession:
    """Local Spark capped so it cannot starve the live trading stack on the VPS."""
    return (
        SparkSession.builder.appName(app)
        .master(f"local[{cfg['cores']}]")
        .config("spark.driver.memory", cfg["driver_memory"])
        .config("spark.sql.shuffle.partitions", cfg["shuffle_partitions"])
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        # Inside Docker the user may have no home directory (Java then sees "?"),
        # so Spark's package cache and bind address are set explicitly.
        .config("spark.jars.ivy", "/tmp/.ivy2")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
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
