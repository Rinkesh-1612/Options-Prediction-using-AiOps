"""Tuning folds must respect time, and the tuning score must beat the prior on planted signal."""

import pytest

from optpred.models import tune
from tests.helpers.planted import LGBM, make


def test_folds_are_walk_forward_by_day():
    days = [f"d{i:02d}" for i in range(30)]
    folds = tune.walk_forward_folds(days, 3, min_train_days=12)
    assert len(folds) == 3
    for train, test in folds:
        assert max(train) < min(test)  # the scored days come after the training days
        assert not set(train) & set(test)  # no day on both sides
    assert len(folds[0][0]) == 12 and len(folds[1][0]) > len(folds[0][0])  # expanding window


def test_too_few_days_is_a_clear_error():
    with pytest.raises(tune.TuneError):
        tune.walk_forward_folds([f"d{i}" for i in range(12)], 3, min_train_days=12)


def test_cv_logloss_is_below_the_no_information_loss_when_a_signal_exists():
    df = make(20, 1.0, 7, "train")
    folds = tune.walk_forward_folds(sorted(df["day"].unique()), 2, min_train_days=10)
    got = tune.cv_logloss(df, LGBM, folds, 0.31, 65, 1, 2, 20)
    assert got["logloss"] < 1.0 and len(got["fold_logloss"]) == 2
