"""Run one function per trading day in parallel on Ray (local cluster, capped CPUs).

Every per-day stage (clean, eda, grid, feat, labels) uses this. A day is the unit of work: days are
independent, so the stages scale with the number of days and the number of CPUs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

log = logging.getLogger("optpred.common.parallel")


def map_days(fn: Callable[[str], dict], days: list[str], cpus: int) -> list[dict]:
    """[fn(day) for day in days], computed as Ray tasks. Results keep the order of `days`."""
    import ray

    started_here = not ray.is_initialized()
    if started_here:
        ray.init(num_cpus=cpus, include_dashboard=False, logging_level=logging.WARNING, log_to_driver=False)
    try:
        task = ray.remote(num_cpus=1)(lambda f, d: f(d))
        t0 = time.monotonic()
        out = ray.get([task.remote(fn, d) for d in days])
        log.info("ray: %d days on %d CPUs in %.1f s", len(days), cpus, time.monotonic() - t0)
        return out
    finally:
        if started_here:
            ray.shutdown()
