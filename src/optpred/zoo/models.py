"""Model zoo. Every model has the same interface:

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


class RandomPick:
    """Random scores: trades at random times on a random side."""

    def __init__(self, params, features):
        self.rng = np.random.default_rng(params.get("seed", SEED))

    def fit(self, ds, rows):
        return self

    def predict_day(self, X):
        return self.rng.random((len(X), 2))


class Momentum:
    """Buy the call after NIFTY rose, the put after it fell, over `window` seconds."""

    def __init__(self, params, features):
        self.col = features.index(f"spot_ret_{params['window']}s")

    def fit(self, ds, rows):
        return self

    def predict_day(self, X):
        r = X[:, self.col].astype(float)
        return np.column_stack([r, -r])


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


class LGBMClassifier(LGBMRegressor):
    """LightGBM classifier of P(net rupees > 0)."""

    def fit(self, ds, rows):
        import lightgbm as lgb

        for j in (0, 1):
            X, y = self._xy(ds, rows, j)
            self.models[j] = lgb.LGBMClassifier(
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
            ).fit(X, (y > 0).astype(int))
        return self

    def _score(self, m, X):
        return m.predict_proba(X)[:, 1]


class MetaLabel(_Tabular):
    """Meta-labelling: momentum picks the side; LightGBM gives P(that trade nets > 0) as its score."""

    def __init__(self, params, features):
        super().__init__(params, features)
        self.mom = features.index(f"spot_ret_{self.p['window']}s")

    def fit(self, ds, rows):
        import lightgbm as lgb

        r = _sample(ds, rows, self.p.get("stride", 5))
        side = (ds.X[r, self.mom] <= 0).astype(int)  # 0 = CE after a rise, 1 = PE after a fall
        ok = ds.valid[r, side] & np.isfinite(ds.X[r, self.mom])
        r, side = r[ok], side[ok]
        X = np.column_stack([ds.X[r][:, self.keep], side])
        y = (ds.net[r, side] > 0).astype(int)
        self.models[0] = lgb.LGBMClassifier(
            n_estimators=self.p["n_estimators"],
            learning_rate=self.p["learning_rate"],
            num_leaves=self.p["num_leaves"],
            min_child_samples=self.p["min_child_samples"],
            colsample_bytree=0.8,
            random_state=SEED,
            n_jobs=self.p.get("n_jobs", 1),
            verbose=-1,
        ).fit(X, y)
        return self

    def predict_day(self, X):
        ret = X[:, self.mom]
        side = (ret <= 0).astype(int)
        p = self.models[0].predict_proba(np.column_stack([X[:, self.keep], side]))[:, 1]
        out = np.full((len(X), 2), -np.inf)
        ok = np.isfinite(ret)
        out[np.flatnonzero(ok), side[ok]] = p[ok]
        return out


class Sequence:
    """GRU or small transformer over the last `seq_len` seconds of features -> net rupees of both sides."""

    def __init__(self, params, features):
        self.p = params
        self.F = len(features)

    def _net(self):
        from optpred.zoo.seqnets import build

        keys = ("hidden", "seq_len", "heads", "layers")
        return build(self.p["arch"], self.F, {k: self.p[k] for k in keys if k in self.p})

    def _norm(self, X):
        return np.nan_to_num((X - self.mu) / self.sd, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    def fit(self, ds, rows):
        import torch

        torch.manual_seed(SEED)
        torch.set_num_threads(self.p.get("n_jobs", 1))
        L = self.p["seq_len"]
        r = _sample(ds, rows, self.p.get("stride", 10))
        r = r[ds.pos[r] >= L - 1]
        Xtr = ds.X[rows]
        self.mu, self.sd = np.nanmean(Xtr, axis=0), np.nanstd(Xtr, axis=0) + 1e-6
        Xn = self._norm(ds.X)  # rows of other days are never in a window: windows stay inside one day
        y = np.nan_to_num(ds.net[r] / 100.0).astype(np.float32)
        mask = ds.valid[r].astype(np.float32)
        self.net = self._net()
        opt = torch.optim.Adam(self.net.parameters(), lr=self.p["lr"])
        rng = np.random.default_rng(SEED)
        offs = np.arange(-L + 1, 1)
        for _ in range(self.p["epochs"]):
            for b in np.array_split(rng.permutation(len(r)), max(1, len(r) // 512)):
                xb = torch.from_numpy(Xn[r[b][:, None] + offs])
                out = self.net(xb)
                loss = (
                    torch.nn.functional.huber_loss(out, torch.from_numpy(y[b]), reduction="none")
                    * torch.from_numpy(mask[b])
                ).sum() / max(mask[b].sum(), 1.0)
                opt.zero_grad()
                loss.backward()
                opt.step()
        return self

    def predict_day(self, X):
        import torch

        L = self.p["seq_len"]
        Xn = self._norm(X)
        out = np.full((len(X), 2), np.nan)
        idx = np.arange(L - 1, len(X))
        offs = np.arange(-L + 1, 1)
        self.net.eval()
        with torch.no_grad():
            for b in np.array_split(idx, max(1, len(idx) // 4096)):
                out[b] = self.net(torch.from_numpy(Xn[b[:, None] + offs])).numpy() * 100.0
        return out


FAMILIES = {
    "stay_out": StayOut,
    "random": RandomPick,
    "momentum": Momentum,
    "linear": Linear,
    "lgbm_reg": LGBMRegressor,
    "lgbm_clf": LGBMClassifier,
    "meta": MetaLabel,
    "gru": Sequence,
    "transformer": Sequence,
}


def make(family: str, params: dict, features: list[str]):
    p = dict(params)
    if family in ("gru", "transformer"):
        p["arch"] = family
    return FAMILIES[family](p, features)


def predict(model, ds, day_slices) -> np.ndarray:
    """(N, 2) scores for the rows of the given days (NaN elsewhere)."""
    score = np.full((len(ds.X), 2), np.nan)
    for _, sl in day_slices:
        score[sl] = model.predict_day(ds.X[sl])
    return score
