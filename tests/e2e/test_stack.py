"""End-to-end: the running Docker stack (api -> model server -> registry, frontend, Prometheus).

Skipped unless E2E_API_URL is set. Run it after `./stack up -d`:
    E2E_API_URL=http://127.0.0.1:8000 E2E_WEB_URL=http://127.0.0.1:8080 ./pipe pytest -q tests/e2e
"""

import os

import httpx
import pytest

API = os.environ.get("E2E_API_URL")
WEB = os.environ.get("E2E_WEB_URL", "http://127.0.0.1:8080")
PROM = os.environ.get("E2E_PROM_URL", "http://127.0.0.1:9091")
pytestmark = pytest.mark.skipif(not API, reason="E2E_API_URL not set (needs the running stack)")


def get(path, **kw):
    r = httpx.get(API + path, timeout=30, **kw)
    r.raise_for_status()
    return r


def test_model_is_served_and_deployed_through_the_gate():
    assert get("/healthz").json() == {"ok": True}
    champ = get("/model").json()["champion"]
    assert champ["deploy_check"] == "passed" and champ["family"]


def test_a_test_day_signal_round_trip():
    test_days = [d["day"] for d in get("/days").json() if d["split"] == "test"]
    r = get("/signal", params={"day": test_days[-1], "sod": 36000}).json()
    assert r["action"] in {"BUY_CE", "BUY_PE", "STAY_OUT"} and r["time"] == "10:00:00"
    assert set(r["hindsight"]) == {"ce", "pe"}


def test_reports_pipeline_and_metrics():
    assert get("/results").json()["champion"]
    stages = {s["name"] for s in get("/pipeline").json()["stages"]}
    assert {"clean", "grid", "feat", "labels", "zoo_train", "zoo_eval", "drift"} <= stages
    assert "signals_total" in get("/metrics").text


def test_web_page_and_its_config():
    assert "NIFTY Signal" in httpx.get(WEB + "/", timeout=10).text
    assert "api_url" in httpx.get(WEB + "/config.json", timeout=10).json()


def test_prometheus_scrapes_the_api():
    r = httpx.get(PROM + "/api/v1/query", params={"query": 'up{job="api"}'}, timeout=10).json()
    assert r["data"]["result"] and r["data"]["result"][0]["value"][1] == "1"
