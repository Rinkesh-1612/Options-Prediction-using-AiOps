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
| [Web page (UI)](ui.md) | DONE (rebuilt for non-technical users; browser audit 12 of 12) |
| [Second model: volatility forecaster](vol_model.md) | DONE (beats the option market on 10/10 test days) |
| Documents: [architecture](../ARCHITECTURE.md), [HLD](../HLD.md), [LLD](../LLD.md), [test plan](../TEST_PLAN.md), [user manual](../USER_MANUAL.md) | DONE |

## Open items

- From the development guideline (sections I, III, IV, V), still to do:
  Docker Hub push (needs account), optional Swarm test, push to GitHub.
- Evaluation guideline checked 2026-10-25: MLproject restored (run log in reports/), speed and throughput shown in the
  "How it's built" tab, architecture + HLD diagrams (svg), paradigm / tracking / monitoring-coverage text in the HLD, viva notes.
- Done from the guideline: Ray runs every per-day data stage (`optpred.common.parallel.map_days`);
  reproducibility: final zoo_train / zoo_eval / drift runs on clean commit 08f847c (MLflow tags
  git_commit=08f847c, git_dirty=False; same results; champion v7); integration test of
  check -> clean -> grid -> feat -> labels; encryption of data + models (AES-256, verified);
  Git LFS sample = one test day of feat + labels; automatic rollback tested (broken v6 -> back to v5);
  per-signal explainability (SHAP: /signal drivers + Forecast tab);
  end-to-end tests (tests/e2e, `make e2e`); scalability and collaboration notes (HLD section 5);
  old caches removed (DVC cache 12 -> 9.5 GB, old MLflow experiments and models purged).
