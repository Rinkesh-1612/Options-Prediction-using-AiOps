# AI disclosure

Rinkesh Patel DA24B017
## Tool

Claude (Anthropic), in Claude Code. It worked in this repository on my server.

## My part

- I chose the problem: NIFTY options, intraday, after costs.
- I supplied the data: my own recordings from my trading system, Ravion V2.
- I made most of the decisions: NIFTY only, the cost rules (from my broker contract notes), a holding time
  that follows the market, a baseline for each model, and an honest report of a negative result.
- I set the architecture: a DVC pipeline, MLflow for tracking and the registry, a REST API in front of the
  model, a separate web page, and Prometheus with Grafana for monitoring.
- I verified the work. I reviewed each lifecycle step (`docs/steps/`), checked the results, and asked for
  changes when something was wrong or not clear.
- I changed the idea when the data said no, and I tried these directions:
  - direction models from simple to deep (linear, LightGBM, GRU, Transformer and others): no edge after costs;
  - a second question, how much NIFTY will move: this forecast beats the option market;
  - trading on that forecast (straddles, expiry days, a search over option structures): no profit after costs;
  - a smaller project at the end: I removed the parts that did not add a result.

## Claude's part

- Claude wrote most of the code, the test and DVC configuration, the monitoring, the web page
  and helped in beautifying the documents.


## Impact

The AI wrote most of the lines. It made a project of this size possible in the time I had. The problem, the
data, the decisions, the architecture and the checks are mine.

Every number comes from a recorded run (`logs/runs.jsonl`) and an MLflow run with its Git commit. No number
comes from text that the AI wrote. I am responsible for each part, and I can explain each part.
