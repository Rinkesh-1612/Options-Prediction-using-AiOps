"""MLflow pyfunc wrapper of a zoo model: what the model server loads. Few imports, on purpose."""

from __future__ import annotations

import json
import pickle

import mlflow
import numpy as np
import pandas as pd

from optpred.zoo.explain import drivers


class SignalModel(mlflow.pyfunc.PythonModel):
    """Input: feature rows of one day, in time order.
    Output per row: score_ce, score_pe, action (BUY_CE / BUY_PE / STAY_OUT, using the model's tau) and
    `drivers`: for the LAST row only, a JSON string with the inputs behind the best side's score
    (optpred.zoo.explain); an empty string for other rows and for models that cannot explain."""

    def load_context(self, context):
        with open(context.artifacts["model"], "rb") as f:
            obj = pickle.load(f)
        self.model, self.features, self.tau = obj["model"], obj["features"], obj["tau"]

    def predict(self, context, model_input: pd.DataFrame, params=None):
        X = model_input[self.features].to_numpy(np.float32)
        s = self.model.predict_day(X)
        s = np.where(np.isfinite(s), s, -np.inf)
        side = s.argmax(axis=1)
        best = s[np.arange(len(s)), side]
        action = np.where(best > self.tau, np.where(side == 0, "BUY_CE", "BUY_PE"), "STAY_OUT")
        why = [""] * len(s)
        if len(s) and np.isfinite(best[-1]):
            d = drivers(self.model, X[-1], int(side[-1]))
            why[-1] = json.dumps(d) if d else ""
        return pd.DataFrame({"score_ce": s[:, 0], "score_pe": s[:, 1], "action": action, "drivers": why})
