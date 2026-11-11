# Source Control & Continuous Integration

> How is continuous integration implemented using DVC? Is there a DVC DAG representing your CI pipeline?
> Are you using Git, Git LFS and/or DVC for source, data, model versioning?

**Method (course lecture 11, "DVC for Continuous Integration").** The CI pipeline is the DVC DAG in
[dvc.yaml](../../dvc.yaml). Each stage declares its code, data and params. `dvc repro` compares their hashes with
`dvc.lock` and reruns only the stages that changed.

**DAG.** `./pipe dvc dag`:
```
export → check → clean → eda
                       → grid → feat, labels → zoo_train → zoo_eval ─┐
                              → vol ──────────────────────────────────┤
                              → drift                                 │
tests (ruff + pytest + report) ───────────────────────────────────────┴→ gate
```

| Stage | Reruns when | Output |
|---|---|---|
| `tests` | any code, test, `docs/LLD.md` or page change | `reports/tests.json`, `reports/test_report.md` |
| `gate` | a test result, the day list, a model result or `params.yaml: gate` changes | `reports/gate.json` |

`gate` ([optpred/ci/gate.py](../../src/optpred/ci/gate.py)) fails `dvc repro` when one criterion fails:
no failed test, ≥ 40 accepted days, vol model beats the option market and passed its deploy smoke test,
direction champion passed its deploy smoke test. Last run: 4 of 4 PASS.

**Commands.**
```bash
make ci                      # = ./pipe dvc repro gate   (the pre-push hook runs the same)
./pipe dvc status            # which stages are stale
./pipe dvc metrics show      # every metric file (quality, cleaning, grid, feat, labels, zoo, vol, drift, tests, gate)
./pipe dvc metrics diff HEAD~1 && ./pipe dvc params diff HEAD~1    # compare two commits
./pipe dvc plots diff HEAD~1 # plots (EDA, drift, vol scatter) side by side
./pipe dvc exp run -S vol.stride_s=60 && ./pipe dvc exp show       # experiment = changed param, then compare
```

**Trigger.** `.githooks/pre-push` runs `dvc repro gate`. The web page can start the same run (Controls → *Run the
pipeline* → `POST /pipeline/run` → runner). The push stops if the gate fails, or if CI changed
`dvc.lock` or `reports/` (then commit them first). No cloud CI: the course does not allow cloud platforms.

**CD.** `zoo_eval` and `vol` register the new model in MLflow; it becomes `champion` only after its smoke test.
The model server follows the alias.

**Versioning.** Git: code, params, `dvc.lock`, metrics, run journal. Git LFS: one sample day (`data/sample/`).
DVC: all data (`data/raw` … `data/labels`, remote `../dvc-remote`). MLflow registry: models.
