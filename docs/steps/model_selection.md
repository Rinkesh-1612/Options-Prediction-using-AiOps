# Model Selection

> Choose appropriate ML algorithms based on the problem and data characteristics.

**Data facts that drive the choice.** Tabular features with NaN, mixed scales and fat tails. Weak signal
(lag-1 autocorrelation of NIFTY returns 0.02). Only 49 independent days. The regime changes every 2–3 months.

**Target: triple-barrier label** (López de Prado). Entry at the ATM ask. Exit at the bid at the first of:
take-profit (+k₁·σ), stop-loss (−k₂·σ), time cap. σ = the option's recent volatility, so the holding period
changes with the market. It is not fixed. One label gives three targets: the barrier that the price touched
first (class), the net ₹ after costs (regression), and the holding time.

**Model zoo.** All models use the same labels, the same walk-forward split (purged, with an embargo) and
the same simulator in net ₹.

| # | Family | Why |
|---|---|---|
| 0 | Baselines: stay out, momentum, random | the minimum that a model must beat |
| 1 | Logistic / ridge | sanity check: if trees do not beat it, the trees overfit |
| 2 | LightGBM classifier + regressor | strongest default for tabular financial data; handles NaN; gives feature importance |
| 3 | Meta-labelling (rule → LightGBM take/skip) | a model that filters a simple signal needs less data |
| 4 | LSTM / GRU on the last 60–120 s | time-series dependencies |
| 5 | Small transformer (TransLOB-style) | attention over the order-book sequence |

**Risk from the literature:** deep order-book models lose accuracy on new data (LOBCAST, 15 models), and
on intraday futures both LSTM and boosting stayed near 50% (2026). A deep model stays only if it beats LightGBM.

Sources: [DeepLOB](https://arxiv.org/pdf/1808.03668) · [TransLOB](https://arxiv.org/pdf/2003.00130) ·
[TLOB](https://arxiv.org/html/2502.15757v1) · [LOBCAST](https://arxiv.org/abs/2308.01915v1) ·
[LOBFrame](https://arxiv.org/html/2403.09267v2) · [GBM vs LSTM intraday](https://econpapers.repec.org/paper/arxpapers/2605.17724.htm)
