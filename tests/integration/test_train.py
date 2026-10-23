"""The model stage on planted data: it must find a planted signal, and must NOT claim one in noise."""

import json

import numpy as np

from optpred.features.labels import STAY_OUT
from optpred.features.minute import FEATURE_COLUMNS
from optpred.models import register, train
from tests.helpers.planted import LGBM, P, T, make, stage_workspace


def fit(signal, seed=0):
    train_df, val_df = make(15, signal, seed, "train"), make(5, signal, seed + 1, "val")
    val_df["day"] = val_df["day"].str.replace("2026-01", "2026-03")  # keep val days distinct from train days
    return train.fit_and_score(train_df, val_df, LGBM, 1, P, T)


def test_finds_a_planted_signal():
    out = fit(signal=1.0)
    assert out["val_logloss"] < out["val_logloss_prior"] - 0.05  # it knows more than the class frequencies
    best = next(r for r in out["threshold_table"] if r["tau"] == out["tau"])
    assert best["mean_net_per_trade_rs"] > 20 and out["tau"] < train.NEVER_TRADE


def test_stays_out_when_there_is_nothing_to_find():
    out = fit(signal=0.0)
    assert out["tau"] == train.NEVER_TRADE  # every way of trading loses after costs on validation


def test_decision_rule():
    proba = np.array([[0.2, 0.5, 0.3], [0.6, 0.2, 0.2], [0.1, 0.2, 0.7], [0.3, 0.3, 0.4]])
    assert list(train.decide(proba, 0.5)) == [1, STAY_OUT, 2, STAY_OUT]
    assert list(train.decide(proba, 0.0)) == [1, STAY_OUT, 2, 2]
    assert (train.decide(proba, train.NEVER_TRADE) == STAY_OUT).all()


def test_stage_tracks_in_mlflow_and_registers_a_champion(tmp_path, monkeypatch):
    import mlflow

    df = stage_workspace(tmp_path, monkeypatch)
    summary = {}
    assert train.main([], summary) == 0
    assert register.main([], {}) == 0  # the register stage moves the aliases
    client = mlflow.MlflowClient()
    run = client.get_run(summary["mlflow_run_id"])
    assert run.data.tags["test_days_read"] == "no" and "git_commit" in run.data.tags
    assert {"seed", "tau", "features_sha", "days_sha"} <= set(run.data.params)
    assert "val_net_per_day_rs_selected" in run.data.metrics
    assert client.get_model_version_by_alias("m", "champion").run_id == summary["mlflow_run_id"]
    # what MLflow serves must give the same answer as the trained model, with the rule inside it
    served = mlflow.pyfunc.load_model("models:/m@champion").predict(
        df[df["split"] == "val"][FEATURE_COLUMNS].head(5).astype(float)
    )
    assert list(served.columns) == ["p_stay_out", "p_buy_ce", "p_buy_pe", "action", "tau", "drivers"]
    assert np.allclose(served[["p_stay_out", "p_buy_ce", "p_buy_pe"]].sum(axis=1), 1.0)
    assert len(json.loads(served["drivers"][0])) == 3


def test_register_promotes_only_a_better_model_and_keeps_the_old_one_for_rollback(tmp_path, monkeypatch):
    import mlflow

    stage_workspace(tmp_path, monkeypatch)
    assert register.main([], {}) == 2  # no train report yet
    assert train.main([], {}) == 0 and register.main([], {}) == 0
    client = mlflow.MlflowClient()
    first = client.get_model_version_by_alias("m", "champion").version
    assert train.main([], {}) == 0 and register.main([], {}) == 0  # same data: not strictly better
    assert client.get_model_version_by_alias("m", "champion").version == first
    assert client.get_model_version_by_alias("m", "candidate").version != first
    out = json.loads((tmp_path / "reports/train.json").read_text())
    report = tmp_path / "reports/train.json"
    report.write_text(json.dumps({**out, "val_net_per_day_rs_selected": 1e9}))  # pretend it is better
    assert register.main([], {}) == 0
    assert client.get_model_version_by_alias("m", "champion").version != first
    assert client.get_model_version_by_alias("m", "previous").version == first
