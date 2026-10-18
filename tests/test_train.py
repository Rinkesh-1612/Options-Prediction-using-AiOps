"""The model stage on planted data: it must find a planted signal, and must NOT claim one in noise."""

import json

import numpy as np
import pandas as pd
import yaml


from optpred import train
from optpred.features import FEATURE_COLUMNS
from optpred.labels import STAY_OUT

P = {"qty": 65, "horizon_min": 2, "_slip": 0.31}
T = {"n_jobs": 2, "early_stopping_rounds": 20, "threshold_grid": [0.0, 0.5, 0.6, 1.01], "min_val_trades": 20}
LGBM = {"n_estimators": 150, "learning_rate": 0.1, "num_leaves": 7, "min_child_samples": 20}


def make(n_days, signal, seed, split):
    """Rows shaped like features.parquet. With `signal`, ce_imb1 predicts the sign of the 2-minute move."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        n = 300
        f = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
        move = 150 * f["ce_imb1"].to_numpy() * signal + rng.normal(0, 40, n)  # rupees per lot
        f["ce_gross_rs"], f["pe_gross_rs"] = move - 16, -move - 16
        f["ce_stat_rs"] = f["pe_stat_rs"] = 13.0
        f["day"], f["minute"], f["split"] = f"2026-0{1 + d // 28}-{1 + d % 28:02d}", np.arange(n) + 560, split
        rows.append(f)
    return pd.concat(rows, ignore_index=True)


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

    monkeypatch.chdir(tmp_path)
    df = pd.concat(
        [make(12, 1.0, 0, "train"), make(4, 1.0, 1, "val"), make(3, 1.0, 2, "test")], ignore_index=True
    )
    df.loc[df["split"] == "val", "day"] = df.loc[df["split"] == "val", "day"].str.replace(
        "2026-01", "2026-03"
    )
    df.loc[df["split"] == "test", "day"] = df.loc[df["split"] == "test", "day"].str.replace(
        "2026-01", "2026-05"
    )
    (tmp_path / "data/features").mkdir(parents=True)
    df.to_parquet(tmp_path / "data/features/features.parquet")
    (tmp_path / "data/days.json").write_text(json.dumps({"accepted": []}))
    (tmp_path / "params.yaml").write_text(
        yaml.safe_dump(
            {
                "features": {"out_dir": "data/features", "qty": 65, "horizon_min": 2},
                "costs": {"slippage_pts_per_leg": 0.31},
                "baselines": {"random_seeds": 3, "bootstrap_resamples": 50, "seed": 1},
                "train": {**T, "seed": 1, "lgbm": LGBM},
                "mlflow": {
                    "tracking_uri": f"sqlite:///{tmp_path}/mlflow/mlflow.db",
                    "artifact_root": "mlflow/artifacts",
                    "experiment": "t",
                    "registered_model": "m",
                },
            }
        )
    )
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    summary = {}
    assert train.main([], summary) == 0
    client = mlflow.MlflowClient()
    run = client.get_run(summary["mlflow_run_id"])
    assert run.data.tags["test_days_read"] == "no" and "git_commit" in run.data.tags
    assert {"seed", "tau", "features_sha", "days_sha"} <= set(run.data.params)
    assert "val_net_per_day_rs_selected" in run.data.metrics
    assert client.get_model_version_by_alias("m", "champion").run_id == summary["mlflow_run_id"]
