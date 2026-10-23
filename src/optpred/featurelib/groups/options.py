"""ATM option order book, option flow and the volatility surface."""

from __future__ import annotations

import numpy as np
import pandas as pd

from optpred.featurelib.groups._util import BP, log_ret, mid, safe_ratio, same_contract
from optpred.featurelib.registry import feature

ATM_LEGS = ("ce_p0", "pe_p0")


@feature(group="book", lookback_s=10)
def book_shape(g: pd.DataFrame) -> pd.DataFrame:
    """For the ATM call and put: spread (bp of mid), level-1 and 5-level size imbalance (+1 = all bids),
    microprice offset (-0.5..+0.5 of the spread), and the 10 s mean of the depth imbalance."""
    cols = {}
    for leg in ATM_LEGS:
        b, a, bq, aq = g[f"{leg}_bid"], g[f"{leg}_ask"], g[f"{leg}_bid_qty"], g[f"{leg}_ask_qty"]
        bd, ad = g[f"{leg}_bid_depth"], g[f"{leg}_ask_depth"]
        m = (b + a) / 2
        micro = safe_ratio(b * aq + a * bq, bq + aq)
        depth_imb = safe_ratio(bd - ad, bd + ad)
        cols[f"{leg}_spread_bp"] = safe_ratio(a - b, m) * BP
        cols[f"{leg}_l1_imb"] = safe_ratio(bq - aq, bq + aq)
        cols[f"{leg}_depth_imb"] = depth_imb
        cols[f"{leg}_micro_off"] = safe_ratio(micro - m, a - b)
        cols[f"{leg}_depth_imb_10s"] = depth_imb.rolling(10).mean()
    return pd.DataFrame(cols, index=g.index)


@feature(group="flow", lookback_s=300)
def option_flow(g: pd.DataFrame) -> pd.DataFrame:
    """For the ATM call and put: mid return over 15 and 60 s (bp), volume traded in 10 and 60 s (log1p),
    OI change over 300 s. NaN when ATM moved inside the window (the leg changed contract)."""
    cols = {}
    for leg in ATM_LEGS:
        m, v, oi = mid(g, leg), g[f"{leg}_volume"], g[f"{leg}_oi"]
        for n in (15, 60):
            cols[f"{leg}_ret_{n}s"] = (log_ret(m, n) * BP).where(same_contract(g, n))
        for n in (10, 60):
            cols[f"{leg}_vol_{n}s"] = np.log1p(v.diff(n).clip(lower=0)).where(same_contract(g, n))
        cols[f"{leg}_oi_chg_300s"] = oi.diff(300).where(same_contract(g, 300))
    return pd.DataFrame(cols, index=g.index)


@feature(group="flow", lookback_s=60)
def call_put_pressure(g: pd.DataFrame) -> pd.DataFrame:
    """Call minus put, scaled to -1..+1: volume traded in the last 60 s, and 5-level depth imbalance."""
    ok = same_contract(g, 60)
    cv = g["ce_p0_volume"].diff(60).clip(lower=0).where(ok)
    pv = g["pe_p0_volume"].diff(60).clip(lower=0).where(ok)

    def imb(leg: str) -> pd.Series:
        return safe_ratio(
            g[f"{leg}_bid_depth"] - g[f"{leg}_ask_depth"], g[f"{leg}_bid_depth"] + g[f"{leg}_ask_depth"]
        )

    return pd.DataFrame(
        {"cp_vol_ratio_60s": safe_ratio(cv - pv, cv + pv), "cp_depth_imb_diff": imb("ce_p0") - imb("pe_p0")},
        index=g.index,
    )


@feature(group="chain", lookback_s=300)
def vol_surface(g: pd.DataFrame) -> pd.DataFrame:
    """ATM implied volatility (mean of call and put), put-minus-call IV skew, IV change over 300 s, and the
    ATM straddle price as bp of spot (the market's expected move to expiry)."""
    iv = (g["ce_iv"] + g["pe_iv"]) / 2
    straddle = mid(g, "ce_p0") + mid(g, "pe_p0")
    return pd.DataFrame(
        {
            "atm_iv": iv,
            "iv_skew": g["pe_iv"] - g["ce_iv"],
            "atm_iv_chg_300s": iv.diff(300),
            "straddle_bp": straddle / g["spot"] * BP,
        },
        index=g.index,
    )
