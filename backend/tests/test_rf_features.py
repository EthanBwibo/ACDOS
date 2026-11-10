"""The feature cross-validation harness (#18, #19)."""

import pytest

from app.ml import journey_time as jt
from benchmarks import rf_features as rff
from tests.test_ml_journey_time import FAST, PLACES, write_trips


def test_folds_cover_everything_once_in_near_equal_parts():
    folds = rff.fold_indices(23, k=5, seed=1)

    assert sorted(i for fold in folds for i in fold) == list(range(23))
    assert sorted(len(f) for f in folds) == [4, 4, 5, 5, 5]
    assert rff.fold_indices(23, k=5, seed=1) == folds
    assert rff.fold_indices(23, k=5, seed=2) != folds


def test_cross_validation_scores_every_fold(tmp_path):
    trips = jt.load_trips(write_trips(tmp_path / "t.csv", n=100))
    scores = rff.cross_validate(trips, jt.Features(cyclic=True, spatial=True), FAST, PLACES, k=4)

    assert len(scores) == 4
    assert all(s["mape"] >= 0 and s["mae_sec"] >= 0 for s in scores)


def test_score_by_hand():
    class Model:
        def predict(self, cells):
            return [110.0, 90.0]

    trips = [jt.Trip("A", "X", 0, 0, 100.0), jt.Trip("A", "X", 0, 1, 100.0)]

    assert rff.score(Model(), trips) == {"mape": pytest.approx(10), "mae_sec": pytest.approx(10)}


def folds(*mapes):
    return [{"mape": m, "mae_sec": 0.0} for m in mapes]


def test_the_lowest_mean_cv_mape_is_chosen():
    cv = {"plain": folds(5, 5), "cyclic": folds(4, 5.5), "spatial": folds(4, 4.9)}

    assert rff.choose(cv) == "spatial"


def test_a_tie_keeps_the_earlier_simpler_set():
    assert rff.choose({"plain": folds(5, 5), "cyclic": folds(4, 6)}) == "plain"


def row(run, actual, before, after, baseline=200.0):
    return {"run_id": run, "actual_sec": actual, "rf": before, "rf_after": after,
            "static_baseline": baseline}  # fmt: skip


def test_after_minus_before_is_below_0_when_the_new_features_help():
    # Before 10% off, after 4% off.
    assert rff.after_minus_before([row("r", 100, 110, 96)]) == pytest.approx(4 - 10)


def test_improvement_works_for_either_model():
    # Baseline 100% off; before 10% off removes 90%, after 4% off removes 96%.
    rows = [row("r", 100, 110, 96)]

    assert rff.improvement("rf")(rows) == pytest.approx(90)
    assert rff.improvement("rf_after")(rows) == pytest.approx(96)
