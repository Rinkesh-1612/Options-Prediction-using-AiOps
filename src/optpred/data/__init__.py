"""Data engineering. Every stage is a DVC stage and writes a journal line.

export   read-only copy of the recorder's ClickHouse tables to Parquet
check    Spark: day-level quality rules (holidays, outages, thin days)
bars     Spark: ticks -> one row per contract per minute (v1)
ticks    Spark: ticks -> one row per contract per second with order-flow measures (v2)
"""
