"""The backend API against a fake model service (the real one is exercised by the smoke test)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from mlflow.exceptions import MlflowException

from optpred import api
from optpred.features import FEATURE_COLUMNS
from optpred.labels import label_actions, net_rs
from tests.test_train import make

REPO = Path(__file__).resolve().parents[1]


class FakeModel(api.ModelServer):
    """Answers like the served model: probabilities from ce_imb1, a fixed rule, three drivers."""

    def __init__(self, tau=0.5, up=True, fail=False):
        self.tau, self.up, self.fail = tau, up, fail

    def ping(self):
        return self.up

    def invoke(self, X):
        if self.fail:
            raise api.ModelUnavailable("the model service did not answer: connection refused")
        z = X["ce_imb1"].to_numpy()
        p_ce, p_pe = 1 / (1 + np.exp(-z)) * 0.8, (1 - 1 / (1 + np.exp(-z))) * 0.8
        proba = np.c_[0.2 * np.ones(len(X)), p_ce, p_pe]
        best = proba.argmax(axis=1)
        action = np.where((best != 0) & (proba.max(axis=1) >= self.tau), best, 0)
        drivers = json.dumps([{"feature": "ce_imb1", "value": float(z[0]), "push": 0.5}] * 3)
        return pd.DataFrame(
            {
                "p_stay_out": proba[:, 0],
                "p_buy_ce": proba[:, 1],
                "p_buy_pe": proba[:, 2],
                "action": action,
                "tau": self.tau,
                "drivers": [drivers] * len(X),
            }
        )


class FakeRegistry:
    def __init__(self, with_previous=True):
        self.alias = {"champion": 3} | ({"previous": 2} if with_previous else {})

    def get_model_version_by_alias(self, name, alias):
        if alias not in self.alias:  # the real client raises this for an alias that is not set
            raise MlflowException(f"alias {alias} not found")
        return type("V", (), {"version": str(self.alias[alias]), "run_id": "r"})()

    def set_registered_model_alias(self, name, alias, version):
        self.alias[alias] = int(version)


@pytest.fixture()
def env(tmp_path):
    df = pd.concat(
        [make(2, 1.0, 0, "train"), make(1, 1.0, 1, "val"), make(1, 1.0, 2, "test")], ignore_index=True
    )
    df["day"] = df["day"].where(
        df["split"] == "train", df["split"].map({"val": "2026-03-01", "test": "2026-05-01"})
    )
    df["spot"], df["strike"] = 22900.0, 22900.0
    df["ce_key"], df["pe_key"] = "NSE_FO|22900CE", "NSE_FO|22900PE"
    df["ce_entry"] = df["pe_entry"] = 100.0
    df["ce_spread"] = df["pe_spread"] = 0.25
    feats = tmp_path / "features.parquet"
    df.to_parquet(feats)
    log_dir = tmp_path / "logs/train"
    log_dir.mkdir(parents=True)
    (log_dir / "a.log").write_text("line1\nline2\nline3\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve")
    runs = tmp_path / "runs.jsonl"
    rec = {
        "stage": "train",
        "status": "ok",
        "started": "2026-10-18T10:00:00",
        "duration_s": 2.0,
        "git_commit": "a" * 40,
        "git_dirty": False,
        "summary": {"rows_per_s": 1000},
    }
    runs.write_text(
        "\n".join(
            json.dumps({**rec, "run_id": rid, "log": log})
            for rid, log in [("ok-run", str(log_dir / "a.log")), ("evil-run", str(secret))]
        )
    )
    params = tmp_path / "params.yaml"
    params.write_text(
        yaml.safe_dump(
            {
                "features": {"qty": 65, "horizon_min": 2},
                "costs": {"slippage_pts_per_leg": 0.31},
                "mlflow": {"registered_model": "m"},
            }
        )
    )
    st = api.Settings(
        features_path=feats,
        runs_path=runs,
        logs_root=tmp_path / "logs",
        dvc_path=REPO / "dvc.yaml",
        params_path=params,
        final_marker=tmp_path / "final.json",
        retrain_request=tmp_path / "state/r.json",
    )
    return st, df


def client(env, **kw):
    st, _ = env
    kw.setdefault("mlflow_client", FakeRegistry())  # never reach for a real registry in tests
    return TestClient(api.create_app(st, model=kw.pop("model", FakeModel()), **kw))


def test_healthz_follows_the_model_service(env):
    assert client(env).get("/healthz").status_code == 200
    assert client(env, model=FakeModel(up=False)).get("/healthz").status_code == 503


def test_locked_test_days_stay_hidden_until_the_final_marker_exists(env):
    st, df = env
    c = client(env)
    days = {d["day"]: d for d in c.get("/days").json()}
    assert "2026-05-01" not in days and days["2026-03-01"]["split"] == "val"
    assert days[sorted(days)[0]]["in_sample"] is True  # train days are flagged
    assert c.post("/predict", json={"day": "2026-05-01", "minute": 600}).status_code == 403
    assert c.get("/minutes", params={"day": "2026-05-01"}).status_code == 404
    st.final_marker.write_text("{}")
    assert "2026-05-01" in {d["day"] for d in c.get("/days").json()}
    assert c.post("/predict", json={"day": "2026-05-01", "minute": 600}).status_code == 200


def test_results_appear_only_after_the_one_time_evaluation(env):
    st, _ = env
    c = client(env)
    assert c.get("/results").status_code == 404
    st.final_marker.write_text(json.dumps({"verdict": {"champion_net_per_day_rs": 0.0}}))
    assert c.get("/results").json()["verdict"]["champion_net_per_day_rs"] == 0.0
    st.final_marker.write_text("{not json")
    assert c.get("/results").status_code == 500


def test_predict_reports_what_actually_happened_with_the_same_costs_as_the_labels(env):
    _, df = env
    r = client(env).post("/predict", json={"day": "2026-03-01", "minute": 600}).json()
    row = df[(df["day"] == "2026-03-01") & (df["minute"] == 600)]
    assert r["outcome"]["call_net_rs"] == pytest.approx(float(net_rs(row, "ce", 0.31, 65).iloc[0]), abs=0.01)
    assert r["outcome"]["put_net_rs"] == pytest.approx(float(net_rs(row, "pe", 0.31, 65).iloc[0]), abs=0.01)
    assert (
        r["outcome"]["best_in_hindsight"]
        == {0: "STAY_OUT", 1: "BUY_CE", 2: "BUY_PE"}[int(label_actions(row, 0.31, 65)[0])]
    )
    assert sum(r["probabilities"].values()) == pytest.approx(1.0)
    assert r["decision_time"] == "10:01" and len(r["drivers"]) == 3 and r["split"] == "val"


def test_a_never_trade_model_says_so_in_plain_words(env):
    r = (
        client(env, model=FakeModel(tau=api.NEVER_TRADE))
        .post("/predict", json={"day": "2026-03-01", "minute": 600})
        .json()
    )
    assert (
        r["action"] == "STAY_OUT"
        and "never trades" in r["reason"]
        and r["outcome"]["result_of_model_action_rs"] == 0
    )


def test_bad_requests_get_clear_errors(env):
    c = client(env)
    assert c.post("/predict", json={"day": "2026-03-01", "minute": 99999}).status_code == 422
    assert c.post("/predict", json={"day": "2020-01-01", "minute": 600}).status_code == 404


def test_model_outage_is_a_readable_503_not_a_crash(env):
    r = client(env, model=FakeModel(fail=True)).post("/predict", json={"day": "2026-03-01", "minute": 600})
    assert r.status_code == 503 and "did not answer" in r.json()["detail"]


def test_pipeline_console_lists_runs_and_serves_only_logs(env):
    c = client(env)
    runs = c.get("/pipeline/runs").json()
    assert [r["run_id"] for r in runs] == ["evil-run", "ok-run"] and runs[0]["rows_per_s"] == 1000
    assert c.get("/pipeline/runs/ok-run/log", params={"lines": 2}).text == "line2\nline3"
    assert c.get("/pipeline/runs/evil-run/log").status_code == 404  # a file outside logs/ is never served
    assert c.get("/pipeline/runs/nope/log").status_code == 404


def test_pipeline_dag_comes_from_the_real_dvc_file(env):
    dag = client(env).get("/pipeline/dag").json()
    edges = {(e["from"], e["to"]) for e in dag["edges"]}
    assert {("export", "check"), ("check", "bars"), ("bars", "features"), ("features", "baselines")} <= edges


def test_rollback_swaps_champion_and_previous_and_refuses_without_one(env):
    reg = FakeRegistry()
    r = client(env, mlflow_client=reg).post("/rollback")
    assert r.json() == {"champion": 2, "previous": 3} and reg.alias["champion"] == 2
    assert client(env, mlflow_client=FakeRegistry(with_previous=False)).post("/rollback").status_code == 409


def test_retrain_request_is_written_for_the_runner(env):
    st, _ = env
    assert client(env).post("/retrain", params={"reason": "drift"}).status_code == 202
    assert json.loads(st.retrain_request.read_text())["reason"] == "drift"


def test_metrics_count_requests_and_predictions(env):
    c = client(env)
    c.post("/predict", json={"day": "2026-03-01", "minute": 600})
    text = c.get("/metrics").text
    assert 'api_requests_total{method="POST",path="/predict",status="200"} 1.0' in text
    assert (
        "predictions_total{" in text
        and "predictions_vs_actual_total{" in text
        and "model_service_up 1.0" in text
    )


def test_every_feature_column_is_sent_to_the_model(env):
    seen = {}

    class Spy(FakeModel):
        def invoke(self, X):
            seen["cols"] = list(X.columns)
            return super().invoke(X)

    client(env, model=Spy()).post("/predict", json={"day": "2026-03-01", "minute": 600})
    assert seen["cols"] == FEATURE_COLUMNS


def test_changing_the_served_model_needs_the_admin_token(env):
    st, _ = env
    guarded = api.Settings(**{**st.__dict__, "admin_token": "s3cret"})
    c = TestClient(api.create_app(guarded, model=FakeModel(), mlflow_client=FakeRegistry()))
    assert c.post("/rollback").status_code == 401 and c.post("/retrain").status_code == 401
    assert c.post("/rollback", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.post("/rollback", headers={"X-Admin-Token": "s3cret"}).status_code == 200
    assert c.get("/days").status_code == 200  # reading stays open


# ------------------------------------------------------------------ monitoring, drift, alerts, LLD
def test_metrics_include_pipeline_journal_and_drift_series(env):
    c = client(env)
    text = c.get("/metrics").text
    assert 'pipeline_last_run_ok{stage="train"} 1.0' in text
    assert 'pipeline_runs{stage="train",status="ok"} 2.0' in text
    assert "drift_detected 0.0" in text and "drift_window_rows 0.0" in text


def test_predictions_feed_result_and_drift_window(env):
    c = client(env)
    for m in (560, 561, 562):
        assert c.post("/predict", json={"day": "2026-03-01", "minute": m}).status_code == 200
    text = c.get("/metrics").text
    assert "drift_window_rows 3.0" in text and "model_result_rs_total" in text
    assert c.get("/drift").json()["ready"] is False  # needs 100 rows


def test_drift_alert_asks_for_a_retrain_once_per_cooldown(env):
    st, _ = env
    c = client(env)
    firing = {"alerts": [{"status": "firing", "labels": {"alertname": "DriftDetected"}}]}
    assert c.post("/alerts/webhook", json=firing).json()["accepted"] is True
    assert "drift alert" in json.loads(st.retrain_request.read_text())["reason"]
    st.retrain_request.unlink()
    assert c.post("/alerts/webhook", json=firing).json()["accepted"] is False  # cooldown
    assert not st.retrain_request.exists()


def test_other_alerts_do_not_trigger_a_retrain(env):
    st, _ = env
    other = {"alerts": [{"status": "firing", "labels": {"alertname": "SlowApi"}}]}
    assert client(env).post("/alerts/webhook", json=other).json()["accepted"] is False
    assert not st.retrain_request.exists()


def test_openapi_matches_the_low_level_design(env):
    """Every endpoint in docs/LLD.md exists in the API, and every API endpoint is in the document."""
    import re

    doc = (REPO / "docs/LLD.md").read_text()
    documented = set(re.findall(r"^### `(GET|POST) (/\S*)`", doc, flags=re.M))
    spec = client(env).app.openapi()["paths"]
    actual = {(m.upper(), path) for path, ops in spec.items() for m in ops}
    assert documented == actual
