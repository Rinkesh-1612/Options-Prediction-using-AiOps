import numpy as np
import pandas as pd

from optpred.common.clock import IST_OFFSET_S
from optpred.eda import fill, rules

P = {
    "spread_min_mid": 1.0,
    "max_rel_spread": 0.25,
    "max_mid_jump": 0.20,
    "close_from_s": 55680,
    "close_max_jump": 0.0015,
    "max_spot_gap_pts": 25,
}
DAY_NS = pd.Timestamp("2026-10-15", tz="UTC").value - IST_OFFSET_S * 1_000_000_000


def ts(h: int, m: int, s: float = 0) -> int:
    return DAY_NS + int(((h * 60 + m) * 60 + s) * 1e9)


def opt(rows):
    cols = ["ts_ns", "instrument_key", "bid1_price", "ask1_price", "volume", "oi"]
    return pd.DataFrame(rows, columns=cols)


def test_opt_tape_rules():
    df = opt(
        [
            (ts(9, 10), "A", 100, 101, 10, 5),  # pre-open
            (ts(9, 15, 0), "A", 100, 101, 9_999, 5),  # yesterday's volume repeated
            (ts(9, 15, 1), "A", 0, 101, 20, 5),  # one-sided
            (ts(9, 15, 2), "A", 100, 101, 30, 5),
            (ts(9, 15, 3), "A", 150, 151, 40, 5),  # spike up ...
            (ts(9, 15, 4), "A", 100, 101, 50, 0),  # ... and back; OI placeholder
            (ts(9, 15, 5), "A", 60, 140, 60, 5),  # spread 80% of mid
            (ts(9, 15, 6), "B", 0.05, 0.10, 1, 5),  # cheap: wide but kept
            (ts(15, 30), "A", 100, 101, 70, 5),  # after close
        ]
    )
    out, c = rules.clean_opt_tape(df, P)
    assert c["drop_outside_session"] == 2
    assert c["drop_one_sided_book"] == 1
    assert c["drop_mid_spike"] == 1
    assert c["drop_wide_spread"] == 1
    assert c["null_volume_above_later"] == 1
    assert c["null_oi_not_positive"] == 1
    assert len(out) == 4 and "B" in set(out["instrument_key"])


def test_index_closing_print_dropped():
    sec = [0, 1, 2, 3]
    df = pd.DataFrame(
        {
            "ts_ns": [ts(15, 28, s) for s in sec],
            "kind": "INDEX",
            "instrument_key": "I",
            "ltp": [25000.0, 25001.0, 25100.0, 25100.0],  # 0.4% jump at 15:28:02, then flat
        }
    )
    out, c = rules.clean_und_tape(df, P)
    assert c["drop_index_closing_print"] == 2
    assert out["ltp"].max() == 25001.0


def test_forward_fill_respects_age_limit():
    ticks = pd.DataFrame({"ts_ns": [ts(10, 0, 0)], "ltp": [1.0]})
    out = fill.asof(ticks, [ts(10, 0, 4), ts(10, 0, 6)], max_age_s=5)
    assert out["ltp"].iloc[0] == 1.0
    assert np.isnan(out["ltp"].iloc[1])  # older than 5 s: missing, not invented


def test_forward_fill_never_uses_future():
    ticks = pd.DataFrame({"ts_ns": [ts(10, 0, 10)], "ltp": [1.0]})
    out = fill.asof(ticks, [ts(10, 0, 5)], max_age_s=60)
    assert np.isnan(out["ltp"].iloc[0])
