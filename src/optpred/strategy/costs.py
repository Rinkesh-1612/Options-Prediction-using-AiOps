"""Statutory charges of a multi-leg position, from the value bought and sold.

Same rates as optpred.labels.costs (one definition of the rates). A short leg sells at entry and buys
back at exit, so its entry premium counts as sold value."""

from __future__ import annotations

import numpy as np

from optpred.labels.costs import EXCH_TXN_RATE, GST_RATE, SEBI_TURNOVER_RATE, STAMP_BUY_RATE, STT_SELL_RATE


def statutory_value_rs(buy_value, sell_value):
    buy, sell = np.asarray(buy_value, dtype=float), np.asarray(sell_value, dtype=float)
    fees = EXCH_TXN_RATE + SEBI_TURNOVER_RATE
    return buy * (fees + STAMP_BUY_RATE) + sell * (fees + STT_SELL_RATE) + GST_RATE * fees * (buy + sell)
