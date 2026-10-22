"""Drift: stable data scores near zero, shifted data scores high, and one noisy feature is not enough."""

import numpy as np
import pandas as pd

from optpred import drift


def frame(n, shift=0.0, seed=0, cols=("a", "b", "c", "d", "e")):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(size=(n, len(cols))), columns=list(cols)).assign(a=lambda d: d["a"] + shift)


def test_psi_is_small_for_the_same_distribution():
    assert drift.psi(frame(5000)["a"], frame(2000, seed=1)["a"]) < drift.PSI_WATCH


def test_psi_is_large_for_a_shifted_distribution():
    assert drift.psi(frame(5000)["a"], frame(2000, shift=1.5, seed=1)["a"]) > drift.PSI_DRIFT


def test_psi_of_a_constant_reference_is_zero():
    assert drift.psi(pd.Series([1.0] * 100), pd.Series([5.0] * 100)) == 0.0


def test_monitor_waits_for_enough_rows():
    m = drift.DriftMonitor(frame(1000), list("abcde"), min_rows=50)
    for _, r in frame(10, seed=2).iterrows():
        m.add(r)
    assert m.scores() == {} and m.summary()["ready"] is False and m.summary()["drifted"] is False


def test_one_drifted_feature_out_of_five_is_not_a_drift_but_two_are():
    cols = list("abcde")
    m = drift.DriftMonitor(frame(3000), cols, window=400, min_rows=100, max_share=0.2)
    for _, r in frame(400, shift=2.0, seed=3).iterrows():  # only column "a" moves
        m.add(r)
    s = m.summary()
    assert s["features_drifted"] == 1 and s["drifted"] is False  # 1/5 is not more than 20%
    m2 = drift.DriftMonitor(frame(3000), cols, window=400, min_rows=100, max_share=0.2)
    moved = frame(400, shift=2.0, seed=4).assign(b=lambda d: d["b"] + 2.0)
    for _, r in moved.iterrows():
        m2.add(r)
    assert m2.summary()["drifted"] is True


def test_window_keeps_only_the_latest_rows():
    m = drift.DriftMonitor(frame(500), list("abcde"), window=120, min_rows=100)
    for _, r in frame(300, seed=5).iterrows():
        m.add(r)
    assert m.summary()["rows"] == 120


def test_calendar_and_price_level_features_are_not_monitored():
    cols = ["ce_imb1", "minute", "dte", "ce_mid", "pe_mid", "is_expiry_day", "spot_rv5"]
    assert drift.monitored(cols) == ["ce_imb1", "spot_rv5"]
