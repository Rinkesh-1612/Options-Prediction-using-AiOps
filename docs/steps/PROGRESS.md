# Progress

| Item | Status |
|---|---|
| [Business Understanding](business_understanding.md) | DONE |
| [Data Identification & Acquisition](data_identification.md) | DONE |
| [Data Exploration & Analysis (EDA)](eda.md) | DONE |
| [Data Cleaning & Transformation](cleaning_transformation.md) | DONE |
| [Feature Engineering](feature_engineering.md) | DONE (open for more features) |

## Open items

- Old `bars` / `ticks` stages (and the models built on them) still read `data/raw`. New work uses
  `data/grid`. Retire the old stages when the new model replaces them.
- Feature importance: in the model training item, log gain/SHAP importance and a per-group ablation
  (train without one `feat` group at a time) to MLflow.
- Data quality monitoring: export `check` / `clean` counts to Prometheus, add a Grafana panel and an
  alert (day rejected, drop rate too high). Do this in the monitoring item.
