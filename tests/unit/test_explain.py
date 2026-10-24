import json
import pickle
from types import SimpleNamespace

import pytest

from optpred.zoo.explain import drivers
from optpred.zoo.models import make
from optpred.zoo.pyfunc import SignalModel
from tests.unit.test_zoo import FEATURES, SMALL, synth_ds


@pytest.fixture(scope="module")
def trained():
    ds = synth_ds(n_days=5)
    return ds, make("lgbm_reg", SMALL["lgbm_reg"], FEATURES).fit(ds, ds.rows(["d0", "d1", "d2", "d3"]))


def test_contributions_add_up_to_the_score_and_name_the_planted_driver(trained):
    ds, m = trained
    X = ds.X[ds.rows(["d4"])][:50]
    for i in (0, 10, 49):
        for side in (0, 1):
            d = drivers(m, X[i], side)
            assert d["score"] == pytest.approx(
                d["base"] + sum(t["contribution"] for t in d["top"]) + d["other"], abs=1e-4
            )
            assert d["score"] == pytest.approx(m.predict_day(X)[i, side], abs=1e-3)
    big = [drivers(m, X[i], 0)["top"][0]["feature"] for i in range(50)]
    assert big.count("spot_ret_60s") > 40  # the planted signal drives the call score


def test_other_families_return_no_drivers():
    ds = synth_ds()
    m = make("linear", SMALL["linear"], FEATURES).fit(ds, ds.rows(["d0", "d1"]))
    assert drivers(m, ds.X[0], 0) is None


def test_served_model_explains_only_the_last_row(trained, tmp_path):
    ds, m = trained
    pkl = tmp_path / "m.pkl"
    pkl.write_bytes(pickle.dumps({"model": m, "features": FEATURES, "tau": 0.0}))
    sm = SignalModel()
    sm.load_context(SimpleNamespace(artifacts={"model": str(pkl)}))
    import pandas as pd

    out = sm.predict(None, pd.DataFrame(ds.X[ds.rows(["d4"])][:20], columns=FEATURES))
    assert list(out.columns) == ["score_ce", "score_pe", "action", "drivers"]
    assert (out["drivers"].iloc[:-1] == "").all()
    d = json.loads(out["drivers"].iloc[-1])
    best = "score_ce" if d["side"] == "ce" else "score_pe"
    assert d["score"] == pytest.approx(out[best].iloc[-1], abs=1e-3) and len(d["top"]) == min(
        5, len(FEATURES)
    )
