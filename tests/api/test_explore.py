import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from optpred.serving.explore import ann_vol
from optpred.serving.signal_api import Settings, create_app
from tests.api.test_signal_api import DAY, FakeModel, FakeRegistry
from tests.helpers.grid_synth import synth_grid


def chain(day: str) -> pd.DataFrame:
    rows = []
    for sod in range(33304, 55800, 60):
        for rank, (exp, dte, base) in enumerate((("2026-10-15", 0, 20.0), ("2026-10-22", 7, 14.0))):
            for strike in range(24800, 25250, 50):
                iv = base + 0.01 * abs(strike - 25000) / 10
                rows.append((sod, exp, rank, dte, float(strike), 25010.0, iv, iv + 1.0))
    cols = ["sod", "expiry", "expiry_rank", "dte", "strike", "spot", "ce_iv", "pe_iv"]
    return pd.DataFrame(rows, columns=cols)


@pytest.fixture
def ex(tmp_path):
    (tmp_path / "grid").mkdir()
    (tmp_path / "chain").mkdir()
    (tmp_path / "vol").mkdir(parents=True)
    g = synth_grid(22500).assign(day=DAY, dte=0)
    g["sod"] = 33300 + np.arange(len(g))
    g.to_parquet(tmp_path / "grid" / f"{DAY}.parquet")
    chain(DAY).to_parquet(tmp_path / "chain" / f"{DAY}.parquet")
    (tmp_path / "days.json").write_text(json.dumps({"accepted": [DAY]}))
    (tmp_path / "zoo").mkdir()
    (tmp_path / "zoo" / "test.json").write_text(json.dumps({"test_days": [DAY]}))
    return Settings(
        grid_dir=tmp_path / "grid",
        chain_dir=tmp_path / "chain",
        modelout_dir=tmp_path / "modelout",
        days_path=tmp_path / "days.json",
        zoo_dir=tmp_path / "zoo",
        reports_dir=tmp_path / "reports",
    )


def client(st):
    return TestClient(create_app(st, FakeModel(), FakeRegistry()))


def test_calendar_marks_unseen_days_and_events(ex):
    d = client(ex).get("/explore/days").json()
    assert [x["day"] for x in d] == [DAY]
    assert d[0]["split"] == "test" and "expiry" in d[0]["events"] and d[0]["weekday"] == "Thu"
    assert d[0]["atm_iv"] > 0 and d[0]["range_pct"] >= 0


def test_iv_day_has_minutes_and_no_forecast_before_the_stage_ran(ex):
    r = client(ex).get("/explore/iv/day", params={"day": DAY}).json()
    assert r["sod"][0] == 34200 and r["sod"][-1] == 54000 and len(r["sod"]) == 331
    assert r["forecast"] is None and 5 < r["iv"][10] < 30
    assert r["realized"][-1] > 0  # 15:00 + 15 min is before the close, so the future move is known


def test_iv_day_and_daily_use_stored_forecast(ex, tmp_path):
    mo = tmp_path / "modelout" / "vol"
    mo.mkdir(parents=True)
    sod = np.arange(33300, 55800, 60)
    pd.DataFrame(
        {"day": DAY, "sod": sod, "family": "har_iv", "fc_300": 8.0, "fc_900": 14.0, "source": "test"}
    ).to_parquet(mo / f"{DAY}.parquet")
    c = client(ex)
    r = c.get("/explore/iv/day", params={"day": DAY}).json()
    assert r["forecast"][5] == pytest.approx(ann_vol(14.0, 900), abs=0.01)
    daily = c.get("/explore/iv/daily").json()[0]
    assert daily["forecast"] == pytest.approx(ann_vol(14.0, 900), abs=0.01) and daily["split"] == "test"
    assert 0 <= daily["iv_rich_share"] <= 1


def test_smile_and_term_structure(ex):
    c = client(ex)
    s = c.get("/explore/iv/smile", params={"day": DAY, "t": 40000}).json()
    assert len(s["expiries"]) == 2 and len(s["expiries"][0]["strikes"]) == 9
    assert s["sod"] == 40000
    t = c.get("/explore/iv/term", params={"day": DAY, "t": 40000}).json()
    assert [x["dte"] for x in t["at"]] == [0, 7] and t["at"][0]["iv"] > t["at"][1]["iv"]
    assert len(t["series"]["sod"]) > 100 and t["series"]["near"][0] is not None


def test_chain_snapshot_merges_expiries_sent_in_separate_seconds(ex, tmp_path):
    c = chain(DAY)
    c.loc[c["expiry_rank"] == 1, "sod"] += 3  # the feed sends the next expiry a few seconds later
    c.to_parquet(tmp_path / "chain" / f"{DAY}.parquet")
    cl = client(ex)
    s = cl.get("/explore/iv/smile", params={"day": DAY, "t": 40000}).json()
    assert [e["dte"] for e in s["expiries"]] == [0, 7] and s["sod"] == 40000
    t = cl.get("/explore/iv/term", params={"day": DAY, "t": 40000}).json()
    assert all(v is not None for v in t["series"]["near"][:50]) and all(
        v is not None for v in t["series"]["next"][:50]
    )


def test_unknown_day_and_missing_files(ex, tmp_path):
    c = client(ex)
    assert c.get("/explore/iv/day", params={"day": "2020-01-01"}).status_code == 404
    assert c.get("/explore/iv/smile", params={"day": "2020-01-01", "t": 40000}).status_code == 404
    (tmp_path / "chain" / f"{DAY}.parquet").unlink()
    assert c.get("/explore/iv/smile", params={"day": DAY, "t": 40000}).status_code == 503


def test_strategies_list_prices_every_template_and_the_detail_route_validates(ex):
    c = client(ex)
    r = c.get("/explore/strategies", params={"day": DAY, "t": 36000}).json()
    assert r["lot"] == 65 and len(r["strategies"]) >= 15
    by = {s["id"]: s for s in r["strategies"]}
    assert by["long_call"]["cost"] > 0 > by["short_straddle"]["cost"]
    assert by["long_call"]["at"]["m5"] is not None and by["iron_condor"]["max_loss"] is not None
    d = c.get("/explore/strategy", params={"day": DAY, "t": 36000, "legs": "buy:ce:0:1,sell:ce:2:2"}).json()
    assert d["legs_text"] == "buy:ce:0:1,sell:ce:2:2" and d["payoff"]["max_loss"] is None
    assert (
        c.get("/explore/strategy", params={"day": DAY, "t": 36000, "legs": "buy:ce:9:1"}).status_code == 422
    )
    assert (
        c.get("/explore/strategy", params={"day": DAY, "t": 55650, "legs": "buy:ce:0:1"}).status_code == 409
    )
    assert c.get("/explore/strategies", params={"day": "2020-01-01", "t": 36000}).status_code == 404


def test_models_at_a_moment_and_over_a_day(ex, tmp_path):
    sod = np.arange(33300, 55800, 60)
    mo = tmp_path / "modelout"
    (mo / "direction").mkdir(parents=True)
    (mo / "vol").mkdir()
    rows = []
    for fam, ce, pe, tau in (
        ("lgbm_reg", 5.0, 1.0, 2.0),
        ("stay_out", -np.inf, -np.inf, np.inf),
        ("random", 0.2, 0.9, 5.0),
    ):
        rows += [(DAY, s, fam, ce, pe, tau, "test") for s in sod]
    pd.DataFrame(rows, columns=["day", "sod", "family", "score_ce", "score_pe", "tau", "source"]).to_parquet(
        mo / "direction" / f"{DAY}.parquet"
    )
    pd.DataFrame(
        {"day": DAY, "sod": sod, "family": "har_iv", "fc_300": 8.0, "fc_900": 14.0, "source": "test"}
    ).to_parquet(mo / "vol" / f"{DAY}.parquet")
    lab = pd.DataFrame({"sod": np.arange(33300, 55800)})
    for s in ("ce", "pe"):
        lab[f"{s}_valid"], lab[f"{s}_net_rs"], lab[f"{s}_hit"], lab[f"{s}_hold_s"] = (
            True,
            100.0 if s == "ce" else -50.0,
            1,
            120.0,
        )
    (tmp_path / "labels").mkdir()
    lab.to_parquet(tmp_path / "labels" / f"{DAY}.parquet")
    c = client(replace(ex, label_dir=tmp_path / "labels"))
    r = c.get("/explore/models", params={"day": DAY, "t": 40000}).json()
    by = {x["family"]: x for x in r["direction"]}
    assert (
        by["lgbm_reg"]["action"] == "BUY_CE"
        and by["lgbm_reg"]["result"] == 100.0
        and by["lgbm_reg"]["ended_by"] == 1
    )
    assert by["stay_out"]["action"] == "STAY_OUT" and by["stay_out"]["result"] is None
    assert (
        by["random"]["action"] == "STAY_OUT"
        and by["lgbm_reg"]["baseline"] is False
        and by["random"]["baseline"] is True
    )
    assert r["vol"][0]["forecast"] == pytest.approx(ann_vol(14.0, 900), abs=0.01) and r["realized"] > 0
    d = c.get("/explore/models/day", params={"day": DAY}).json()
    dd = {x["family"]: x for x in d["direction"]}
    assert (
        dd["stay_out"]["trades"] == 0
        and dd["lgbm_reg"]["trades"] > 100
        and dd["lgbm_reg"]["net"] == 100.0 * dd["lgbm_reg"]["trades"]
    )
    assert dd["lgbm_reg"]["hit_rate"] == 1.0 and d["vol"][0]["qlike"] is not None
