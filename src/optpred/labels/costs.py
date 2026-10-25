"""Cost of one long-option round trip, in rupees. One definition for labels, simulator and baselines.

Buy at the ASK, sell at the BID: the spread is paid by the prices themselves. On top of that:
  statutory  exchange charges, SEBI fee, stamp duty (buy), STT (sell), GST on fees. Zero brokerage.
             Matches the author's broker contract note (Rs150 premium, 65 qty -> Rs18.13).
  slippage   extra points per leg beyond the best quote (params.yaml -> labels.slippage_pts_per_leg).
"""

from __future__ import annotations

import numpy as np

STT_SELL_RATE = 0.0010  # 0.10% of premium, sell side only
EXCH_TXN_RATE = 0.0003503  # both sides
SEBI_TURNOVER_RATE = 0.000001  # both sides
STAMP_BUY_RATE = 0.00003  # buy side only
GST_RATE = 0.18  # on exchange + SEBI fees


def statutory_rs(entry, exit_, qty: int):
    buy = np.asarray(entry, dtype=float) * qty
    sell = np.asarray(exit_, dtype=float) * qty
    fees = EXCH_TXN_RATE + SEBI_TURNOVER_RATE
    return buy * (fees + STAMP_BUY_RATE) + sell * (fees + STT_SELL_RATE) + GST_RATE * fees * (buy + sell)


def net_rs(entry, exit_, qty: int, slippage_pts_per_leg: float):
    """Net rupees of buying at `entry` and selling at `exit_` (premiums), after all costs."""
    entry, exit_ = np.asarray(entry, dtype=float), np.asarray(exit_, dtype=float)
    gross = (exit_ - entry) * qty
    return gross - statutory_rs(entry, exit_, qty) - 2 * slippage_pts_per_leg * qty


def statutory_value_rs(buy_value, sell_value):
    """Same charges as `statutory_rs`, from the total rupee value bought and sold (any number of legs).

    A short leg sells at entry and buys back at exit, so its entry premium counts as sold value."""
    buy, sell = np.asarray(buy_value, dtype=float), np.asarray(sell_value, dtype=float)
    fees = EXCH_TXN_RATE + SEBI_TURNOVER_RATE
    return buy * (fees + STAMP_BUY_RATE) + sell * (fees + STT_SELL_RATE) + GST_RATE * fees * (buy + sell)
