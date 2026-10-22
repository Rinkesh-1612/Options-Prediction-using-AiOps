# Results

**Verdict: no tradable edge detected on 10 unseen days.** The model chose "never trade" on validation, and that was
the right call: every rule that trades lost between Rs 11,500 and Rs 13,300 per day on the test days. The model does
know *something* about the next two minutes (it beats the no-information baseline on 9 of 10 test days), but it cannot
pick the winning side: when forced to trade it did no better than coin flips.

Every number below comes from a journaled run (`runs/runs.jsonl`, `logs/`) or an MLflow run, named next to it.
The test-day rules were fixed in advance in [FINAL_TEST_PROTOCOL.md](FINAL_TEST_PROTOCOL.md) (commit `7d65338`).

## 1. Setup

| Item | Value |
|---|---|
| Decision | Each minute 09:21–15:28: buy the ATM call, buy the ATM put, or stay out |
| Trade | Buy at the ask, sell at the bid 2 minutes later, statutory charges + 0.31 points slippage per leg, one lot (65) |
| Days | 49 accepted of 55. Train 33 (3 Aug – 17 Sep), validation 6 (18 Sep – 30 Sep), test 10 (1 Oct – 15 Oct) |
| Model | LightGBM, 3 classes, 38 features. Trade threshold chosen on validation; "never trade" allowed |
| Evidence unit | The day. Intervals: 95%, 5,000 resamples of whole days |

## 2. Validation (6 days) — how the model was chosen

Champion: registry version 1, MLflow run `8fb773ac`, journal `20261018T112025-train` (clean commit `387c81e`).
Re-trained from clean commit `167de2b` on 22 Oct (journal `20261022T161418-train`, version 3): identical numbers.

| | Value |
|---|---|
| Log loss, model / no-information prior | 1.0865 / 1.0964 |
| Best trade threshold on validation | **never trade** (every threshold that traded lost money) |
| Ray Tune (16 settings, walk-forward on train days, `20261019T094114-tune`) | best log loss 1.0890 vs 1.0894 default: tuning does not help |

Baselines on validation at 0.31 slippage (`20261018T105829-baselines`):

| Rule | Net per day (Rs) | 95% interval | Net per trade | Hit rate |
|---|---|---|---|---|
| Stay out | 0 | – | – | – |
| Always call | −14,464 | −17,067 to −11,889 | −78.7 | 32% |
| Always put | −11,439 | −13,365 to −9,325 | −62.2 | 36% |
| Momentum (last 2 min) | −13,204 | −15,394 to −10,757 | −73.9 | 32% |
| Random side (100 seeds) | −13,059 | – | −71.0 | 34% |
| Oracle (hindsight, not tradable) | +21,547 | +15,651 to +27,902 | +146.6 | 100% |

## 3. Test days (10 days, opened once) — the honest number

Journal `20261022T161450-evaluate` (clean commit `2ccd869`, `git_dirty: false`), MLflow run `b4123eab`,
`reports/final.json`. The DVC stage `evaluate` is frozen after this run.

### Primary: champion against the baselines (slippage 0.31)

| Rule | Net per day (Rs) | 95% interval | Net per trade | Hit rate | Trades per day |
|---|---|---|---|---|---|
| **Champion (never trade)** | **0** | – | – | – | 0 |
| Always call | −12,854 | −17,053 to −8,436 | −70.1 | 39% | 183 |
| Always put | −13,331 | −17,132 to −9,485 | −72.7 | 40% | 183 |
| Momentum | −11,522 | −14,084 to −8,850 | −64.5 | 39% | 179 |
| Random side (100 seeds) | −13,167 | – | −71.8 | 39% | 183 |
| Oracle (hindsight, not tradable) | +38,454 | +34,305 to +42,667 | +239.0 | 100% | 161 |

Every rule that trades lost, with intervals far below zero. "Never trade" was the right decision.

### S1: does the model know anything on unseen days?

| | Value |
|---|---|
| Log loss, model / no-information prior | 1.0739 / 1.0902 |
| Gain per day | 0.0162, 95% interval **0.0099 to 0.0222** (above zero) |
| Days with a gain | 9 of 10 |
| Accuracy (3 classes) | 39% |

**Detected.** The model's probabilities are better than the class shares on unseen days.

### S2: can it pick the side?

Forced policy: trade the most likely class whenever it is a side, ignoring the threshold. Control: the same entry
minutes with the side picked by coin flip.

| | Net per day (Rs) | 95% interval | Hit rate |
|---|---|---|---|
| Forced model | −13,254 | −17,396 to −9,102 | 40% |
| Coin flip, same minutes (100 seeds) | −12,914 (5th–95th: −15,534 to −10,462) | – | – |
| Seeds the model beats | **37 of 100** (needed 95) | | |

**Not detected.** The information from S1 does not tell the call from the put well enough to pay.
A likely reading (not tested): the model learns *when* moves are large, not *which way* they go.

### S3: cost sensitivity (net per day, Rs)

| Slippage per leg | Champion | Momentum | Always call | Forced model | Coin flip, same minutes |
|---|---|---|---|---|---|
| 0.00 | 0 | −4,320 | −5,463 | −6,048 | −5,708 |
| 0.15 | 0 | −7,805 | −9,040 | −9,534 | −9,195 |
| 0.31 | 0 | −11,522 | −12,854 | −13,254 | −12,914 |

Even with zero slippage every trading rule loses. The bid/ask spread alone is larger than what direction can earn.

## 4. What this sample can and cannot show

* The smallest daily effect the 10 test days can resolve is about **Rs 4,400 per day** (forced policy). A smaller real
  edge would be invisible here. So the claim is "no edge detected", not "no edge exists".
* One market regime (Aug–Oct 2026), one index (NIFTY), one hold (2 minutes).
* The slippage of 0.31 points may already include part of the spread; S3 shows the result does not depend on it.
* The `check` and `bars` stages ran from a working tree with uncommitted changes (`git_dirty: true` in the journal);
  their outputs are pinned by DVC hashes in `dvc.lock`.

## 5. Side experiments (archived, not part of the graded pipeline)

Before the test days were opened, two further experiments were run on train and validation days only, each with its
pass rule written before the run. They live on the Git branch `alpha-lab`.

1. Longer holds (5, 10, 30 minutes) × two feature sets: 6 settings. None was positive out of fold with an interval
   above zero. The one setting that traded on validation (+Rs 910/day) lost Rs 1,077/day out of fold.
2. A rule-based "band breakout" entry from the author's own trading system, with and without a small LightGBM gate:
   −Rs 209/day on untouched days at book prices; the gate made it worse.

Neither experiment read a test day. They support the same conclusion: after the spread, short-term direction on
ATM NIFTY options was not predictable enough to pay in this data.

## 6. Answer to the project question

> Can a model, each minute, choose call / put / stay out on NIFTY options and make money after costs?

Not on this data. The system measured it honestly: the model carries real but small information, the costs
are larger than what that information can earn, and the model's own rule correctly chose to stay out.
