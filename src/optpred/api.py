"""Backend API. The web page talks to this and to nothing else (loose coupling, by REST only).

What it does: lets a person pick a past minute, asks the MLflow-served model what it would have
said, and shows what actually happened next. Also shows the pipeline (stages, runs, failures,
speed), exposes Prometheus metrics, and lets an operator roll the model back.

Integrity rules built in:
  * The locked test days are hidden (and refused with 403) until the final evaluation has been
    written to reports/final.json. Looking at them earlier would be peeking at the exam.
  * Days the model was trained on are marked in_sample, so nobody mistakes a good-looking
    training day for evidence.
  * The decision rule lives inside the served model; this API never re-applies a threshold.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from optpred.features import FEATURE_COLUMNS
from optpred.labels import ACTION_NAMES, STAY_OUT, label_actions, net_rs
from optpred.serving_model import NEVER_TRADE

log = logging.getLogger("optpred.api")


@dataclass(frozen=True)
class Settings:
    features_path: Path = Path("data/features/features.parquet")
    runs_path: Path = Path("runs/runs.jsonl")
    logs_root: Path = Path("logs")
    dvc_path: Path = Path("dvc.yaml")
    params_path: Path = Path("params.yaml")
    final_marker: Path = Path("reports/final.json")
    retrain_request: Path = Path("state/retrain_request.json")
    model_url: str = "http://model:5001"
    tracking_uri: str = "http://mlflow:5000"
    cors_origins: tuple[str, ...] = ("*",)

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ
        return cls(
            features_path=Path(e.get("FEATURES_PATH", cls.features_path)),
            runs_path=Path(e.get("RUNS_PATH", cls.runs_path)),
            logs_root=Path(e.get("LOGS_ROOT", cls.logs_root)),
            dvc_path=Path(e.get("DVC_PATH", cls.dvc_path)),
            params_path=Path(e.get("PARAMS_PATH", cls.params_path)),
            final_marker=Path(e.get("FINAL_MARKER", cls.final_marker)),
            retrain_request=Path(e.get("RETRAIN_REQUEST", cls.retrain_request)),
            model_url=e.get("MODEL_URL", cls.model_url),
            tracking_uri=e.get("MLFLOW_TRACKING_URI", cls.tracking_uri),
            cors_origins=tuple(e.get("CORS_ORIGINS", "*").split(",")),
        )


class ModelUnavailable(RuntimeError):
    """The model service cannot be reached or gave an answer we cannot read."""


class ModelServer:
    """Client for `mlflow models serve` (REST). Replaceable in tests."""

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
    """Prometheus instruments, on a private registry so tests can build many apps."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        self.requests = Counter(
            "api_requests_total", "HTTP requests", ["path", "method", "status"], registry=r
        )
        self.latency = Histogram("api_request_seconds", "HTTP request time", ["path"], registry=r)
        self.model_seconds = Histogram("model_call_seconds", "Time spent in the model service", registry=r)
        self.predictions = Counter("predictions_total", "Predictions served", ["action"], registry=r)
        self.vs_actual = Counter(
            "predictions_vs_actual_total",
            "Served prediction against the hindsight label",
            ["predicted", "actual"],
            registry=r,
        )
        self.model_up = Gauge("model_service_up", "1 if the model service answered its last ping", registry=r)


# ----------------------------------------------------------------------------- response shapes
class DayInfo(BaseModel):
    day: str
    split: str
    in_sample: bool = Field(description="True if the model was trained on this day")
    minutes: int
    first_time: str
    last_time: str


class PredictRequest(BaseModel):
    day: str = Field(examples=["2026-10-14"])
    minute: int = Field(ge=0, le=1439, description="minute of the day, 560 = 09:20")


class Contract(BaseModel):
    instrument_key: str
    strike: float
    entry_ask: float
    spread_pts: float


class Outcome(BaseModel):
    horizon_min: int
    call_net_rs: float
    put_net_rs: float
    best_in_hindsight: str
    result_of_model_action_rs: float


class PredictResponse(BaseModel):
    day: str
    minute: int
    decision_time: str
    split: str
    in_sample: bool
    spot: float
    probabilities: dict[str, float]
    action: str
    headline: str
    reason: str
    drivers: list[dict]
    call: Contract
    put: Contract
    outcome: Outcome


def clock(minute: int) -> str:
    """The moment a decision for `minute` is made: the END of that minute."""
    return f"{(minute + 1) // 60:02d}:{(minute + 1) % 60:02d}"


def load_features(path: Path, p: dict, slip: float) -> pd.DataFrame:
    df = pd.read_parquet(path).sort_values(["day", "minute"]).reset_index(drop=True)
    df["ce_net"] = net_rs(df, "ce", slip, p["qty"])
    df["pe_net"] = net_rs(df, "pe", slip, p["qty"])
    df["label"] = label_actions(df, slip, p["qty"])
    return df


def dag_from_dvc(dvc_yaml: dict) -> dict:
    """Stages as nodes; an edge A -> B when one of B's dependencies lives under one of A's outputs."""
    stages = dvc_yaml.get("stages", {})

    def paths(items):
        return [next(iter(i)) if isinstance(i, dict) else i for i in items or []]

    outs = {n: paths(s.get("outs")) for n, s in stages.items()}
    edges = {
        (a, b)
        for b, sb in stages.items()
        for dep in paths(sb.get("deps"))
        for a, o in outs.items()
        if a != b and any(dep == x or dep.startswith(x.rstrip("/") + "/") for x in o)
    }
    nodes = [
        {"id": n, "cmd": s.get("cmd", ""), "deps": paths(s.get("deps")), "outs": outs[n]}
        for n, s in stages.items()
    ]
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in sorted(edges)]}


def journal(path: Path) -> list[dict]:
    """Raw run records, oldest first."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_runs(path: Path, limit: int) -> list[dict]:
    """Newest-first run list for the pipeline console."""
    out = []
    for r in reversed(journal(path)[-limit:]):
        s = r.get("summary", {})
        out.append(
            {
                "run_id": r["run_id"],
                "stage": r["stage"],
                "status": r["status"],
                "started": r["started"],
                "duration_s": r["duration_s"],
                "git_commit": r["git_commit"][:10],
                "git_dirty": r["git_dirty"],
                "rows_per_s": s.get("tape_rows_per_s") or s.get("rows_per_s"),
                "summary": s,
            }
        )
    return out


def create_app(
    settings: Settings | None = None, model: ModelServer | None = None, mlflow_client=None
) -> FastAPI:
    st = settings or Settings.from_env()
    model = model or ModelServer(st.model_url)
    metrics = Metrics()
    with open(st.params_path) as f:
        params = yaml.safe_load(f)
    p = {**params["features"], "slip": params["costs"]["slippage_pts_per_leg"]}
    frame = load_features(st.features_path, p, p["slip"])
    index = {(d, m): i for i, (d, m) in enumerate(zip(frame["day"], frame["minute"], strict=True))}

    app = FastAPI(title="NIFTY option direction API", version="1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=list(st.cors_origins), allow_methods=["*"], allow_headers=["*"]
    )

    def final_done() -> bool:
        return st.final_marker.exists()

    def visible(df: pd.DataFrame) -> pd.DataFrame:
        return df if final_done() else df[df["split"] != "test"]

    def mlflow_api():
        if mlflow_client is not None:
            return mlflow_client
        from mlflow import MlflowClient

        return MlflowClient(tracking_uri=st.tracking_uri)

    @app.middleware("http")
    async def track(request: Request, call_next):
        t0, status = time.perf_counter(), 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            route = request.scope.get("route")
            path = route.path if route else "unmatched"
            metrics.requests.labels(path, request.method, str(status)).inc()
            metrics.latency.labels(path).observe(time.perf_counter() - t0)

    @app.exception_handler(ModelUnavailable)
    async def _model_down(_: Request, exc: ModelUnavailable):
        metrics.model_up.set(0)
        return JSONResponse(status_code=503, content={"error": "model_unavailable", "detail": str(exc)})

    @app.get("/healthz", summary="200 only when the model service answers")
    def healthz():
        up = model.ping()
        metrics.model_up.set(1 if up else 0)
        if not up:
            raise HTTPException(503, "model service not ready")
        return {"status": "ok", "rows": len(frame)}

    @app.get("/days", response_model=list[DayInfo])
    def days():
        out = []
        for d, g in visible(frame).groupby("day"):
            split = str(g["split"].iloc[0])
            out.append(
                DayInfo(
                    day=d,
                    split=split,
                    in_sample=split == "train",
                    minutes=len(g),
                    first_time=clock(int(g["minute"].min())),
                    last_time=clock(int(g["minute"].max())),
                )
            )
        return out

    @app.get("/minutes")
    def minutes(day: str):
        g = visible(frame)
        g = g[g["day"] == day]
        if g.empty:
            raise HTTPException(404, f"no minutes available for {day}")
        return [{"minute": int(m), "time": clock(int(m))} for m in g["minute"]]

    @app.post("/predict", response_model=PredictResponse)
    def predict(req: PredictRequest):
        i = index.get((req.day, req.minute))
        if i is None:
            raise HTTPException(404, f"no decision row for {req.day} minute {req.minute}")
        row = frame.iloc[i]
        if row["split"] == "test" and not final_done():
            raise HTTPException(403, "the locked test days stay hidden until the final evaluation is done")
        X = frame.iloc[[i]][FEATURE_COLUMNS].astype(float)
        t0 = time.perf_counter()
        out = model.invoke(X).iloc[0]
        metrics.model_seconds.observe(time.perf_counter() - t0)
        metrics.model_up.set(1)

        action = int(out["action"])
        probs = {
            "STAY_OUT": float(out["p_stay_out"]),
            "BUY_CE": float(out["p_buy_ce"]),
            "BUY_PE": float(out["p_buy_pe"]),
        }
        ce_net, pe_net, label = float(row["ce_net"]), float(row["pe_net"]), int(row["label"])
        got = {STAY_OUT: 0.0, 1: ce_net, 2: pe_net}[action]
        metrics.predictions.labels(ACTION_NAMES[action]).inc()
        metrics.vs_actual.labels(ACTION_NAMES[action], ACTION_NAMES[label]).inc()
        return PredictResponse(
            day=req.day,
            minute=req.minute,
            decision_time=clock(req.minute),
            split=str(row["split"]),
            in_sample=row["split"] == "train",
            spot=float(row["spot"]),
            probabilities=probs,
            action=ACTION_NAMES[action],
            headline=headline(action, row),
            reason=reason(action, probs, float(out["tau"])),
            drivers=json.loads(out["drivers"]),
            call=Contract(
                instrument_key=row["ce_key"],
                strike=float(row["strike"]),
                entry_ask=float(row["ce_entry"]),
                spread_pts=float(row["ce_spread"]),
            ),
            put=Contract(
                instrument_key=row["pe_key"],
                strike=float(row["strike"]),
                entry_ask=float(row["pe_entry"]),
                spread_pts=float(row["pe_spread"]),
            ),
            outcome=Outcome(
                horizon_min=p["horizon_min"],
                call_net_rs=round(ce_net, 2),
                put_net_rs=round(pe_net, 2),
                best_in_hindsight=ACTION_NAMES[label],
                result_of_model_action_rs=round(got, 2),
            ),
        )

    @app.get("/model")
    def model_info():
        c, name = mlflow_api(), params["mlflow"]["registered_model"]
        info = {}
        try:
            for alias in ("champion", "previous", "candidate"):
                try:
                    v = c.get_model_version_by_alias(name, alias)
                except Exception:
                    continue
                run = c.get_run(v.run_id)
                info[alias] = {
                    "version": int(v.version),
                    "run_id": v.run_id,
                    "tau": run.data.params.get("tau"),
                    "git_commit": run.data.tags.get("git_commit", "")[:10],
                    "val_metrics": {
                        k: round(x, 4) for k, x in run.data.metrics.items() if k.startswith("val_")
                    },
                }
        except Exception as e:
            raise HTTPException(503, f"model registry not reachable: {e}") from e
        if "champion" not in info:
            raise HTTPException(404, "no champion model registered yet")
        return {"registered_model": name, **info}

    @app.post("/rollback")
    def rollback():
        c, name = mlflow_api(), params["mlflow"]["registered_model"]
        try:
            champ = c.get_model_version_by_alias(name, "champion")
            prev = c.get_model_version_by_alias(name, "previous")
        except Exception as e:
            raise HTTPException(409, "there is no previous model to roll back to") from e
        c.set_registered_model_alias(name, "champion", prev.version)
        c.set_registered_model_alias(name, "previous", champ.version)
        log.warning("rolled back champion v%s -> v%s", champ.version, prev.version)
        return {"champion": int(prev.version), "previous": int(champ.version)}

    @app.post("/retrain", status_code=202)
    def retrain(reason: str = Query("manual", max_length=200)):
        st.retrain_request.parent.mkdir(parents=True, exist_ok=True)
        st.retrain_request.write_text(
            json.dumps({"requested": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason})
        )
        return {"accepted": True, "reason": reason}

    @app.get("/pipeline/dag")
    def pipeline_dag():
        return dag_from_dvc(yaml.safe_load(st.dvc_path.read_text()))

    @app.get("/pipeline/runs")
    def pipeline_runs(limit: int = Query(50, ge=1, le=500)):
        return read_runs(st.runs_path, limit)

    @app.get("/pipeline/runs/{run_id}/log", response_class=PlainTextResponse)
    def pipeline_log(run_id: str, lines: int = Query(200, ge=1, le=2000)):
        rec = next((r for r in journal(st.runs_path) if r["run_id"] == run_id), None)
        if rec is None:
            raise HTTPException(404, "unknown run")
        path = Path(rec["log"]).resolve()
        if st.logs_root.resolve() not in path.parents or not path.exists():  # never serve files outside logs/
            raise HTTPException(404, "log not available")
        return "\n".join(path.read_text().splitlines()[-lines:])

    @app.get("/metrics")
    def prometheus_metrics():
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app


def headline(action: int, row: pd.Series) -> str:
    if action == STAY_OUT:
        return "Stay out"
    side = "call (CE)" if action == 1 else "put (PE)"
    return f"Buy the {int(row['strike'])} {side}"


def reason(action: int, probs: dict, tau: float) -> str:
    side = max(("BUY_CE", "BUY_PE"), key=probs.get)
    name = "the call" if side == "BUY_CE" else "the put"
    if tau >= NEVER_TRADE:
        return (
            "This model never trades: on its validation days no way of trading beat the costs, "
            "so its rule is to stay out. The probabilities below show what it thinks anyway."
        )
    if action == STAY_OUT:
        return f"Not confident enough to trade: its best choice, buying {name}, is only {probs[side]:.0%} likely (it needs {tau:.0%})."
    return f"Confident enough to trade: buying {name} is {probs[side]:.0%} likely (it needs {tau:.0%})."


__all__ = ["ModelServer", "ModelUnavailable", "Settings", "create_app"]
