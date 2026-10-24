"""Load features + labels into one in-memory dataset, and split days into walk-forward folds.

Splits are by whole day. A label never crosses a day (forced exit 15:28), so day splits need no purge.
The last `n_test_days` accepted days are the test set; only `evaluate` reads them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from optpred.featurelib.registry import KEYS, load

SIDES = ("ce", "pe")


@dataclass
class Dataset:
    days: list[str]
    features: list[str]
    X: np.ndarray  # (N, F) float32, all seconds of all days, day after day in time order
    day_idx: np.ndarray  # (N,) index into days
    pos: np.ndarray  # (N,) second number within its day (0 = 09:15:00)
    valid: np.ndarray  # (N, 2) bool: an entry is possible (ce, pe)
    net: np.ndarray  # (N, 2) float32: net rupees of the trade (NaN if not valid)
    hold: np.ndarray  # (N, 2) float32: seconds held

    def rows(self, days: list[str]) -> np.ndarray:
        want = np.isin(np.array(self.days)[self.day_idx], days)
        return np.flatnonzero(want)

    def day_slices(self, days: list[str]) -> list[tuple[str, slice]]:
        out = []
        for d in days:
            r = np.flatnonzero(self.day_idx == self.days.index(d))
            out.append((d, slice(r[0], r[-1] + 1)))
        return out


def feature_groups(columns: list[str]) -> dict[str, list[str]]:
    """Feature group -> its columns (from the registry and reports/feat.json)."""
    reg = load()
    cols = json.loads(Path("reports/feat.json").read_text())["features"]
    out: dict[str, list[str]] = {}
    for name, f in reg.items():
        out.setdefault(f.group, []).extend(c for c in cols.get(name, []) if c in columns)
    return out


def load_dataset(days: list[str], feat_dir: Path, label_dir: Path) -> Dataset:
    parts_x, parts_l, day_idx, pos = [], [], [], []
    features: list[str] | None = None
    for i, d in enumerate(days):
        f = pd.read_parquet(feat_dir / f"{d}.parquet")
        lab = pd.read_parquet(label_dir / f"{d}.parquet")
        if not (f["sod"].to_numpy() == lab["sod"].to_numpy()).all():
            raise ValueError(f"{d}: features and labels are not aligned")
        if features is None:
            features = [c for c in f.columns if c not in KEYS]
        parts_x.append(f[features].to_numpy(np.float32))
        parts_l.append(lab)
        day_idx.append(np.full(len(f), i, dtype=np.int16))
        pos.append(np.arange(len(f), dtype=np.int32))
    lab = pd.concat(parts_l, ignore_index=True)
    return Dataset(
        days=list(days),
        features=features or [],
        X=np.concatenate(parts_x),
        day_idx=np.concatenate(day_idx),
        pos=np.concatenate(pos),
        valid=lab[[f"{s}_valid" for s in SIDES]].to_numpy(bool),
        net=lab[[f"{s}_net_rs" for s in SIDES]].to_numpy(np.float32),
        hold=lab[[f"{s}_hold_s" for s in SIDES]].to_numpy(np.float32),
    )


def split_days(accepted: list[str], n_test: int, min_train: int, val_days: int):
    """(dev days, test days, folds). Folds: expanding window, `val_days` validation days each."""
    dev, test = accepted[:-n_test], accepted[-n_test:]
    folds = []
    start = min_train
    while start + val_days <= len(dev):
        folds.append((dev[:start], dev[start : start + val_days]))
        start += val_days
    return dev, test, folds
