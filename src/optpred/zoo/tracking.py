"""MLflow setup and the tags that tie every run to its code and data versions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import mlflow
import yaml


def setup(m: dict) -> None:
    uri = os.environ.get("MLFLOW_TRACKING_URI", m["tracking_uri"])
    if uri.startswith("sqlite:///"):
        Path(uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(m["experiment"]) is None:
        mlflow.create_experiment(
            m["experiment"], artifact_location=Path(m["artifact_root"]).resolve().as_uri()
        )
    mlflow.set_experiment(m["experiment"])


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def version_tags(data_outs: tuple[str, ...] = ("data/feat", "data/labels")) -> dict[str, str]:
    """Git commit (+ dirty flag) and the DVC hash of each data folder the run read."""
    tags = {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": str(bool(_git("status", "--porcelain", "src"))),
    }
    lock = yaml.safe_load(Path("dvc.lock").read_text())["stages"]
    for st in lock.values():
        for o in st.get("outs", []):
            if o["path"] in data_outs:
                tags[f"dvc_{o['path'].replace('/', '_')}"] = o["md5"]
    return tags
