# Results

> **DEPRECATED (2026-10-23).** This document was written before the owner reviewed the project. It is not approved by the owner. Do not use it as a reference. A reviewed version will replace it.

**Verdict: no tradable edge detected.**

* **v1 (minute model, fixed 2-minute hold):** on 10 locked test days every rule that trades lost Rs 11,500 – 13,300
  per day. The model chose "never trade", which was right. It knew a little about the next minutes, but could not
  pick the side.
* **v2 (second-level order book and futures flow, barrier exits, statutory costs only):** it **can** pick the side
  (it beats random side choice in 98 of 100 tries), but the gain is about Rs 5 per trade and the 95% interval
  includes zero. On the 10 held-out days it traded once and lost Rs 136.
* **Alpha sprint (six pre-registered ideas, 99% bar):** none passed. Two leads remain for paper trading only:
  the first 25 minutes of the session, and expiry-day afternoons.

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

## 7. v2: second-level microstructure model

Rules: `docs/V2_PROTOCOL.md` (written before any v2 code), amendment 1 (statutory costs only, author's decision after
seeing development results) and amendment 2 (no forward days; the v1 test days are the held-out set).

| Item | Value |
|---|---|
| Decisions | every second 09:20:00 – 15:25:00; 1,071,575 decision seconds over 49 days |
| Trade | buy the ATM call or put at the ask; exit at the bid on +3.5 / −2.0 points or after 180 s |
| Cost | statutory charges only (brokerage is zero); 0.15 and 0.31 points slippage as sensitivity |
| Model | two LightGBM binary models, P(call wins), P(put wins); trade the likelier side if P ≥ tau |
| Spark stage `ticks` | 32 M option ticks → 20.6 M contract-seconds with order-flow imbalance and signed volume (journal `20261022T192516-ticks`) |

### Development days, out of fold (24 days; journal `micro_train`, `reports/micro_train.json`)

| tau | Trades | Net per day (Rs) |
|---|---|---|
| 0.50 | 2,666 | −1,566 |
| 0.55 | 1,136 | −301 |
| 0.60 | 346 | −135 |
| **0.65 (chosen)** | **66** | **+13** (95% interval −89 to +146; hit rate 47%; +Rs 4.9 per trade) |
| 0.70 | 10 | +10 |

Random side at the same entry seconds: the model beats it in 98 of 100 seeds. Blind entries on the same days:
always call −Rs 11,027, always put −Rs 5,699, futures-flow rule −Rs 5,750 per day.
Pass rule 1 (interval above zero): **failed**. Pass rule 2 (side picking): **passed**.

### Held-out days, one look (10 v1 test days, second look; journal `20261023T164424-micro_evaluate`, `reports/micro_final.json`)

| Rule | Trades | Net per day (Rs) |
|---|---|---|
| **v2 model (tau 0.65)** | **1** | **−14** |
| Always call | 5,919 | −19,059 |
| Always put | 5,920 | −17,849 |
| Futures-flow rule | 5,392 | −16,204 |

The model's probabilities rarely reached 0.65 on these days, so it almost never traded. Pass rule 3: **failed**.
One trade is no evidence either way.

## 8. Alpha sprint (six pre-registered trials, out of fold, 99% bar)

Rules: `docs/ALPHA_SPRINT.md`. Numbers: `reports/sprint.json`. Statutory costs only.

| Trial | Trades | Hit rate | Net per day (Rs) | 99% interval | Beats control |
|---|---|---|---|---|---|
| v2 (reference) | 66 | 47% | +13 | −116 to +193 | 98/100 |
| A: magnitude gate | 24 | 50% | +35 | −46 to +128 | 89/100 |
| C: trailing-stop exit | 234 | 47% | +74 | −217 to +395 | 92/100 |
| D1: 09:20 – 09:45 only | 187 | 49% | +131 | −163 to +456 | 100/100 |
| D2: expiry day after 13:00 | 85 | 54% | +115 | −41 to +395 | 85/100 |
| D3: realised > implied vol | 60 | 47% | +35 | −173 to +245 | 94/100 |
| E: liquidity sweep (no model) | 6,774 | 36% | −7,477 | −10,248 to −5,322 | 0/100 |

No trial passed. D1 and D2 are leads for a live paper trade, not findings: they are the best 2 of about 19 trials
in this project.

**Disclosure.** The first version of `reports/micro.json` printed label base rates (share of winning trades) over
all 49 days, including the v1 test days. It was corrected to development days only before any v2 model existed.

## 9. What the project shows

1. After the bid/ask spread and taxes, buying ATM NIFTY options on 2-minute or barrier horizons did not pay in
   Aug – Oct 2026, for any blind rule and for both models.
2. Minute summaries carry information about *when* moves come, not *which way*. Second-level order flow and
   futures flow add a measurable but small ability to pick the side.
3. The cost assumption decides the sign of the result. A real slippage measurement would settle the question
   better than any further model search.
