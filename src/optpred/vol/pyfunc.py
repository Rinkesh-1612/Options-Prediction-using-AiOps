"""MLflow pyfunc wrapper of the volatility champion.

Input: input rows (optpred.vol.inputs) plus feature columns when the model uses them.
Output: fc_300, fc_900 = forecast NIFTY move over the next 5 / 15 min, in bp.
"""

from __future__ import annotations

import pickle

import mlflow


class VolModel(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        with open(context.artifacts["model"], "rb") as f:
            self.model = pickle.load(f)["model"]

    def predict(self, context, model_input, params=None):
        return self.model.predict(model_input)
