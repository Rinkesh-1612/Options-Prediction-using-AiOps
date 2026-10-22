# v2 protocol: second-level microstructure model with barrier exits

Written on 2026-10-22, before any v2 code or v2 result existed. The Git commit of this file is the proof.
v1 (minute features, fixed 2-minute hold) stays in the project as the baseline. Its result is in `docs/RESULTS.md`.

## 1. Question

Can a model that reads the order book and the futures trade flow second by second pick moments to **buy**
the ATM NIFTY call or put, exit by fixed barriers, and make money after costs on days it did not train on?

## 2. Why v2 differs from v1

v1 showed that every rule lost after costs, even at zero slippage, and that the model could not pick the side.
v2 changes three things and nothing else:

| Item | v1 | v2 |
|---|---|---|
| Decision grid | end of each minute | every second, 09:20:00 – 15:25:00 |
| Inputs | minute summaries | order-flow imbalance, microprice, signed trade flow, queue depletion, depth shape, futures flow (section 5) |
| Exit | fixed 2-minute hold | triple barrier (section 4) |

Entry stays **taker**: buy at the ask, walking the 5 visible levels for one lot (65). Buy side only.

## 3. Days

| Use | Days | Rule |
|---|---|---|
| Development | the 39 train + validation days (3 Aug – 30 Sep) | Walk-forward folds by whole days. Every choice is made here. |
| Clean test | forward days recorded after the v1 freeze: 19, 22, 23 Oct 2026 (those that pass `check`) | Opened once, after the final model is registered. |
| Second look (disclosed) | the 10 v1 test days (1 – 15 Oct) | Already seen for v1 (aggregate results only). Reported separately and labelled "second look". Never used to choose anything. |

## 4. Trade and label (fixed now, never tuned)

* **Contract:** at decision second *t*, ATM = round(spot / 50) × 50 from the last NIFTY index tick at or before *t*;
  nearest expiry; the call and the put of that strike. Identified by `instrument_key`.
* **Entry:** the book of that contract at the last tick at or before *t*. Skip if that tick is older than 5 s,
  if the 5 levels cannot fill 65, or if the premium is below 5.
* **Barriers**, checked on the last book of each later second, for the **same** contract:
  * take profit: best bid ≥ entry price + **3.5** points
  * stop loss: best bid ≤ entry price − **2.0** points
  * time stop: **180 s** after entry
  The first barrier touched decides the exit. The exit sells 65 at the bid side of that second's book
  (walking the levels). So a gap past a barrier fills at the worse price.
* **Costs:** statutory charges (as v1) plus slippage of **0.31** points per leg. Also reported at 0 and 0.15.
* **Label per side:** 1 if that side's trade nets above zero after costs, else 0. Two labels per second (call, put).
* **Break-even hit rate** with these barriers: about 53% at 0.31 slippage, about 41% at zero slippage.
* Barriers were chosen by the author from move sizes on 6 train days (around the 75th percentile of the best bid reached in 120–180 s),
  before any model existed.

## 5. Inputs (all from data at or before second *t*)

For the ATM call and the ATM put:
* spread (points, % of mid), microprice minus mid, L1 and L1–L5 imbalance, depth slope
* order-flow imbalance (Cont–Kukanov–Stoikov) summed over 1, 5, 15, 30 s
* signed trade volume (trade at or above ask = buy, at or below bid = sell, else tick rule) over 5, 15, 30 s
* ask-1 and bid-1 queue change over 5 s, tick count over 30 s
* mid return over 5, 15, 30, 60 s

Market-wide:
* NIFTY futures: return and signed volume (tick rule) over 1, 5, 15, 30 s
* NIFTY index: return over 5, 15, 60 s, realised volatility over 60 s
* futures return minus option-implied move over 5 s (lead–lag gap)
* ATM IV and its 5-minute change (last chain snapshot), seconds since open, days to expiry

## 6. Model and decision

* Two LightGBM binary models: *P(call trade wins)* and *P(put trade wins)*. Fixed settings; Ray Tune may search
  them on train folds only, scored by log loss, never by profit.
* Rule: at second *t*, take the side with the higher probability if it is at least **tau**; else stay out.
  One position at a time. A new entry is allowed the second after an exit.
* tau grid: 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, never. Chosen on walk-forward out-of-fold results
  (3 expanding folds over the 39 days), among taus with at least 20 out-of-fold trades.

## 7. Pass rule (all must hold; fixed now)

1. Out-of-fold (development days): mean net per day **above zero**, 95% day-bootstrap interval **excludes zero**.
2. Out-of-fold: it beats random side choice **at the same entry seconds** in at least 95 of 100 seeds.
3. Clean test (forward days): mean net per day above zero.

Rule 3 has very few days. It can reject a false pass; it cannot prove an edge. A pass is "a lead worth a live paper
trade", not a finding. A fail is "no edge detected at this sample size".

## 8. Trials counted

One feature set, one model family, 8 tau values, one barrier set. Any extra trial is added to this list before it runs.
