"""Direction models (call / put / stay out). Three families: a baseline that never trades, a linear model
and LightGBM. Every model has the same interface:

    m = make(family, params, features)
    m.fit(ds, train_rows)             # train_rows: dataset rows of the training days
    score = m.predict_day(X_day)      # (n, 2) score for (CE, PE) for one whole day, in time order

A higher score = a better trade for that side. Scores feed the same simulator (optpred.zoo.sim).
Add a family: write a class with fit / predict_day and add it to FAMILIES.
"""

from __future__ import annotations

import numpy as np

SEED = 20261023


def _sample(ds, rows: np.ndarray, stride: int, side: int | None = None) -> np.ndarray:
    """Every `stride`-th second (neighbours are almost the same row), where an entry is possible."""
    r = rows[ds.pos[rows] % stride == 0]
    ok = ds.valid[r].any(axis=1) if side is None else ds.valid[r, side]
    return r[ok]


class StayOut:
    """Never trades. The result every model must beat."""

    def __init__(self, params, features):
        pass

    def fit(self, ds, rows):
        return self

    def predict_day(self, X):
        return np.full((len(X), 2), -np.inf)


class _Tabular:
    """One model per side on the feature row of second t."""

    def __init__(self, params, features):
        self.p = dict(params)
        self.features = features
        self.drop = set(self.p.pop("drop_columns", []))
        self.keep = np.array([f not in self.drop for f in features])
        self.models = [None, None]

    def _xy(self, ds, rows, side):
        r = _sample(ds, rows, self.p.get("stride", 5), side)
        return ds.X[r][:, self.keep], ds.net[r, side]

    def predict_day(self, X):
        Xk = X[:, self.keep]
        return np.column_stack([self._score(m, Xk) for m in self.models])


class Linear(_Tabular):
    """Ridge regression of net rupees. Median imputation and scaling from the training rows only."""

    def fit(self, ds, rows):
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        for j in (0, 1):
            X, y = self._xy(ds, rows, j)
            lo, hi = np.quantile(y, [0.01, 0.99])
            self.models[j] = make_pipeline(
                SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=self.p["alpha"])
            ).fit(X, np.clip(y, lo, hi))
        return self

    def _score(self, m, X):
        return m.predict(X)


class LGBMRegressor(_Tabular):
    """LightGBM regression of net rupees (Huber loss: robust to fat tails)."""

    def fit(self, ds, rows):
        import lightgbm as lgb

        for j in (0, 1):
            X, y = self._xy(ds, rows, j)
            self.models[j] = lgb.LGBMRegressor(
                objective="huber",
                alpha=self.p.get("huber_delta", 50.0),
                n_estimators=self.p["n_estimators"],
                learning_rate=self.p["learning_rate"],
                num_leaves=self.p["num_leaves"],
                min_child_samples=self.p["min_child_samples"],
                colsample_bytree=0.8,
                subsample=0.8,
                subsample_freq=1,
                random_state=SEED,
                n_jobs=self.p.get("n_jobs", 1),
                verbose=-1,
            ).fit(X, y)
        return self

    def _score(self, m, X):
        return m.predict(X)

    def importance(self) -> dict[str, float]:
        names = [f for f, k in zip(self.features, self.keep, strict=True) if k]
        gain = sum(m.booster_.feature_importance("gain") for m in self.models)
        return dict(zip(names, (gain / gain.sum()).round(5).tolist(), strict=True))


FAMILIES = {"stay_out": StayOut, "linear": Linear, "lgbm_reg": LGBMRegressor}


def make(family: str, params: dict, features: list[str]):
    return FAMILIES[family](dict(params), features)


def predict(model, ds, day_slices) -> np.ndarray:
    """(N, 2) scores for the rows of the given days (NaN elsewhere)."""
    score = np.full((len(ds.X), 2), np.nan)
    for _, sl in day_slices:
        score[sl] = model.predict_day(ds.X[sl])
    return score
