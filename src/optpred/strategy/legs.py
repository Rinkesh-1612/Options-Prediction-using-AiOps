"""Legs of an option strategy, and the ready-made templates.

A leg: side (ce / pe), `k` = strike offset from the ATM strike at entry (in strikes, -2 .. +2: the grid
holds these five strikes), action (buy / sell) and `lots` (1 lot = 65). Text form: `buy:ce:0:1,sell:ce:2:2`.
"""

from __future__ import annotations

from dataclasses import dataclass

STEP = 50  # NIFTY strike step (params.yaml grid.strike_step)
N_STRIKES = 2  # strikes each side of ATM in the grid (grid.n_strikes)
MAX_LEGS = 4
MAX_LOTS = 10


@dataclass(frozen=True)
class Leg:
    side: str  # "ce" | "pe"
    k: int
    action: str  # "buy" | "sell"
    lots: int = 1

    @property
    def sign(self) -> int:
        return 1 if self.action == "buy" else -1


def parse_legs(text: str) -> list[Leg]:
    """`buy:ce:0:1,sell:pe:-1:2` -> legs. Raises ValueError with a plain message."""
    legs = []
    for part in filter(None, (x.strip() for x in text.split(","))):
        f = part.split(":")
        if len(f) not in (3, 4):
            raise ValueError(f"leg '{part}' must look like buy:ce:0:1 (action:side:strike offset:lots)")
        action, side, k = f[0].lower(), f[1].lower(), f[2]
        lots = f[3] if len(f) == 4 else "1"
        if action not in ("buy", "sell") or side not in ("ce", "pe"):
            raise ValueError(f"leg '{part}': action is buy or sell, side is ce or pe")
        try:
            kk, ll = int(k), int(lots)
        except ValueError as e:
            raise ValueError(f"leg '{part}': strike offset and lots must be whole numbers") from e
        if not -N_STRIKES <= kk <= N_STRIKES:
            raise ValueError(f"leg '{part}': strike offset must be from -{N_STRIKES} to {N_STRIKES}")
        if not 1 <= ll <= MAX_LOTS:
            raise ValueError(f"leg '{part}': lots must be from 1 to {MAX_LOTS}")
        legs.append(Leg(side, kk, action, ll))
    if not 1 <= len(legs) <= MAX_LEGS:
        raise ValueError(f"a strategy has 1 to {MAX_LEGS} legs")
    return legs


def legs_text(legs: list[Leg]) -> str:
    return ",".join(f"{x.action}:{x.side}:{x.k}:{x.lots}" for x in legs)


# id -> (name, kind, text form). kind: long / short / credit spread / debit spread / unbalanced
TEMPLATES: dict[str, tuple[str, str, str]] = {
    "long_call": ("Buy a call", "directional", "buy:ce:0:1"),
    "long_put": ("Buy a put", "directional", "buy:pe:0:1"),
    "long_straddle": ("Long straddle", "volatility", "buy:ce:0:1,buy:pe:0:1"),
    "long_strangle": ("Long strangle", "volatility", "buy:ce:1:1,buy:pe:-1:1"),
    "short_straddle": ("Short straddle", "short volatility", "sell:ce:0:1,sell:pe:0:1"),
    "short_strangle": ("Short strangle", "short volatility", "sell:ce:1:1,sell:pe:-1:1"),
    "bull_call_spread": ("Bull call spread", "spread", "buy:ce:0:1,sell:ce:2:1"),
    "bear_put_spread": ("Bear put spread", "spread", "buy:pe:0:1,sell:pe:-2:1"),
    "bear_call_spread": ("Bear call spread (credit)", "spread", "sell:ce:0:1,buy:ce:2:1"),
    "bull_put_spread": ("Bull put spread (credit)", "spread", "sell:pe:0:1,buy:pe:-2:1"),
    "iron_condor": ("Iron condor", "spread", "sell:ce:1:1,buy:ce:2:1,sell:pe:-1:1,buy:pe:-2:1"),
    "iron_butterfly": ("Iron butterfly", "spread", "sell:ce:0:1,sell:pe:0:1,buy:ce:2:1,buy:pe:-2:1"),
    "call_ratio": ("Call ratio spread 1x2", "unbalanced", "buy:ce:0:1,sell:ce:2:2"),
    "put_ratio": ("Put ratio spread 1x2", "unbalanced", "buy:pe:0:1,sell:pe:-2:2"),
    "call_backspread": ("Call backspread 1x2", "unbalanced", "sell:ce:0:1,buy:ce:1:2"),
    "put_backspread": ("Put backspread 1x2", "unbalanced", "sell:pe:0:1,buy:pe:-1:2"),
    "broken_wing": ("Broken-wing butterfly (calls)", "unbalanced", "buy:ce:-1:1,sell:ce:0:2,buy:ce:2:1"),
    "jade_lizard": ("Jade lizard", "unbalanced", "sell:pe:-1:1,sell:ce:1:1,buy:ce:2:1"),
}
