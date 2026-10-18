"""Stage 4 -- features: one row per decision minute with its inputs and what each trade would pay.

Reads the minute bars (stage 3) and writes data/features/features.parquet plus
reports/features.json. Plain pandas on purpose: after `bars` the data is ~1M rows,
which Spark would only slow down.

A ROW is "the market at the end of minute t on one day". At that moment we could buy the
at-the-money call (CE) or put (PE) of the nearest expiry, and sell it `horizon_min`
minutes later.

CONVENTIONS (every one of these changes the answer, so each is stated):
  decision time   end of minute t. Everything used is from ticks at or before that moment.
  contract        ATM = round(spot/strike_step)*strike_step, spot = last NIFTY index tick in
                  minute t. Nearest expiry that day. Re-chosen EVERY minute, because each
                  minute is a fresh decision. Identified by instrument_key, never by strike.
  entry           ask side of that contract's book at its last tick in minute t. Row is
                  DROPPED if that tick is older than entry_max_age_s, the 5 levels cannot fill
                  `qty`, or the premium is below min_entry_premium. All three are known at
                  decision time, so the same filter applies in training and in evaluation.
  exit            bid side of THE SAME instrument_key, book as it stood at the end of minute
                  t+horizon (carried forward if that minute had no tick). NO filter at the exit:
                  every entered trade gets an exit, however stale the book. If the visible
                  depth cannot absorb `qty`, the remainder is sold at the deepest visible
                  price (flagged *_exit_thin).
  not used        tick COUNTS. The recorder subscribed to more strikes from 11-Aug and added an
                  instrument on 15-Sep, so counts change with the recorder, not the market.
  not modelled    latency, market impact beyond the visible 5 levels.

Outputs per row: day, minute, split, contract keys, spot, ce_*/pe_* features, and for each side
entry, exit, gross and statutory rupees (costs.slippage is applied later, in labels.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from optpred import runlog
from optpred.labels import ACTION_NAMES, label_actions, statutory_cost_rs
from optpred.spark_common import SESSION_FIRST_MIN, SESSION_LAST_MIN

log = logging.getLogger("optpred.features")

MINUTES = np.arange(SESSION_FIRST_MIN, SESSION_LAST_MIN + 1)
BOOK_PRICE = [f"{s}{i}_price" for s in ("bid", "ask") for i in range(1, 6)]
BOOK_QTY = [f"{s}{i}_qty" for s in ("bid", "ask") for i in range(1, 6)]
SIDE_FEATURES = [
    "mid",
    "spread",
    "spread_pct",
    "imb1",
    "imb5",
    "tbq",
    "ret1",
    "ret3",
    "ret5",
    "vol1",
    "vol5",
    "oi_chg5",
]


class FeatureError(RuntimeError):
    """Raised when the bars break an assumption this stage relies on."""


def assign_splits(accepted: list[str], n_val: int, n_test: int) -> dict[str, str]:
    """Whole days in time order: train first, then validation, then the locked test days."""
    days = sorted(accepted)
    if len(days) <= n_val + n_test:
        raise FeatureError(f"{len(days)} days is not enough for {n_val} validation + {n_test} test days")
    cut_val, cut_test = len(days) - n_val - n_test, len(days) - n_test
    return {d: "train" if i < cut_val else "val" if i < cut_test else "test" for i, d in enumerate(days)}


def fill_price(prices, qtys, need: float, allow_thin: bool = False) -> float:
    """Average price for `need` units walking the visible book (best level first)."""
    got = cost = 0.0
    last = np.nan
    for p, q in zip(prices, qtys, strict=True):
        if not (p > 0 and q > 0):
            break
        take = min(q, need - got)
        cost += p * take
        got += take
        last = p
        if got >= need:
            return cost / need
    if allow_thin and got > 0:
        return (cost + last * (need - got)) / need
    return np.nan


def _fills(book: pd.DataFrame, side: str, qty: int, allow_thin: bool) -> np.ndarray:
    p = book[[f"{side}{i}_price" for i in range(1, 6)]].to_numpy(float)
    q = book[[f"{side}{i}_qty" for i in range(1, 6)]].to_numpy(float)
    return np.array([fill_price(p[r], q[r], qty, allow_thin) for r in range(len(book))])


def to_date(col: pd.Series) -> pd.Series:
    """Expiry as a date. ClickHouse writes its Date type to Parquet as days since 1970 (a number)."""
    if pd.api.types.is_numeric_dtype(col):
        return pd.to_datetime(col, unit="D")
    return pd.to_datetime(col)


def _read_day(root: Path, name: str, day: str) -> pd.DataFrame:
    # partitioning=None: read the one day folder as-is (day is already known from its name)
    return pq.read_table(root / name / f"day={day}", partitioning=None).to_pandas()


def instrument_grid(g: pd.DataFrame) -> pd.DataFrame:
    """One contract on every session minute: book carried forward, plus its own features."""
    g = g.drop_duplicates("minute").set_index("minute").reindex(MINUTES)
    g = g.ffill()
    # age of the book at the END of each minute, counted from the last tick seen so far
    g["age_s"] = (g.index.to_numpy() + 1) * 60 - g["last_sod"]
    mid = (g["bid1_price"] + g["ask1_price"]) / 2
    g["mid"] = mid
    g["spread"] = g["ask1_price"] - g["bid1_price"]
    g["spread_pct"] = g["spread"] / mid
    b1, a1 = g["bid1_qty"], g["ask1_qty"]
    g["imb1"] = (b1 - a1) / (b1 + a1)
    sb = g[[f"bid{i}_qty" for i in range(1, 6)]].sum(axis=1, min_count=5)
    sa = g[[f"ask{i}_qty" for i in range(1, 6)]].sum(axis=1, min_count=5)
    g["imb5"] = (sb - sa) / (sb + sa)
    g["tbq"] = (g["total_buy_qty"] - g["total_sell_qty"]) / (g["total_buy_qty"] + g["total_sell_qty"])
    for k in (1, 3, 5):
        g[f"ret{k}"] = np.log(mid / mid.shift(k))
    g["vol1"] = g["volume"].diff().clip(lower=0)
    g["vol5"] = g["vol1"].rolling(5).sum()
    g["oi_chg5"] = g["oi"] - g["oi"].shift(5)
    return g.replace([np.inf, -np.inf], np.nan)


def spot_grid(spot: pd.DataFrame, step: int) -> pd.DataFrame:
    s = spot.drop_duplicates("minute").set_index("minute").reindex(MINUTES).ffill()
    s["spot_age_s"] = (s.index.to_numpy() + 1) * 60 - s["last_sod"]
    c = s["close"]
    s["spot_ret1"], s["spot_ret2"], s["spot_ret3"], s["spot_ret5"] = (
        np.log(c / c.shift(k)) for k in (1, 2, 3, 5)
    )
    s["spot_range5"] = (s["high"].rolling(5).max() - s["low"].rolling(5).min()) / c
    s["spot_rv5"] = np.log(c).diff().rolling(5).std()
    s["atm"] = np.floor(c / step + 0.5) * step
    return s


def chain_features(chain: pd.DataFrame, atm: pd.Series) -> pd.DataFrame:
    """ATM implied volatility, its 5-minute change, and put/call open interest near ATM."""
    out = pd.DataFrame(index=MINUTES, columns=["atm_iv", "iv_gap", "pcr", "iv_chg5", "pcr_chg5"], dtype=float)
    c = chain[chain["expiry_rank"] == chain["expiry_rank"].min()].copy()
    if c.empty:
        return out
    c["strike"] = c["strike"].round().astype(int)
    a = atm.rename("atm").rename_axis("minute").reset_index()
    a["atm"] = a["atm"].round().astype(int)
    at = c.merge(a, left_on=["minute", "strike"], right_on=["minute", "atm"]).drop_duplicates("minute")
    ce_iv, pe_iv = at["ce_iv"].where(at["ce_iv"] > 0), at["pe_iv"].where(at["pe_iv"] > 0)
    iv = pd.DataFrame({"atm_iv": (ce_iv + pe_iv) / 2, "iv_gap": pe_iv - ce_iv}).set_axis(
        at["minute"].to_numpy()
    )
    near = c.merge(a, on="minute")
    near = near[(near["strike"] - near["atm"]).abs() <= 5 * 50]
    oi = near.groupby("minute")[["ce_oi", "pe_oi"]].sum()
    pcr = (oi["pe_oi"] / oi["ce_oi"]).replace([np.inf, -np.inf], np.nan).rename("pcr")
    out.update(iv.reindex(MINUTES))
    out["pcr"] = pcr.reindex(MINUTES)
    out[["atm_iv", "iv_gap", "pcr"]] = out[["atm_iv", "iv_gap", "pcr"]].ffill(limit=3)
    out["iv_chg5"] = out["atm_iv"] - out["atm_iv"].shift(5)
    out["pcr_chg5"] = out["pcr"] - out["pcr"].shift(5)
    return out


def build_day(day: str, bars_dir: Path, p: dict, drops: dict) -> pd.DataFrame:
    """All decision rows for one day. `drops` counts every row removed, by reason."""
    h, qty, age_max = p["horizon_min"], p["qty"], p["entry_max_age_s"]
    opt = _read_day(bars_dir, "opt", day)
    opt["expiry"] = to_date(opt["expiry"])
    near_exp = opt.loc[opt["expiry"] >= pd.Timestamp(day), "expiry"].min()
    if pd.isna(near_exp):
        raise FeatureError(
            f"{day}: no option expiry on or after the day. expiry dtype={opt['expiry'].dtype}, "
            f"range {opt['expiry'].min()} .. {opt['expiry'].max()}, {len(opt)} bar rows"
        )
    near = opt[opt["expiry"] == near_exp]
    key_of = near.drop_duplicates(["strike", "side", "instrument_key"])
    if key_of.duplicated(["strike", "side"]).any():
        raise FeatureError(
            f"{day}: a strike/side maps to more than one instrument_key in expiry {near_exp:%F}"
        )
    ce_key = key_of[key_of["side"] == "CE"].set_index("strike")["instrument_key"]
    pe_key = key_of[key_of["side"] == "PE"].set_index("strike")["instrument_key"]

    grids = {
        k: instrument_grid(g.drop(columns=["instrument_key", "expiry", "strike", "side"]))
        for k, g in near.groupby("instrument_key")
    }
    G = pd.concat(grids, names=["instrument_key", "minute"])

    sp = spot_grid(_read_day(bars_dir, "spot", day), p["strike_step"])
    ch = chain_features(_read_day(bars_dir, "chain", day), sp["atm"])

    last_entry = SESSION_LAST_MIN - h
    d = pd.DataFrame({"minute": np.arange(p["first_minute"], last_entry + 1)})
    d["day"] = day
    n0 = len(d)
    d = d.join(
        sp[
            [
                "close",
                "spot_age_s",
                "spot_ret1",
                "spot_ret2",
                "spot_ret3",
                "spot_ret5",
                "spot_range5",
                "spot_rv5",
                "atm",
            ]
        ],
        on="minute",
    )
    d = d.rename(columns={"close": "spot"}).join(ch, on="minute")
    ok = d["spot_age_s"] <= age_max
    drops["spot_stale"] += int((~ok).sum())
    d = d[ok].copy()
    d["strike"] = d["atm"]
    d["ce_key"], d["pe_key"] = d["atm"].map(ce_key), d["atm"].map(pe_key)
    ok = d["ce_key"].notna() & d["pe_key"].notna()
    drops["no_contract"] += int((~ok).sum())
    d = d[ok].copy()
    d["expiry"], d["dte"] = near_exp, (near_exp - pd.Timestamp(day)).days
    d["is_expiry_day"] = int(d["dte"].iloc[0] == 0) if len(d) else 0
    d["mins_to_close"] = SESSION_LAST_MIN - d["minute"]

    book_cols = BOOK_PRICE + BOOK_QTY
    for side, keycol in (("ce", "ce_key"), ("pe", "pe_key")):
        at_in = G.reindex(pd.MultiIndex.from_arrays([d[keycol], d["minute"]]))
        at_out = G.reindex(pd.MultiIndex.from_arrays([d[keycol], d["minute"] + h]))
        at_in.index = at_out.index = d.index
        for f in SIDE_FEATURES:
            d[f"{side}_{f}"] = at_in[f]
        d[f"{side}_age_s"] = at_in["age_s"]
        d[f"{side}_entry"] = _fills(at_in[book_cols], "ask", qty, allow_thin=False)
        d[f"{side}_exit"] = _fills(at_out[book_cols], "bid", qty, allow_thin=True)
        d[f"{side}_exit_age_s"] = at_out["age_s"]
        strict = _fills(at_out[book_cols], "bid", qty, allow_thin=False)
        d[f"{side}_exit_thin"] = (np.isnan(strict) & d[f"{side}_exit"].notna()).astype(int)
    for reason, bad in (
        (
            "stale_entry",
            (d["ce_age_s"] > age_max)
            | (d["pe_age_s"] > age_max)
            | d["ce_age_s"].isna()
            | d["pe_age_s"].isna(),
        ),
        ("thin_entry", d["ce_entry"].isna() | d["pe_entry"].isna()),
        ("low_premium", (d["ce_entry"] < p["min_entry_premium"]) | (d["pe_entry"] < p["min_entry_premium"])),
    ):
        drops[reason] += int(bad.sum())
        d = d[~bad]
    for side in ("ce", "pe"):
        d[f"{side}_gross_rs"] = (d[f"{side}_exit"] - d[f"{side}_entry"]) * qty
        d[f"{side}_stat_rs"] = statutory_cost_rs(d[f"{side}_entry"], d[f"{side}_exit"], qty)
    drops["rows_possible"] += n0
    drops["rows_kept"] += len(d)
    return d.drop(columns=["atm"]).reset_index(drop=True)


def report(df: pd.DataFrame, drops: dict, p: dict, costs: dict) -> dict:
    """Numbers for the report: row counts, label balance per split, the break-even hurdle."""
    rep: dict = {"drops": dict(drops), "rows": len(df), "per_split": {}}
    for split, g in df.groupby("split"):
        item = {"days": int(g["day"].nunique()), "rows": len(g), "label_share_by_slippage": {}}
        for slip in costs["sensitivity_pts_per_leg"]:
            lab = label_actions(g, slip, p["qty"])
            item["label_share_by_slippage"][str(slip)] = {
                n: round(float((lab == c).mean()), 4) for c, n in ACTION_NAMES.items()
            }
        item["mean_gross_rs"] = {s: round(float(g[f"{s}_gross_rs"].mean()), 2) for s in ("ce", "pe")}
        item["mean_stat_rs"] = {s: round(float(g[f"{s}_stat_rs"].mean()), 2) for s in ("ce", "pe")}
        item["median_spread_pts"] = {s: round(float(g[f"{s}_spread"].median()), 3) for s in ("ce", "pe")}
        rep["per_split"][split] = item
    rep["exit_thin_rows"] = int(df["ce_exit_thin"].sum() + df["pe_exit_thin"].sum())
    rep["exit_age_s_p50_p95_max"] = [
        round(float(x), 1)
        for x in np.nanpercentile(np.r_[df["ce_exit_age_s"], df["pe_exit_age_s"]], [50, 95, 100])
    ]
    return rep


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", default="params.yaml")
    args = ap.parse_args(argv)
    with open(args.params) as f:
        params = yaml.safe_load(f)
    p, costs, bars_dir = params["features"], params["costs"], Path(params["bars"]["out_dir"])
    accepted = json.loads(Path("data/days.json").read_text())["accepted"]
    splits = assign_splits(accepted, p["n_val_days"], p["n_test_days"])

    drops = dict.fromkeys(
        [
            "spot_stale",
            "no_contract",
            "stale_entry",
            "thin_entry",
            "low_premium",
            "rows_possible",
            "rows_kept",
        ],
        0,
    )
    frames = []
    for day in sorted(accepted):
        d = build_day(day, bars_dir, p, drops)
        d["split"] = splits[day]
        frames.append(d)
        log.info(
            "%s %-5s %4d rows  (expiry %s, dte %d)",
            day,
            splits[day],
            len(d),
            d["expiry"].iloc[0].date() if len(d) else "-",
            d["dte"].iloc[0] if len(d) else -1,
        )
    df = pd.concat(frames, ignore_index=True)

    out = Path(p["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "features.parquet", index=False)
    Path("data/splits.json").write_text(json.dumps(splits, indent=1))
    rep = report(df, drops, p, costs)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/features.json").write_text(json.dumps(rep, indent=1))

    summary.update(
        rows=len(df),
        days=len(accepted),
        drops=drops,
        split_days={s: int(sum(v == s for v in splits.values())) for s in ("train", "val", "test")},
    )
    for split, item in rep["per_split"].items():
        log.info(
            "%-5s %2d days %6d rows  label share @0.31: %s",
            split,
            item["days"],
            item["rows"],
            item["label_share_by_slippage"].get("0.31"),
        )
    log.info(
        "dropped: %s",
        {k: v for k, v in drops.items() if k.startswith(("spot", "no_", "stale", "thin", "low"))},
    )
    return 0


if __name__ == "__main__":
    sys.exit(runlog.run("features", main))
