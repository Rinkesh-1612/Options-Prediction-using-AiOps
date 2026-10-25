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

from optpred.strategy.legs import TEMPLATES, legs_text, parse_legs
from optpred.strategy.sim import LOT, Unavailable, evaluate, grid_columns, load_quotes
from optpred.vol.inputs import YEAR_S, inputs, targets
from optpred.vol.models import qlike

BASELINES = {"stay_out", "random", "momentum"}
LABEL_COLS = [f"{s}_{c}" for s in ("ce", "pe") for c in ("valid", "net_rs", "hit", "hold_s")] + ["sod"]
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


@functools.lru_cache(maxsize=64)
def _labels(path: str, mtime: int) -> pd.DataFrame:
    return pd.read_parquet(path, columns=LABEL_COLS).set_index("sod")


@functools.lru_cache(maxsize=6)
def _quotes(path: str, mtime: int):
    return load_quotes(pd.read_parquet(path, columns=grid_columns()))


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

    def quotes(day: str):
        p = need(day)
        return _quotes(str(p), _mt(p))

    def priced(day: str, t: int, legs):
        try:
            return evaluate(quotes(day), t, legs)
        except Unavailable as e:
            raise HTTPException(409, str(e)) from e

    @r.get("/strategies")
    def strategies(day: str, t: int):
        """Every ready-made strategy entered at second t: cost, result after 5 / 15 / 30 / 60 min, best exit
        in hindsight, the barrier-rule result, maximum profit and loss. Unpriceable ones carry `error`."""
        q, out = quotes(day), []
        for key, (name, kind, text) in TEMPLATES.items():
            row = {"id": key, "name": name, "kind": kind, "legs_text": text}
            try:
                e = evaluate(q, t, parse_legs(text))
            except Unavailable as err:
                out.append(row | {"error": str(err)})
                continue
            at = {f"m{m}": (e["curve"][m - 1] if m <= len(e["curve"]) else None) for m in (5, 15, 30, 60)}
            out.append(
                row
                | {
                    "legs": e["legs"],
                    "cost": e["cost"],
                    "curve": e["curve"],
                    "at": at,
                    "best_exit": e["best_exit"],
                    "barrier": e["barrier"],
                    "max_profit": e["payoff"]["max_profit"],
                    "max_loss": e["payoff"]["max_loss"],
                    "breakevens": e["payoff"]["breakevens"],
                }
            )
        i = int(np.searchsorted(q.sod, t))
        atm = num(q.atm[i]) if i < len(q.sod) and q.sod[i] == t else None
        return {"day": day, "sod": t, "lot": LOT, "atm": atm, "strategies": out}

    @r.get("/strategy")
    def strategy(day: str, t: int, legs: str):
        """One strategy of 1-4 legs (`buy:ce:0:1,sell:ce:2:2`): quotes, exit curve, barrier result, payoff."""
        try:
            parsed = parse_legs(legs)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"day": day, "sod": t, "legs_text": legs_text(parsed)} | priced(day, t, parsed)

    def direction_rows(day: str) -> pd.DataFrame:
        p = st.modelout_dir / "direction" / f"{day}.parquet"
        if not p.exists():
            raise HTTPException(503, "the model outputs are not computed yet (stage modelout)")
        return _modelout(str(p), _mt(p))

    def labels_of(day: str) -> pd.DataFrame:
        p = st.label_dir / f"{day}.parquet"
        if not p.exists():
            raise HTTPException(503, f"labels for {day} are not available now")
        return _labels(str(p), _mt(p))

    def action_of(row) -> str:
        ce, pe = float(row.score_ce), float(row.score_pe)
        best = max(ce if np.isfinite(ce) else -np.inf, pe if np.isfinite(pe) else -np.inf)
        if not best > row.tau:
            return "STAY_OUT"
        return "BUY_CE" if ce >= pe else "BUY_PE"

    @r.get("/models")
    def models(day: str, t: int):
        """What every model said at the minute of `t`, and what happened.
        Direction models: call, put or stay out, and the net ₹ of following them (one lot, barrier exit).
        Volatility forecasters: forecast vs realized."""
        need(day)
        m = int(t) // 60 * 60
        d, lab = direction_rows(day), labels_of(day)
        at = d[d["sod"] == m]
        row = lab.loc[m] if m in lab.index else None
        out = []
        for x in at.itertuples():
            act = action_of(x)
            side = "ce" if act == "BUY_CE" else "pe" if act == "BUY_PE" else None
            net = {
                s: (num(row[f"{s}_net_rs"], 0) if row is not None and bool(row[f"{s}_valid"]) else None)
                for s in ("ce", "pe")
            }
            followed = net[side] if side else None
            out.append(
                {
                    "family": x.family,
                    "baseline": x.family in BASELINES,
                    "source": x.source,
                    "action": act,
                    "score_ce": num(x.score_ce, 3),
                    "score_pe": num(x.score_pe, 3),
                    "tau": num(x.tau, 3),
                    "ce_net": net["ce"],
                    "pe_net": net["pe"],
                    "result": followed,
                    "ended_by": int(row[f"{side}_hit"]) if side and followed is not None else None,
                }
            )
        rows = minute_rows(day)
        iv, rv = (rows["iv"].get(m), rows["rv_fwd_900"].get(m)) if m in rows.index else (None, None)
        v = st.modelout_dir / "vol" / f"{day}.parquet"
        vol = []
        if v.exists():
            vd = _modelout(str(v), _mt(v))
            for x in vd[vd["sod"] == m].itertuples():
                f = float(ann_vol(x.fc_900, 900))
                vol.append(
                    {
                        "family": x.family,
                        "source": x.source,
                        "forecast": num(f),
                        "kind": "market" if x.family == "implied" else "forecast",
                    }
                )
        return {
            "day": day,
            "sod": m,
            "iv": num(iv),
            "realized": num(float(ann_vol(rv, 900))) if rv is not None and math.isfinite(rv) else None,
            "direction": out,
            "vol": vol,
        }

    @r.get("/models/day")
    def models_day(day: str):
        """The whole day for every model: direction models trade one position at a time at the minute rows
        (net ₹, trades, hit rate); volatility forecasters: QLIKE (lower is better)."""
        need(day)
        d, lab = direction_rows(day), labels_of(day)
        direction = []
        for fam, g in d.groupby("family"):
            g, net, n, hits, free = g.sort_values("sod"), 0.0, 0, 0, 0
            for x in g.itertuples():
                if x.sod < free:
                    continue
                act = action_of(x)
                if act == "STAY_OUT" or x.sod not in lab.index:
                    continue
                side = "ce" if act == "BUY_CE" else "pe"
                row = lab.loc[x.sod]
                if not bool(row[f"{side}_valid"]):
                    continue
                n, net, hits = n + 1, net + float(row[f"{side}_net_rs"]), hits + (row[f"{side}_net_rs"] > 0)
                free = x.sod + float(row[f"{side}_hold_s"])
            direction.append(
                {
                    "family": fam,
                    "baseline": fam in BASELINES,
                    "source": g["source"].iloc[0],
                    "trades": n,
                    "net": num(net, 0),
                    "hit_rate": num(hits / n, 3) if n else None,
                }
            )
        vol = []
        v = st.modelout_dir / "vol" / f"{day}.parquet"
        if v.exists():
            rows = minute_rows(day)
            vd = _modelout(str(v), _mt(v))
            for fam, g in vd.groupby("family"):
                j = g.set_index("sod").reindex(rows.index)
                ok = j["fc_900"].notna() & rows["rv_fwd_900"].notna()
                vol.append(
                    {
                        "family": fam,
                        "source": g["source"].iloc[0],
                        "qlike": num(qlike(rows.loc[ok, "rv_fwd_900"], j.loc[ok, "fc_900"]), 4)
                        if ok.any()
                        else None,
                    }
                )
        return {"day": day, "direction": direction, "vol": vol}

    return r
