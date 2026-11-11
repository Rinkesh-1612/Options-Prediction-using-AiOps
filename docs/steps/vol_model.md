# Second model: volatility forecaster

> Why: direction is not predictable (correlation ≈ 0.01). HRT, Jane Street and Optiver write that the target is
> where the signal is; for options the key quantity is volatility. Research: `research/` on branch `vol-track`.

**Code.** [src/optpred/vol/](../../src/optpred/vol/) — stage `vol`, settings `params.yaml → vol`, tests `tests/unit/test_vol.py`.
- Target: realized NIFTY move over the next 5 and 15 min (bp). Inputs (HAR): realized move over the last 1/5/15/30 min,
  since the open, time of day, ATM-IV implied move. No look-ahead (tested).
- Forecasters: implied (the option market, the baseline), HAR, HAR + IV. Walk-forward CV on the dev days; champion =
  lowest CV QLIKE at 15 min.
- **Success rule, set before the test:** the champion's daily QLIKE is below the implied forecast's on the test days,
  95% bootstrap interval of the difference below 0.

**Result** (`reports/vol/comparison.md`). Champion **HAR + IV**. Test days: better than the option market on
**10 of 10 days** at 5 and at 15 min; daily QLIKE difference 15 min −0.200 [−0.370, −0.068] → **PASS**.
Correlation with the realized move 0.68 (implied: −0.18).

**Serving.** Registered as `nifty-vol` after a smoke test; the API loads `nifty-vol@champion` (`GET /vol`);
the Explore tab shows IV against the forecast by day and by minute; the Results tab has the table.

**Limit.** A good forecast is not a trade: buying straddles on it lost money after the spread (research note on
`vol-track`). For Ravion it is a filter and position-size input.

