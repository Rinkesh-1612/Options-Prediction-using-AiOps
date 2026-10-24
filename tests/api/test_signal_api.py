import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from optpred.serving.signal_api import ModelUnavailable, Settings, create_app

DAY = "2026-10-15"


class FakeModel:
    def __init__(self, action="BUY_CE", up=True):
        self.action, self.up, self.seen = action, up, None

    def ping(self):
        return self.up

    def invoke(self, X):
        if not self.up:
            raise ModelUnavailable("down")
        self.seen = X
        return pd.DataFrame(
            {"score_ce": [1.0] * len(X), "score_pe": [0.0] * len(X), "action": [self.action] * len(X)}
        )


class FakeRegistry:
    def __init__(self):
        self.alias = {"champion": "2", "previous": "1"}

    def get_model_version_by_alias(self, name, alias):
        if alias not in self.alias:
            raise KeyError(alias)
        return SimpleNamespace(version=self.alias[alias], run_id="r", tags={"deploy_check": "passed"})

    def get_run(self, run_id):
        return SimpleNamespace(
            data=SimpleNamespace(tags={"family": "lgbm_reg"}, metrics={"test_net_per_day": 1.0})
        )

    def set_registered_model_alias(self, name, alias, version):
        self.alias[alias] = version


@pytest.fixture
def env(tmp_path):
    sod = np.arange(33300, 33300 + 400)
    (tmp_path / "feat").mkdir()
    (tmp_path / "labels").mkdir()
    pd.DataFrame({"day": DAY, "sod": sod, "atm": 25000.0, "f1": np.arange(400.0)}).to_parquet(
        tmp_path / "feat" / f"{DAY}.parquet"
    )
    lab = {"day": DAY, "sod": sod}
    for s in ("ce", "pe"):
        lab |= {
            f"{s}_valid": True,
            f"{s}_entry": 100.0,
            f"{s}_sigma": 1.0,
            f"{s}_hit": 1,
            f"{s}_hold_s": 30.0,
            f"{s}_exit": 104.0,
            f"{s}_net_rs": 240.0,
        }
    pd.DataFrame(lab).to_parquet(tmp_path / "labels" / f"{DAY}.parquet")
    (tmp_path / "days.json").write_text(json.dumps({"accepted": [DAY]}))
    st = Settings(
        feat_dir=tmp_path / "feat",
        label_dir=tmp_path / "labels",
        days_path=tmp_path / "days.json",
        zoo_dir=tmp_path / "zoo",
        admin_token="secret",
    )
    return st


def test_signal_returns_action_and_outcome_without_future_rows(env):
    fake = FakeModel()
    c = TestClient(create_app(env, fake, FakeRegistry()))
    r = c.get("/signal", params={"day": DAY, "sod": 33500})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "BUY_CE" and body["outcome"]["net_rs"] == 240.0
    assert len(fake.seen) == 120 and fake.seen["f1"].iloc[-1] == 200  # rows up to sod only
    assert "signal_outcomes_total" in c.get("/metrics").text


def test_unknown_day_and_model_down(env):
    c = TestClient(create_app(env, FakeModel(up=False), FakeRegistry()))
    assert c.get("/signal", params={"day": "2020-01-01", "sod": 33500}).status_code == 404
    assert c.get("/signal", params={"day": DAY, "sod": 33500}).status_code == 503
    assert c.get("/healthz").status_code == 503


def test_rollback_needs_token_and_swaps(env):
    reg = FakeRegistry()
    c = TestClient(create_app(env, FakeModel(), reg))
    assert c.post("/rollback").status_code == 401
    r = c.post("/rollback", headers={"X-Admin-Token": "secret"})
    assert r.json() == {"champion": 1, "previous": 2} and reg.alias["champion"] == "1"


def alert(name, status="firing"):
    return {"alerts": [{"status": status, "labels": {"alertname": name}}]}


def test_drift_alert_requests_one_retrain_then_cooldown(env, tmp_path):
    from dataclasses import replace

    st = replace(env, retrain_request=tmp_path / "state" / "req.json", retrain_cooldown_s=3600)
    c = TestClient(create_app(st, FakeModel(), FakeRegistry()))
    assert c.post("/alerts/webhook", json=alert("DriftDetected")).json()["retrain_requested"] is True
    assert json.loads(st.retrain_request.read_text())["source"] == "alert"
    assert c.post("/alerts/webhook", json=alert("DriftDetected")).json()["retrain_requested"] is False
    assert c.post("/alerts/webhook", json=alert("SlowApi")).json()["retrain_requested"] is False


def test_online_drift_and_gauges(env, tmp_path):
    from dataclasses import replace

    from optpred.drift.psi import reference

    ref = reference(np.arange(1000.0).reshape(-1, 1), ["f1"])
    p = tmp_path / "ref.json"
    p.write_text(json.dumps({"ref": ref, "psi_limit": 0.25, "share_limit": 0.3, "min_rows": 5}))
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"stage": "zoo_eval", "status": "failed"}) + "\n")
    c = TestClient(create_app(replace(env, drift_ref=p, runs_path=runs), FakeModel(), FakeRegistry()))
    for sod in range(33500, 33510):
        c.get("/signal", params={"day": DAY, "sod": sod})
    assert c.get("/drift").json()["ready"]
    text = c.get("/metrics").text
    assert 'pipeline_last_run_ok{stage="zoo_eval"} 0.0' in text and "model_service_up 1.0" in text
    assert 'feature_psi{feature="f1"}' in text


def test_data_quality_gauges(env, tmp_path):
    from dataclasses import replace

    (tmp_path / "rep" / "eda").mkdir(parents=True)
    (tmp_path / "rep" / "eda" / "cleaning.json").write_text(
        json.dumps(
            {
                "total": {
                    "opt_tape": {
                        "rows_in": 1100,
                        "drop_outside_session": 100,
                        "drop_one_sided_book": 10,
                        "null_oi_not_positive": 5,
                        "rows_out": 990,
                    }
                }
            }
        )
    )
    c = TestClient(create_app(replace(env, reports_dir=tmp_path / "rep"), FakeModel(), FakeRegistry()))
    text = c.get("/metrics").text
    assert 'data_rows_dropped_share{table="opt_tape"} 0.01' in text
    assert 'data_days{verdict="accepted"} 1.0' in text


def test_buy_without_tradable_entry_is_blocked(env):
    import pandas as pd

    lab_path = env.label_dir / f"{DAY}.parquet"
    lab = pd.read_parquet(lab_path)
    lab["ce_valid"] = False  # e.g. 09:15, before the entry window
    lab.to_parquet(lab_path)
    c = TestClient(create_app(env, FakeModel("BUY_CE"), FakeRegistry()))
    body = c.get("/signal", params={"day": DAY, "sod": 33500}).json()
    assert body["action"] == "STAY_OUT" and body["blocked"] == "BUY_CE" and body["outcome"] is None
    assert "signals_blocked_total 1.0" in c.get("/metrics").text


def test_losing_trade_lowers_the_running_net(env):
    import pandas as pd

    lab_path = env.label_dir / f"{DAY}.parquet"
    lab = pd.read_parquet(lab_path)
    lab["ce_net_rs"] = -150.0
    lab.to_parquet(lab_path)
    c = TestClient(create_app(env, FakeModel("BUY_CE"), FakeRegistry()))
    assert c.get("/signal", params={"day": DAY, "sod": 33500}).status_code == 200
    text = c.get("/metrics").text
    assert "signal_net_rupees_cum -150.0" in text and 'signal_outcomes_total{result="loss"} 1.0' in text


def test_missing_day_file_is_503_not_500(env):
    (env.feat_dir / f"{DAY}.parquet").unlink()
    c = TestClient(create_app(env, FakeModel(), FakeRegistry()))
    assert c.get("/signal", params={"day": DAY, "sod": 33500}).status_code == 503
