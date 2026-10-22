import math
import random

import pytest

from app.solver.fitness import UNASSIGNED_WEIGHT, fitness
from app.solver.individual import Individual, split
from app.solver.insertion import (
    _best_position,
    _positions_worth_costing,
    greedy_insertion,
    insertion_cost,
)
from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time
from app.solver.removal import removal_count
from app.solver.shaw import relatedness_matrix, shaw_removal
from tests.solver_checks import assert_feasible


def legs_problem(deadlines, capacities):
    """Every leg takes 600 s, as in the fitness tests."""
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline)
        for i, deadline in enumerate(deadlines)
    )
    vehicles = tuple(
        Vehicle(f"v{v}", capacity, Point(-1.30, 36.80)) for v, capacity in enumerate(capacities)
    )
    return Problem(pickups, vehicles, lambda origin, dest, depart_sec: 600.0)


def map_problem(points, capacities):
    """Pickups at these (lat, lon) points, depot at (0, 0), destination at
    (0, 0.4), straight-line travel at 60 km/h, no deadlines. Along the equator
    straight-line distances add up, so a pickup between two others on the
    line costs nothing extra to collect on the way."""
    pickups = tuple(Pickup(f"p{i}", Point(*p), math.inf) for i, p in enumerate(points))
    vehicles = tuple(Vehicle(f"v{v}", c, Point(0.0, 0.0)) for v, c in enumerate(capacities))
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=60), Point(0.0, 0.4))


# On the equator, 0.1 degree of longitude is 11.12 km: 667 s at 60 km/h.
TENTH_DEGREE_SEC = 0.1 * math.pi / 180 * 6371.0 / 60 * 3600


def test_takes_the_cheapest_position_checked_by_hand():
    # p0 and p2 at 0.1 and 0.3 on the way to the destination at 0.4. p1 at
    # 0.2 is on the way between them: free at position 1. At position 0 or 2
    # the vehicle doubles back 0.1 twice: 1334 s. An empty vehicle would
    # cost 3600 for itself plus 0.4 of driving.
    problem = map_problem([(0.0, 0.1), (0.0, 0.2), (0.0, 0.3)], capacities=[14, 14])
    individual = Individual([[0, 2], []], unassigned=[1])

    costs = [insertion_cost(problem, individual.routes, 0, 1, k) for k in range(3)]
    result = greedy_insertion(problem, individual)

    assert costs == pytest.approx([2 * TENTH_DEGREE_SEC, 0, 2 * TENTH_DEGREE_SEC], abs=1e-6)
    assert result.routes == [[0, 1, 2], []]
    assert assert_feasible(problem, result) == {}


def test_a_removed_pickup_goes_back_to_its_uniquely_cheapest_position():
    # v0 collects p0, p1, p2 in a line on the way; v1 collects p3, north of
    # the depot and off the line. p1 is free only at its old position.
    problem = map_problem([(0.0, 0.1), (0.0, 0.2), (0.0, 0.3), (0.3, 0.0)], capacities=[14, 14])
    original = Individual([[0, 1, 2], [3]])
    removed = Individual([[0, 2], [3]], unassigned=[1])

    assert greedy_insertion(problem, removed) == original


def test_crew_reporting_30_minutes_apart_join_the_open_route():
    problem = legs_problem([20000, 21800], capacities=[14, 14])

    result = greedy_insertion(problem, Individual([[0], []], unassigned=[1]))

    assert sorted(result.routes[0]) == [0, 1]
    assert result.routes[1] == []
    assert_feasible(problem, result)


def test_crew_reporting_90_minutes_apart_get_their_own_vehicle():
    problem = legs_problem([20000, 25400], capacities=[14, 14])

    result = greedy_insertion(problem, Individual([[0], []], unassigned=[1]))

    assert result.routes == [[0], [1]]
    assert_feasible(problem, result)


def test_a_lost_cause_is_not_put_where_it_makes_an_on_time_crew_member_late():
    # #12's instance. On v1 the lost cause p4 would make p3 600 s late; the
    # late-crew count (#75) makes v0 cheaper. Every position on v0 costs the
    # same (all legs equal), so it takes the first.
    problem = legs_problem([math.inf, math.inf, math.inf, 1200, 0], capacities=[14, 14])

    result = greedy_insertion(problem, Individual([[0, 1, 2], [3]], unassigned=[4]))

    assert result.routes == [[4, 0, 1, 2], [3]]
    assert assert_feasible(problem, result) == {"p4": 3000}


def test_pickups_that_do_not_fit_stay_unassigned_in_their_order():
    # Room for two; all cost the same, so the lowest pickup indices go in.
    problem = legs_problem([math.inf] * 4, capacities=[2])

    result = greedy_insertion(problem, Individual([[]], unassigned=[3, 0, 2, 1]))

    assert sorted(result.routes[0]) == [0, 1]
    assert result.unassigned == [3, 2]
    assert_feasible(problem, result)


def test_does_not_change_the_input_and_is_deterministic():
    problem = legs_problem([20000, 21800, 25400], capacities=[14, 14])
    individual = Individual([[0], []], unassigned=[2, 1])

    first = greedy_insertion(problem, individual)
    second = greedy_insertion(problem, individual)

    assert individual == Individual([[0], []], unassigned=[2, 1])
    assert first == second


def test_nothing_to_insert_returns_an_equal_copy():
    problem = legs_problem([20000], capacities=[14])
    individual = Individual([[0]])

    result = greedy_insertion(problem, individual)

    assert result == individual
    assert result is not individual


def random_problem(rng, n_pickups=12, n_vehicles=4, capacity=4):
    pickups = tuple(
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(1800, 4 * 3600),
            service_sec=60,
        )
        for i in range(n_pickups)
    )
    vehicles = tuple(
        Vehicle(f"v{v}", capacity, Point(-1.30, 36.80), available_from=rng.uniform(0, 1800))
        for v in range(n_vehicles)
    )
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=30))


@pytest.mark.parametrize("seed", range(10))
def test_insertion_cost_matches_a_full_re_evaluation(seed):
    rng = random.Random(seed)
    problem = random_problem(rng)
    tour = rng.sample(range(12), 12)
    i = tour.pop()
    individual = split(problem, tour)
    individual.unassigned.append(i)
    before = fitness(problem, individual)

    for v, route in enumerate(individual.routes):
        for k in range(len(route) + 1):
            cost = insertion_cost(problem, individual.routes, v, i, k)
            if cost is None:
                continue
            routes = [r.copy() for r in individual.routes]
            routes[v].insert(k, i)
            unassigned = [j for j in individual.unassigned if j != i]
            after = fitness(problem, Individual(routes, unassigned))

            # Costs are around 1e10, so allow for float rounding at that scale.
            assert after - before == pytest.approx(cost - UNASSIGNED_WEIGHT, abs=1e-3)


@pytest.mark.parametrize("seed", range(20))
def test_shaw_then_greedy_stays_feasible_and_places_everyone_when_there_is_room(seed):
    # 12 crew, 4 vehicles of 4 seats: room for everyone.
    rng = random.Random(seed)
    problem = random_problem(rng)
    individual = split(problem, rng.sample(range(12), 12))
    routed = sum(len(route) for route in individual.routes)

    destroyed, _ = shaw_removal(
        individual, relatedness_matrix(problem), removal_count(routed, rng), rng
    )
    repaired = greedy_insertion(problem, destroyed)

    assert repaired.unassigned == []
    assert_feasible(problem, repaired)


# Positions worth costing (#88)


def test_only_the_smallest_detours_are_fully_costed(monkeypatch):
    # On the road to JKIA (0.4): p0 at 0.1, p2 at 0.3. p1 at 0.2 is on the way
    # between them (no detour); before p0 or after p2 it doubles back.
    monkeypatch.setattr("app.solver.insertion.FULLY_COSTED_POSITIONS", 1)
    problem = map_problem([(0.0, 0.1), (0.0, 0.2), (0.0, 0.3)], capacities=[14])

    assert _positions_worth_costing(problem, [0, 2], 0, 1) == [1]


def test_ties_in_detour_go_to_the_lowest_positions(monkeypatch):
    # Every leg 600 s: every position adds the same detour.
    monkeypatch.setattr("app.solver.insertion.FULLY_COSTED_POSITIONS", 2)
    problem = map_problem([(0.0, 0.1 * k) for k in range(1, 6)], capacities=[14])
    object.__setattr__(problem, "travel_time", lambda o, d, t: 600.0)
    object.__setattr__(problem, "legs", problem._leg_table())

    assert _positions_worth_costing(problem, [0, 1, 2, 3], 0, 4) == [0, 1]


def test_short_routes_cost_every_position(monkeypatch):
    monkeypatch.setattr("app.solver.insertion.FULLY_COSTED_POSITIONS", 2)
    problem = map_problem([(0.0, 0.1), (0.0, 0.2)], capacities=[14])

    assert _positions_worth_costing(problem, [0], 0, 1) == [0, 1]


def test_travel_time_that_depends_on_departure_costs_every_position(monkeypatch):
    monkeypatch.setattr("app.solver.insertion.FULLY_COSTED_POSITIONS", 1)
    problem = legs_problem([20000] * 5, capacities=[14])  # a lambda: no leg table

    assert problem.legs is None
    assert _positions_worth_costing(problem, [0, 1, 2, 3], 0, 4) == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("seed", range(10))
def test_the_shortlist_never_beats_costing_every_position(seed, monkeypatch):
    # The cheapest among the shortlisted positions can only be the overall
    # cheapest or dearer; with a long enough shortlist they are the same.
    rng = random.Random(seed)
    problem = random_problem(rng, n_pickups=12, n_vehicles=2, capacity=14)
    routes = [rng.sample(range(11), 9), []]
    i = next(p for p in range(12) if p not in routes[0])

    monkeypatch.setattr("app.solver.insertion.FULLY_COSTED_POSITIONS", 1)
    shortlist = _best_position(problem, routes, 0, i, {})
    monkeypatch.setattr("app.solver.insertion.FULLY_COSTED_POSITIONS", 100)
    every = _best_position(problem, routes, 0, i, {})

    assert shortlist[0] >= every[0]
