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

## Tests

```bash
pytest -q && ruff check .
```
