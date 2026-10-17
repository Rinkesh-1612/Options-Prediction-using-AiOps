"""Spark check + bars on a synthetic snapshot: 2 good days and 1 frozen holiday."""

import json
from datetime import date

import pandas as pd
import pytest
import yaml

from tests.synth import write_day, write_holiday

pytest.importorskip("pyspark")


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    import os

    d = tmp_path_factory.mktemp("pipe")
    write_day(d / "data/raw", date(2026, 10, 14), seed=1)
    write_day(d / "data/raw", date(2026, 10, 15), seed=2)
    write_holiday(d / "data/raw", date(2026, 10, 2))
    (d / "params.yaml").write_text(
        yaml.safe_dump(
            {
                "export": {"out_dir": "data/raw"},
                "spark": {"cores": 2, "driver_memory": "1g", "shuffle_partitions": 2},
                "check": {"min_coverage": 0.95},
                "bars": {"out_dir": "data/bars"},
            }
        )
    )
    old = os.getcwd()
    os.chdir(d)
    yield d
    os.chdir(old)


def test_check_rejects_holiday_and_counts_duplicates(workdir):
    from optpred import check

    summary = {}
    assert check.main([], summary) == 0
    days = json.loads((workdir / "data/days.json").read_text())
    assert days["accepted"] == ["2026-10-14", "2026-10-15"]
    assert "2026-10-02" in days["rejected"]
    q = json.loads((workdir / "reports/quality.json").read_text())
    assert q["2026-10-15"]["tape_duplicate_keys"] == 10
    assert q["2026-10-15"]["tape_minutes"] == 375


def test_bars_one_row_per_instrument_minute(workdir):
    from optpred import bars

    summary = {}
    assert bars.main([], summary) == 0
    opt = pd.read_parquet(workdir / "data/bars/opt")
    assert len(opt) == 2 * 6 * 375  # days x instruments x session minutes
    assert opt["minute"].between(555, 929).all()
    spot = pd.read_parquet(workdir / "data/bars/spot")
    assert len(spot) == 2 * 375
    # last tick of minute 555 (09:15) is at 09:15:58 -> close equals that tick's price
    assert (spot["last_sod"] == spot["minute"] * 60 + 58).all()
