import numpy as np

from optpred.drift.psi import DriftMonitor, psi_all, reference

F = ["a", "b"]


def test_same_distribution_has_low_psi_and_shift_has_high_psi():
    rng = np.random.default_rng(0)
    ref = reference(rng.normal(size=(5000, 2)), F)
    same = psi_all(rng.normal(size=(2000, 2)), F, ref)
    moved = psi_all(rng.normal(size=(2000, 2)) + [2.0, 0.0], F, ref)
    assert max(same.values()) < 0.05
    assert moved["a"] > 0.25 and moved["b"] < 0.05


def test_nan_share_change_is_drift():
    rng = np.random.default_rng(1)
    ref = reference(rng.normal(size=(5000, 2)), F)
    x = rng.normal(size=(2000, 2))
    x[:1000, 0] = np.nan  # half the values suddenly missing
    assert psi_all(x, F, ref)["a"] > 0.25


def test_monitor_needs_min_rows_then_flags_drift():
    rng = np.random.default_rng(2)
    ref = reference(rng.normal(size=(5000, 2)), F)
    mon = DriftMonitor(ref, window=500, min_rows=100, share_limit=0.3)
    for r in rng.normal(size=(50, 2)) + 3:
        mon.add({"a": r[0], "b": r[1]})
    assert not mon.status()["ready"]
    for r in rng.normal(size=(200, 2)) + 3:
        mon.add({"a": r[0], "b": r[1]})
    s = mon.status()
    assert s["ready"] and s["drift"] and s["share"] == 1.0
