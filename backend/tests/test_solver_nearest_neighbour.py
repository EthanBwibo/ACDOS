import math
import random

import pytest

from app.solver.nearest_neighbour import nearest_neighbour
from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time
from tests.solver_checks import assert_feasible


def legs_problem(deadlines, capacities):
    """Every leg takes 600 s, so a route with n pickups reaches JKIA at
    (n + 1) * 600 s, and every pickup is equally near: ties go to the index."""
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline)
        for i, deadline in enumerate(deadlines)
    )
    vehicles = tuple(
        Vehicle(f"v{v}", capacity, Point(-1.30, 36.80)) for v, capacity in enumerate(capacities)
    )
    return Problem(pickups, vehicles, lambda origin, dest, depart_sec: 600.0)


def test_starts_with_the_most_urgent_pickup_then_goes_to_the_nearest():
    # Depot at 0, JKIA at 0.4 along the equator. p2 at 0.3 reports first, so
    # it seeds the route; from there p1 (0.25) is nearer than p0 (0.1).
    # Nearest-first from the depot alone would go p0, p1, p2.
    pickups = (
        Pickup("p0", Point(0.0, 0.1), deadline=12000),
        Pickup("p1", Point(0.0, 0.25), deadline=11000),
        Pickup("p2", Point(0.0, 0.3), deadline=10000),
    )
    vehicles = (Vehicle("v0", 14, Point(0.0, 0.0)),)
    problem = Problem(pickups, vehicles, haversine_travel_time(speed_kmh=60), Point(0.0, 0.4))

    individual = nearest_neighbour(problem)

    assert individual.routes == [[2, 1, 0]]
    assert assert_feasible(problem, individual) == {}


def test_skips_a_pickup_that_would_make_someone_on_board_late():
    # p0 alone reaches JKIA at 1200, exactly its report time; adding p1 would
    # make it 1800, so p1 goes to the next vehicle.
    problem = legs_problem([1200, math.inf], capacities=[14, 14])

    individual = nearest_neighbour(problem)

    assert individual.routes == [[0], [1]]
    assert assert_feasible(problem, individual) == {}


def test_a_lost_cause_joins_an_open_route_without_making_anyone_late():
    # p0 (reports at 0) is a lost cause. p1 (1200) seeds v0 and p2 cannot
    # join it on time, so p2 opens v1. p0 then joins v1, where nobody else
    # becomes late, rather than v0 (p1 would be late) or the unused v2.
    problem = legs_problem([0, 1200, math.inf], capacities=[14, 14, 14])

    individual = nearest_neighbour(problem)

    assert individual.routes == [[1], [2, 0], []]
    assert assert_feasible(problem, individual) == {"p0": 1800}


def test_lost_causes_open_a_vehicle_only_when_no_open_route_exists():
    problem = legs_problem([0, 0], capacities=[14, 14])

    individual = nearest_neighbour(problem)

    assert individual.routes == [[0, 1], []]
    assert assert_feasible(problem, individual) == {"p0": 1800, "p1": 1800}


def test_pickups_the_fleet_cannot_take_go_to_unassigned_in_report_time_order():
    problem = legs_problem([math.inf, 3000, 2000], capacities=[1])

    individual = nearest_neighbour(problem)

    assert individual.routes == [[2]]
    assert individual.unassigned == [1, 0]
    assert_feasible(problem, individual)


def test_nothing_to_route_gives_empty_routes():
    problem = legs_problem([], capacities=[14, 14])

    individual = nearest_neighbour(problem)

    assert individual.routes == [[], []]
    assert individual.unassigned == []


def random_problem(rng):
    pickups = tuple(
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(1800, 4 * 3600),
            service_sec=60,
        )
        for i in range(15)
    )
    vehicles = tuple(
        Vehicle(f"v{v}", 4, Point(-1.30, 36.80), available_from=rng.uniform(0, 1800))
        for v in range(5)
    )
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=30))


@pytest.mark.parametrize("seed", range(20))
def test_is_feasible_and_deterministic_on_random_instances(seed):
    problem = random_problem(random.Random(seed))

    first = nearest_neighbour(problem)

    assert first == nearest_neighbour(problem)
    assert_feasible(problem, first)
