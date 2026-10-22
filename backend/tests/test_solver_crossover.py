import random

import pytest

from app.solver.crossover import order_crossover, ox1
from app.solver.individual import Individual, split
from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time
from tests.solver_checks import assert_feasible


def random_problem(seed, n_pickups=12):
    rng = random.Random(seed)
    pickups = tuple(
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(1800, 4 * 3600),
            service_sec=60,
        )
        for i in range(n_pickups)
    )
    vehicles = tuple(Vehicle(f"v{v}", 4, Point(-1.30, 36.80)) for v in range(4))
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=30))


def test_ox1_checked_by_hand():
    # Slice [2, 4) of A is [2, 3], kept in place. Reading B from position 4
    # and wrapping: 4, 2, 5, 3, 1, 0; without 2 and 3 that is 4, 5, 1, 0,
    # which fills positions 4, 5, 0, 1.
    a = [0, 1, 2, 3, 4, 5]
    b = [5, 3, 1, 0, 4, 2]

    assert ox1(a, b, 2, 4) == [1, 0, 2, 3, 4, 5]


def test_ox1_with_the_whole_tour_as_slice_gives_parent_a():
    assert ox1([3, 1, 2, 0], [0, 1, 2, 3], 0, 4) == [3, 1, 2, 0]


@pytest.mark.parametrize("seed", range(50))
def test_ox1_keeps_a_slice_in_place_and_the_rest_in_b_order(seed):
    rng = random.Random(seed)
    a = rng.sample(range(10), 10)
    b = rng.sample(range(10), 10)
    start, end = sorted(rng.sample(range(11), 2))

    child = ox1(a, b, start, end)

    assert sorted(child) == list(range(10))
    assert child[start:end] == a[start:end]
    rest = child[end:] + child[:start]
    assert rest == [i for i in b[end:] + b[:end] if i not in a[start:end]]


@pytest.mark.parametrize("seed", range(10))
def test_child_is_feasible_and_the_parents_are_unchanged(seed):
    problem = random_problem(seed)
    rng = random.Random(seed)
    parent_a = split(problem, rng.sample(range(12), 12))
    parent_b = split(problem, rng.sample(range(12), 12))
    a_before, b_before = parent_a.copy(), parent_b.copy()

    child = order_crossover(problem, parent_a, parent_b, rng)

    assert_feasible(problem, child)
    assert parent_a == a_before
    assert parent_b == b_before


def test_identical_parents_give_the_parent_back_after_split():
    problem = random_problem(1)
    parent = split(problem, random.Random(1).sample(range(12), 12))

    child = order_crossover(problem, parent, parent, random.Random(0))

    assert child == split(problem, parent.giant_tour())


def test_the_same_rng_seed_gives_the_same_child():
    problem = random_problem(2)
    rng = random.Random(2)
    parent_a = split(problem, rng.sample(range(12), 12))
    parent_b = split(problem, rng.sample(range(12), 12))

    first = order_crossover(problem, parent_a, parent_b, random.Random(9))
    second = order_crossover(problem, parent_a, parent_b, random.Random(9))

    assert first == second


def test_fewer_than_two_pickups_has_nothing_to_cross():
    problem = random_problem(3, n_pickups=1)
    parent = Individual([[0], [], [], []])

    assert order_crossover(problem, parent, parent, random.Random(0)) == parent
