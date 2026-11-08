"""Stage `gate`: the last node of the DVC DAG. It fails the pipeline when an acceptance criterion fails.

CI with DVC (course lecture 11): `dvc repro` reruns only the stages whose code, data or params changed,
then this stage checks the result. A non-zero exit stops `dvc repro`, so a broken change cannot pass CI.

Criteria (docs/TEST_PLAN.md section 4; limits in params.yaml `gate`):
  * tests  -- reports/tests.json: no failed or errored test, at least `min_tests` tests ran
  * data   -- data/days.json: at least `min_days` accepted days
  * vol    -- reports/vol/test.json: the forecaster beats the option market on the test days, and passed
              its deploy smoke test
  * zoo    -- reports/zoo/test.json: the direction champion passed its deploy smoke test
              (no profit criterion: the honest result is "no edge after costs")

Output: reports/gate.json (DVC metric).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from optpred.common import runlog

log = logging.getLogger("optpred.ci.gate")
OUT = Path("reports/gate.json")


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def check(tests: dict, days: dict, vol: dict, zoo: dict, limits: dict) -> dict[str, dict]:
    """One entry per criterion: {"pass": bool, "detail": str}."""
    bad = tests["failed"] + tests["errors"]
    horizon = str(vol["main_horizon_s"])
    zoo_dep = zoo["results"][zoo["champion"]].get("deployment") or {}
    vol_dep = vol.get("deployment") or {}
    return {
        "tests": {
            "pass": bad == 0 and tests["total"] >= limits["min_tests"],
            "detail": f"{tests['passed']} passed, {bad} failed, {tests['skipped']} skipped",
        },
        "data": {
            "pass": len(days["accepted"]) >= limits["min_days"],
            "detail": f"{len(days['accepted'])} accepted days",
        },
        "vol": {
            "pass": bool(vol["verdict"][horizon]["beats_implied"]) and bool(vol_dep.get("deployed")),
            "detail": f"beats implied at {horizon}s: {vol['verdict'][horizon]['beats_implied']}, "
            f"deployed v{vol_dep.get('version')}",
        },
        "zoo": {
            "pass": bool(zoo_dep.get("deployed")),
            "detail": f"champion {zoo['champion']} deployed v{zoo_dep.get('version')}",
        },
    }


def main(argv: list[str], summary: dict) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default="params.yaml")
    a = ap.parse_args(argv)
    limits = yaml.safe_load(Path(a.params).read_text())["gate"]
    result = check(
        _load("reports/tests.json"),
        _load("data/days.json"),
        _load("reports/vol/test.json"),
        _load("reports/zoo/test.json"),
        limits,
    )
    ok = all(r["pass"] for r in result.values())
    OUT.write_text(json.dumps({"pass": ok, "checks": result}, indent=1) + "\n")
    for name, r in result.items():
        log.info("%-5s %s  %s", name, "PASS" if r["pass"] else "FAIL", r["detail"])
    summary.update(passed=ok, failed=[n for n, r in result.items() if not r["pass"]])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(runlog.run("gate", main))
