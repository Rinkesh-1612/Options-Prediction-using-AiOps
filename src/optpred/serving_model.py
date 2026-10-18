"""The model as MLflow serves it: features in -> probabilities, action and reasons out.

The decision rule (confidence threshold `tau`) is stored INSIDE the model, so the service that
answers a request can never apply a different rule from the one chosen in training. This is the
course's "training-serving skew" problem, closed by construction.

`score_frame` is the single scoring function: training uses it to build the model's signature and
to check itself, serving uses it to answer requests.
"""

from __future__ import annotations

import json

import lightgbm as lgb
import mlflow.pyfunc
import numpy as np
import pandas as pd

from optpred.labels import ACTION_NAMES, STAY_OUT

NEVER_TRADE = 1.01  # a threshold no probability can reach
OUTPUT_COLUMNS = ["p_stay_out", "p_buy_ce", "p_buy_pe", "action", "tau", "drivers"]


def decide(proba: np.ndarray, tau: float) -> np.ndarray:
    """Most likely class if it is a side and at least tau confident, else STAY_OUT."""
    best, conf = proba.argmax(axis=1), proba.max(axis=1)
    return np.where((best != STAY_OUT) & (conf >= tau), best, STAY_OUT)


def score_frame(
    booster: lgb.Booster, classes: list[int], X: pd.DataFrame, tau: float, top_k: int = 3
) -> pd.DataFrame:
    """Probabilities for the three actions, the decision, and the inputs that pushed hardest."""
    raw = np.asarray(booster.predict(X))
    proba = np.zeros((len(X), 3))
    proba[:, classes] = raw.reshape(len(X), -1)
    contrib = np.asarray(booster.predict(X, pred_contrib=True))
    n_cls, n_feat = len(classes), X.shape[1]
    contrib = contrib.reshape(len(X), n_cls, n_feat + 1)[:, :, :-1]  # drop the per-class bias column
    top_cls = raw.reshape(len(X), -1).argmax(axis=1)  # explain the class the model finds most likely
    drivers = []
    for i in range(len(X)):
        c = contrib[i, top_cls[i]]
        order = np.argsort(-np.abs(c))[:top_k]
        drivers.append(
            json.dumps(
                [
                    {
                        "feature": X.columns[j],
                        "value": None if pd.isna(X.iloc[i, j]) else float(X.iloc[i, j]),
                        "push": round(float(c[j]), 4),
                    }
                    for j in order
                ]
            )
        )
    return pd.DataFrame(
        {
            "p_stay_out": proba[:, STAY_OUT],
            "p_buy_ce": proba[:, 1],
            "p_buy_pe": proba[:, 2],
            "action": decide(proba, tau).astype(int),
            "tau": float(tau),
            "drivers": drivers,
        }
    )


class DirectionModel(mlflow.pyfunc.PythonModel):
    """MLflow pyfunc wrapper around the LightGBM booster plus the decision rule."""

    def __init__(self, tau: float, features: list[str]):
        self.tau, self.features = tau, list(features)

    def load_context(self, context):
        self.booster = lgb.Booster(model_file=context.artifacts["booster"])
        with open(context.artifacts["meta"]) as f:
            self.classes = json.load(f)["classes"]

    def predict(self, context, model_input, params=None):
        missing = [c for c in self.features if c not in model_input.columns]
        if missing:
            raise ValueError(f"missing input columns: {missing}")
        return score_frame(self.booster, self.classes, model_input[self.features].astype(float), self.tau)


__all__ = ["ACTION_NAMES", "DirectionModel", "NEVER_TRADE", "OUTPUT_COLUMNS", "decide", "score_frame"]
