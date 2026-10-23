"""The one-time test-day evaluation: it must refuse early or repeated looks and score the served model."""

import json

import mlflow
import numpy as np
import pandas as pd

from optpred.features.labels import STAY_OUT
from optpred.models import evaluate, register, train
from tests.helpers.planted import stage_workspace


def test_refuses_without_final_and_refuses_a_second_look(tmp_path, monkeypatch):
    stage_workspace(tmp_path, monkeypatch)
    assert evaluate.main([], {}) == 2  # no --final: the test days stay locked
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/final.json").write_text("{}")
    assert evaluate.main(["--final"], {}) == 3  # already scored once


def test_scores_the_registered_champion_and_writes_the_marker(tmp_path, monkeypatch):
    stage_workspace(tmp_path, monkeypatch, signal=1.0)
    assert train.main([], {}) == 0 and register.main([], {}) == 0
    summary = {}
    assert evaluate.main(["--final"], summary) == 0
    res = json.loads((tmp_path / "reports/final.json").read_text())
    champ = mlflow.MlflowClient().get_model_version_by_alias("m", "champion")
    assert res["model"]["version"] == int(champ.version) and res["model"]["run_id"] == champ.run_id
    assert res["tau"] == float(mlflow.MlflowClient().get_run(champ.run_id).data.params["tau"])
    assert len(res["days"]) == 3 and set(res["by_slippage"]) == {"0.0", "0.31"}
    # a planted signal must be found on the unseen days
    assert res["information"]["detected"] and res["verdict"]["side_picking_detected"]
    run = mlflow.MlflowClient().get_run(summary["mlflow_run_id"])
    assert run.data.tags["test_days_read"] == "yes" and run.data.tags["champion_run_id"] == champ.run_id


def test_a_never_trade_model_scores_zero_and_finds_nothing_in_noise():
    rng = np.random.default_rng(0)
    from tests.helpers.planted import make

    test = make(4, 0.0, 3, "test").sort_values(["day", "minute"]).reset_index(drop=True)
    proba = rng.dirichlet([5, 5, 5], size=len(test))
    served = pd.DataFrame(proba, columns=evaluate.PROBA_COLUMNS).assign(action=STAY_OUT)
    p = {"qty": 65, "horizon_min": 2}
    costs = {"slippage_pts_per_leg": 0.31, "sensitivity_pts_per_leg": [0.31]}
    b = {"random_seeds": 20, "bootstrap_resamples": 200, "seed": 1}
    res = evaluate.score_test(test, served, 1.01, np.array([1 / 3] * 3), p, costs, b)
    assert res["verdict"]["champion_net_per_day_rs"] == 0.0
    assert res["by_slippage"]["0.31"]["champion"]["trades"] == 0
    assert not res["information"]["detected"] and not res["verdict"]["side_picking_detected"]
