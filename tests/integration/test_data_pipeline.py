"""Integration: export snapshot -> check (Spark) -> clean -> grid -> feat -> labels on synthetic raw data.

Two good days and one frozen holiday, in the exact export schema (tests/helpers/synth.py).
Each stage runs through its real `main`, with the real params.yaml sections (fewer CPUs).
"""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from tests.helpers.synth import write_day, write_holiday

pytest.importorskip("pyspark")
ROOT = Path(__file__).resolve().parents[2]
DAYS = ["2026-10-14", "2026-10-15"]


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    import os

    d = tmp_path_factory.mktemp("pipe")
    write_day(d / "data/raw", date(2026, 10, 14), seed=1)
    write_day(d / "data/raw", date(2026, 10, 15), seed=2)
    write_holiday(d / "data/raw", date(2026, 10, 2))
    p = yaml.safe_load((ROOT / "params.yaml").read_text())
    p["spark"] = {"cores": 2, "driver_memory": "1g", "shuffle_partitions": 2}
    p["eda"]["workers"] = 2
    (d / "params.yaml").write_text(
        yaml.safe_dump({k: p[k] for k in ("export", "spark", "check", "eda", "grid", "feat", "labels")})
    )
    old = os.getcwd()
    os.chdir(d)
    from optpred.data import check
    from optpred.eda import clean
    from optpred.featurelib import build
    from optpred.labels import barrier
    from optpred.transform import grid

    for stage in (check, clean, grid, build, barrier):
        assert stage.main([], {}) == 0, stage.__name__
    yield d
    os.chdir(old)


def test_check_rejects_holiday_and_counts_duplicates(workdir):
    days = json.loads((workdir / "data/days.json").read_text())
    assert days["accepted"] == DAYS
    assert "2026-10-02" in days["rejected"]
    q = json.loads((workdir / "reports/quality.json").read_text())
    assert q["2026-10-15"]["tape_duplicate_keys"] == 10
    assert q["2026-10-15"]["tape_minutes"] == 375


def test_clean_keeps_only_session_rows(workdir):
    c = json.loads((workdir / "reports/eda/cleaning.json").read_text())["total"]["opt_tape"]
    assert c["drop_outside_session"] > 0 and c["rows_out"] == c["rows_in"] - sum(
        v for k, v in c.items() if k.startswith("drop_")
    )
    sod = pd.read_parquet(workdir / "data/clean/opt_tape/2026-10-15.parquet")["sod"]
    assert sod.min() >= 33300 and sod.max() < 55800


def test_grid_one_row_per_second_with_legs(workdir):
    g = pd.read_parquet(workdir / "data/grid/2026-10-15.parquet")
    assert len(g) == 22500 and g["sod"].is_monotonic_increasing
    assert g["spot"].notna().mean() > 0.99 and g["ce_p0_ask"].notna().mean() > 0.99
    ok = g["ce_p0_ask"].notna() & g["ce_p0_bid"].notna()
    assert (g.loc[ok, "ce_p0_ask"] > g.loc[ok, "ce_p0_bid"]).all()


def test_feat_rows_columns_and_floats(workdir):
    f = pd.read_parquet(workdir / "data/feat/2026-10-15.parquet")
    feats = f.drop(columns=["day", "sod", "atm"])
    assert len(f) == 22500 and feats.shape[1] >= 40
    assert all(t == np.float64 for t in feats.dtypes)
    assert not np.isinf(feats.to_numpy()).any()


def test_labels_are_aligned_and_consistent(workdir):
    lab = pd.read_parquet(workdir / "data/labels/2026-10-15.parquet")
    f = pd.read_parquet(workdir / "data/feat/2026-10-15.parquet")
    assert (lab["sod"].to_numpy() == f["sod"].to_numpy()).all()
    v = lab[lab["ce_valid"]]
    assert len(v) > 1000
    assert set(v["ce_hit"].unique()) <= {-1, 0, 1} and v["ce_net_rs"].notna().all()
    assert (v["ce_hold_s"] >= 1).all()
