# Test plan

## 1. Scope

We test the code we wrote: the pipeline stages, the simulator, the model stage, the API,
the drift check, the replay tool and the web page configuration.
We do not test Spark, LightGBM, MLflow or Docker themselves.

## 2. Test levels

| Level | What it proves | Where |
|---|---|---|
| Unit | One function does what its name says (labels, costs, simulator, PSI, folds). | `tests/test_labels.py`, `test_sim.py`, `test_drift.py`, `test_tune.py`, `test_export.py` |
| Integration | Stages work together on small planted data: Spark `check`, `bars`, `features`, `baselines`; the model stage with MLflow. | `tests/test_spark_stages.py`, `test_train.py` |
| API contract | Each endpoint returns the documented status and body. The OpenAPI document equals `docs/LLD.md`. | `tests/test_api.py` |
| End to end | The running stack answers: page, API, model server, MLflow, Prometheus, Grafana. | Section 6 (smoke test) |

## 3. Method

* **Planted data.** `tests/synth.py` and `tests/test_train.py::make` build data where we know the answer.
  A planted signal must be found. Pure noise must give "never trade".
* **Independent route.** One test recomputes the features from raw ticks with different code and compares.
* **Fake model service.** API tests use a fake `ModelServer`. The real one is covered by the smoke test.
* **No look-ahead.** One test changes future ticks and checks that the features do not move.
* **Locked test days.** Tests check that the baselines stage and the API refuse them.

## 4. Test cases

The full list, with a result for every case, is in `reports/test_report.md`.
A script creates that report from pytest's own output.

| ID | Area | Case | Expected |
|---|---|---|---|
| T-01 | Labels | `test_label_rules` | The label is the action with the best net result. Ties go to the call. |
| T-02 | Labels | `test_statutory_cost_matches_ravion_contract_note` | Cost equals the contract note to the paisa. |
| T-03 | Splits | `test_assign_splits_is_chronological_and_whole_days` | Train < validation < test in time. No day is split. |
| T-04 | Simulator | `test_one_position_at_a_time` | Signals inside an open trade are ignored. |
| T-05 | Simulator | `test_stay_out_is_exactly_zero_and_days_without_trades_count_as_zero` | Staying out gives exactly 0. |
| T-06 | Simulator | `test_open_trade_does_not_carry_over_to_next_day` | No overnight position. |
| T-07 | Data quality | `test_check_rejects_holiday_and_counts_duplicates` | Frozen-price days are rejected. |
| T-08 | Features | `test_features_use_only_the_past` | Future ticks do not change a feature. |
| T-09 | Features | `test_features_match_raw_ticks_by_an_independent_route` | Two routes agree. |
| T-10 | Baselines | `test_baselines_run_and_the_locked_test_days_stay_locked` | Test days need `--final`. |
| T-11 | Model | `test_finds_a_planted_signal` | Log loss beats the prior. A threshold below "never" is chosen. |
| T-12 | Model | `test_stays_out_when_there_is_nothing_to_find` | The model chooses "never trade". |
| T-13 | Model | `test_stage_tracks_in_mlflow_and_registers_a_champion` | MLflow run has params, metrics, tags, model. A champion alias exists. |
| T-14 | Tune | `test_folds_are_walk_forward_by_day` | Scored days come after training days. |
| T-15 | Drift | `test_psi_is_large_for_a_shifted_distribution` | PSI above 0.25. |
| T-16 | Drift | `test_one_drifted_feature_out_of_five_is_not_a_drift_but_two_are` | One noisy feature does not trigger a retrain. |
| T-17 | API | `test_locked_test_days_stay_hidden_until_the_final_marker_exists` | 403 and 404 before the marker. |
| T-18 | API | `test_model_outage_is_a_readable_503_not_a_crash` | 503 with a readable body. |
| T-19 | API | `test_changing_the_served_model_needs_the_admin_token` | 401 without the token. |
| T-20 | API | `test_rollback_swaps_champion_and_previous_and_refuses_without_one` | Aliases swap. 409 when no previous model. |
| T-21 | API | `test_pipeline_console_lists_runs_and_serves_only_logs` | A log path outside `logs/` gives 404. |
| T-22 | API | `test_drift_alert_asks_for_a_retrain_once_per_cooldown` | One request. The second is refused. |
| T-23 | API | `test_openapi_matches_the_low_level_design` | Every endpoint is documented. |
| T-24 | Serving | `test_serving_code_imports_without_spark` | The serving image needs no Spark. |
| T-25 | UI | `test_page_reads_the_api_address_from_config_not_from_code` | No hard-coded back end address. |
| T-26 | Replay | `test_every_minute_is_sent_once_per_loop` | One call per minute. |

## 5. Acceptance criteria (written before the final run)

1. Every automated test passes. Zero failures. Zero errors.
2. `ruff check .` reports no problem.
3. `dvc dag` prints the six-stage graph without error.
4. The smoke test (section 6) passes every step.
5. The web page opens, lists the days, and returns a prediction for a validation minute with no error shown.
6. No locked test day is visible in the page or the API before the final evaluation.
7. Rolling back and rolling forward changes the champion version that `/model` shows.

## 6. Smoke test of the running stack

Run these after `./stack up -d --build`. Each step has an expected result.

| Step | Command or action | Expected |
|---|---|---|
| S-1 | `./stack ps` | Every service is `running`; mlflow, model, api are `healthy`. |
| S-2 | `curl -s localhost:8000/healthz` | `{"status":"ok",...}` |
| S-3 | `curl -s localhost:8000/days` | A list. No day with `split` equal to `test`. |
| S-4 | `curl -s -XPOST localhost:8000/predict -H 'content-type: application/json' -d '{"day":"2026-09-30","minute":600}'` | Status 200 with `action`. |
| S-5 | Open `http://127.0.0.1:9091/targets` | All targets are `UP`. |
| S-6 | Open `http://127.0.0.1:3001` | The dashboard "NIFTY option model — live" loads. |
| S-7 | `./stack --profile demo up -d replay` and wait 60 seconds | "Predictions served" rises on the dashboard. |
| S-8 | `curl -XPOST 'localhost:8000/retrain?reason=smoke' -H "X-Admin-Token: $ADMIN_TOKEN"` | 202. A file appears in `state/`. |
| S-9 | `curl -XPOST localhost:8000/rollback -H "X-Admin-Token: $ADMIN_TOKEN"` | 200 with swapped versions, or 409 when only one version exists. |

## 7. How to run

```bash
./pipe python scripts/test_report.py      # runs every test, writes reports/test_report.md
./pipe ruff check .
```

The pre-push hook runs the same checks before every `git push`.

## 8. Test report

The test report is `reports/test_report.md`. It lists the number of cases, passed and failed,
and the result of every case. A script generates it. Nobody edits it by hand.
