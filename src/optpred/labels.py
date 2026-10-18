"""Costs and labels: what a trade is worth in rupees after everything it costs.

One definition, used by the labels, the simulator and the baselines, so the model
and its yardsticks can never be charged differently.

Trade (long option only):  buy at the ASK, sell at the BID  -> the spread is paid.
Costs on top of that:
  statutory  exchange charges, SEBI fee, stamp duty (buy side), STT (sell side), GST on the
             fees. Copied from Ravion-V2 common/ravion_quant.py::option_roundtrip_cost_rs, with
             the buy and sell premiums charged separately (as ravlab/costs.py does). Brokerage
             is zero on this account (contract note 2026-08-06).
  slippage   `slippage_pts_per_leg` points per leg, 2 legs, times the quantity. A setting, not
             a fact: see params.yaml -> costs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STT_SELL_RATE = 0.0010  # 0.10% of premium, sell side only
EXCH_TXN_RATE = 0.0003503  # both sides
SEBI_TURNOVER_RATE = 0.000001  # both sides
STAMP_BUY_RATE = 0.00003  # buy side only
GST_RATE = 0.18  # on exchange + SEBI fees

STAY_OUT, BUY_CE, BUY_PE = 0, 1, 2
ACTION_NAMES = {STAY_OUT: "STAY_OUT", BUY_CE: "BUY_CE", BUY_PE: "BUY_PE"}


def statutory_cost_rs(entry, exit_, qty):
    """Statutory cost of buying at `entry` and selling at `exit_` (premiums in rupees)."""
    buy = np.asarray(entry, dtype=float) * qty
    sell = np.asarray(exit_, dtype=float) * qty
    fees = EXCH_TXN_RATE + SEBI_TURNOVER_RATE
    return buy * (fees + STAMP_BUY_RATE) + sell * (fees + STT_SELL_RATE) + GST_RATE * fees * (buy + sell)


def slippage_rs(slippage_pts_per_leg: float, qty: int) -> float:
    return slippage_pts_per_leg * 2.0 * qty


def net_rs(df: pd.DataFrame, side: str, slippage_pts_per_leg: float, qty: int) -> pd.Series:
    """Net rupee result of one trade per row. `side` is "ce" or "pe"."""
    return df[f"{side}_gross_rs"] - df[f"{side}_stat_rs"] - slippage_rs(slippage_pts_per_leg, qty)


def label_actions(df: pd.DataFrame, slippage_pts_per_leg: float, qty: int) -> np.ndarray:
    """BUY_CE if the call nets > 0 and beats the put, BUY_PE if the put does, else STAY_OUT."""
    ce = net_rs(df, "ce", slippage_pts_per_leg, qty).to_numpy()
    pe = net_rs(df, "pe", slippage_pts_per_leg, qty).to_numpy()
    out = np.full(len(df), STAY_OUT, dtype=int)
    out[(ce > 0) & (ce >= pe)] = BUY_CE
    out[(pe > 0) & (pe > ce)] = BUY_PE
    return out
