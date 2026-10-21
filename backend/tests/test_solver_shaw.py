import math
import random

import pytest

from app.solver.individual import Individual
from app.solver.problem import Pickup, Point, Problem, Vehicle
from app.solver.shaw import (
    SHAW_DEMAND_WEIGHT,
    SHAW_DISTANCE_WEIGHT,
    SHAW_TIME_WEIGHT,
    relatedness_matrix,
    removal_count,
    shaw_removal,
)
from tests.solver_checks import assert_feasible

DEPOT = Point(-1.30, 36.80)
# Hard to beat: y^10000 is about 0 unless y is within 0.0002 of 1.
NEARLY_ALWAYS_MOST_RELATED = 10_000


def make_problem(pickups, capacities):
    vehicles = tuple(Vehicle(f"v{v}", capacity, DEPOT) for v, capacity in enumerate(capacities))
    return Problem(tuple(pickups), vehicles, lambda origin, dest, depart_sec: 600.0)


def line_problem(n, capacities):
    """n pickups 1 km-ish apart on a line, all reporting at 10000 s."""
    pickups = [Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), 10000) for i in range(n)]
    return make_problem(pickups, capacities)


def by_index_gap(n):
    """Hand-built relatedness: pickups with nearby indices are related."""
    return [[abs(i - j) for j in range(n)] for i in range(n)]


# Relatedness matrix


def test_relatedness_weights_each_normalised_term():
    # On the equator, distance is proportional to longitude: p0-p1 is 1 unit,
    # p1-p2 2 units, p0-p2 3 units, so normalised 1/3, 2/3 and 1.
    # Report gaps 0, 3000, 3000 -> 0, 1, 1. Demand gaps 1, 1, 0 -> 1, 1, 0.
    pickups = [
        Pickup("p0", Point(0.0, 0.0), deadline=1000, demand=1),
        Pickup("p1", Point(0.0, 0.1), deadline=1000, demand=2),
        Pickup("p2", Point(0.0, 0.3), deadline=4000, demand=1),
    ]
    r = relatedness_matrix(make_problem(pickups, capacities=[14]))

    phi, chi, psi = SHAW_DISTANCE_WEIGHT, SHAW_TIME_WEIGHT, SHAW_DEMAND_WEIGHT
    assert r[0][1] == pytest.approx(phi / 3 + psi)  # 5 with R&P's 9/3/2
    assert r[1][2] == pytest.approx(phi * 2 / 3 + chi + psi)  # 11
    assert r[0][2] == pytest.approx(phi + chi)  # 12


def test_relatedness_is_symmetric_zero_on_the_diagonal_and_bounded():
    rng = random.Random(1)
    pickups = [
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(0, 8 * 3600),
            demand=rng.randint(1, 3),
        )
        for i in range(10)
    ]
    r = relatedness_matrix(make_problem(pickups, capacities=[14]))

    bound = SHAW_DISTANCE_WEIGHT + SHAW_TIME_WEIGHT + SHAW_DEMAND_WEIGHT
    for i in range(10):
        assert r[i][i] == 0
        for j in range(10):
            assert r[i][j] == r[j][i]
            assert 0 <= r[i][j] <= bound + 1e-9


def test_pickups_with_no_report_time_are_alike_and_unlike_the_rest():
    # Same place, same demand: only report time separates them.
    pickups = [
        Pickup("p0", Point(-1.28, 36.81), deadline=math.inf),
        Pickup("p1", Point(-1.28, 36.81), deadline=math.inf),
        Pickup("p2", Point(-1.28, 36.81), deadline=1000),
    ]
    r = relatedness_matrix(make_problem(pickups, capacities=[14]))

    assert r[0][1] == 0
    assert r[0][2] == r[1][2] == SHAW_TIME_WEIGHT


# Removal


def test_removes_q_pickups_into_unassigned_and_keeps_the_rest_in_order():
    problem = line_problem(6, capacities=[14, 14])
    individual = Individual([[0, 1, 2], [3, 4]], unassigned=[5])

    result, removed = shaw_removal(individual, by_index_gap(6), 2, random.Random(0))

    assert len(removed) == 2
    assert result.unassigned == [5, *removed]
    for before, after in zip(individual.routes, result.routes, strict=True):
        assert after == [i for i in before if i not in removed]
    assert_feasible(problem, result)


def test_does_not_change_the_input():
    individual = Individual([[0, 1, 2], [3, 4]], unassigned=[5])

    shaw_removal(individual, by_index_gap(6), 3, random.Random(0))

    assert individual.routes == [[0, 1, 2], [3, 4]]
    assert individual.unassigned == [5]


def test_q_zero_changes_nothing():
    individual = Individual([[0, 1], [2]])

    result, removed = shaw_removal(individual, by_index_gap(3), 0, random.Random(0))

    assert removed == []
    assert result == individual
    assert result is not individual


def test_q_above_the_routed_count_removes_every_routed_pickup():
    problem = line_problem(4, capacities=[14, 14])
    individual = Individual([[0, 1], [2]], unassigned=[3])

    result, removed = shaw_removal(individual, by_index_gap(4), 10, random.Random(0))

    assert sorted(removed) == [0, 1, 2]
    assert result.routes == [[], []]
    assert_feasible(problem, result)


def test_nothing_routed_means_nothing_removed():
    individual = Individual([[], []], unassigned=[0, 1])

    result, removed = shaw_removal(individual, by_index_gap(2), 2, random.Random(0))

    assert removed == []
    assert result == individual


def test_a_route_may_be_emptied():
    # p1 and p2 are closely related, p0 is equally far from both. Seeded on p1
    # or p2, it takes the pair and empties v1; seeded on p0, it takes p1 (the
    # lower index on a tie) and empties v0. Either way a route ends up empty.
    problem = line_problem(3, capacities=[14, 14])
    individual = Individual([[0], [1, 2]])
    relatedness = [[0, 9, 9], [9, 0, 1], [9, 1, 0]]

    for seed in range(10):
        result, _ = shaw_removal(
            individual, relatedness, 2, random.Random(seed), NEARLY_ALWAYS_MOST_RELATED
        )

        assert [] in result.routes
        assert_feasible(problem, result)


@pytest.mark.parametrize("seed", range(50))
def test_removes_one_whole_cluster_when_it_nearly_always_takes_the_most_related(seed):
    # Cluster A: p0-p2 in one area, reporting about 06:00. Cluster B: p3-p5,
    # about 12 km away, reporting about 09:00. Routes mix the two.
    a = [Pickup(f"p{i}", Point(-1.26 + i / 1000, 36.80), deadline=21600 + 60 * i) for i in range(3)]
    b = [
        Pickup(f"p{3 + i}", Point(-1.33 + i / 1000, 36.90), deadline=32400 + 60 * i)
        for i in range(3)
    ]
    problem = make_problem(a + b, capacities=[14, 14])
    individual = Individual([[0, 3, 1], [4, 2, 5]])

    result, removed = shaw_removal(
        individual, relatedness_matrix(problem), 3, random.Random(seed), NEARLY_ALWAYS_MOST_RELATED
    )

    assert sorted(removed) in ([0, 1, 2], [3, 4, 5])
    assert_feasible(problem, result)


def test_the_same_rng_seed_gives_the_same_removal():
    individual = Individual([[0, 1, 2, 3], [4, 5, 6, 7]])
    relatedness = by_index_gap(8)

    first = shaw_removal(individual, relatedness, 4, random.Random(7))
    second = shaw_removal(individual, relatedness, 4, random.Random(7))

    assert first == second


# Removal count


@pytest.mark.parametrize(
    ("n_routed", "low", "high"),
    [(0, 0, 0), (2, 2, 2), (4, 4, 4), (10, 4, 4), (20, 4, 8), (25, 4, 10)],
)
def test_removal_count_stays_between_4_and_40_percent(n_routed, low, high):
    rng = random.Random(0)

    counts = {removal_count(n_routed, rng) for _ in range(500)}

    assert min(counts) == low
    assert max(counts) == high
