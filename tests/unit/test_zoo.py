import numpy as np
import pytest

from optpred.zoo.data import Dataset, split_days
from optpred.zoo.models import FAMILIES, make, predict
from optpred.zoo.sim import choose_tau, simulate, trades_one_day

FEATURES = ["spot_ret_15s", "spot_ret_60s", "spot_ret_300s", "f3"]
SMALL = {
    "stay_out": {},
    "random": {"seed": 1},
    "momentum": {"window": 60},
    "linear": {"alpha": 1.0},
    "lgbm_reg": {"n_estimators": 20, "learning_rate": 0.1, "num_leaves": 7, "min_child_samples": 20},
    "lgbm_clf": {"n_estimators": 20, "learning_rate": 0.1, "num_leaves": 7, "min_child_samples": 20},
    "meta": {
        "window": 60,
        "n_estimators": 20,
        "learning_rate": 0.1,
        "num_leaves": 7,
        "min_child_samples": 20,
    },
    "gru": {"hidden": 8, "seq_len": 10, "epochs": 1, "lr": 0.01},
    "transformer": {"hidden": 8, "heads": 2, "layers": 1, "seq_len": 10, "epochs": 1, "lr": 0.01},
}


def synth_ds(n_days=4, n=600, seed=0):
    rng = np.random.default_rng(seed)
    N = n_days * n
    X = rng.normal(size=(N, len(FEATURES))).astype(np.float32)
    # planted signal: the call pays after a 60 s rise
    net = np.column_stack([60 * X[:, 1], -60 * X[:, 1]]) + rng.normal(0, 20, (N, 2))
    return Dataset(
        days=[f"d{i}" for i in range(n_days)],
        features=FEATURES,
        X=X,
        day_idx=np.repeat(np.arange(n_days), n).astype(np.int16),
        pos=np.tile(np.arange(n), n_days),
        valid=np.ones((N, 2), bool),
        net=net.astype(np.float32),
        hold=np.full((N, 2), 30, np.float32),
    )


def test_one_position_at_a_time():
    score = np.zeros((100, 2))
    score[[0, 10, 40], 0] = 1.0  # t=10 is inside the first trade (hold 30): must be skipped
    t, side, net = trades_one_day(
        score, np.ones((100, 2), bool), np.ones((100, 2)), np.full((100, 2), 30), 0.5
    )
    assert t.tolist() == [0, 40] and side.tolist() == [0, 0]


def test_nan_score_never_trades():
    score = np.full((5, 2), np.nan)
    score[2, 1] = 1.0
    t, side, _ = trades_one_day(score, np.ones((5, 2), bool), np.ones((5, 2)), np.ones((5, 2)), 0.0)
    assert t.tolist() == [2] and side.tolist() == [1]


def test_folds_are_walk_forward():
    dev, test, folds = split_days([f"d{i}" for i in range(20)], n_test=5, min_train=5, val_days=5)
    assert test == [f"d{i}" for i in range(15, 20)]
    assert [len(tr) for tr, _ in folds] == [5, 10] and all(
        dev.index(tr[-1]) + 1 == dev.index(v[0]) for tr, v in folds
    )


@pytest.mark.parametrize("family", list(FAMILIES))
def test_every_family_fits_and_scores(family):
    ds = synth_ds()
    m = make(family, SMALL[family], FEATURES).fit(ds, ds.rows(["d0", "d1", "d2"]))
    sl = ds.day_slices(["d3"])
    score = predict(m, ds, sl)
    assert score[sl[0][1]].shape == (600, 2)
    simulate(score, ds, sl, 0.0)


def test_trees_find_the_planted_signal():
    ds = synth_ds(n_days=6)
    m = make("lgbm_reg", SMALL["lgbm_reg"], FEATURES).fit(ds, ds.rows(["d0", "d1", "d2", "d3"]))
    sl = ds.day_slices(["d4", "d5"])
    tau, q, res = choose_tau(predict(m, ds, sl), ds, sl, [0.5, 0.9], min_trades=5)
    assert res["net_per_day"] > 0 and res["hit_rate"] > 0.6


def test_choose_tau_with_no_finite_score_never_trades():
    ds = synth_ds(n_days=2)
    sl = ds.day_slices(["d0", "d1"])
    tau, q, res = choose_tau(np.full((len(ds.X), 2), -np.inf), ds, sl, [0.9], min_trades=1)
    assert tau == np.inf and res["trades"] == 0
