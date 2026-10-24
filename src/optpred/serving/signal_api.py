"""Signal API (online serving of the zoo champion). The web page and Ravion talk to this, never to the model.

  GET  /healthz            200 when the model server answers
  GET  /days               accepted days and their split (dev / test)
  GET  /signal?day&sod     the champion's action at that second, and what happened after it (the label)
  GET  /model              champion and previous versions, family, CV and test metrics
  GET  /results            the zoo comparison on the test days (reports/zoo)
  POST /rollback           champion <-> previous (needs X-Admin-Token when ADMIN_TOKEN is set)
  POST /retrain            ask the runner to retrain (zoo_train -> zoo_eval -> gate -> deploy); admin
  GET  /drift              online drift: PSI per feature of the served rows vs the training days
  POST /alerts/webhook     Alertmanager: DriftDetected / ModelLosing -> retrain request (with a cooldown)
  GET  /metrics            Prometheus: requests, latency, actions, served signals vs their outcome, drift,
                           model server up, last run of each pipeline stage

The decision rule (tau) lives inside the served model. This API never applies a threshold.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from optpred.common.clock import SESSION_FIRST_MIN, SESSION_LAST_MIN
from optpred.drift.psi import DriftMonitor

log = logging.getLogger("optpred.serving.signal_api")
KEYS = ["day", "sod", "atm"]


@dataclass(frozen=True)
class Settings:
    feat_dir: Path = Path("data/feat")
    label_dir: Path = Path("data/labels")
    days_path: Path = Path("data/days.json")
    zoo_dir: Path = Path("reports/zoo")
    model_url: str = "http://model:5001"
    tracking_uri: str = "http://mlflow:5000"
    model_name: str = "nifty-signal"
    window_rows: int = 120  # rows sent per request: enough history for the sequence models (seq_len <= 120)
    admin_token: str = ""
    drift_ref: Path = Path("reports/drift/reference.json")
    reports_dir: Path = Path("reports")
    runs_path: Path = Path("runs/runs.jsonl")
    retrain_request: Path = Path("state/retrain_request.json")
    retrain_cooldown_s: float = 3600.0  # alerts cannot start retrains more often than this

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ
        return cls(
            feat_dir=Path(e.get("FEAT_DIR", cls.feat_dir)),
            label_dir=Path(e.get("LABEL_DIR", cls.label_dir)),
            days_path=Path(e.get("DAYS_PATH", cls.days_path)),
            zoo_dir=Path(e.get("ZOO_DIR", cls.zoo_dir)),
            model_url=e.get("MODEL_URL", cls.model_url),
            tracking_uri=e.get("MLFLOW_TRACKING_URI", cls.tracking_uri),
            model_name=e.get("MODEL_NAME", cls.model_name),
            admin_token=e.get("ADMIN_TOKEN", ""),
            drift_ref=Path(e.get("DRIFT_REF", cls.drift_ref)),
            reports_dir=Path(e.get("REPORTS_DIR", cls.reports_dir)),
            runs_path=Path(e.get("RUNS_PATH", cls.runs_path)),
            retrain_request=Path(e.get("RETRAIN_REQUEST", cls.retrain_request)),
            retrain_cooldown_s=float(e.get("RETRAIN_COOLDOWN_S", cls.retrain_cooldown_s)),
        )


class ModelUnavailable(RuntimeError):
    pass


class ModelServer:
    """Client of `mlflow models serve`. Replaceable in tests."""

    def __init__(self, url: str, timeout_s: float = 10.0):
        self.url, self.timeout_s = url.rstrip("/"), timeout_s

    def ping(self) -> bool:
        try:
            return httpx.get(f"{self.url}/ping", timeout=self.timeout_s).status_code == 200
        except httpx.HTTPError:
            return False

    def invoke(self, X: pd.DataFrame) -> pd.DataFrame:
        body = {
            "dataframe_split": {"columns": list(X.columns), "data": json.loads(X.to_json(orient="values"))}
        }
        try:
            r = httpx.post(f"{self.url}/invocations", json=body, timeout=self.timeout_s)
            r.raise_for_status()
            return pd.DataFrame(r.json()["predictions"])
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ModelUnavailable(f"the model service did not answer: {e}") from e


class Metrics:
    def __init__(self) -> None:
        r = self.registry = CollectorRegistry()
        self.requests = Counter("api_requests_total", "HTTP requests", ["path", "status"], registry=r)
        self.latency = Histogram("api_request_seconds", "HTTP request time", ["path"], registry=r)
        self.model_seconds = Histogram("model_call_seconds", "Time in the model server", registry=r)
        self.signals = Counter("signals_total", "Signals served", ["action"], registry=r)
        self.blocked = Counter("signals_blocked_total", "Model buys blocked: no tradable entry", registry=r)
        self.outcomes = Counter("signal_outcomes_total", "Served trades by result", ["result"], registry=r)
        self.net = Gauge(
            "signal_net_rupees_cum", "Running sum of net rupees of served trades (can fall)", registry=r
        )
        self.net_hist = Histogram(
            "signal_trade_net_rupees",
            "Net rupees per served trade",
            registry=r,
            buckets=(-500, -200, -100, -50, -20, 0, 20, 50, 100, 200, 500),
        )
        self.version = Gauge("model_version", "Registry version of the champion", registry=r)
        self.model_up = Gauge("model_service_up", "1 when the model server answers /ping", registry=r)
        self.drift = Gauge(
            "drift_detected", "1 when the served rows drift from the training data", registry=r
        )
        self.drift_share = Gauge("drift_share", "Share of features with PSI above the limit", registry=r)
        self.drift_rows = Gauge("drift_window_rows", "Served rows in the drift window", registry=r)
        self.psi = Gauge(
            "feature_psi", "PSI of one feature, served rows vs training", ["feature"], registry=r
        )
        self.stage_ok = Gauge(
            "pipeline_last_run_ok", "1 if the last run of a stage succeeded", ["stage"], registry=r
        )
        self.retrains = Counter("retrain_requests_total", "Retrain requests", ["source"], registry=r)
        self.days = Gauge("data_days", "Trading days by check verdict", ["verdict"], registry=r)
        self.dropped = Gauge(
            "data_rows_dropped_share",
            "Share of in-session rows dropped as bad data (clean)",
            ["table"],
            registry=r,
        )
        self.rule_rows = Gauge(
            "data_rule_rows", "Rows dropped or nulled by each clean rule", ["table", "rule"], registry=r
        )


def create_app(settings: Settings | None = None, model: ModelServer | None = None, client=None) -> FastAPI:
    st = settings or Settings.from_env()
    srv = model or ModelServer(st.model_url)
    m = Metrics()
    app = FastAPI(title="NIFTY signal API", version="2.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def registry():
        if client is not None:
            return client
        from mlflow import MlflowClient

        return MlflowClient(tracking_uri=st.tracking_uri)

    drift = None
    if st.drift_ref.exists():
        d = json.loads(st.drift_ref.read_text())
        drift = DriftMonitor(
            d["ref"],
            d.get("window", 1000),
            d.get("min_rows", 300),
            d["psi_limit"],
            d["share_limit"],
            d.get("limits"),
        )
    last_retrain = {"t": 0.0}

    def request_retrain(reason: str, source: str) -> bool:
        if source == "alert" and time.time() - last_retrain["t"] < st.retrain_cooldown_s:
            return False
        st.retrain_request.parent.mkdir(parents=True, exist_ok=True)
        st.retrain_request.write_text(
            json.dumps({"requested": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason, "source": source})
        )
        last_retrain["t"] = time.time()
        m.retrains.labels(source).inc()
        log.warning("retrain requested (%s): %s", source, reason)
        return True

    def accepted() -> list[str]:
        return json.loads(st.days_path.read_text())["accepted"]

    @lru_cache(maxsize=4)
    def day_frames(day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        return (
            pd.read_parquet(st.feat_dir / f"{day}.parquet").set_index("sod", drop=False),
            pd.read_parquet(st.label_dir / f"{day}.parquet").set_index("sod"),
        )

    def require_admin(x_admin_token: str = Header(default="")) -> None:
        if st.admin_token and not hmac.compare_digest(x_admin_token, st.admin_token):
            raise HTTPException(401, "admin token missing or wrong")

    @app.middleware("http")
    async def track(request: Request, call_next):
        t0, status = time.perf_counter(), 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            path = request.scope.get("route").path if request.scope.get("route") else "other"
            m.requests.labels(path, str(status)).inc()
            m.latency.labels(path).observe(time.perf_counter() - t0)

    @app.get("/healthz")
    def healthz():
        if not srv.ping():
            raise HTTPException(503, "model server not ready")
        return {"ok": True}

    @app.get("/days")
    def days():
        acc = accepted()
        test_path = st.zoo_dir / "test.json"
        test = set(json.loads(test_path.read_text())["test_days"]) if test_path.exists() else set()
        return [{"day": d, "split": "test" if d in test else "dev"} for d in acc]

    @app.get("/signal")
    def signal(
        day: str, sod: int = Query(..., ge=SESSION_FIRST_MIN * 60, le=(SESSION_LAST_MIN + 1) * 60 - 1)
    ):
        if day not in accepted():
            raise HTTPException(404, f"no data for {day}")
        try:
            feat, lab = day_frames(day)
        except FileNotFoundError as e:  # e.g. the pipeline is rebuilding data/feat right now
            raise HTTPException(503, f"data for {day} is not available now") from e
        window = feat.loc[:sod].tail(st.window_rows)
        t0 = time.perf_counter()
        try:
            pred = srv.invoke(window.drop(columns=KEYS).astype("float64")).iloc[-1]
        except ModelUnavailable as e:
            raise HTTPException(503, str(e)) from e
        m.model_seconds.observe(time.perf_counter() - t0)
        action, blocked = str(pred["action"]), None
        row = lab.loc[sod]
        if action != "STAY_OUT" and not bool(row[f"{'ce' if action == 'BUY_CE' else 'pe'}_valid"]):
            # Same entry rules as the simulator, all known at t: 09:20-15:15, premium >= Rs5, fresh quote.
            blocked, action = action, "STAY_OUT"
            m.blocked.inc()
        m.signals.labels(action).inc()
        if drift is not None:
            drift.add(window.iloc[-1].to_dict())
        outcome = None
        if action != "STAY_OUT":
            s = "ce" if action == "BUY_CE" else "pe"
            net = float(row[f"{s}_net_rs"])
            outcome = {
                "net_rs": net,
                "hold_s": float(row[f"{s}_hold_s"]),
                "barrier": int(row[f"{s}_hit"]),
                "entry": float(row[f"{s}_entry"]),
                "exit": float(row[f"{s}_exit"]),
            }
            m.outcomes.labels("win" if net > 0 else "loss").inc()
            m.net.inc(net)
            m.net_hist.observe(net)
        return {
            "day": day,
            "sod": sod,
            "time": f"{sod // 3600:02d}:{sod % 3600 // 60:02d}:{sod % 60:02d}",
            "atm": float(feat.loc[sod, "atm"]),
            "action": action,
            "score_ce": float(pred["score_ce"]),
            "score_pe": float(pred["score_pe"]),
            "blocked": blocked,
            "outcome": outcome,
        }

    @app.get("/model")
    def model_info():
        c, out = registry(), {}
        for alias in ("champion", "previous"):
            try:
                v = c.get_model_version_by_alias(st.model_name, alias)
            except Exception:  # noqa: BLE001 -- an alias that does not exist yet
                continue
            run = c.get_run(v.run_id)
            out[alias] = {
                "version": int(v.version),
                "family": run.data.tags.get("family"),
                "git_commit": run.data.tags.get("git_commit"),
                "deploy_check": v.tags.get("deploy_check"),
                "metrics": {k: round(x, 3) for k, x in run.data.metrics.items()},
            }
        if "champion" in out:
            m.version.set(out["champion"]["version"])
        return out

    @app.get("/results")
    def results():
        p = st.zoo_dir / "test.json"
        if not p.exists():
            raise HTTPException(404, "zoo_eval has not run yet")
        return json.loads(p.read_text())

    @app.post("/rollback", dependencies=[Depends(require_admin)])
    def rollback():
        c = registry()
        try:
            champ = c.get_model_version_by_alias(st.model_name, "champion")
            prev = c.get_model_version_by_alias(st.model_name, "previous")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(409, "there is no previous model to roll back to") from e
        c.set_registered_model_alias(st.model_name, "champion", prev.version)
        c.set_registered_model_alias(st.model_name, "previous", champ.version)
        log.warning("rollback: champion v%s -> v%s", champ.version, prev.version)
        return {"champion": int(prev.version), "previous": int(champ.version)}

    @app.post("/retrain", status_code=202, dependencies=[Depends(require_admin)])
    def retrain(reason: str = Query("manual", max_length=200)):
        request_retrain(reason, "manual")
        return {"accepted": True, "reason": reason}

    @app.get("/drift")
    def drift_status():
        if drift is None:
            raise HTTPException(404, "no drift reference yet (run the drift stage)")
        return drift.status()

    @app.post("/alerts/webhook", status_code=202)
    async def alert_webhook(request: Request):
        body = await request.json()
        names = {
            a.get("labels", {}).get("alertname")
            for a in body.get("alerts", [])
            if a.get("status") == "firing"
        }
        acted = bool(names & {"DriftDetected", "ModelLosing"}) and request_retrain(
            ", ".join(sorted(names)), "alert"
        )
        return {"alerts": sorted(n for n in names if n), "retrain_requested": acted}

    def refresh_gauges() -> None:
        m.model_up.set(1 if srv.ping() else 0)
        if drift is not None:
            s = drift.status()
            m.drift.set(1 if s["drift"] else 0)
            m.drift_share.set(s["share"])
            m.drift_rows.set(s["rows"])
            for f, v in s["psi"].items():
                m.psi.labels(f).set(v)
        if st.days_path.exists():
            d = json.loads(st.days_path.read_text())
            m.days.labels("accepted").set(len(d.get("accepted", [])))
            m.days.labels("rejected").set(len(d.get("rejected", {})))
        cleaning = st.reports_dir / "eda" / "cleaning.json"
        if cleaning.exists():
            for table, c in json.loads(cleaning.read_text())["total"].items():
                in_session = c["rows_in"] - c.get("drop_outside_session", 0)
                bad = sum(v for k, v in c.items() if k.startswith("drop_") and k != "drop_outside_session")
                m.dropped.labels(table).set(bad / in_session if in_session else 0.0)
                for k, v in c.items():
                    if k.startswith(("drop_", "null_")):
                        m.rule_rows.labels(table, k).set(v)
        if st.runs_path.exists():
            last = {}
            for line in st.runs_path.read_text().splitlines():
                try:
                    r = json.loads(line)
                    last[r["stage"]] = r.get("status") == "ok"
                except (ValueError, KeyError):
                    continue
            for stage, ok in last.items():
                m.stage_ok.labels(stage).set(1 if ok else 0)

    @app.get("/metrics")
    def metrics():
        refresh_gauges()
        return Response(generate_latest(m.registry), media_type=CONTENT_TYPE_LATEST)

    return app
