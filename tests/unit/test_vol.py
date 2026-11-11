import numpy as np
import pandas as pd
import pytest

from optpred.vol.inputs import HORIZONS, inputs, targets
from optpred.vol.models import FAMILIES, make, qlike
from tests.helpers.grid_synth import synth_grid


def test_inputs_have_no_look_ahead():
    g = synth_grid(n=2400)
    full = inputs(g)
    for cut in (700, 1900):
        pd.testing.assert_frame_equal(full.iloc[:cut], inputs(g.iloc[:cut]), check_exact=False, rtol=1e-9)


def test_targets_look_only_forward():
    g = synth_grid(n=2400)
    t = targets(g)
    assert t["rv_fwd_300"].iloc[-300:].isna().all() and t["rv_fwd_300"].iloc[:1000].notna().all()
    g2 = g.copy()
    g2.loc[:999, "spot"] *= 1.01  # change the past: the target from row 1000 on must not move
    pd.testing.assert_series_equal(targets(g2)["rv_fwd_300"].iloc[1001:], t["rv_fwd_300"].iloc[1001:])


def test_qlike_is_zero_for_a_perfect_forecast_and_grows_with_error():
    y = np.array([10.0, 20.0, 5.0])
    assert qlike(y, y) == pytest.approx(0.0)
    assert qlike(y, y * 2) > qlike(y, y * 1.2) > 0


def planted(n=6000, seed=0):
    """Volatility clusters: past move predicts the future move; IV is noise."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.uniform(5, 40, n // 300), 300)
    X = pd.DataFrame({f"rv_past_{w}": regime * rng.lognormal(0, 0.1, n) for w in (60, 300, 900, 1800)})
    X["rv_day"] = regime.mean()
    X["iv_move_300"], X["iv_move_900"] = rng.uniform(5, 40, n), rng.uniform(5, 40, n)
    X["tod"] = np.tile(np.linspace(0, 1, 300), n // 300)
    Y = pd.DataFrame({f"rv_fwd_{h}": regime * rng.lognormal(0, 0.2, n) for h in HORIZONS})
    return X, Y


@pytest.mark.parametrize("name", list(FAMILIES))
def test_every_forecaster_fits_and_predicts_positive(name):
    X, Y = planted()
    p = {}
    fc = make(name, p).fit(X[:4000], Y[:4000]).predict(X[4000:])
    assert list(fc.columns) == ["fc_300", "fc_900"] and (fc.to_numpy() > 0).all()


def test_har_beats_noise_iv_on_clustered_volatility():
    X, Y = planted()
    har = make("har", {}).fit(X[:4000], Y[:4000]).predict(X[4000:])
    imp = make("implied", {}).fit(X[:4000], Y[:4000]).predict(X[4000:])
    assert qlike(Y["rv_fwd_900"][4000:], har["fc_900"]) < qlike(Y["rv_fwd_900"][4000:], imp["fc_900"])
