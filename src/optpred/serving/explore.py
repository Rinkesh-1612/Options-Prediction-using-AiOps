"""Read-only data for the explore page: the calendar, implied volatility over days, one day by the minute,
the smile and the term structure. Everything comes from files (data/grid, data/clean/option_chain_snap,
data/modelout); no model runs here."""

from __future__ import annotations

import functools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from optpred.vol.inputs import YEAR_S, inputs, targets

BIG_MOVE_PCT = 1.0  # |close / open - 1| at or above this is a "big move" day
BIG_RANGE_PCT = 1.5  # or a high-to-low range at or above this
MINUTE_FROM, MINUTE_TO = 34200, 54000  # 09:30 .. 15:00, the span the page shows
CHAIN_WINDOW_S = 120  # a chain snapshot may be this old
GRID_COLS = ["sod", "spot", "atm", "dte", "ce_iv", "pe_iv"]


def ann_vol(move_bp, h: int):
    """A move over h seconds, in bp, as an annual volatility in percent (the unit of implied volatility)."""
    return np.asarray(move_bp, float) / 1e4 / math.sqrt(h / YEAR_S) * 100


def num(x, nd: int = 2):
    return round(float(x), nd) if x is not None and math.isfinite(x) else None


def col(values, nd: int = 2) -> list[float | None]:
    return [num(x, nd) for x in values]


@functools.lru_cache(maxsize=256)
def _grid(path: str, mtime: int) -> pd.DataFrame:
    g = pd.read_parquet(path, columns=GRID_COLS).sort_values("sod").reset_index(drop=True)
    g["iv"] = (g["ce_iv"] + g["pe_iv"]) / 2
    return g


@functools.lru_cache(maxsize=256)
def _day_frame(path: str, mtime: int) -> pd.DataFrame:
    """Grid columns + the vol inputs and targets, one row per second."""
    g = _grid(path, mtime)
    full = pd.read_parquet(path).sort_values("sod").reset_index(drop=True)
    return pd.concat([g[["sod", "spot", "iv"]], inputs(full), targets(full)], axis=1)


@functools.lru_cache(maxsize=256)
def _chain(path: str, mtime: int) -> pd.DataFrame:
    return pd.read_parquet(path).sort_values(["sod", "expiry_rank", "strike"]).reset_index(drop=True)


@functools.lru_cache(maxsize=512)
def _modelout(path: str, mtime: int) -> pd.DataFrame:
    return pd.read_parquet(path)


def _mt(p: Path) -> int:
    return p.stat().st_mtime_ns


def explore_router(st, accepted, vol_champion) -> APIRouter:
    """`st`: API Settings; `accepted()`: the days; `vol_champion()`: the volatility family shown."""
    r = APIRouter(prefix="/explore")

    def need(day: str) -> Path:
        if day not in accepted():
            raise HTTPException(404, f"no data for {day}")
        p = st.grid_dir / f"{day}.parquet"
        if not p.exists():
            raise HTTPException(503, f"data for {day} is not available now")
        return p

    def split_of() -> dict[str, str]:
        p = st.zoo_dir / "test.json"
        test = set(json.loads(p.read_text())["test_days"]) if p.exists() else set()
        return {d: ("test" if d in test else "dev") for d in accepted()}

    def drift_flags() -> dict[str, bool]:
        p = st.reports_dir / "drift" / "daily.json"
        return {k: bool(v["drift"]) for k, v in json.loads(p.read_text()).items()} if p.exists() else {}

    def source_of() -> dict[str, str]:
        p = st.reports_dir / "modelout.json"
        return json.loads(p.read_text())["source"] if p.exists() else {}

    def forecast(day: str) -> pd.DataFrame | None:
        """Our volatility forecast of the day: minute rows with fc_300, fc_900 (None before the stage ran)."""
        p = st.modelout_dir / "vol" / f"{day}.parquet"
        if not p.exists():
            return None
        d = _modelout(str(p), _mt(p))
        fam = vol_champion()
        d = d[d["family"] == fam] if (d["family"] == fam).any() else d[d["family"] == "har_iv"]
        return d.set_index("sod")[["fc_300", "fc_900"]] if len(d) else None

    def minute_rows(day: str) -> pd.DataFrame:
        p = need(day)
        f = _day_frame(str(p), _mt(p))
        return f[(f["sod"] >= MINUTE_FROM) & (f["sod"] <= MINUTE_TO) & (f["sod"] % 60 == 0)].set_index("sod")

    @r.get("/days")
    def days():
        """One row per day for the calendar: kind of day, how it moved and its events."""
        split, drift, src = split_of(), drift_flags(), source_of()
        out = []
        for d in accepted():
            p = st.grid_dir / f"{d}.parquet"
            if not p.exists():
                continue
            g = _grid(str(p), _mt(p))
            sp = g["spot"].dropna()
            if sp.empty:
                continue
            o, c, hi, lo = sp.iloc[0], sp.iloc[-1], sp.max(), sp.min()
            ret, rng = (c / o - 1) * 100, (hi - lo) / o * 100
            iv = g.loc[g["sod"] >= MINUTE_FROM, "iv"].dropna()
            events = (
                (["expiry"] if int(g["dte"].iloc[0]) == 0 else [])
                + (["big_move"] if abs(ret) >= BIG_MOVE_PCT or rng >= BIG_RANGE_PCT else [])
                + (["drift"] if drift.get(d) else [])
            )
            out.append(
                {
                    "day": d,
                    "weekday": pd.Timestamp(d).strftime("%a"),
                    "split": split.get(d, "dev"),
                    "source": src.get(d),
                    "open": num(o),
                    "close": num(c),
                    "ret_pct": num(ret),
                    "range_pct": num(rng),
                    "dte": int(g["dte"].iloc[0]),
                    "atm_iv": num(iv.mean()) if len(iv) else None,
                    "events": events,
                }
            )
        return out

    @r.get("/iv/daily")
    def iv_daily():
        """Per day: mean ATM IV, our forecast volatility and realized volatility, all in annual percent."""
        split, out = split_of(), []
        for d in accepted():
            p = st.grid_dir / f"{d}.parquet"
            if not p.exists():
                continue
            rows = minute_rows(d)
            rows = rows[rows["rv_fwd_900"].notna() & rows["iv"].notna()]
            if rows.empty:
                continue
            fc = forecast(d)
            fcv = None
            if fc is not None:
                j = fc.reindex(rows.index)["fc_900"].dropna()
                fcv = num(ann_vol(j.mean(), 900)) if len(j) else None
            iv, rv = rows["iv"].mean(), ann_vol(rows["rv_fwd_900"].mean(), 900)
            out.append(
                {
                    "day": d,
                    "split": split.get(d, "dev"),
                    "iv": num(iv),
                    "forecast": fcv,
                    "realized": num(float(rv)),
                    "iv_rich_share": num(float((rows["iv"] > ann_vol(rows["rv_fwd_900"], 900)).mean()), 3),
                }
            )
        return out

    @r.get("/iv/day")
    def iv_day(day: str):
        """One day by the minute: spot, ATM IV, our forecast and realized volatility (annual %)."""
        rows = minute_rows(day)
        fc = forecast(day)
        out = {
            "day": day,
            "sod": [int(s) for s in rows.index],
            "spot": col(rows["spot"]),
            "iv": col(rows["iv"]),
            "realized": col(ann_vol(rows["rv_fwd_900"], 900)),
            "forecast": col(ann_vol(fc.reindex(rows.index)["fc_900"], 900)) if fc is not None else None,
        }
        return out

    def chain_of(day: str) -> pd.DataFrame:
        p = st.chain_dir / f"{day}.parquet"
        if day not in accepted():
            raise HTTPException(404, f"no data for {day}")
        if not p.exists():
            raise HTTPException(503, f"option chain for {day} is not available now")
        return _chain(str(p), _mt(p))

    def snapshot(c: pd.DataFrame, t: int) -> pd.DataFrame:
        """The chain at time t: the latest row of every (expiry, strike) in the 2 minutes up to t.
        The feed sends one expiry at a time, so a single second holds only part of the chain."""
        w = c[(c["sod"] <= t) & (c["sod"] > t - CHAIN_WINDOW_S)]
        if w.empty:  # before the first snapshot: take the first 2 minutes
            w = c[c["sod"] < c["sod"].min() + CHAIN_WINDOW_S]
        return w.groupby(["expiry_rank", "strike"], as_index=False).last()

    @functools.lru_cache(maxsize=64)
    def _atm(day: str, mtime: int) -> pd.DataFrame:
        """ATM IV of each expiry rank at every second that has a row (index = sod, columns = ranks)."""
        c = chain_of(day)
        i = (c["strike"] - c["spot"]).abs().groupby([c["sod"], c["expiry_rank"]]).idxmin()
        a = c.loc[i.to_numpy()]
        a = a.assign(iv=(a["ce_iv"] + a["pe_iv"]) / 2)
        return a.pivot_table(index="sod", columns="expiry_rank", values="iv", aggfunc="last").sort_index()

    @r.get("/iv/smile")
    def iv_smile(day: str, t: int):
        """IV by strike for each expiry in the chain at the time t (seconds of day)."""
        s = snapshot(chain_of(day), t)
        return {
            "day": day,
            "sod": int(t),
            "spot": num(s["spot"].iloc[-1]),
            "expiries": [
                {
                    "expiry": str(e["expiry"].iloc[0]),
                    "dte": int(e["dte"].iloc[0]),
                    "strikes": [float(x) for x in e["strike"]],
                    "call_iv": col(e["ce_iv"]),
                    "put_iv": col(e["pe_iv"]),
                }
                for _, e in s.groupby("expiry_rank")
            ],
        }

    @r.get("/iv/term")
    def iv_term(day: str, t: int):
        """ATM IV of each expiry at the time t, and of the first two expiries through the day."""
        c = chain_of(day)
        s = snapshot(c, t)

        def atm(e: pd.DataFrame) -> float | None:
            i = (e["strike"] - e["spot"]).abs().idxmin()
            return num((e.loc[i, "ce_iv"] + e.loc[i, "pe_iv"]) / 2)

        at = [
            {"expiry": str(e["expiry"].iloc[0]), "dte": int(e["dte"].iloc[0]), "iv": atm(e)}
            for _, e in s.groupby("expiry_rank")
        ]
        a = _atm(day, _mt(st.chain_dir / f"{day}.parquet"))
        minutes = np.arange(MINUTE_FROM, MINUTE_TO + 1, 60)
        g = a.reindex(a.index.union(minutes)).ffill(limit=CHAIN_WINDOW_S).reindex(minutes)
        series = {"sod": [int(m) for m in minutes]} | {
            name: col(g[k]) if k in g else [None] * len(minutes) for name, k in (("near", 0), ("next", 1))
        }
        return {"day": day, "sod": int(t), "at": at, "series": series}

    return r
