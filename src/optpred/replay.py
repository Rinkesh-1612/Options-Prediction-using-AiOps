"""Replay: feed a past day to the API minute by minute, as if the market were live.

Why: the Grafana dashboard needs a moving stream to be useful in a demo, and the drift check needs
served rows. The replay calls the same REST endpoint a person uses (`POST /predict`), so every
prediction, latency and "prediction against what happened" counter is real, not simulated.
Only days that the API shows (never the locked test days) can be replayed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import httpx

log = logging.getLogger("optpred.replay")


class ReplayError(RuntimeError):
    """The API refused or did not answer."""


def pick_day(days: list[dict], wanted: str | None) -> str:
    """The wanted day, or the latest validation day, or the latest visible day."""
    names = {d["day"] for d in days}
    if wanted:
        if wanted not in names:
            raise ReplayError(f"day {wanted} is not available from the API")
        return wanted
    val = sorted(d["day"] for d in days if d["split"] == "val")
    if val:
        return val[-1]
    if not names:
        raise ReplayError("the API shows no days")
    return max(names)


def replay(
    api: str,
    day: str | None,
    delay_s: float,
    loops: int,
    client: httpx.Client | None = None,
    split: str | None = None,
) -> int:
    """Send every minute of the day (or of every day of a split, in order) to /predict.

    Returns the number of predictions served. A drift verdict needs several sessions of rows,
    so `split="val"` replays all validation days, one after the other.
    """
    c = client or httpx.Client(base_url=api, timeout=20)
    try:
        all_days = c.get("/days").raise_for_status().json()
        names = (
            sorted(d["day"] for d in all_days if d["split"] == split) if split else [pick_day(all_days, day)]
        )
        if not names:
            raise ReplayError(f"the API shows no days in split {split!r}")
        plan = [(d, c.get("/minutes", params={"day": d}).raise_for_status().json()) for d in names]
    except httpx.HTTPError as e:
        raise ReplayError(f"cannot reach the API at {api}: {e}") from e
    served = 0
    for n in range(loops):
        for d, minutes in plan:
            log.info("replay of %s, pass %d, %d minutes", d, n + 1, len(minutes))
            for m in minutes:
                try:
                    c.post("/predict", json={"day": d, "minute": m["minute"]}).raise_for_status()
                    served += 1
                except httpx.HTTPError as e:
                    log.warning("minute %s failed: %s", m["time"], e)
                time.sleep(delay_s)
    return served


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="http://api:8000")
    ap.add_argument("--day", default=None, help="default: the latest validation day")
    ap.add_argument("--split", default=None, help="replay every day of this split (train, val), in order")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between minutes")
    ap.add_argument("--loops", type=int, default=1000000, help="how many times to replay the day")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        n = replay(a.api, a.day, a.delay, a.loops, split=a.split)
    except ReplayError as e:
        log.error("%s", e)
        return 1
    log.info("served %d predictions", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
