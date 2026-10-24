import numpy as np
import pandas as pd
import pytest

from optpred.labels import costs
from optpred.labels.barrier import barrier_side

P = {
    "strike_step": 50,
    "n_strikes": 1,
    "qty": 65,
    "slippage_pts_per_leg": 0.0,
    "min_entry_premium": 5.0,
    "max_entry_age_s": 5,
    "first_entry_s": 0,
    "last_entry_s": 10**6,
    "force_exit_s": 10**6,
    "sigma_window_s": 4,
    "sigma_horizon_s": 1,
    "k_tp": 2.0,
    "k_sl": 2.0,
    "max_hold_s": 20,
}


def grid(ce_p0_mid, atm=25000.0, ce_m1_mid=None):
    n = len(ce_p0_mid)
    g = {"sod": np.arange(n), "atm": np.full(n, atm) if np.isscalar(atm) else np.asarray(atm, float)}
    legs = {
        "p0": np.asarray(ce_p0_mid, float),
        "m1": np.asarray(ce_m1_mid if ce_m1_mid is not None else ce_p0_mid, float),
        "p1": np.asarray(ce_p0_mid, float),
    }
    for leg, m in legs.items():
        g[f"ce_{leg}_bid"], g[f"ce_{leg}_ask"] = m - 0.5, m + 0.5
    g["ce_p0_age_s"] = 0.0
    return pd.DataFrame(g)


def test_statutory_cost_matches_contract_note():
    assert costs.statutory_rs(150, 150, 65) == pytest.approx(18.13, abs=0.01)


def test_take_profit_stop_loss_and_time_cap():
    wiggle = [100, 101, 100, 101, 100, 101]  # sigma of 1-s changes = 1.095
    up = grid(wiggle + [101] * 3 + [110] * 30)
    down = grid(wiggle + [101] * 3 + [90] * 30)
    flat = grid(wiggle + [101] * 40)
    t = 5
    r_up, r_dn, r_flat = (barrier_side(g, "ce", P).iloc[t] for g in (up, down, flat))
    assert r_up["ce_hit"] == 1 and r_up["ce_hold_s"] == 4 and r_up["ce_exit"] == 109.5
    assert r_dn["ce_hit"] == -1 and r_dn["ce_exit"] == 89.5
    assert r_flat["ce_hit"] == 0 and r_flat["ce_hold_s"] == P["max_hold_s"]
    assert r_up["ce_net_rs"] == pytest.approx(costs.net_rs(101.5, 109.5, 65, 0.0))


def test_follows_the_bought_contract_when_atm_moves():
    wiggle = [100, 101, 100, 101, 100, 101]
    n = 30
    # At t=5 ATM is 25000 (ce_p0). From t=6 ATM is 25050, so the bought contract is now leg m1.
    atm = [25000.0] * 6 + [25050.0] * (n - 6)
    p0 = wiggle + [50.0] * (n - 6)  # new ATM contract: different price, must be ignored
    m1 = wiggle + [120.0] * (n - 6)  # the contract we hold, now one strike below ATM: rises
    r = barrier_side(grid(p0, atm=atm, ce_m1_mid=m1), "ce", P).iloc[5]
    assert r["ce_hit"] == 1 and r["ce_exit"] == 119.5
