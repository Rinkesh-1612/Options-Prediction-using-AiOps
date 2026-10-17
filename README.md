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

## Tests

```bash
pytest -q && ruff check .
```
