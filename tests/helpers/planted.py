"""Planted data for model tests: rows shaped like the feature tables, with or without a real signal."""

import json

import numpy as np
import pandas as pd
import yaml

from optpred.features.minute import FEATURE_COLUMNS

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


def stage_workspace(tmp_path, monkeypatch, signal=1.0):
    """A temporary repo: features with train, val and test days, params.yaml, its own MLflow store."""
    monkeypatch.chdir(tmp_path)
    df = pd.concat(
        [make(12, signal, 0, "train"), make(4, signal, 1, "val"), make(3, signal, 2, "test")],
        ignore_index=True,
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
                "costs": {"slippage_pts_per_leg": 0.31, "sensitivity_pts_per_leg": [0.0, 0.31]},
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
    # isolate from an outer MLflow run (`mlflow run` sets these in its container)
    for var in ("MLFLOW_TRACKING_URI", "MLFLOW_RUN_ID", "MLFLOW_EXPERIMENT_ID", "MLFLOW_EXPERIMENT_NAME"):
        monkeypatch.delenv(var, raising=False)
    return df
