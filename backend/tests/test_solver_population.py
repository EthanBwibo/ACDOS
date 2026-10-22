import math
import random

import pytest

from app.solver.individual import Individual
from app.solver.nearest_neighbour import nearest_neighbour
from app.solver.population import initial_population, structure_key
from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time
from tests.solver_checks import assert_feasible

DEPOT = Point(-1.30, 36.80)


def legs_problem(deadlines, vehicles):
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline)
        for i, deadline in enumerate(deadlines)
    )
    return Problem(pickups, tuple(vehicles), lambda origin, dest, depart_sec: 600.0)


def random_problem(seed):
    rng = random.Random(seed)
    pickups = tuple(
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(1800, 4 * 3600),
            service_sec=60,
        )
        for i in range(15)
    )
    vehicles = tuple(Vehicle(f"v{v}", 4, DEPOT) for v in range(5))
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=30))


# Structure key


def test_swapping_routes_between_identical_vehicles_gives_the_same_key():
    problem = legs_problem([math.inf] * 3, [Vehicle("v0", 14, DEPOT), Vehicle("v1", 14, DEPOT)])

    assert structure_key(problem, Individual([[0, 1], [2]])) == structure_key(
        problem, Individual([[2], [0, 1]])
    )


@pytest.mark.parametrize(
    "other",
    [
        Vehicle("v1", 14, DEPOT, available_from=300),  # leaves later
        Vehicle("v1", 4, DEPOT),  # smaller
        Vehicle("v1", 14, Point(-1.25, 36.85)),  # starts elsewhere
    ],
)
def test_swapping_routes_between_different_vehicles_gives_a_different_key(other):
    problem = legs_problem([math.inf] * 3, [Vehicle("v0", 14, DEPOT), other])

    assert structure_key(problem, Individual([[0, 1], [2]])) != structure_key(
        problem, Individual([[2], [0, 1]])
    )


def test_the_order_of_stops_matters_but_the_order_of_unassigned_does_not():
    problem = legs_problem([math.inf] * 4, [Vehicle("v0", 14, DEPOT)])

    key = structure_key(problem, Individual([[0, 1]], unassigned=[2, 3]))

    assert key == structure_key(problem, Individual([[0, 1]], unassigned=[3, 2]))
    assert key != structure_key(problem, Individual([[1, 0]], unassigned=[2, 3]))


# Initial population


@pytest.mark.parametrize("seed", range(5))
def test_gives_size_distinct_feasible_individuals_with_the_seed_first(seed):
    problem = random_problem(seed)
    baseline = nearest_neighbour(problem)

    population = initial_population(problem, 30, random.Random(seed), seeds=(baseline,))

    assert len(population) == 30
    assert population[0] == baseline
    assert len({structure_key(problem, individual) for individual in population}) == 30
    for individual in population:
        assert_feasible(problem, individual)


def test_a_tiny_instance_returns_fewer_without_hanging():
    # Two pickups, one vehicle, no deadlines: split() can only produce
    # [[0, 1]] or [[1, 0]].
    problem = legs_problem([math.inf, math.inf], [Vehicle("v0", 14, DEPOT)])

    population = initial_population(problem, 30, random.Random(0))

    assert sorted(individual.routes for individual in population) == [[[0, 1]], [[1, 0]]]


def test_a_duplicate_seed_is_skipped():
    problem = legs_problem([math.inf] * 3, [Vehicle("v0", 14, DEPOT), Vehicle("v1", 14, DEPOT)])
    seed = Individual([[0, 1], [2]])
    same_plan = Individual([[2], [0, 1]])

    population = initial_population(problem, 5, random.Random(0), seeds=(seed, same_plan))

    assert population[0] == seed
    assert same_plan not in population


def test_size_zero_gives_an_empty_population():
    problem = random_problem(0)

    assert (
        initial_population(problem, 0, random.Random(0), seeds=(nearest_neighbour(problem),)) == []
    )


def test_the_same_rng_seed_gives_the_same_population():
    problem = random_problem(3)

    first = initial_population(problem, 20, random.Random(11))
    second = initial_population(problem, 20, random.Random(11))

    assert first == second
