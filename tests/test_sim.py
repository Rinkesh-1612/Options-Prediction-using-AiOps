import numpy as np
import pandas as pd
import pytest

from optpred import baselines, sim
from optpred.labels import BUY_CE, BUY_PE, STAY_OUT


def frame(minutes, ce_gross, pe_gross=None, day="2026-10-01"):
    n = len(minutes)
    return pd.DataFrame(
        {
            "day": day,
            "minute": minutes,
            "ce_gross_rs": ce_gross,
            "pe_gross_rs": pe_gross if pe_gross is not None else [0.0] * n,
            "ce_stat_rs": 20.0,
            "pe_stat_rs": 20.0,
            "spot_ret2": [1.0] * n,
        }
    )


def test_one_position_at_a_time():
    df = frame([560, 561, 562, 563, 564], [100.0] * 5)
    t = sim.simulate(df, [BUY_CE] * 5, slippage_pts_per_leg=0.0, qty=65, horizon=2)
    assert list(t["minute"]) == [560, 562, 564]  # signals at 561 and 563 land inside an open trade
    assert list(t["net_rs"]) == [80.0] * 3  # gross 100 - statutory 20


def test_open_trade_does_not_carry_over_to_next_day():
    df = pd.concat(
        [frame([926, 927], [100.0] * 2, day="2026-10-01"), frame([560], [100.0], day="2026-10-02")],
        ignore_index=True,
    )
    assert len(sim.simulate(df, [BUY_CE] * 3, 0.0, 65, 2)) == 2


def test_unsorted_rows_are_refused():
    with pytest.raises(ValueError):
        sim.simulate(frame([561, 560], [1.0, 1.0]), [BUY_CE, BUY_CE], 0.0, 65, 2)


def test_stay_out_is_exactly_zero_and_days_without_trades_count_as_zero():
    df = frame([560, 561], [100.0, 100.0])
    t = sim.simulate(df, [STAY_OUT, STAY_OUT], 0.31, 65, 2)
    s = sim.summarize(t, ["2026-10-01", "2026-10-02"], 100, 0)
    assert s["trades"] == 0 and s["mean_net_per_day_rs"] == 0.0


def test_bootstrap_interval_collapses_when_every_day_is_identical():
    days = [f"2026-10-{d:02d}" for d in range(1, 9)]
    t = pd.DataFrame({"day": days, "minute": 560, "side": 1, "net_rs": 50.0, "gross_rs": 70.0})
    s = sim.summarize(t, days, 500, 0)
    assert s["per_day_ci95_rs"] == [50.0, 50.0] and s["hit_rate"] == 1.0 and s["resolvable_per_day_rs"] == 0.0


def test_momentum_follows_the_last_two_minutes():
    df = frame([560, 561, 562], [0.0] * 3)
    df["spot_ret2"] = [0.001, -0.002, 0.0]
    assert list(baselines.rule_actions(df, "momentum")) == [BUY_CE, BUY_PE, STAY_OUT]


def test_oracle_never_loses_and_beats_random():
    rng = np.random.default_rng(1)
    n = 400
    df = frame(list(range(560, 560 + n)), rng.normal(0, 200, n), rng.normal(0, 200, n))
    o = sim.simulate(df, sim.oracle_actions(df, 0.31, 65), 0.31, 65, 1)
    r = sim.simulate(df, baselines.rule_actions(df, "random", rng), 0.31, 65, 1)
    assert (o["net_rs"] > 0).all() and o["net_rs"].mean() > r["net_rs"].mean()


def test_summarize_without_intervals_works_for_many_days():
    """Regression: resamples=0 with 2+ days crashed (it hid behind single-day tests)."""
    days = [f"2026-10-{d:02d}" for d in range(1, 6)]
    t = pd.DataFrame(
        {"day": days, "minute": 560, "side": 1, "net_rs": [10.0, -5.0, 20.0, 0.0, 7.0], "gross_rs": 0.0}
    )
    s = sim.summarize(t, days, resamples=0, seed=0)
    assert s["trades"] == 5 and "per_day_ci95_rs" not in s and s["positive_days"] == 3
