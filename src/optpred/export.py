"""Stage 1 -- export: copy the raw NIFTY option data out of Ravion's ClickHouse.

Writes one Parquet file per (table, trading day) under data/raw/ and a manifest
with the row count of every file. After this stage the project never reads
ClickHouse again: the Parquet files are the frozen, DVC-versioned snapshot that
anyone can reproduce the rest of the pipeline from.

Conventions (stated, because they are easy to get wrong):
  * Timestamps are exported as `ts_ns` = Unix epoch nanoseconds (UTC). IST is
    applied later, explicitly. No timezone is carried implicitly by Parquet.
  * Nothing is filtered here except underlying = NIFTY and the calendar day.
    Session hours, holidays, duplicates are the `check` stage's job, so that
    every rejection is counted and reported instead of silently missing.
  * Every query runs with readonly=1: this stage cannot modify Ravion's data.
  * A file is verified after download: its Parquet row count must equal a
    separate count(*) on the server, or the file is deleted and the stage fails.

Usage:
    python -m optpred.export --dry-run   # per-day row counts, writes nothing
    python -m optpred.export             # export missing days
    python -m optpred.export --force     # re-export every day
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq
import yaml

log = logging.getLogger("optpred.export")

IST = timezone(timedelta(hours=5, minutes=30))

# Explicit column lists per table: the export is a contract, not "whatever the
# table holds today". Enums are cast to strings so Parquet readers agree.
TABLES: dict[str, dict[str, str]] = {
    "opt_tape": {
        "source": "ravion.opt_tape",
        "where": "underlying = 'NIFTY'",
        "columns": (
            "toUnixTimestamp64Nano(ts) AS ts_ns, expiry, dte, strike, "
            "toString(side) AS side, instrument_key, lot_size, ltp, ltq, ltt, "
            "volume, avg_price, oi, total_buy_qty, total_sell_qty, "
            "bid1_price, bid1_qty, bid2_price, bid2_qty, bid3_price, bid3_qty, "
            "bid4_price, bid4_qty, bid5_price, bid5_qty, "
            "ask1_price, ask1_qty, ask2_price, ask2_qty, ask3_price, ask3_qty, "
            "ask4_price, ask4_qty, ask5_price, ask5_qty"
        ),
    },
    "und_tape": {
        "source": "ravion.und_tape",
        "where": "underlying = 'NIFTY'",
        "columns": (
            "toUnixTimestamp64Nano(ts) AS ts_ns, toString(kind) AS kind, expiry, "
            "instrument_key, toString(trading_symbol) AS trading_symbol, "
            "ltp, ltq, volume, oi"
        ),
    },
    "option_chain_snap": {
        "source": "ravion.option_chain_snap",
        "where": "underlying = 'NIFTY'",
        "columns": (
            "toUnixTimestamp64Nano(ts) AS ts_ns, expiry, expiry_rank, dte, strike, "
            "spot, ce_key, ce_ltp, ce_bid, ce_ask, ce_oi, ce_volume, ce_iv, ce_delta, "
            "pe_key, pe_ltp, pe_bid, pe_ask, pe_oi, pe_volume, pe_iv, pe_delta"
        ),
    },
}


class ExportError(RuntimeError):
    """Raised when a query fails or a downloaded file does not verify."""


class ClickHouse:
    """Minimal read-only ClickHouse HTTP client (stdlib only)."""

    def __init__(self, url: str, user: str, password: str, timeout_s: int) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    def _open(self, sql: str):
        params = urllib.parse.urlencode({"readonly": 1, "max_execution_time": self.timeout_s})
        req = urllib.request.Request(f"{self.url}/?{params}", data=sql.encode(), headers=self.headers)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout_s)
        except urllib.error.HTTPError as e:
            raise ExportError(f"ClickHouse HTTP {e.code}: {e.read()[:500].decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise ExportError(f"cannot reach ClickHouse at {self.url}: {e.reason}") from e

    def text(self, sql: str) -> str:
        with self._open(sql) as resp:
            return resp.read().decode()

    def to_file(self, sql: str, path: Path) -> None:
        with self._open(sql) as resp, open(path, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)


def load_params(path: str = "params.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["export"]


def day_counts(ch: ClickHouse, table: str, start: str, end: str) -> dict[str, int]:
    """Rows per calendar day for one table, between start and end inclusive."""
    t = TABLES[table]
    sql = (
        f"SELECT toDate(ts) AS d, count() FROM {t['source']} "
        f"WHERE {t['where']} AND toDate(ts) BETWEEN '{start}' AND '{end}' "
        f"GROUP BY d ORDER BY d FORMAT TSV"
    )
    out = {}
    for line in ch.text(sql).splitlines():
        d, n = line.split("\t")
        out[d] = int(n)
    return out


def export_day(ch: ClickHouse, table: str, day: str, expected: int, out_root: Path) -> int:
    """Export one (table, day) to Parquet and verify its row count. Returns rows."""
    t = TABLES[table]
    out_dir = out_root / table
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{day}.parquet"
    tmp = final.with_suffix(".parquet.part")
    sql = (
        f"SELECT {t['columns']} FROM {t['source']} "
        f"WHERE {t['where']} AND toDate(ts) = '{day}' ORDER BY ts FORMAT Parquet"
    )
    ch.to_file(sql, tmp)
    got = pq.ParquetFile(tmp).metadata.num_rows
    if got != expected:
        tmp.unlink(missing_ok=True)
        raise ExportError(f"{table} {day}: file has {got} rows, server counted {expected}")
    tmp.replace(final)
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print per-day counts, write nothing")
    ap.add_argument("--force", action="store_true", help="re-export days that already exist")
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    p = load_params(args.params)
    password = os.environ.get("CH_PASSWORD")
    if password is None:
        log.error("CH_PASSWORD is not set (see README: export it from Ravion-V2/.env)")
        return 2
    ch = ClickHouse(p["clickhouse_url"], os.environ.get("CH_USER", "ravion"), password, p["timeout_s"])
    start, end = str(p["start_date"]), str(p["end_date"] or datetime.now(IST).date())
    out_root = Path(p["out_dir"])

    try:
        counts = {t: day_counts(ch, t, start, end) for t in p["tables"]}
    except ExportError as e:
        log.error("%s", e)
        return 1

    days = sorted(set().union(*counts.values()))
    log.info("%d calendar days with data between %s and %s", len(days), start, end)
    if args.dry_run:
        print("day         " + "  ".join(f"{t:>18}" for t in p["tables"]))
        for d in days:
            print(d + "  " + "  ".join(f"{counts[t].get(d, 0):>18,}" for t in p["tables"]))
        return 0

    manifest_path = out_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    failures = 0
    for table in p["tables"]:
        for day, n in counts[table].items():
            key = f"{table}/{day}"
            if not args.force and manifest.get(key) == n and (out_root / table / f"{day}.parquet").exists():
                continue
            try:
                rows = export_day(ch, table, day, n, out_root)
            except ExportError as e:
                log.error("%s", e)
                failures += 1
                continue
            manifest[key] = rows
            log.info("exported %-18s %s  %10d rows", table, day, rows)
            manifest_path.write_text(json.dumps(dict(sorted(manifest.items())), indent=1))

    log.info("done: %d files in manifest, %d failures", len(manifest), failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
