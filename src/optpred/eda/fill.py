"""Missing-value policy: forward fill with an age limit. Nothing else.

At time t a trader knows only the LAST quote seen at or before t. So a gap is filled with that quote,
but only while it is younger than `max_age_s`; after that the value is missing (NaN).

Not used, on purpose:
  * backward fill, interpolation, KNN or model imputation -- they use values from AFTER t
    (look-ahead) and create prices that never existed on the screen.
  * filling whole missing days -- a day with no recording is dropped (check stage), never invented.
"""

from __future__ import annotations

import pandas as pd


def asof(
    ticks: pd.DataFrame, grid_ns: pd.Series | list[int], max_age_s: float, by: str | None = None
) -> pd.DataFrame:
    """Last tick at or before each grid time (per `by` key), or NaN if it is older than `max_age_s`.

    `ticks` needs a `ts_ns` column. With `by`, `grid_ns` is crossed with every key in `ticks`.
    The result has `grid_ns`, the tick columns, and `age_s` (seconds since that tick).
    """
    grid = pd.DataFrame({"grid_ns": pd.Series(grid_ns, dtype="int64")}).sort_values("grid_ns")
    if by is not None:
        grid = grid.merge(pd.DataFrame({by: ticks[by].unique()}), how="cross").sort_values("grid_ns")
    t = ticks.sort_values("ts_ns").rename(columns={"ts_ns": "tick_ns"})
    out = pd.merge_asof(
        grid,
        t,
        left_on="grid_ns",
        right_on="tick_ns",
        by=by,
        direction="backward",
        tolerance=int(max_age_s * 1e9),
    )
    out["age_s"] = (out["grid_ns"] - out["tick_ns"]) / 1e9
    return out
