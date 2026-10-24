"""Volatility forecasters. Each predicts log(rv_fwd_h) for both horizons. Same interface:

m = make(name, params).fit(X, Y)      # X: inputs (+ features for lgbm), Y: targets
m.predict(X) -> DataFrame [fc_300, fc_900] in bp
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from optpred.vol.inputs import HORIZONS, design

SEED = 20261024


class Implied:
    """The option market's forecast: the IV-implied move, with a constant scale fitted on training rows."""

    def __init__(self, params):
        self.k = {}

    def fit(self, X, Y):
        for h in HORIZONS:
            ok = Y[f"rv_fwd_{h}"].gt(0) & X[f"iv_move_{h}"].gt(0)
            self.k[h] = float(np.mean(np.log(Y.loc[ok, f"rv_fwd_{h}"]) - np.log(X.loc[ok, f"iv_move_{h}"])))
        return self

    def predict(self, X):
        return pd.DataFrame(
            {f"fc_{h}": X[f"iv_move_{h}"] * np.exp(self.k[h]) for h in HORIZONS}, index=X.index
        )


class Linear:
    """HAR: linear regression of log future move on log past moves (+ IV when with_iv)."""

    def __init__(self, params):
        self.with_iv = params.get("with_iv", False)
        self.m = {}

    def fit(self, X, Y):
        from sklearn.linear_model import Ridge

        for h in HORIZONS:
            ok = Y[f"rv_fwd_{h}"].gt(0)
            self.m[h] = Ridge(alpha=1e-3).fit(
                design(X[ok], h, self.with_iv), np.log(Y.loc[ok, f"rv_fwd_{h}"])
            )
        return self

    def predict(self, X):
        return pd.DataFrame(
            {f"fc_{h}": np.exp(self.m[h].predict(design(X, h, self.with_iv))) for h in HORIZONS},
            index=X.index,
        )


class LGBM:
    """LightGBM on the HAR inputs and every library feature."""

    def __init__(self, params):
        self.p, self.m, self.cols = params, {}, None

    def fit(self, X, Y):
        import lightgbm as lgb

        self.cols = list(X.columns)
        for h in HORIZONS:
            ok = Y[f"rv_fwd_{h}"].gt(0)
            self.m[h] = lgb.LGBMRegressor(
                n_estimators=self.p.get("n_estimators", 400),
                learning_rate=self.p.get("learning_rate", 0.03),
                num_leaves=self.p.get("num_leaves", 15),
                min_child_samples=self.p.get("min_child_samples", 200),
                subsample=0.8,
                subsample_freq=1,
                colsample_bytree=0.8,
                random_state=SEED,
                n_jobs=self.p.get("n_jobs", 4),
                verbose=-1,
            ).fit(X.loc[ok, self.cols], np.log(Y.loc[ok, f"rv_fwd_{h}"]))
        return self

    def predict(self, X):
        return pd.DataFrame(
            {f"fc_{h}": np.exp(self.m[h].predict(X[self.cols])) for h in HORIZONS}, index=X.index
        )


FAMILIES = {"implied": Implied, "har": Linear, "har_iv": Linear, "lgbm": LGBM}


def make(name: str, params: dict):
    p = dict(params)
    if name == "har_iv":
        p["with_iv"] = True
    return FAMILIES[name](p)


def qlike(y: np.ndarray, f: np.ndarray) -> float:
    """QLIKE loss of a volatility forecast (robust to noise in the realized proxy). Lower is better."""
    v, p = np.asarray(y, float) ** 2, np.asarray(f, float) ** 2
    ok = (v > 0) & (p > 0)
    r = v[ok] / p[ok]
    return float(np.mean(r - np.log(r) - 1))
