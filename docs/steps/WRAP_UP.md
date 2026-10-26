# Wrap-up and handover (2026-10-26)

The project is stopped here so that you can study it. Everything below is committed.

## What it is, in 5 lines
1. Your recorded NIFTY options data (Upstox → Ravion V2 → ClickHouse → Parquet) goes through a DVC pipeline: export → check (Spark) → clean → eda → grid → feat → labels (Ray per day).
2. Models: a volatility forecaster (`vol`, beats the options market on 10 of 10 unseen days) and a model zoo for call/put (`zoo_train`, `zoo_eval`: no edge after costs).
3. `modelout` stores every model's answer for every minute of every day. Strategies are simulated on the real quotes (`optpred.strategy`).
4. Serving: MLflow Serve (model) → FastAPI (API, port 8000) → web page (nginx, 8080). Prometheus, Grafana, Alertmanager watch it; two alerts start a retrain.
5. Everything is tracked: Git (code), DVC (data), MLflow (runs, models). Docker Compose runs the stack.

## Start, stop, check
```bash
./stack up -d --build      # start (page 8080, API 8000, MLflow 5050, Grafana 3001)
./stack ps                 # state
./pipe dvc status          # pipeline up to date?
make test && make e2e      # tests; make ui = browser audit of the page
```

## Where to read first (one file per rubric item, short)
`docs/steps/`: business_understanding, data_identification, eda, cleaning_transformation, feature_engineering, model_selection,
model_training, deployment, monitoring, ui, vol_model. Then `docs/ARCHITECTURE.md`, `HLD.md`, `LLD.md`, `TEST_PLAN.md`,
`USER_MANUAL.md`, `UI_DESIGN.md`, `VIVA_NOTES.md` (straight answers, including what is NOT used).

## Honest results
- Volatility forecast: works (15-minute QLIKE better than the options market on 10 of 10 unseen days).
- Call/put models: lost about ₹1,376 a day on the unseen days after costs. No edge.
- Strategies (page step 4): examples for one moment. Not tested across days.

## Not done (say so in the viva)
- A rule or model that picks strategies, and an equity curve over all unseen days (the "alpha test").
- Docker Hub push (needs your account), Swarm test, an off-machine DVC remote (today the remote is a folder on the same disk).
- `docs/steps/data_identification.md` still names old folders (bars, ticks, micro) from removed stages.
- Margin for short strategies is not modelled.

## Tools: used / not used
Used: Git, Git LFS (2 sample files), DVC, MLflow (tracking, registry, serve, MLproject), Spark (check), Ray (per-day jobs, Tune),
FastAPI, Docker, Docker Compose, Prometheus, Grafana, Alertmanager, Plotly.js. Not used: Ray Serve, Kubernetes, Swarm, Docker Hub.
