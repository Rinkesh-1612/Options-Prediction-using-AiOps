"""Stage 4b -- micro: one row per decision SECOND with microstructure inputs and barrier-exit trades.

Reads the per-second tables of the `ticks` stage and follows docs/V2_PROTOCOL.md exactly.

A ROW is "the market at the end of second t". At that moment we could buy the at-the-money call (CE) or
put (PE) of the nearest expiry. Each side's trade is then followed second by second until a barrier:
  take profit   best bid >= entry + take_profit_pts
  stop loss     best bid <= entry - stop_loss_pts
  time stop     max_hold_s seconds after entry
The exit sells `qty` into the bid side of that second's book (walking the 5 levels), so a jump past a
barrier fills at the worse price. Costs are applied later (labels.py), so slippage stays a setting.

CONVENTIONS (each one changes the answer, so each is stated):
  decision time   end of second t. Every input uses ticks at or before that moment.
  contract        ATM = round(spot / strike_step) * strike_step from the last index tick at or before t;
                  nearest expiry; re-chosen every second. Identified by instrument_key.
  entry           ask side of that contract's book for `qty`. The row is DROPPED if the last tick is older
                  than entry_max_age_s, the 5 levels cannot fill `qty`, or the premium is below
                  min_entry_premium, for either side. All known at decision time.
  barriers        checked on the last book of each later second, same instrument_key.
  chain inputs    ATM IV and its 5-minute change from the v1 features of the PREVIOUS minute (already known).
Outputs: data/micro/micro.parquet and reports/micro.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from optpred import runlog
from optpred.clock import IST_OFFSET_S
from optpred.labels import statutory_cost_rs

log = logging.getLogger("optpred.micro")

SEC0, SEC_END = 9 * 3600 + 15 * 60, 15 * 3600 + 30 * 60 - 1  # the session grid, 09:15:00 .. 15:29:59
GRID = np.arange(SEC0, SEC_END + 1)
LEVELS = range(1, 6)
SIDE_FEATURES = [
    "spread",
    "spread_pct",
    "micro_gap",
    "imb1",
    "imb5",
    "top_gap",
    "ofi1",
    "ofi5",
    "ofi15",
    "ofi30",
    "sv5",
    "sv15",
    "sv30",
    "qa_chg5",
    "qb_chg5",
    "ticks30",
    "ret5",
    "ret15",
    "ret30",
    "ret60",
    "age",
]
MARKET_FEATURES = [
    "fut_ret1",
    "fut_ret5",
    "fut_ret15",
    "fut_ret30",
    "fut_sv1",
    "fut_sv5",
    "fut_sv15",
    "fut_sv30",
    "spot_ret5",
    "spot_ret15",
    "spot_ret60",
    "spot_rv60",
    "lead_gap5",
    "atm_iv",
    "iv_chg5",
    "sec",
    "dte",
]
# The model's inputs, shared by training and evaluation. Nothing here looks past second t.
MICRO_COLUMNS = [f"{s}_{f}" for s in ("ce", "pe") for f in SIDE_FEATURES] + MARKET_FEATURES


class MicroError(RuntimeError):
    """The micro stage cannot build its table."""


# ----------------------------------------------------------------------------- small array helpers
def rsum(x: np.ndarray, k: int) -> np.ndarray:
    """Sum of the last k values (this one included); NaN until k values exist."""
    c = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x))])
    out = np.full(len(x), np.nan)
    out[k - 1 :] = c[k:] - c[:-k]
    return out


def lag(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    return out


def logret(x: np.ndarray, k: int) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log(x / lag(x, k))


def fill_vec(prices: np.ndarray, qtys: np.ndarray, need: float, allow_thin: bool) -> np.ndarray:
    """Average price for `need` units walking the book, row by row (vectorised features.fill_price)."""
    valid = np.cumprod((prices > 0) & (qtys > 0), axis=1).astype(bool)  # stop at the first empty level
    q = np.where(valid, qtys, 0.0)
    before = np.cumsum(q, axis=1) - q
    take = np.clip(need - before, 0.0, q)
    cost, got = (np.where(valid, prices, 0.0) * take).sum(axis=1), take.sum(axis=1)
    out = np.where(got >= need - 1e-9, cost / need, np.nan)
    if allow_thin:
        n_valid = valid.sum(axis=1)
        last = np.where(n_valid > 0, prices[np.arange(len(prices)), np.maximum(n_valid - 1, 0)], np.nan)
        out = np.where(np.isnan(out) & (got > 0), (cost + last * (need - got)) / need, out)
    return out


def barrier_exits(entry, bid1, exit_fill, tp: float, sl: float, max_hold: int):
    """For a trade entered at every second t: exit price, seconds held and reason (1 TP, 2 SL, 3 time)."""
    n = len(entry)
    exit_px, hold, reason = np.full(n, np.nan), np.zeros(n, dtype=np.int16), np.zeros(n, dtype=np.int8)
    alive = np.isfinite(entry)
    for k in range(1, max_hold + 1):
        j = np.minimum(np.arange(n) + k, n - 1)
        b = bid1[j]
        hit_tp = alive & (b >= entry + tp)
        hit_sl = alive & (b <= entry - sl)
        for hit, code in ((hit_tp, 1), (hit_sl, 2)):
            exit_px[hit], hold[hit], reason[hit] = exit_fill[j[hit]], k, code
        alive &= ~(hit_tp | hit_sl)
    j = np.minimum(np.arange(n) + max_hold, n - 1)
    exit_px[alive], hold[alive], reason[alive] = exit_fill[j[alive]], max_hold, 3
    return exit_px, hold, reason


def trailing_exits(entry, bid1, exit_fill, stop: float, start: float, trail: float, max_hold: int):
    """Sprint trial C: stop at entry - stop; once the bid reaches entry + start, the stop trails `trail`
    below the highest bid since entry; time stop after max_hold.

    Returns exit price, seconds held and reason (2 stop, 3 time). The stop level at second k uses only the
    bids before k, so a single second can never both raise the stop and trigger it.
    """
    n = len(entry)
    exit_px, hold, reason = np.full(n, np.nan), np.zeros(n, dtype=np.int16), np.zeros(n, dtype=np.int8)
    alive = np.isfinite(entry)
    best = np.full(n, -np.inf)
    for k in range(1, max_hold + 1):
        j = np.minimum(np.arange(n) + k, n - 1)
        b = bid1[j]
        level = np.where(best >= entry + start, best - trail, entry - stop)  # the stop set by earlier seconds
        hit = alive & (b <= level)
        exit_px[hit], hold[hit], reason[hit] = exit_fill[j[hit]], k, 2
        alive &= ~hit
        best = np.where(alive, np.fmax(best, b), best)
    j = np.minimum(np.arange(n) + max_hold, n - 1)
    exit_px[alive], hold[alive], reason[alive] = exit_fill[j[alive]], max_hold, 3
    return exit_px, hold, reason


def max_excursion(x: np.ndarray, horizon: int) -> np.ndarray:
    """Largest |x[t+k] - x[t]| for k = 1..horizon. A LABEL (it looks ahead), never an input."""
    out = np.zeros(len(x))
    for k in range(1, horizon + 1):
        out = np.fmax(out, np.abs(np.roll(x, -k) - x))
    out[len(x) - horizon :] = np.nan  # not enough future left
    return out


# ----------------------------------------------------------------------------- per contract
def contract_series(rows: pd.DataFrame, day_epoch: float, p: dict) -> dict[str, np.ndarray]:
    """Second-grid features, entry/exit fills and barrier trades for ONE contract on one day."""
    g = rows.set_index("sec").reindex(GRID)
    book = [f"{s}{i}_{k}" for s in ("bid", "ask") for i in LEVELS for k in ("price", "qty")]
    g[book + ["ltp", "last_ts_ns"]] = g[book + ["ltp", "last_ts_ns"]].ffill()
    flow = {c: g[c].fillna(0.0).to_numpy(float) for c in ("ofi", "vol", "signed_vol", "ticks")}
    b1, a1 = g["bid1_price"].to_numpy(float), g["ask1_price"].to_numpy(float)
    bq1, aq1 = g["bid1_qty"].to_numpy(float), g["ask1_qty"].to_numpy(float)
    bqs = g[[f"bid{i}_qty" for i in LEVELS]].to_numpy(float).sum(axis=1)
    aqs = g[[f"ask{i}_qty" for i in LEVELS]].to_numpy(float).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        mid = (a1 + b1) / 2
        depth = pd.Series(bq1 + aq1).rolling(300, min_periods=30).mean().to_numpy()
        f = {
            "spread": a1 - b1,
            "spread_pct": (a1 - b1) / mid,
            "micro_gap": (a1 * bq1 + b1 * aq1) / (bq1 + aq1) - mid,
            "imb1": (bq1 - aq1) / (bq1 + aq1),
            "imb5": (bqs - aqs) / (bqs + aqs),
            "top_gap": bq1 / bqs - aq1 / aqs,
            "qa_chg5": (aq1 - lag(aq1, 5)) / depth,
            "qb_chg5": (bq1 - lag(bq1, 5)) / depth,
            "ticks30": rsum(flow["ticks"], 30),
            "age": day_epoch + GRID + 1 - g["last_ts_ns"].to_numpy(float) / 1e9,
        }
        for k in (1, 5, 15, 30):
            f[f"ofi{k}"] = rsum(flow["ofi"], k) / depth
        for k in (5, 15, 30):
            f[f"sv{k}"] = rsum(flow["signed_vol"], k) / (rsum(flow["vol"], k) + p["qty"])
        for k in (5, 15, 30, 60):
            f[f"ret{k}"] = logret(mid, k)
    f["chg5"] = mid - lag(mid, 5)  # for the lead-lag gap; not a model input on its own

    bp = g[[f"bid{i}_price" for i in LEVELS]].to_numpy(float)
    bq = g[[f"bid{i}_qty" for i in LEVELS]].to_numpy(float)
    ap = g[[f"ask{i}_price" for i in LEVELS]].to_numpy(float)
    aq = g[[f"ask{i}_qty" for i in LEVELS]].to_numpy(float)
    entry = fill_vec(np.nan_to_num(ap), np.nan_to_num(aq), p["qty"], allow_thin=False)
    exit_fill = fill_vec(np.nan_to_num(bp), np.nan_to_num(bq), p["qty"], allow_thin=True)
    ok = (f["age"] <= p["entry_max_age_s"]) & (entry >= p["min_entry_premium"])
    entry = np.where(ok, entry, np.nan)
    exit_px, hold, reason = barrier_exits(
        entry,
        b1,
        exit_fill,
        p["take_profit_pts"],
        p["stop_loss_pts"],
        p["max_hold_s"],  # NaN bid: no barrier
    )
    f.update(entry=entry, exit=exit_px, hold_s=hold.astype(float), reason=reason.astype(float))
    tr_px, tr_hold, _ = trailing_exits(
        entry, b1, exit_fill, p["stop_loss_pts"], p["trail_start_pts"], p["trail_pts"], p["trail_max_hold_s"]
    )
    f.update(tr_exit=tr_px, tr_hold_s=tr_hold.astype(float))
    # sprint trial E: in this second the best ask rose by a jump and aggressive buyers traded at least N lots
    with np.errstate(invalid="ignore"):
        f["sweep"] = (
            ((a1 - lag(a1, 1)) >= p["sweep_min_ask_jump"])
            & (flow["signed_vol"] >= p["sweep_min_lots"] * p["qty"])
        ).astype(float)
    return f


# ----------------------------------------------------------------------------- per day
def build_day(day: str, ticks_dir: str, feats_path: str, p: dict) -> pd.DataFrame:
    def read(name):
        return pd.read_parquet(f"{ticks_dir}/{name}/day={day}")

    opt, fut, spot = read("opt"), read("fut"), read("spot")
    if opt.empty or spot.empty:
        return pd.DataFrame()
    day_epoch = (pd.Timestamp(day) - pd.Timestamp("1970-01-01")).total_seconds() - IST_OFFSET_S
    s = spot.set_index("sec")["ltp"].reindex(GRID).ffill().to_numpy(float)
    fl = fut.set_index("sec").reindex(GRID)
    fp = fl["ltp"].ffill().to_numpy(float)
    fsv, fv = fl["signed_vol"].fillna(0).to_numpy(float), fl["vol"].fillna(0).to_numpy(float)
    r1 = logret(s, 1)
    market = {
        **{f"fut_ret{k}": logret(fp, k) for k in (1, 5, 15, 30)},
        **{f"fut_sv{k}": rsum(fsv, k) / (rsum(fv, k) + p["qty"]) for k in (1, 5, 15, 30)},
        **{f"spot_ret{k}": logret(s, k) for k in (5, 15, 60)},
        "spot_rv60": np.sqrt(rsum(r1**2, 60)),
        "sec": GRID.astype(float),
    }
    fut_chg5 = fp - lag(fp, 5)

    keys = opt[["instrument_key", "strike", "side", "expiry"]].drop_duplicates("instrument_key")
    series = {k: contract_series(g, day_epoch, p) for k, g in opt.groupby("instrument_key")}
    atm = np.round(s / p["strike_step"]) * p["strike_step"]
    lookup = {(round(r.strike), r.side): r.instrument_key for r in keys.itertuples()}
    expiry = pd.Timestamp(keys["expiry"].iloc[0])
    dec = (GRID >= p["first_sec"]) & (GRID <= p["last_sec"]) & np.isfinite(atm)
    idx = np.flatnonzero(dec)

    out = {"day": day, "sec_idx": idx}
    for side in ("ce", "pe"):
        names = [lookup.get((int(a), side.upper())) for a in atm[idx]]
        cols = SIDE_FEATURES + ["entry", "exit", "hold_s", "reason", "chg5", "tr_exit", "tr_hold_s", "sweep"]
        mat = {c: np.full(len(idx), np.nan) for c in cols}
        mat["key"] = np.array(names, dtype=object)
        for key in set(n for n in names if n is not None):
            rows = np.flatnonzero(mat["key"] == key)
            for c in cols:
                mat[c][rows] = series[key][c][idx[rows]]
        for c, v in mat.items():
            out[f"{side}_{c}"] = v
    df = pd.DataFrame(out)
    for c, v in market.items():
        df[c] = v[idx]
    df["lead_gap5"] = fut_chg5[idx] - (df["ce_chg5"] - df["pe_chg5"])
    df["strike"] = atm[idx]
    df["spot"] = s[idx]
    df["spot_mfe120"] = max_excursion(s, p["big_move_horizon_s"])[idx]  # label for sprint trial A
    df["dte"] = float((expiry - pd.Timestamp(day)).days)
    df = df.drop(columns=["sec_idx", "ce_chg5", "pe_chg5"])

    # chain inputs from the v1 features of the previous minute (already known at second t)
    ch = pd.read_parquet(
        feats_path, columns=["day", "minute", "atm_iv", "iv_chg5"], filters=[("day", "==", day)]
    )
    df["minute"] = (df["sec"] // 60).astype(int) - 1
    df = df.merge(ch.drop(columns="day"), on="minute", how="left").drop(columns="minute")

    df = df[np.isfinite(df["ce_entry"]) & np.isfinite(df["pe_entry"])].copy()
    for side in ("ce", "pe"):
        df[f"{side}_gross_rs"] = (df[f"{side}_exit"] - df[f"{side}_entry"]) * p["qty"]
        df[f"{side}_stat_rs"] = statutory_cost_rs(df[f"{side}_entry"], df[f"{side}_exit"], p["qty"])
        df[f"{side}_tr_gross_rs"] = (df[f"{side}_tr_exit"] - df[f"{side}_entry"]) * p["qty"]
        df[f"{side}_tr_stat_rs"] = statutory_cost_rs(df[f"{side}_entry"], df[f"{side}_tr_exit"], p["qty"])
    num = df.select_dtypes("float64").columns
    df[num] = df[num].astype("float32")
    return df.reset_index(drop=True)


def report(df: pd.DataFrame, p: dict, slip: float) -> dict:
    """Row counts for every split; label statistics for the development days only (no test-day peeking)."""
    rep = {
        "rows": len(df),
        "days": int(df["day"].nunique()),
        "rows_by_split": df["split"].value_counts().to_dict(),
        "label_stats_days": "train+val only",
    }
    df = df[df["split"].isin(["train", "val"])]
    for side in ("ce", "pe"):
        net = df[f"{side}_gross_rs"] - df[f"{side}_stat_rs"] - 2 * slip * p["qty"]
        rep[side] = {
            "win_share": round(float((net > 0).mean()), 4),
            "mean_net_rs": round(float(net.mean()), 2),
            "exit_reason_share": {
                n: round(float((df[f"{side}_reason"] == c).mean()), 4)
                for c, n in ((1, "take_profit"), (2, "stop_loss"), (3, "time"))
            },
            "mean_hold_s": round(float(df[f"{side}_hold_s"].mean()), 1),
        }
    return rep


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, ticks_dir = params["micro"], params["ticks"]["out_dir"]
    feats_path = str(Path(params["features"]["out_dir"]) / "features.parquet")
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    have = {d.name.removeprefix("day=") for d in Path(ticks_dir, "opt").glob("day=*")}
    days = sorted(set(accepted) & have)
    if not days:
        raise MicroError(f"no accepted day has per-second ticks in {ticks_dir}: run the ticks stage first")
    splits = json.loads(Path("data/splits.json").read_text())

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        parts = list(
            pool.map(build_day, days, [ticks_dir] * len(days), [feats_path] * len(days), [p] * len(days))
        )
    for d, part in zip(days, parts, strict=True):
        log.info("%s  %6d decision seconds", d, len(part))
    df = pd.concat([x for x in parts if len(x)], ignore_index=True)
    df["split"] = df["day"].map(splits).fillna("forward")  # days after the v1 freeze are forward days
    out = Path(p["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "micro.parquet", index=False)
    rep = report(df, p, p["slippage_pts_per_leg"])  # v2 headline cost (protocol amendment 1)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/micro.json").write_text(json.dumps(rep, indent=1))
    log.info(
        "rows %d over %d days; CE wins %.1f%%, PE wins %.1f%% at the headline slippage",
        rep["rows"],
        rep["days"],
        100 * rep["ce"]["win_share"],
        100 * rep["pe"]["win_share"],
    )
    summary.update(rows=rep["rows"], days=rep["days"], rows_by_split=rep["rows_by_split"])
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("micro", main))
