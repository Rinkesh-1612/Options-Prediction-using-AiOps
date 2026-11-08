"""The CI gate (optpred.ci.gate) fails on each broken criterion."""

from optpred.ci.gate import check

LIMITS = {"min_tests": 10, "min_days": 3}


def _inputs():
    tests = {"total": 20, "passed": 20, "failed": 0, "errors": 0, "skipped": 0}
    days = {"accepted": ["d1", "d2", "d3"]}
    vol = {
        "main_horizon_s": 900,
        "verdict": {"900": {"beats_implied": True}},
        "deployment": {"deployed": True},
    }
    zoo = {"champion": "m", "results": {"m": {"deployment": {"deployed": True, "version": 1}}}}
    return tests, days, vol, zoo


def test_all_pass():
    assert all(r["pass"] for r in check(*_inputs(), LIMITS).values())


def test_each_broken_criterion_fails():
    tests, days, vol, zoo = _inputs()
    tests["failed"] = 1
    days["accepted"] = ["d1"]
    vol["verdict"]["900"]["beats_implied"] = False
    zoo["results"]["m"]["deployment"] = {"deployed": False}
    r = check(tests, days, vol, zoo, LIMITS)
    assert not any(v["pass"] for v in r.values())
