"""Per-signal explanation: why did the model give this score? Exact SHAP values from LightGBM.

Source: `pred_contrib` of the booster.
For one row and one side: score = base + sum of the contributions of all inputs.
For the regression champion the unit is expected net rupees, so "ATM IV: +₹40" reads directly.
Only LightGBM models can explain; other families (linear, GRU, ...) return None and the signal has no drivers.
"""

from __future__ import annotations

import numpy as np

from optpred.zoo.models import LGBMClassifier, LGBMRegressor

SIDES = ("ce", "pe")


def drivers(model, x_row: np.ndarray, side: int, k: int = 5) -> dict | None:
    """The k inputs that moved the score of `side` most (by size), for one feature row (shape (F,))."""
    if not isinstance(model, LGBMRegressor):  # LGBMClassifier is a subclass: log-odds instead of rupees
        return None
    names = [f for f, kept in zip(model.features, model.keep, strict=True) if kept]
    x = np.asarray(x_row, dtype=np.float32)[model.keep]
    contrib = model.models[side].predict(x.reshape(1, -1), pred_contrib=True)[0]
    c, base = contrib[:-1], float(contrib[-1])
    top = np.argsort(-np.abs(c))[:k]
    return {
        "side": SIDES[side],
        "unit": "log-odds" if isinstance(model, LGBMClassifier) else "net_rs",
        "base": base,
        "score": float(contrib.sum()),
        "top": [
            {
                "feature": names[i],
                "value": float(x[i]) if np.isfinite(x[i]) else None,
                "contribution": float(c[i]),
            }
            for i in top
        ],
        "other": float(c.sum() - c[top].sum()),
    }
