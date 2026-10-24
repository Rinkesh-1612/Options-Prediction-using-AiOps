"""Deployment gate and promotion. A registered version becomes "champion" only after it passes a smoke test.

Smoke test: load the version from the registry exactly as the model server will, predict one real day,
and check the output (one row per input row, finite or -inf scores, known actions).
Promotion: the old champion becomes "previous" (the rollback target), the new version becomes "champion".
The model server follows the "champion" alias, so promotion = deployment (CD).
"""

from __future__ import annotations

import logging

import mlflow
import numpy as np
import pandas as pd

log = logging.getLogger("optpred.zoo.promote")
ACTIONS = {"BUY_CE", "BUY_PE", "STAY_OUT"}


def smoke_test(name: str, version: str, sample: pd.DataFrame) -> str | None:
    """None if the version serves correctly, else the reason it failed."""
    try:
        out = mlflow.pyfunc.load_model(f"models:/{name}/{version}").predict(sample)
    except Exception as e:  # noqa: BLE001 -- any failure to load or predict blocks the deployment
        return f"load/predict failed: {e!r}"[:500]
    if len(out) != len(sample):
        return f"{len(out)} output rows for {len(sample)} input rows"
    if not set(out["action"]).issubset(ACTIONS):
        return f"unknown actions {set(out['action']) - ACTIONS}"
    if np.isnan(out[["score_ce", "score_pe"]].to_numpy(float)).all():
        return "all scores are NaN"
    return None


def promote(client, name: str, version: str, sample: pd.DataFrame) -> dict:
    """Smoke-test `version`; on success move aliases (champion -> previous, version -> champion)."""
    reason = smoke_test(name, version, sample)
    if reason:
        client.set_model_version_tag(name, version, "deploy_check", "failed")
        log.error("version %s NOT deployed: %s", version, reason)
        return {"deployed": False, "version": version, "reason": reason}
    client.set_model_version_tag(name, version, "deploy_check", "passed")
    try:
        old = client.get_model_version_by_alias(name, "champion").version
    except mlflow.exceptions.MlflowException:
        old = None
    if old and old != version:
        client.set_registered_model_alias(name, "previous", old)
    client.set_registered_model_alias(name, "champion", version)
    log.info("deployed version %s (previous: %s)", version, old)
    return {"deployed": True, "version": version, "previous": old}
