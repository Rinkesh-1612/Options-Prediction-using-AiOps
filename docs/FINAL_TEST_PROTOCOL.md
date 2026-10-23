# Final test protocol (written before the test days are opened)

> **DEPRECATED (2026-10-23).** This document was written before the owner reviewed the project. It is not approved by the owner. Do not use it as a reference. A reviewed version will replace it.

Committed on 2026-10-22, before `src/optpred/evaluate.py` existed. The Git commit of this file is the proof
that every rule below was fixed before any test-day number was seen.

## 1. What is tested

| Item | Value |
|---|---|
| Model | The registry's `champion`: `nifty-option-direction` version 1, MLflow run `8fb773ac99404901ba17592595ef4f52`, trained at commit `387c81e` (clean). Its rule is "never trade" (tau = 1.01), chosen on validation. |
| Test days | The 10 locked days in `data/splits.json` (`split == "test"`): 1, 5, 6, 7, 8, 9, 12, 13, 14, 15 Oct 2026. No stage has read them. |
| Trades | Same simulator as everywhere: ATM option, buy at the ask, sell at the bid 2 minutes later, statutory costs plus slippage, one position at a time. |
| Unit of evidence | The day. 95% intervals come from resampling whole test days (5,000 resamples, seed 20261018). |

Nothing is retrained, re-tuned or re-thresholded after this file is committed. The evaluation runs **once**.
Its DVC stage is frozen after the run so `dvc repro` cannot run it again.

## 2. Primary result

Mean net rupees per day of the champion's own policy on the test days, with its 95% interval,
next to the same numbers for: stay out, always call, always put, momentum, random (100 seeds).

Reading:
* The champion never trades, so its result is Rs 0 per day by construction. The primary question is therefore:
  **was "never trade" the right call?** It was, if every baseline that trades has a mean net per day below zero.
* The oracle (perfect hindsight) is reported as the ceiling only. It is not tradable.

## 3. Secondary results (declared now, so they are not chosen after the fact)

**S1. Does the model carry any information on unseen days?**
Test log loss of the model's probabilities against the no-information prior (class shares of the train days).
Gain = prior log loss − model log loss, per day, with a day-bootstrap 95% interval.
Information is "detected" only if the interval is above zero.

**S2. Can it pick the side, ignoring the confidence rule?**
Forced policy: trade the most likely class whenever it is a side (tau = 0). Report mean net per day and per trade,
hit rate and interval. Control: the **same entry minutes** with the side chosen by coin flip, 100 seeds.
Report the share of seeds the model beats. Side-picking skill is "detected" only if the model beats at least 95 of 100.

**S3. Cost sensitivity.** The primary and S2 tables at slippage 0, 0.15 and 0.31 points per leg.
The headline is 0.31.

## 4. Outputs

* `reports/final.json` — every number above, the model version, run ID, Git commit of the evaluation, and this file's name.
* An MLflow run `final-evaluation` tagged with the champion's run ID and version and `test_days_read=yes`.
* A journal line in `runs/runs.jsonl` (stage `evaluate`).
* `docs/RESULTS.md` — the tables, written from `reports/final.json` only.

## 5. What a null result means

If nothing is detected, the report says "no edge detected on 10 unseen days" and gives the smallest daily effect
the sample could resolve. It does not say "there is no edge".
