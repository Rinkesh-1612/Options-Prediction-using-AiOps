"""Simulate an option strategy entered at one second, on the recorded quotes of one day.

  entry    buy legs at the ASK, sell legs at the BID, at the entry second. The strikes are fixed at entry
           (ATM at that second + k strikes) and FOLLOWED afterwards, as in the labels.
  exit     buy legs at the BID, sell legs at the ASK. A quote that is missing is the last known one.
  costs    statutory charges on the value bought and sold (optpred.labels.costs), zero brokerage, no slippage.
  curve    net rupees if the whole position is closed after 1, 2, 3 ... minutes.
  barrier  the same rule as the labels: take profit at +k_tp * sigma, stop loss at -k_sl * sigma, time cap.
           sigma = std of the 1-second changes of the position's mid value in the last 5 minutes, x sqrt(60).
  payoff   profit at expiry (before costs) for a range of NIFTY levels, break-evens, maximum profit / loss.

Margin is not modelled: short legs need margin and carry large risk. Nothing here looks ahead of the exit rule
except the "best exit" of the curve, which is hindsight by design.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from optpred.labels.barrier import contract_matrix
from optpred.strategy.costs import statutory_value_rs
from optpred.strategy.legs import N_STRIKES, STEP, Leg

LOT = 65
K_TP = K_SL = 2.0
SIGMA_WINDOW_S, SIGMA_HORIZON_S = 300, 60
MAX_HOLD_S = 900  # barrier mode: time cap (labels.max_hold_s)
MAX_CURVE_S = 7200
FORCE_EXIT_S = 55680  # 15:28
MIN_PREMIUM = 0.05  # one tick: a quote below this is not a price

FIELDS = ("bid", "ask")


@dataclass
class DayQuotes:
    sod: np.ndarray
    atm: np.ndarray
    spot: np.ndarray
    strikes: np.ndarray
    bid: dict  # side -> (n, strikes) float32
    ask: dict


def grid_columns() -> list[str]:
    legs = [f"{'m' if k < 0 else 'p'}{abs(k)}" for k in range(-N_STRIKES, N_STRIKES + 1)]
    return ["sod", "atm", "spot"] + [f"{s}_{lg}_{f}" for s in ("ce", "pe") for lg in legs for f in FIELDS]


def load_quotes(g: pd.DataFrame) -> DayQuotes:
    g = g.sort_values("sod").reset_index(drop=True)
    bid, ask, strikes = {}, {}, None
    for side in ("ce", "pe"):
        strikes, b = contract_matrix(g, side, "bid", STEP, N_STRIKES)
        _, a = contract_matrix(g, side, "ask", STEP, N_STRIKES)
        bid[side], ask[side] = b.astype(np.float32), a.astype(np.float32)
    return DayQuotes(g["sod"].to_numpy(), g["atm"].to_numpy(), g["spot"].to_numpy(), strikes, bid, ask)


def ffill(a: np.ndarray) -> np.ndarray:
    """Last known value; NaN only before the first quote."""
    idx = np.where(np.isfinite(a), np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = a[idx]
    out[: int(np.argmax(np.isfinite(a)))] = np.nan  # before the first quote there is nothing to carry
    return out


class Unavailable(ValueError):
    """The position cannot be priced at this second (no ATM, or a leg has no quote)."""


def evaluate(q: DayQuotes, t: int, legs: list[Leg], max_curve_s: int = MAX_CURVE_S) -> dict:
    i0 = int(np.searchsorted(q.sod, t))
    if i0 >= len(q.sod) or q.sod[i0] != t:
        raise Unavailable("no data at this time")
    if not np.isfinite(q.atm[i0]):
        raise Unavailable("no ATM strike at this time")
    last = int(np.searchsorted(q.sod, FORCE_EXIT_S)) - 1
    hs = min(max_curve_s, last - i0)
    if hs < 60:
        raise Unavailable("too close to the close to hold the position")
    cols, strikes = [], []
    for lg in legs:
        k_abs = float(q.atm[i0] + lg.k * STEP)
        j = int(np.searchsorted(q.strikes, k_abs))
        if j >= len(q.strikes) or q.strikes[j] != k_abs:
            raise Unavailable("strike not in the data")
        cols.append(j)
        strikes.append(k_abs)
    bid_s, ask_s, mid_past = [], [], []
    for lg, j in zip(legs, cols, strict=True):
        b, a = q.bid[lg.side][:, j].astype(float), q.ask[lg.side][:, j].astype(float)
        if not (np.isfinite(b[i0]) and np.isfinite(a[i0]) and b[i0] >= 0 and a[i0] >= MIN_PREMIUM):
            raise Unavailable(f"no quote for {lg.side.upper()} {int(q.atm[i0] + lg.k * STEP)} at this time")
        bid_s.append(ffill(b[i0 : i0 + hs + 1]))
        ask_s.append(ffill(a[i0 : i0 + hs + 1]))
        lo = max(0, i0 - SIGMA_WINDOW_S)
        mid_past.append((b[lo : i0 + 1] + a[lo : i0 + 1]) / 2)
    qty = np.array([lg.lots for lg in legs], float)
    sgn = np.array([lg.sign for lg in legs], float)
    bid_a, ask_a = np.array(bid_s), np.array(ask_s)  # (legs, hs + 1)
    buy = (sgn > 0)[:, None]
    # entry prices (premium per unit) and the value of the position if closed at each second (premium units)
    p_in = np.where(sgn > 0, ask_a[:, 0], bid_a[:, 0])
    p_out = np.where(buy, bid_a, ask_a)  # (legs, hs + 1)
    gross = ((p_out - p_in[:, None]) * (sgn * qty)[:, None]).sum(axis=0)  # premium units, per second
    bought = np.where(sgn > 0, p_in, 0) * qty  # value bought at entry
    sold = np.where(sgn < 0, p_in, 0) * qty
    buy_v = (bought.sum() + (np.where(sgn < 0, p_out.T, 0) * qty).sum(axis=1)) * LOT
    sell_v = (sold.sum() + (np.where(sgn > 0, p_out.T, 0) * qty).sum(axis=1)) * LOT
    net = gross * LOT - statutory_value_rs(buy_v, sell_v)  # (hs + 1,) rupees if closed at second s
    minutes = np.arange(1, hs // 60 + 1)
    curve = net[minutes * 60]
    debit = float((sgn * qty * p_in).sum() * LOT)  # > 0 pay, < 0 receive (before charges)
    out = {
        "legs": [
            {"side": lg.side, "action": lg.action, "lots": lg.lots, "strike": s, "price": float(p), "k": lg.k}
            for lg, s, p in zip(legs, strikes, p_in, strict=True)
        ],
        "cost": round(debit, 2),
        "minutes": minutes.tolist(),
        "curve": [round(float(x), 1) for x in curve],
    }
    bi = int(np.argmax(curve))
    out["best_exit"] = {"minute": int(minutes[bi]), "net": round(float(curve[bi]), 1)}
    out["barrier"] = barrier(net, gross, np.array(mid_past), sgn * qty, hs)
    out["payoff"] = payoff(legs, strikes, p_in, q.spot[i0])
    out["atm"], out["spot"] = float(q.atm[i0]), float(q.spot[i0])
    return out


def barrier(net: np.ndarray, gross: np.ndarray, mid_past: np.ndarray, w: np.ndarray, hs: int) -> dict | None:
    m = (mid_past * w[:, None]).sum(axis=0)  # position mid value over the last minutes (premium units)
    d = np.diff(m)
    d = d[np.isfinite(d)]
    if len(d) < SIGMA_WINDOW_S // 2:
        return None
    sigma = float(d.std(ddof=1)) * np.sqrt(SIGMA_HORIZON_S)
    if not sigma > 0:
        return None
    n = min(MAX_HOLD_S, hs)
    g = gross[1 : n + 1]
    up, down = g >= K_TP * sigma, g <= -K_SL * sigma
    hit_up, hit_dn = np.flatnonzero(up), np.flatnonzero(down)
    iu = hit_up[0] if len(hit_up) else n + 1
    idn = hit_dn[0] if len(hit_dn) else n + 1
    if iu <= idn and iu <= n:
        h, code = iu + 1, 1
    elif idn <= n and idn < iu:
        h, code = idn + 1, -1
    else:
        h, code = n, 0
    return {"hit": code, "hold_s": int(h), "net": round(float(net[h]), 1), "sigma": round(sigma, 3)}


def payoff(legs: list[Leg], strikes: list[float], p_in: np.ndarray, spot: float) -> dict:
    """Profit at expiry before charges, per NIFTY level; break-evens; maximum profit and loss."""
    lo, hi = max(0.0, spot * 0.94), spot * 1.06
    s = np.linspace(lo, hi, 241)
    pnl = np.zeros_like(s)
    for lg, k, p in zip(legs, strikes, p_in, strict=True):
        intrinsic = np.maximum(s - k, 0) if lg.side == "ce" else np.maximum(k - s, 0)
        pnl += lg.sign * lg.lots * (intrinsic - p) * LOT
    # Net long calls: profit grows without limit as NIFTY rises; net short calls: loss does.
    # Puts do the same as NIFTY falls to zero: the number is huge, so it is reported as unlimited too.
    calls = sum(lg.sign * lg.lots for lg in legs if lg.side == "ce")
    puts = sum(lg.sign * lg.lots for lg in legs if lg.side == "pe")
    unlimited_profit, unlimited_loss = calls > 0 or puts > 0, calls < 0 or puts < 0

    def at(x: float) -> float:
        return sum(
            lg.sign * lg.lots * ((max(x - k, 0) if lg.side == "ce" else max(k - x, 0)) - p) * LOT
            for lg, k, p in zip(legs, strikes, p_in, strict=True)
        )

    kinks = [0.0, *strikes, hi]  # the payoff is a straight line between kinks
    ends = [at(x) for x in kinks]
    flips = np.flatnonzero(np.diff(np.sign(pnl)) != 0)
    be = [
        round(float(s[i] - pnl[i] * (s[i + 1] - s[i]) / (pnl[i + 1] - pnl[i])), 1)
        for i in flips
        if pnl[i + 1] != pnl[i]
    ]
    return {
        "spot": s[::4].round(1).tolist(),
        "pnl": pnl[::4].round(1).tolist(),
        "breakevens": be,
        "max_profit": None if unlimited_profit else round(float(max(ends)), 1),
        "max_loss": None if unlimited_loss else round(float(min(ends)), 1),
    }
