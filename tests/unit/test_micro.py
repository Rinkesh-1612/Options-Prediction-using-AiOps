"""v2 building blocks: book fills, barrier exits, rolling sums (docs/V2_PROTOCOL.md section 4)."""

import numpy as np

from optpred.features import micro
from optpred.features.minute import fill_price


def test_vectorised_fill_matches_the_v1_fill_row_by_row():
    rng = np.random.default_rng(0)
    p = np.sort(rng.uniform(90, 110, size=(200, 5)), axis=1)
    q = rng.integers(0, 60, size=(200, 5)).astype(float)
    q[::7, 2] = 0  # an empty level stops the walk
    for thin in (False, True):
        got = micro.fill_vec(p, q, 65, thin)
        want = np.array([fill_price(p[i], q[i], 65, thin) for i in range(len(p))])
        assert np.allclose(got, want, equal_nan=True)


def test_take_profit_stop_loss_and_time_stop():
    bid = np.array([100, 101, 104, 99, 97, 100, 100, 100], dtype=float)
    entry = np.full(len(bid), 100.5)
    exit_px, hold, reason = micro.barrier_exits(entry, bid, bid, tp=3.5, sl=2.0, max_hold=3)
    assert (reason[0], hold[0], exit_px[0]) == (1, 2, 104)  # 104 >= 104.0 at t+2
    assert (reason[2], hold[2], exit_px[2]) == (2, 2, 97)  # 97 <= 98.5 at t+2: filled at the worse price
    assert (reason[5], hold[5], exit_px[5]) == (3, 3, 100)  # nothing touched: time stop


def test_the_first_barrier_touched_wins():
    bid = np.array([100, 98, 105], dtype=float)
    entry = np.array([100.0, np.nan, np.nan])
    _, hold, reason = micro.barrier_exits(entry, bid, bid, tp=3.5, sl=2.0, max_hold=2)
    assert (reason[0], hold[0]) == (2, 1)  # the stop came first, the later jump does not count


def test_no_trade_without_an_entry_and_no_barrier_on_a_missing_bid():
    bid = np.array([100, np.nan, np.nan, 100], dtype=float)
    entry = np.array([np.nan, 100.0, np.nan, np.nan])
    exit_px, _, reason = micro.barrier_exits(entry, bid, bid, tp=3.5, sl=2.0, max_hold=2)
    assert reason[0] == 0 and np.isnan(exit_px[0])
    assert reason[1] == 3  # a missing bid never fakes a stop loss


def test_rolling_sum_uses_only_the_past():
    x = np.arange(10, dtype=float)
    r = micro.rsum(x, 3)
    assert np.isnan(r[:2]).all() and r[2] == 0 + 1 + 2 and r[9] == 7 + 8 + 9
    y = x.copy()
    y[6:] = 1000  # a change in the future
    assert np.array_equal(micro.rsum(y, 3)[:6], r[:6], equal_nan=True)


def test_decision_rule_takes_the_likelier_side_only_above_tau():
    from optpred.models.micro_train import decide

    p_ce, p_pe = np.array([0.6, 0.3, 0.55, 0.2]), np.array([0.4, 0.62, 0.55, 0.3])
    assert list(decide(p_ce, p_pe, 0.55)) == [1, 2, 1, 0]
    assert (decide(p_ce, p_pe, 1.01) == 0).all()


def test_one_position_at_a_time_with_barrier_holds():
    import pandas as pd

    from optpred.models.micro_train import simulate

    df = pd.DataFrame(
        {
            "day": ["d"] * 6 + ["e"],
            "sec": [100, 101, 103, 104, 105, 200, 100],
            "ce_hold_s": [3, 3, 3, 3, 3, 3, 3],
            "pe_hold_s": [1, 1, 1, 1, 1, 1, 1],
            "ce_gross_rs": [100.0] * 7,
            "ce_stat_rs": [0.0] * 7,
            "pe_gross_rs": [-50.0] * 7,
            "pe_stat_rs": [0.0] * 7,
        }
    )
    tr = simulate(df, np.array([1, 1, 1, 2, 2, 1, 1]), slip=0.0, qty=65)
    # 100 opens a 3 s call (busy to 103); 104 opens a 1 s put; 105 is busy; 200 and day e open
    assert list(tr["sec"]) == [100, 104, 200, 100] and list(tr["side"]) == [1, 2, 1, 1]
    assert list(tr["net_rs"]) == [100.0, -50.0, 100.0, 100.0]


def test_trailing_stop_follows_the_best_bid_and_keeps_the_initial_stop_before_it_arms():
    bid = np.array([100, 101, 103, 106, 105, 103.9, 110], dtype=float)
    entry = np.array([100.0] + [np.nan] * 6)
    exit_px, hold, reason = micro.trailing_exits(entry, bid, bid, stop=2.0, start=2.0, trail=2.0, max_hold=10)
    # arms at 103 (>= 102); best 106 -> stop 104; 105 holds; 103.9 <= 104 exits at k=5
    assert (reason[0], hold[0], exit_px[0]) == (2, 5, 103.9)
    bid2 = np.array([100, 101, 97.9, 120], dtype=float)
    e2 = np.array([100.0, np.nan, np.nan, np.nan])
    px2, hold2, _ = micro.trailing_exits(e2, bid2, bid2, stop=2.0, start=2.0, trail=2.0, max_hold=10)
    assert (hold2[0], px2[0]) == (2, 97.9)  # the initial stop works before the trail arms


def test_spot_excursion_label_looks_ahead_only_within_the_horizon():
    x = np.array([0, 1, 5, 2, 0, 0], dtype=float)
    out = micro.max_excursion(x, 2)
    assert list(out[:4]) == [5, 4, 5, 2] and np.isnan(out[4:]).all()


def test_v2_evaluation_refuses_without_final_and_refuses_a_second_look(tmp_path):
    from optpred.models import micro_evaluate

    out = tmp_path / "micro_final.json"
    assert micro_evaluate.main(["--out", str(out)], {}) == 2
    out.write_text("{}")
    assert micro_evaluate.main(["--final", "--out", str(out)], {}) == 3
