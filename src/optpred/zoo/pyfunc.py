"""MLflow pyfunc wrapper of a zoo model: what the model server loads. Few imports, on purpose."""

from __future__ import annotations

import pickle

import mlflow
import numpy as np
import pandas as pd


class SignalModel(mlflow.pyfunc.PythonModel):
    """Input: feature rows of one day, in time order (sequence models need the previous seq_len rows).
    Output per row: score_ce, score_pe and action (BUY_CE / BUY_PE / STAY_OUT, using the model's tau)."""

    def load_context(self, context):
        with open(context.artifacts["model"], "rb") as f:
            obj = pickle.load(f)
        self.model, self.features, self.tau = obj["model"], obj["features"], obj["tau"]

    def predict(self, context, model_input: pd.DataFrame, params=None):
        s = self.model.predict_day(model_input[self.features].to_numpy(np.float32))
        s = np.where(np.isfinite(s), s, -np.inf)
        side = s.argmax(axis=1)
        best = s[np.arange(len(s)), side]
        action = np.where(best > self.tau, np.where(side == 0, "BUY_CE", "BUY_PE"), "STAY_OUT")
        return pd.DataFrame({"score_ce": s[:, 0], "score_pe": s[:, 1], "action": action})
