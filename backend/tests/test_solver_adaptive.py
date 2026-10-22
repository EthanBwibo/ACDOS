import csv
import math
import random

import pytest

from app.solver.individual import split
from app.solver.instances import morning_wave, morning_wave_120, smoke_30
from app.solver.mutation import AdaptiveMutation, Outcome, write_operator_log
from tests.solver_checks import assert_feasible

PROBLEM = morning_wave(n_crew=12, n_vans=4, seed=1)


def used(mutation, destroy, outcome):
    """Record outcome as if destroy and greedy had just been applied."""
    mutation._last = {"destroy": destroy, "repair": "greedy"}
    mutation.record(outcome)


def test_weights_follow_ropke_and_pisinger_after_one_segment_checked_by_hand():
    mutation = AdaptiveMutation(PROBLEM, segment_length=4, reaction_factor=0.1)

    used(mutation, "shaw", Outcome.NEW_BEST)  # 33
    used(mutation, "shaw", Outcome.NO_SCORE)  # 0
    used(mutation, "random", Outcome.IMPROVED)  # 9
    used(mutation, "random", Outcome.ACCEPTED_NEW)  # 13

    # w = 1 * 0.9 + 0.1 * score / uses
    assert mutation.weights["destroy"] == pytest.approx(
        {"shaw": 0.9 + 0.1 * 33 / 2, "random": 0.9 + 0.1 * 22 / 2, "worst": 1.0}
    )
    # Greedy took part in all four: 55 over 4 uses.
    assert mutation.weights["repair"] == pytest.approx({"greedy": 0.9 + 0.1 * 55 / 4})


def test_an_operator_not_used_in_a_segment_keeps_its_weight():
    mutation = AdaptiveMutation(PROBLEM, segment_length=2)
    mutation.weights["destroy"]["worst"] = 1.7

    used(mutation, "shaw", Outcome.NO_SCORE)
    used(mutation, "random", Outcome.NO_SCORE)

    assert mutation.weights["destroy"]["worst"] == 1.7


def test_an_operator_that_never_scores_decays_but_never_reaches_zero():
    mutation = AdaptiveMutation(PROBLEM, segment_length=1, reaction_factor=0.1)

    for _ in range(50):
        used(mutation, "shaw", Outcome.NO_SCORE)

    assert mutation.weights["destroy"]["shaw"] == pytest.approx(0.9**50)
    assert mutation.weights["destroy"]["shaw"] > 0


def test_weights_change_only_at_the_end_of_a_segment():
    mutation = AdaptiveMutation(PROBLEM, segment_length=3)

    used(mutation, "shaw", Outcome.NEW_BEST)
    used(mutation, "shaw", Outcome.NEW_BEST)

    assert mutation.weights["destroy"]["shaw"] == 1.0
    assert mutation.log == []


def test_roulette_picks_operators_in_proportion_to_their_weights():
    mutation = AdaptiveMutation(PROBLEM)
    mutation.weights["destroy"] = {"shaw": 6.0, "random": 3.0, "worst": 1.0}
    rng = random.Random(0)

    picks = [mutation._roulette("destroy", rng) for _ in range(20_000)]

    for name, share in {"shaw": 0.6, "random": 0.3, "worst": 0.1}.items():
        assert picks.count(name) / len(picks) == pytest.approx(share, abs=0.015)


def test_each_segment_logs_one_row_per_operator_and_the_csv_round_trips(tmp_path):
    mutation = AdaptiveMutation(PROBLEM, segment_length=2)
    for outcome in (Outcome.NEW_BEST, Outcome.NO_SCORE, Outcome.IMPROVED, Outcome.NO_SCORE):
        used(mutation, "shaw", outcome)
    used(mutation, "random", Outcome.NEW_BEST)  # an unfinished third segment

    # Two whole segments, four operators each (three destroy, one repair).
    assert [(row.segment, row.kind, row.operator) for row in mutation.log] == [
        (s, kind, name)
        for s in (1, 2)
        for kind, name in [
            ("destroy", "shaw"),
            ("destroy", "random"),
            ("destroy", "worst"),
            ("repair", "greedy"),
        ]
    ]
    path = tmp_path / "weights.csv"
    write_operator_log(mutation.log, path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 8
    assert rows[0]["operator"] == "shaw"
    assert math.isclose(float(rows[0]["weight"]), mutation.log[0].weight)


@pytest.mark.parametrize("seed", range(10))
def test_adaptive_mutation_stays_feasible_and_places_everyone_when_there_is_room(seed):
    rng = random.Random(seed)
    mutation = AdaptiveMutation(PROBLEM)
    individual = split(PROBLEM, rng.sample(range(12), 12))

    mutated = mutation(individual, rng)
    mutation.record(Outcome.NO_SCORE)

    assert mutated.unassigned == []
    assert_feasible(PROBLEM, mutated)


def test_benchmark_instances_match_the_fleet():
    for problem, crew, vans in ((smoke_30(), 30, 8), (morning_wave_120(), 120, 20)):
        assert len(problem.pickups) == crew
        assert len(problem.vehicles) == vans
        assert {v.capacity for v in problem.vehicles} == {14}
        assert all(7200 <= p.deadline <= 21600 for p in problem.pickups)
