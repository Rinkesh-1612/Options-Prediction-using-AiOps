# Progress

| Item | Status |
|---|---|
| [Business Understanding](business_understanding.md) | DONE |
| [Data Identification & Acquisition](data_identification.md) | DONE |
| [Data Exploration & Analysis (EDA)](eda.md) | DONE |
| [Data Cleaning & Transformation](cleaning_transformation.md) | DONE |
| [Feature Engineering](feature_engineering.md) | DONE (open for more features) |
| [Model Selection](model_selection.md) | DONE |
| [Model Training & Evaluation](model_training.md) | DONE (result: no edge on test days) |
| [Model Deployment](deployment.md) | DONE |
| [Model Monitoring & Maintenance](monitoring.md) | DONE |
| [Web page (UI)](ui.md) | DONE |

## Open items

- From the development guideline (sections I, III, IV, V), still to do:
  Docker Hub push (needs account), optional Swarm test, end-to-end test against the running stack,
  per-signal explainability (SHAP), scalability note, documentation (architecture, HLD/LLD, test plan,
  user manual), collaboration / continuous-improvement note.
- Done from the guideline: Ray runs every per-day data stage (`optpred.common.parallel.map_days`);
  final pipeline rerun on the committed code (same results, dvc.lock up to date); integration test of
  check -> clean -> grid -> feat -> labels; encryption of data + models (AES-256, verified);
  Git LFS sample = one test day of feat + labels; automatic rollback tested (broken v6 -> back to v5).
