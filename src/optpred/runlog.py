"""Run journal: every pipeline stage run leaves a permanent, checkable record.

For each run this writes
  * logs/<stage>/<run_id>.log   -- the full log of that run
  * runs/runs.jsonl             -- one JSON line: who/what/when/which code/which
                                   params/how long/exit code/stage summary

Both are committed to Git, so any number in the report can be traced to the
exact run, code commit and parameters that produced it. A run on uncommitted
code is recorded with git_dirty=true, so it can never pass as reproducible.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import platform
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

IST = timezone(timedelta(hours=5, minutes=30))
LOG_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _params_hash(stage: str, path: str = "params.yaml") -> str | None:
    """Hash of this stage's params section, so two runs can be compared exactly."""
    try:
        with open(path) as f:
            section = yaml.safe_load(f).get(stage)
    except OSError:
        return None
    return hashlib.sha256(json.dumps(section, sort_keys=True, default=str).encode()).hexdigest()[:12]


def run(stage: str, main: Callable[[list[str], dict], int], argv: list[str] | None = None) -> int:
    """Run `main(argv, summary)` with logging to file and a journal entry.

    `main` fills `summary` with whatever proves what it did (rows, files, days).
    """
    argv = sys.argv[1:] if argv is None else argv
    started = datetime.now(IST)
    run_id = f"{started:%Y%m%dT%H%M%S}-{stage}"
    log_path = Path("logs") / stage / f"{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FMT,
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
        force=True,
    )
    log = logging.getLogger(f"optpred.{stage}")
    record = {
        "run_id": run_id,
        "stage": stage,
        "argv": argv,
        "started": started.isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": _git("status", "--porcelain") not in ("", "unknown"),
        "params_hash": _params_hash(stage),
        "host": platform.node(),
        "user": getpass.getuser(),
        "python": platform.python_version(),
        "log": str(log_path),
    }
    log.info(
        "run %s  commit %s%s", run_id, record["git_commit"][:10], " (DIRTY)" if record["git_dirty"] else ""
    )
    summary: dict = {}
    t0 = time.monotonic()
    try:
        code = main(argv, summary)
    except Exception:  # the journal must record crashes too, then re-raise
        log.error("crashed:\n%s", traceback.format_exc())
        code = 99
        raise
    finally:
        record.update(
            exit_code=code,
            status="ok" if code == 0 else "failed",
            duration_s=round(time.monotonic() - t0, 1),
            summary=summary,
        )
        Path("runs").mkdir(exist_ok=True)
        with open("runs/runs.jsonl", "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        log.info("run %s finished: %s in %.1fs", run_id, record["status"], record["duration_s"])
    return code
