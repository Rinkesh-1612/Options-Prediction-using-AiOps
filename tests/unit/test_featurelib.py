"""CI for features: every registered feature is checked here automatically, including new ones."""

import numpy as np
import pandas as pd
import pytest

from optpred.featurelib.registry import compute, load
from tests.helpers.grid_synth import synth_grid

FEATURES = list(load().values())
GRID = synth_grid()


def test_registry_is_not_empty():
    assert len(FEATURES) >= 5


@pytest.mark.parametrize("f", FEATURES, ids=lambda f: f.name)
def test_feature_has_docstring_and_rows(f):
    assert f.doc, f"{f.name}: add a docstring (it goes into the catalog)"
    out = f.fn(GRID)
    assert len(out) == len(GRID) and out.index.equals(GRID.index)
    assert not np.isinf(out.to_numpy(dtype=float)).any()


@pytest.mark.parametrize("f", FEATURES, ids=lambda f: f.name)
def test_feature_has_no_look_ahead(f):
    """A value at second t must be the same whether or not rows after t exist."""
    full = f.fn(GRID)
    for cut in (400, 900):
        part = f.fn(GRID.iloc[:cut])
        pd.testing.assert_frame_equal(full.iloc[:cut], part, check_exact=False, rtol=1e-9)


@pytest.mark.parametrize("f", FEATURES, ids=lambda f: f.name)
def test_feature_is_full_after_its_lookback(f):
    """After the declared lookback (+ ATM-roll masking), a feature must produce values."""
    out = f.fn(GRID).iloc[f.lookback_s + 1 :]
    assert out.notna().any().all(), f"{f.name}: a column is all NaN after its lookback"


def test_all_columns_unique():
    df = compute(GRID, FEATURES)
    assert not df.columns.duplicated().any()


def test_every_feature_column_is_float64():
    """The served model's schema is all double; an int column would be rejected at inference."""
    df = compute(GRID, FEATURES)
    assert (df.dtypes == "float64").all(), df.dtypes[df.dtypes != "float64"].to_dict()
