import numpy as np
import pandas as pd
import pytest

from optpred.labels.costs import statutory_rs, statutory_value_rs
from optpred.strategy.legs import parse_legs
from optpred.strategy.sim import LOT, Unavailable, evaluate, load_quotes
from tests.helpers.grid_synth import LEGS


def flat_grid(n=22500, bid=100.0, ask=101.0, atm=25000.0):
    g = pd.DataFrame({"sod": 33300 + np.arange(n), "atm": atm, "spot": atm + 3.0})
    for leg in LEGS:
        g[f"{leg}_bid"], g[f"{leg}_ask"] = bid, ask
    return g


def test_statutory_value_matches_the_single_leg_formula():
    e, x, q = 150.0, 170.0, 65
    assert statutory_value_rs(e * q, x * q) == pytest.approx(statutory_rs(e, x, q))


def test_parse_legs_rejects_bad_text_with_a_plain_message():
    assert [x.sign for x in parse_legs("buy:ce:0:1,sell:pe:-2:3")] == [1, -1]
    for bad in (
        "",
        "buy:ce",
        "hold:ce:0:1",
        "buy:ce:3:1",
        "buy:ce:0:0",
        "buy:ce:x:1",
        ",".join(["buy:ce:0:1"] * 5),
    ):
        with pytest.raises(ValueError):
            parse_legs(bad)


def test_flat_market_loses_exactly_the_spread_and_charges():
    q = load_quotes(flat_grid())
    e = evaluate(q, 36000, parse_legs("buy:ce:0:1"))
    gross = (100.0 - 101.0) * LOT
    assert e["cost"] == pytest.approx(101.0 * LOT)
    assert e["curve"][0] < gross < 0  # the spread plus the charges
    assert e["barrier"] is None or e["barrier"]["hit"] == 0  # nothing moves: no barrier is touched


def test_short_straddle_is_a_credit_and_has_unlimited_upside_loss():
    q = load_quotes(flat_grid())
    e = evaluate(q, 36000, parse_legs("sell:ce:0:1,sell:pe:0:1"))
    assert e["cost"] == pytest.approx(-2 * 100.0 * LOT)  # sells at the bid
    assert e["payoff"]["max_loss"] is None and e["payoff"]["max_profit"] == pytest.approx(2 * 100.0 * LOT)
    assert len(e["payoff"]["breakevens"]) == 2


def test_long_call_payoff_has_one_breakeven_at_strike_plus_premium():
    q = load_quotes(flat_grid())
    e = evaluate(q, 36000, parse_legs("buy:ce:0:1"))
    assert e["payoff"]["max_profit"] is None and e["payoff"]["max_loss"] == pytest.approx(-101.0 * LOT)
    assert e["payoff"]["breakevens"][0] == pytest.approx(25000 + 101, abs=1)


def test_take_profit_when_the_bid_jumps_and_the_position_follows_the_strike():
    g = flat_grid()
    # noisy quotes before entry give a sigma; then the ATM call bid jumps by 30 points
    rng = np.random.default_rng(1)
    base = 100 + rng.normal(0, 0.5, len(g))
    g["ce_p0_bid"], g["ce_p0_ask"] = base, base + 1
    i0 = 36000 - 33300
    g.loc[i0 + 120 :, "ce_p0_bid"] = 140.0
    e = evaluate(load_quotes(g), 36000, parse_legs("buy:ce:0:1"))
    assert e["barrier"]["hit"] == 1 and 100 < e["barrier"]["hold_s"] <= 130 and e["barrier"]["net"] > 0
    assert e["best_exit"]["net"] > 0


def test_unavailable_when_no_quote_or_too_late():
    g = flat_grid()
    g.loc[36000 - 33300, "ce_p0_ask"] = np.nan
    q = load_quotes(g)
    with pytest.raises(Unavailable):
        evaluate(q, 36000, parse_legs("buy:ce:0:1"))
    with pytest.raises(Unavailable):
        evaluate(q, 55650, parse_legs("buy:pe:0:1"))


def test_put_side_extremes_are_unlimited_not_a_silly_number():
    q = load_quotes(flat_grid())
    lp = evaluate(q, 36000, parse_legs("buy:pe:0:1"))["payoff"]
    assert lp["max_profit"] is None and lp["max_loss"] == pytest.approx(-101.0 * LOT)
    bps = evaluate(q, 36000, parse_legs("sell:pe:0:1,buy:pe:-2:1"))["payoff"]  # bull put spread: both finite
    assert bps["max_profit"] is not None and bps["max_loss"] is not None
