from optpred.modelout.stage import groups, sources

DEV = [f"d{i:02d}" for i in range(39)]
TEST = [f"t{i}" for i in range(10)]
FOLDS = [(DEV[: 19 + 5 * k], DEV[19 + 5 * k : 24 + 5 * k]) for k in range(4)]


def test_every_day_gets_one_source_and_models_never_see_their_own_oof_days():
    plan = sources(DEV, TEST, FOLDS)
    assert set(plan) == set(DEV) | set(TEST)
    for d, (src, train) in plan.items():
        if src in ("oof", "test"):
            assert d not in train
    assert {plan[d][0] for d in DEV[:19]} == {"train"} and {plan[d][0] for d in TEST} == {"test"}
    assert sum(1 for s, _ in plan.values() if s == "oof") == 20


def test_one_fit_per_training_set():
    plan = sources(DEV, TEST, FOLDS)
    g = groups(plan)
    assert len(g) == 6  # first days (in-sample), four folds, test
    assert sorted(d for _, days, _ in g for d in days) == sorted(plan)
