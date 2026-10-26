# Strategy search: volatility gate and 27 structures (research, 2026-10-25)

> Copied from branch `strategy-search`, commit 0177756 (`research/strategy/`: PROTOCOL.md, RESULTS.md, FINDINGS.md and code `src/optpred/strategy/search.py`, `structures.py`). The branch is not merged into `main`; the page in `main` has its own simpler `optpred.strategy` package.


Protocol: [PROTOCOL.md](PROTOCOL.md) (committed before any result). Tables: [RESULTS.md](RESULTS.md).
Code: `src/optpred/strategy/` (wide book, 27 structures, P&L engine, search). Tests: `tests/unit/test_strategy_structures.py`.

**Gate: FAIL.** The ML selector on the 20 out-of-fold dev days: +₹346/day, 95% interval [−90, +934], from only 4 trades.
It does not beat the author's rule R1 (+₹425/day, [−388, +1,270]). **Test and forward days were not scored.**

## The two ideas, tested
| Idea | Result (dev days, after spread and statutory costs, per entry) |
|---|---|
| Low volatility → sell both sides | Short straddle / strangle / iron condor lose at 5–60 min holds in every volatility bucket (−₹7 … −₹81). Crossing 2–4 legs costs ₹50–100; 15 min of decay earns about ₹10–17. Only holds **to the close** are positive, and only **naked** (short strangle ±1: +₹80, ±2: +₹156). The defined-risk versions lose (iron condor −₹69, iron fly −₹68), because the wings cost spread. |
| High volatility → buy options | Buying a call or put has no edge (direction correlation ≈ 0.01). Buying a straddle or strangle improves with the forecast: by forecast level, long strangle ±1 goes from −₹51 (lowest fifth) to −₹7 (highest), but never above 0. |

## Why the table looks better than it is
- **The dev period was a falling market** (NIFTY −7.9%; test days +1.7%). Long puts (+₹47 … +₹91 at 60 min / close) and
  short calls (+₹69 … +₹147) profit from the fall; long calls (−₹203) and short puts (−₹90) lose from it. That is
  market direction, not skill. It would reverse in a rising market.
- **The ML selector overfits.** It predicts thousands of rupees for rare rows (long ITM options held to the close),
  trades 3–19 times in 20 days, and its low-threshold version chose naked shorts with a worst trade of **−₹9,024**.
- **Risk is not in the mean.** Naked short results hide tail losses (worst trade −₹7,500 for the best-fixed rule).

## Verdict
No structure, strike, expiry, hold time or volatility regime makes money after costs on this data. The volatility
forecast is real (it beats the option market), but the spread of multi-leg structures is larger than what it adds.

## Open lead (needs more data, not tested)
Short-volatility carry to the close (sell a strangle at 09:30, hold to 15:15, one trade per day) is the only
unconditional positive, +₹80 … +₹156 per day. It is naked and the dev sample is one falling market of 39 days.
Test it with a protocol written first, when Ravion has 20+ more days (and a market that rises).
