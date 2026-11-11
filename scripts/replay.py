"""Demo: replay past days through the API so the Grafana dashboard moves in near real time.

It calls the same REST endpoints as the web page (`GET /signal`, `GET /vol`), one call per market minute,
so every request, latency, served trade and drift number in Prometheus is real, not simulated.

Run:  ./stack --profile demo up -d replay        (or: make demo)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import httpx

log = logging.getLogger("replay")
# 09:20 .. 15:15: the window in which the models may enter (params.yaml, labels)
FIRST_S, LAST_S = 33600, 54900


def replay(api: str, split: str, delay_s: float, step_s: int, client: httpx.Client | None = None) -> dict:
    """Ask for a signal and a volatility forecast at every step of every day of `split`. Return counts."""
    c = client or httpx.Client(base_url=api, timeout=30)
    days = [d["day"] for d in c.get("/days").raise_for_status().json() if d["split"] == split]
    if not days:
        raise RuntimeError(f"the API shows no days in split {split!r}")
    n = {"days": len(days), "ok": 0, "refused": 0}
    for day in days:
        for sod in range(FIRST_S, LAST_S + 1, step_s):
            for path in ("/signal", "/vol"):
                try:
                    r = c.get(path, params={"day": day, "sod": sod})
                    n["ok" if r.status_code == 200 else "refused"] += 1
                except httpx.HTTPError as e:  # the API is restarting: keep the demo running
                    n["refused"] += 1
                    log.warning("%s %s %s: %r", path, day, sod, e)
            time.sleep(delay_s)
        log.info("replayed %s: %d answers, %d refused so far", day, n["ok"], n["refused"])
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--split", default="test", choices=["test", "dev"])
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between market minutes")
    ap.add_argument("--step", type=int, default=60, help="market seconds between calls")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per day, not per request
    try:
        log.info("done: %s", replay(a.api, a.split, a.delay, a.step))
    except (httpx.HTTPError, RuntimeError) as e:
        log.error("replay stopped: %r", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
