"""check -> bars -> features on a synthetic snapshot: 2 good days and 1 frozen holiday."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
import yaml

from tests.synth import write_day, write_holiday

pytest.importorskip("pyspark")
STRIKES = list(range(22700, 23101, 50))


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
                "features": {
                    "out_dir": "data/features",
                    "horizon_min": 2,
                    "first_minute": 560,
                    "qty": 65,
                    "strike_step": 50,
                    "entry_max_age_s": 20,
                    "min_entry_premium": 5.0,
                    "n_val_days": 0,
                    "n_test_days": 1,
                },
                "costs": {"slippage_pts_per_leg": 0.31, "sensitivity_pts_per_leg": [0.0, 0.31]},
                "baselines": {"random_seeds": 5, "bootstrap_resamples": 50, "seed": 1},
            }
        )
    )
    old = os.getcwd()
    os.chdir(d)
    from optpred import bars, check

    assert check.main([], {}) == 0
    assert bars.main([], {}) == 0
    yield d
    os.chdir(old)


def test_check_rejects_holiday_and_counts_duplicates(workdir):
    days = json.loads((workdir / "data/days.json").read_text())
    assert days["accepted"] == ["2026-10-14", "2026-10-15"]
    assert "2026-10-02" in days["rejected"]
    q = json.loads((workdir / "reports/quality.json").read_text())
    assert q["2026-10-15"]["tape_duplicate_keys"] == 10
    assert q["2026-10-15"]["tape_minutes"] == 375


def test_bars_one_row_per_instrument_minute(workdir):
    opt = pd.read_parquet(workdir / "data/bars/opt")
    assert len(opt) == 2 * len(STRIKES) * 2 * 375  # days x contracts x session minutes
    assert opt["minute"].between(555, 929).all()
    spot = pd.read_parquet(workdir / "data/bars/spot")
    assert len(spot) == 2 * 375
    # last tick of minute 555 (09:15) is at 09:15:58 -> close equals that tick's price
    assert (spot["last_sod"] == spot["minute"] * 60 + 58).all()


@pytest.fixture(scope="module")
def feats(workdir):
    from optpred import features

    assert features.main([], {}) == 0
    return pd.read_parquet(workdir / "data/features/features.parquet")


def test_features_rows_and_splits(workdir, feats):
    # decision minutes 560..927 (368), 2 days; the synthetic walk stays inside the strike ladder
    assert len(feats) == 2 * 368
    assert feats.groupby("day")["split"].first().to_dict() == {"2026-10-14": "train", "2026-10-15": "test"}
    assert not feats[["ce_entry", "pe_entry", "ce_exit", "pe_exit"]].isna().any().any()
    assert (feats["ce_entry"] >= feats["ce_exit"] - 5).all()  # sanity: no impossible jumps


def test_features_match_raw_ticks_by_an_independent_route(workdir, feats):
    """Recompute entry/exit/strike straight from the raw ticks, not through bars or features."""
    day = "2026-10-15"
    tape = pd.read_parquet(workdir / f"data/raw/opt_tape/{day}.parquet")
    und = pd.read_parquet(workdir / f"data/raw/und_tape/{day}.parquet").query("kind == 'INDEX'")
    for df in (tape, und):
        df["minute"] = (((df["ts_ns"] // 1_000_000_000) + 19800) % 86400) // 60
    row = feats[(feats["day"] == day) & (feats["minute"] == 700)].iloc[0]

    spot = und[und["minute"] == 700].sort_values("ts_ns").iloc[-1]["ltp"]
    assert row["strike"] == np.floor(spot / 50 + 0.5) * 50
    assert row["spot"] == pytest.approx(spot)

    def last_book(key, minute):
        g = tape[(tape["instrument_key"] == key) & (tape["minute"] == minute)]
        return g.sort_values("ts_ns").iloc[-1]

    for side in ("ce", "pe"):
        key = row[f"{side}_key"]
        assert key.endswith(f"{int(row['strike'])}{side.upper()}")
        assert row[f"{side}_entry"] == pytest.approx(last_book(key, 700)["ask1_price"])
        assert row[f"{side}_exit"] == pytest.approx(last_book(key, 702)["bid1_price"])
        assert row[f"{side}_gross_rs"] == pytest.approx((row[f"{side}_exit"] - row[f"{side}_entry"]) * 65)


def test_features_use_only_the_past(workdir, feats):
    """spot_ret1 at minute t must equal log(close_t / close_{t-1}) -- no look-ahead."""
    spot = pd.read_parquet(workdir / "data/bars/spot").sort_values(["day", "minute"])
    spot["day"] = spot["day"].astype(str)
    spot["expected"] = spot.groupby("day")["close"].transform(lambda c: np.log(c / c.shift(1)))
    m = feats.merge(spot[["day", "minute", "expected"]], on=["day", "minute"])
    assert np.allclose(m["spot_ret1"], m["expected"], equal_nan=True)


def test_baselines_run_and_the_locked_test_days_stay_locked(workdir, feats):
    from optpred import baselines

    assert baselines.main(["--splits", "test"], {}) == 2  # refused without --final
    assert baselines.main(["--splits", "train"], {}) == 0
    res = json.loads((workdir / "reports/baselines.json").read_text())["results"]["train"]["0.31"]
    assert res["stay_out"]["trades"] == 0 and res["stay_out"]["mean_net_per_day_rs"] == 0.0
    assert res["oracle_not_tradable"]["mean_net_per_trade_rs"] > res["random"]["mean_net_per_trade_rs"]


@pytest.fixture(scope="module")
def micro_rows(workdir, feats):
    from optpred import micro, ticks

    params = yaml.safe_load((workdir / "params.yaml").read_text())
    params["ticks"] = {"out_dir": "data/ticks", "strike_margin": 150}
    params["micro"] = {
        "out_dir": "data/micro",
        "qty": 65,
        "strike_step": 50,
        "first_sec": 33600,
        "last_sec": 55500,
        "entry_max_age_s": 5,
        "min_entry_premium": 5.0,
        "take_profit_pts": 3.5,
        "stop_loss_pts": 2.0,
        "max_hold_s": 180,
        "slippage_pts_per_leg": 0.0,
        "trail_start_pts": 2.0,
        "trail_pts": 2.0,
        "trail_max_hold_s": 300,
        "sweep_min_ask_jump": 0.10,
        "sweep_min_lots": 2,
        "big_move_horizon_s": 120,
    }
    (workdir / "params.yaml").write_text(yaml.safe_dump(params))
    assert ticks.main([], {}) == 0
    assert micro.main(["--workers", "1"], {}) == 0
    return pd.read_parquet(workdir / "data/micro/micro.parquet")


def test_ticks_keep_only_contracts_that_can_be_at_the_money(workdir, micro_rows):
    opt = pd.read_parquet(workdir / "data/ticks/opt")
    spot = pd.read_parquet(workdir / "data/ticks/spot")
    lo, hi = spot["ltp"].min() - 150, spot["ltp"].max() + 150
    assert opt["strike"].between(lo, hi).all() and opt["strike"].nunique() < len(STRIKES)
    assert not opt.duplicated(["day", "instrument_key", "sec"]).any()
    assert opt["sec"].between(555 * 60, 929 * 60 + 59).all()
    # the synthetic tape trades 65 every tick (a tick every 2 s): each traded second carries 65
    traded = opt[opt["vol"] > 0]
    assert np.allclose(traded["vol"], 65) and (traded["signed_vol"].abs() <= traded["vol"]).all()
    fut = pd.read_parquet(workdir / "data/ticks/fut")
    assert len(fut) > 0 and np.allclose(fut.loc[fut["vol"] > 0, "vol"], 75)


def test_micro_rows_have_every_input_and_a_barrier_trade_for_both_sides(micro_rows):
    from optpred.micro import MICRO_COLUMNS

    assert set(MICRO_COLUMNS) <= set(micro_rows.columns)
    assert micro_rows["sec"].between(33600, 55500).all()
    for side in ("ce", "pe"):
        assert micro_rows[f"{side}_reason"].isin([1, 2, 3]).all()
        assert micro_rows[f"{side}_hold_s"].between(1, 180).all()
        assert np.isfinite(micro_rows[f"{side}_gross_rs"]).all()
    assert set(micro_rows["split"]) <= {"train", "val", "test", "forward"}
