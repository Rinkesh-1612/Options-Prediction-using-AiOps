from functools import partial

from optpred.common.parallel import map_days


def work(day: str, suffix: str) -> dict:
    return {"day": day + suffix}


def test_map_days_keeps_order_on_ray():
    days = [f"2026-10-{d:02d}" for d in range(1, 9)]
    assert [r["day"] for r in map_days(partial(work, suffix="!"), days, cpus=2)] == [d + "!" for d in days]
