import numpy as np
import pandas as pd

from optpred.transform.grid import option_legs, second_ends

P = {"strike_step": 50, "n_strikes": 1}


def quote(ts_ns, key, strike, side, bid):
    row = {
        "ts_ns": ts_ns,
        "instrument_key": key,
        "strike": strike,
        "side": side,
        "ltp": bid,
        "volume": 1,
        "oi": 1,
    }
    for i in range(1, 6):
        row |= {f"bid{i}_price": bid, f"ask{i}_price": bid + 1, f"bid{i}_qty": 65, f"ask{i}_qty": 130}
    return row


def test_legs_follow_atm_and_never_look_ahead():
    sod, ns = second_ends("2026-10-15")
    t0, t1 = ns[0], ns[1]
    opt = pd.DataFrame(
        [
            quote(t0 - 5, "A", 25000, "CE", 100),
            quote(t0 - 5, "B", 25050, "CE", 80),
            quote(t0 - 5, "C", 24950, "CE", 120),
            quote(t1 + 5, "A", 25000, "CE", 999),  # after second 1 ends: must not appear
        ]
    )
    grid = pd.DataFrame({"grid_ns": [t0, t1], "atm": [25000.0, 25050.0]})
    out = option_legs(opt, grid, P, max_age_s=20)
    # second 0: ATM 25000 -> p0 = A, p1 = B, m1 = C
    assert out.loc[0, ["ce_p0_bid", "ce_p1_bid", "ce_m1_bid"]].tolist() == [100, 80, 120]
    # second 1: ATM moved to 25050 -> p0 = B, m1 = A (old value, the 999 quote is in the future)
    assert out.loc[1, ["ce_p0_bid", "ce_m1_bid"]].tolist() == [80, 100]
    assert np.isnan(out.loc[1, "ce_p1_bid"])  # 25100 not listed
    assert out.loc[0, "ce_p0_ask_depth"] == 5 * 130
