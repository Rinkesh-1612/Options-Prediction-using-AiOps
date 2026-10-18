import numpy as np
import pandas as pd
import pytest

from optpred import features, labels


def test_statutory_cost_matches_ravion_contract_note():
    # Ravion docs: a Rs150 premium on a 65 lot costs Rs18.13 all-in at zero brokerage
    assert labels.statutory_cost_rs(150, 150, 65) == pytest.approx(18.13, abs=0.01)


def test_label_rules():
    df = pd.DataFrame(
        {
            "ce_gross_rs": [100.0, 0.0, 10.0, 90.0],
            "pe_gross_rs": [0.0, 100.0, 5.0, 100.0],
            "ce_stat_rs": 18.0,
            "pe_stat_rs": 18.0,
        }
    )
    # slippage 0.31 * 2 * 65 = Rs40.3 -> hurdle Rs58.3
    got = labels.label_actions(df, 0.31, 65)
    assert list(got) == [labels.BUY_CE, labels.BUY_PE, labels.STAY_OUT, labels.BUY_PE]


def test_fill_price_walks_the_book_and_flags_thin_exits():
    assert features.fill_price([10, 9.9], [40, 100], 65) == pytest.approx((10 * 40 + 9.9 * 25) / 65)
    assert np.isnan(features.fill_price([10, 0, 0], [40, 0, 0], 65))  # cannot fill an entry
    assert features.fill_price([10, 0, 0], [40, 0, 0], 65, allow_thin=True) == pytest.approx(10.0)


def test_assign_splits_is_chronological_and_whole_days():
    days = [f"2026-09-{d:02d}" for d in range(1, 11)]
    s = features.assign_splits(days[::-1], n_val=2, n_test=3)
    assert [s[d] for d in days] == ["train"] * 5 + ["val"] * 2 + ["test"] * 3
    with pytest.raises(features.FeatureError):
        features.assign_splits(days[:4], 2, 3)
