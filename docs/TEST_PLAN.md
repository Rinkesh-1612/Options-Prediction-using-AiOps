# Test plan

> **DEPRECATED (2026-10-23).** This document was written before the owner reviewed the project. It is not approved by the owner. Do not use it as a reference. A reviewed version will replace it.

## 1. Scope

We test the code we wrote: the pipeline stages, the simulator, the model, register and evaluate stages, the API,
the drift check, the replay tool and the web page configuration.
We do not test Spark, LightGBM, MLflow or Docker themselves.

## 2. Test levels

| Level | What it proves | Where |
|---|---|---|
| Unit | One function does what its name says (labels, costs, simulator, PSI, folds). | `tests/unit/` (labels, simulator, PSI, folds, export, v2 fills and barriers, replay, serving imports) |
| Integration | Stages work together on small planted data: Spark `check`, `bars`, `features`, `baselines`; `train`, `register` and `evaluate` with a real MLflow store. | `tests/integration/` (Spark stages incl. v2 `ticks` and `micro`, train, register, evaluate) |
| API contract | Each endpoint returns the documented status and body. The OpenAPI document equals `docs/LLD.md`. Every path the page calls is in `docs/LLD.md`. | `tests/api/` (API contract, page-to-API contract) |
| End to end | The running stack answers: page, API, model server, MLflow, Prometheus, Grafana. | Section 6 (smoke test) |

## 3. Method

* **Planted data.** `tests/helpers/synth.py` and `tests/helpers/planted.py` build data where we know the answer.
  A planted signal must be found. Pure noise must give "never trade".
* **Independent route.** One test recomputes the features from raw ticks with different code and compares.
* **Fake model service.** API tests use a fake `ModelServer`. The real one is covered by the smoke test.
* **No look-ahead.** One test changes future ticks and checks that the features do not move.
* **Locked test days.** Tests check that the baselines stage, the API and the evaluate stage refuse them, and that `evaluate` refuses a second look.

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
| T-27 | Register | `test_register_promotes_only_a_better_model_and_keeps_the_old_one_for_rollback` | Equal model: champion stays. Better model: champion moves, old one becomes `previous`. |
| T-28 | Evaluate | `test_refuses_without_final_and_refuses_a_second_look` | Exit 2 without `--final`. Exit 3 when `reports/final.json` exists. |
| T-29 | Evaluate | `test_scores_the_registered_champion_and_writes_the_marker` | Scores the registry champion with its own tau. A planted signal is detected on unseen days. MLflow run tagged `test_days_read=yes`. |
| T-30 | Evaluate | `test_a_never_trade_model_scores_zero_and_finds_nothing_in_noise` | Never-trade model: 0 trades, Rs 0. Noise: nothing detected. |
| T-31 | API | `test_results_appear_only_after_the_one_time_evaluation` | 404 before, the file after, 500 for a broken file. |
| T-32 | UI | `test_every_backend_path_the_page_calls_is_in_the_low_level_design` | No undocumented endpoint is used by the page. |
| T-33 | v2 fills | `test_vectorised_fill_matches_the_v1_fill_row_by_row` | The fast book fill equals the v1 fill on 200 random books. |
| T-34 | v2 barriers | `test_take_profit_stop_loss_and_time_stop`, `test_the_first_barrier_touched_wins` | The first barrier touched decides the exit; a gap fills at the worse price. |
| T-35 | v2 barriers | `test_no_trade_without_an_entry_and_no_barrier_on_a_missing_bid` | A missing bid never fakes a stop loss. |
| T-36 | v2 inputs | `test_rolling_sum_uses_only_the_past` | A change in the future does not move a past input. |
| T-37 | v2 simulator | `test_one_position_at_a_time_with_barrier_holds` | Signals during an open trade are ignored; no overnight position. |
| T-38 | v2 Spark | `test_ticks_keep_only_contracts_that_can_be_at_the_money` | One row per contract-second; strikes near the day's range only; volumes add up. |
| T-39 | v2 micro | `test_micro_rows_have_every_input_and_a_barrier_trade_for_both_sides` | Every input exists; every row has a call and a put trade with a valid exit. |
| T-40 | Splits | `test_forward_days_never_move_the_locked_split` | New days become "forward"; the v1 split never changes. |
| T-41 | v2 evaluate | `test_v2_evaluation_refuses_without_final_and_refuses_a_second_look` | Exit 2 without `--final`; exit 3 on a second run. |
| T-42 | API | `test_v2_results_need_all_three_reports` | `/results/v2` is 404 until all three v2 reports exist. |

## 5. Acceptance criteria

Criteria 1–7 were written on 19 Oct, before the final run. Criterion 8 was added on 22 Oct with the `evaluate` stage.

1. Every automated test passes. Zero failures. Zero errors.
2. `ruff check .` reports no problem.
3. `dvc dag` prints the graph (nine v1 stages and four v2 stages) without error, and `dvc status` reports nothing to rerun.
4. The smoke test (section 6) passes every step.
5. The web page opens, lists the days, and returns a prediction for a validation minute with no error shown.
6. No locked test day is visible in the page or the API before the final evaluation. After it, they are visible and `/results` answers.
7. Rolling back and rolling forward changes the champion version that `/model` shows.
8. The final evaluation ran once, from a clean commit (`git_dirty: false` in the journal), after its protocol was committed.

## 6. Smoke test of the running stack

Run these after `./stack up -d --build`. Each step has an expected result.

| Step | Command or action | Expected |
|---|---|---|
| S-1 | `./stack ps` | Every service is `running`; mlflow, model, api are `healthy`. |
| S-2 | `curl -s localhost:8000/healthz` | `{"status":"ok",...}` |
| S-3 | `curl -s localhost:8000/days` | A list. Before the final evaluation: no day with `split` equal to `test`. After it: 10 test days. |
| S-4 | `curl -s -XPOST localhost:8000/predict -H 'content-type: application/json' -d '{"day":"2026-09-30","minute":600}'` | Status 200 with `action`. |
| S-5 | Open `http://127.0.0.1:9091/targets` | All targets are `UP`. |
| S-6 | Open `http://127.0.0.1:3001` | The dashboard "NIFTY option model — live" loads. |
| S-7 | `./stack --profile demo up -d replay` and wait 60 seconds | "Predictions served" rises on the dashboard. |
| S-8 | `curl -XPOST 'localhost:8000/retrain?reason=smoke' -H "X-Admin-Token: $ADMIN_TOKEN"` | 202. A file appears in `state/`. |
| S-9 | `curl -XPOST localhost:8000/rollback -H "X-Admin-Token: $ADMIN_TOKEN"` | 200 with swapped versions, or 409 when only one version exists. |
| S-10 | `curl -s localhost:8000/results` | The final result: `verdict`, `by_slippage`, `information`. |
| S-11 | Open the page, tab **Results** | The table of rules on the unseen days; no error banner. |

## 7. How to run

```bash
./pipe python scripts/test_report.py      # runs every test, writes reports/test_report.md
./pipe ruff check .
```

The pre-push hook runs the same checks before every `git push`.

## 8. Test report

The test report is `reports/test_report.md`. It lists the number of cases, passed and failed,
and the result of every case. A script generates it. Nobody edits it by hand.

## 9. Acceptance record (22 Oct 2026)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | All automated tests pass | **Met.** 73 of 73 | `reports/test_report.md`; the same 73 pass under `mlflow run . -e test` (`reports/mlproject_test_run.log`) |
| 2 | `ruff check .` clean | **Met** | pre-push hook; `./pipe ruff check .` |
| 3 | Nine-stage DAG, nothing to rerun | **Met** | `./pipe dvc dag`; `./pipe dvc status` → "Data and pipelines are up to date" (`evaluate` frozen) |
| 4 | Smoke test S-1 to S-11 | **Met** | S-1 all services up, 3 healthy; S-2 ok; S-3 33 train, 6 val, 10 test days; S-4 200; S-5 targets api, host, mlflow, prometheus all `up`; S-6, S-7 `docs/img/grafana.png`; S-8 401 without token, 202 with it, runner retrained (registry v5, not promoted); S-9 409 (no previous model, as expected); S-10 verdict returned; S-11 `docs/img/results-desktop.png` |
| 5 | Page lists days and predicts with no error | **Met** | `docs/img/predict-desktop.png`, `docs/img/predict-phone.png` |
| 6 | Test days hidden until the final evaluation, visible after | **Met** | T-17, T-31; S-3 after the run |
| 7 | Roll back and forward changes the champion | **Met by tests only** (T-20, T-27). Live: no second model has ever beaten version 1 on validation, so there is no `previous` version and the API answers 409, as designed. |
| 8 | Final evaluation once, clean commit, protocol first | **Met** | protocol commit `7d65338`; journal `20261022T161450-evaluate`, `git_dirty: false`; a second run exits 3 (T-28) |

**Drift → retrain, end to end (observed, not staged).** During the replay demo the drift window passed 1,000 rows.
Ten features crossed PSI 0.25, Prometheus fired `DriftDetected`, Alertmanager called the API, the API wrote a
retrain request, and the runner trained and registered version 4 (`state/retrain_20261022T112001_ok.json`,
journal `20261022T164936-train`). It was not promoted: it was no better on validation.
