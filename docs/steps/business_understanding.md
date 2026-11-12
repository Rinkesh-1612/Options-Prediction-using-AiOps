# Business Understanding

> Clearly define the business problem and desired outcomes. Establish measurable success metrics.

**Problem.** I trade NIFTY options and I have my own recorded market data. I need signals that make
money after costs.

**Outcomes.**
1. A controlled AIOps ML/DL pipeline that meets the course requirements.
2. A reusable signal library that Ravion V2 can use.

**Two questions, each with a measurable success metric on days the model has not seen.**

| Question | Metric | Baseline to beat | Result |
|---|---|---|---|
| Call, put or stay out? | net rupees per day after costs, 95% interval over days | "stay out" (₹0) | not met: −₹1,376 a day |
| How much will NIFTY move in the next 15 minutes? | QLIKE error of the forecast, per day | the option market's implied move | met: better on 10 of 10 days |
