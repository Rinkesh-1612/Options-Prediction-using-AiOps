# Options-Prediction-using-AiOps

DA3408 course project: predict, each minute, whether buying the ATM NIFTY call,
buying the put, or staying out pays **after costs** over the next 2 minutes.
Plan and every decision with its reason: [PLAN.md](PLAN.md).

## Setup (on the VPS)

```bash
git clone <this repo> && cd Options-Prediction-using-AiOps
git checkout ccr-65d528eb-0u5j23
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e .
```

## Stage 1 — export (read-only copy out of Ravion's ClickHouse)

```bash
export CH_PASSWORD="$(grep '^CLICKHOUSE_PASSWORD=' ~/Ravion-V2/.env | cut -d= -f2-)"
python -m optpred.export --dry-run   # rows per day per table, writes nothing
python -m optpred.export             # writes data/raw/<table>/<day>.parquet + manifest.json
```

Every run is journaled: `logs/<stage>/<run_id>.log` + one line in `runs/runs.jsonl`
(git commit, params hash, duration, exit code, summary). Commit both after a run:

```bash
git add logs runs && git commit -m "run: export" && git push
```

## Stages 2-6 — the pipeline (inside the pipeline image)

```bash
./pipe build                                  # once, ~5-8 min
./pipe python -m optpred.check
./pipe python -m optpred.bars
./pipe python -m optpred.features
./pipe python -m optpred.baselines            # train + validation only
./pipe python -m optpred.train                # logs to MLflow, registers the model
git add logs runs reports data/days.json data/splits.json && git commit -m "run: ..." && git push
```

## The web stack (MLflow, model server, API, web page, retrain runner)

```bash
cp .env.example .env && nano .env             # set ADMIN_TOKEN
./stack up -d --build                         # first build ~5 min
./stack ps                                    # everything should say "healthy"
```

| What | Address on the VPS | From your laptop (SSH tunnel) |
|---|---|---|
| Web page | http://127.0.0.1:8080 | `ssh -L 8080:127.0.0.1:8080 -L 8000:127.0.0.1:8000 -L 5050:127.0.0.1:5050 trader@<vps>` then open http://127.0.0.1:8080 |
| Backend API docs | http://127.0.0.1:8000/docs | same tunnel |
| MLflow UI | http://127.0.0.1:5050 | same tunnel |

Nothing is exposed publicly unless you set `BIND=0.0.0.0` in `.env`.

## Tests

```bash
pytest -q && ruff check .
```
