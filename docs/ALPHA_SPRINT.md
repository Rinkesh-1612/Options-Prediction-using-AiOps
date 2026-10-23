# Alpha sprint (written 2026-10-23, before any sprint code or result)

Builds on v2 (`docs/V2_PROTOCOL.md`, amendment 1: statutory costs only). Buy side only, taker entry (ask in, bid out).
Development: the 39 train + validation days, walk-forward (3 expanding folds, 24 scored days), as v2.
Clean test: the forward days (19, 22, 23 Oct 2026), opened once, only for trials that pass rules 1 and 2.
The v1 test days are not used.

## Trials (exactly six; nothing else is tried in this sprint)

| ID | Trial | Definition |
|---|---|---|
| A | Magnitude gate | A third LightGBM model predicts "big move": the largest NIFTY spot excursion in the next 120 s is at least the **80th percentile** of that value on the train days of the fold. Enter when P(big) ≥ tau on the side v2's side models prefer. v2 barriers (+3.5 / −2.0 / 180 s). |
| C | Trailing exit | Same entry rule as the better of v2 and A (higher out-of-fold net per day). Exit: stop at entry − 2.0; once the bid reaches entry + 2.0, the stop trails 2.0 below the highest bid since entry; time stop 300 s. Side models retrained on trailing-exit labels. |
| D1 | Open window | The best of v2, A, C, restricted to 09:20–09:45. |
| D2 | Expiry afternoon | The best of v2, A, C, restricted to expiry day (0 days to expiry) after 13:00. |
| D3 | Realised > implied | The best of v2, A, C, restricted to seconds where the NIFTY realised volatility over 60 s (annualised) exceeds the ATM implied volatility. |
| E | Liquidity sweep | No model. Buy the call (put) when, in one second, its best ask rises by at least 0.10 and the signed traded volume is at least 2 lots. v2 barriers. One position at a time. |

"Best" = highest out-of-fold mean net per day at the headline cost. For D1–D3, tau is chosen again inside the filter
from the same grid, out of fold.

## Pass rule (all must hold)

1. Out-of-fold mean net per day above zero, and the **99%** day-bootstrap interval above zero.
2. For model trials (A, C, D1–D3): beats random side at the same entry seconds in at least 95 of 100 seeds.
   For E: beats random entry seconds on the same days, same count, in at least 95 of 100 seeds.
3. Forward days: mean net per day above zero.

A pass means "worth a live paper trade". It does not prove an edge. A fail is "not detected at this sample size".

## Trials counted so far in this project

v1: 1 model. Alpha lab (archived): 6 + 4. v2: 1 model, then amendment 1 (a second cost setting).
This sprint: 6. Total about 19. At this count, a 95% rule would give about one false pass by chance; that is why
this sprint uses 99%.

## Time box

Code and development runs on 23 Oct. Forward test after the 23 Oct ticks are built (21:30 IST).
After that, no more trials before submission.
