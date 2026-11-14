# Model Selection

> Choose appropriate ML algorithms based on the problem and data characteristics.

**Data facts that drive the choice.** Tabular features with NaN, mixed scales and fat tails. Weak signal
(lag-1 autocorrelation of NIFTY returns 0.02). Only 49 independent days. The regime changes every 2 to 3 months.

**Target: triple-barrier label** (López de Prado). Entry at the ATM ask. Exit at the bid at the first of:
take-profit (+k₁·σ), stop-loss (−k₂·σ), time cap. σ = the option's recent volatility, so the holding period
changes with the market. It is not fixed. One label gives three targets: the barrier that the price touched
first (class), the net ₹ after costs (regression), and the holding time.

**Models.** All models use the same labels, the same walk-forward split (purged, with an embargo) and
the same simulator in net ₹.

| Family | Why |
|---|---|
| Baseline: stay out | the minimum that a model must beat |
| Ridge regression (linear) | sanity check: if trees do not beat it, the trees overfit |
| LightGBM regressor | strongest default for tabular financial data; handles NaN; gives feature importance |

**Kept simple on purpose.** Six more families were tried first (LightGBM classifier, meta-labelling, GRU, a small
transformer, momentum and random baselines). None beat "stay out" on the test days, so they were removed
(Git history before 2026-11-11). The literature says the same: deep order-book models lose accuracy on new data
([LOBCAST](https://arxiv.org/abs/2308.01915v1)).
