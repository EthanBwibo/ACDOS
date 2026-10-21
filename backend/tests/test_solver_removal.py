import math
import random
from collections import Counter

import pytest

from app.solver.fitness import (
    BUFFER_WEIGHT,
    LATE_CREW_WEIGHT,
    LATENESS_WEIGHT,
    UNASSIGNED_WEIGHT,
    fitness,
)
from app.solver.individual import Individual, split
from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time
from app.solver.removal import (
    _route_excess,
    random_removal,
    removal_count,
    take_out,
    unavoidable_costs,
    worst_removal,
)
from tests.solver_checks import assert_feasible

# Hard to beat: y^10000 is about 0 unless y is within 0.0002 of 1.
NEARLY_ALWAYS_WORST = 10_000


def legs_problem(deadlines, capacities, available_from=None):
    """Every leg takes 600 s, so a route with n pickups reaches JKIA at
    (n + 1) * 600 s after it leaves."""
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline)
        for i, deadline in enumerate(deadlines)
    )
    starts = available_from or [0.0] * len(capacities)
    vehicles = tuple(
        Vehicle(f"v{v}", capacity, Point(-1.30, 36.80), available_from=start)
        for v, (capacity, start) in enumerate(zip(capacities, starts, strict=True))
    )
    return Problem(pickups, vehicles, lambda origin, dest, depart_sec: 600.0)


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


PROBLEM = legs_problem([20000 + 600 * i for i in range(7)], capacities=[14, 14])
FLOOR = unavoidable_costs(PROBLEM)
OPERATORS = {
    "random": random_removal,
    "worst": lambda individual, q, rng: worst_removal(PROBLEM, individual, q, rng, FLOOR),
}


# What every destroy operator must do


@pytest.mark.parametrize("name", OPERATORS)
def test_removes_q_pickups_into_unassigned_and_keeps_the_rest_in_order(name):
    individual = Individual([[0, 1, 2], [3, 4, 5]], unassigned=[6])

    result, removed = OPERATORS[name](individual, 3, random.Random(0))

    assert len(set(removed)) == 3
    assert result.unassigned == [6, *removed]
    for before, after in zip(individual.routes, result.routes, strict=True):
        assert after == [i for i in before if i not in removed]
    assert_feasible(PROBLEM, result)


@pytest.mark.parametrize("name", OPERATORS)
def test_does_not_change_the_input(name):
    individual = Individual([[0, 1, 2], [3, 4, 5]], unassigned=[6])

    OPERATORS[name](individual, 3, random.Random(0))

    assert individual == Individual([[0, 1, 2], [3, 4, 5]], unassigned=[6])


@pytest.mark.parametrize("name", OPERATORS)
def test_q_zero_changes_nothing(name):
    individual = Individual([[0, 1], [2]], unassigned=[3, 4, 5, 6])

    result, removed = OPERATORS[name](individual, 0, random.Random(0))

    assert removed == []
    assert result == individual
    assert result is not individual


@pytest.mark.parametrize("name", OPERATORS)
def test_q_above_the_routed_count_removes_every_routed_pickup(name):
    individual = Individual([[0, 1], [2]], unassigned=[3, 4, 5, 6])

    result, removed = OPERATORS[name](individual, 10, random.Random(0))

    assert sorted(removed) == [0, 1, 2]
    assert result.routes == [[], []]
    assert_feasible(PROBLEM, result)


@pytest.mark.parametrize("name", OPERATORS)
def test_the_same_rng_seed_gives_the_same_removal(name):
    individual = Individual([[0, 1, 2, 3], [4, 5, 6]])

    first = OPERATORS[name](individual, 4, random.Random(7))
    second = OPERATORS[name](individual, 4, random.Random(7))

    assert first == second


def test_take_out_appends_to_unassigned_in_the_order_given():
    individual = Individual([[0, 1, 2], [3]], unassigned=[4])

    assert take_out(individual, [3, 1]) == Individual([[0, 2], []], unassigned=[4, 3, 1])


@pytest.mark.parametrize(
    ("n_routed", "low", "high"),
    [(0, 0, 0), (2, 2, 2), (4, 4, 4), (10, 4, 4), (20, 4, 8), (25, 4, 10)],
)
def test_removal_count_stays_between_4_and_40_percent(n_routed, low, high):
    rng = random.Random(0)

    counts = {removal_count(n_routed, rng) for _ in range(500)}

    assert min(counts) == low
    assert max(counts) == high


# Random removal


def test_random_removal_takes_each_routed_pickup_about_equally_often():
    individual = Individual([[0, 1, 2], [3, 4, 5]], unassigned=[6])
    rng = random.Random(0)

    counts = Counter(random_removal(individual, 1, rng)[1][0] for _ in range(2000))

    assert set(counts) == {0, 1, 2, 3, 4, 5}
    for count in counts.values():
        assert count == pytest.approx(2000 / 6, rel=0.2)


# Worst removal


def map_problem(points, deadlines, capacities):
    """Depot at (0, 0), JKIA at (0, 0.4), straight-line travel at 60 km/h.
    0.1 degree along the equator is 667 s."""
    pickups = tuple(
        Pickup(f"p{i}", Point(*p), d)
        for i, (p, d) in enumerate(zip(points, deadlines, strict=True))
    )
    vehicles = tuple(Vehicle(f"v{v}", c, Point(0.0, 0.0)) for v, c in enumerate(capacities))
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=60), Point(0.0, 0.4))


def test_worst_removal_takes_the_detour_that_makes_others_late():
    # p0 and p1 lie on the straight road to JKIA (0.1 and 0.2) and report at
    # 3600 s: on time going straight (about 2670 s). p2, off the road to the
    # north (0.3, 0), adds a detour that makes both about 2500 s late.
    # Removing p2 puts both back on time; removing p0 or p1 saves much less.
    problem = map_problem(
        [(0.0, 0.1), (0.0, 0.2), (0.3, 0.0)], [3600, 3600, math.inf], capacities=[14]
    )
    individual = Individual([[2, 0, 1]])
    assert set(assert_feasible(problem, individual)) == {"p0", "p1"}

    result, removed = worst_removal(
        problem, individual, 1, random.Random(0), unavoidable_costs(problem), NEARLY_ALWAYS_WORST
    )

    assert removed == [2]
    assert assert_feasible(problem, result) == {}


def test_worst_removal_re_costs_the_route_after_each_removal():
    # v0 = [p0, p1, p2]: JKIA at 2400, p0 (reports 1800) 600 s late. Removing
    # any one of them puts p0 on time; p0 saves the most (its own buffer too)
    # and goes first. Then p1 and p2 save only 600 s of driving each, less
    # than v1's lone p3 (a whole vehicle: 3600 + 1200). Without re-costing,
    # p1 would still look worth 24,000,600 and go second.
    problem = legs_problem([1800, math.inf, math.inf, math.inf], capacities=[14, 14])
    individual = Individual([[0, 1, 2], [3]])

    _, removed = worst_removal(
        problem, individual, 2, random.Random(0), unavoidable_costs(problem), NEARLY_ALWAYS_WORST
    )

    assert removed == [0, 3]


def test_the_floor_stops_worst_removal_from_always_taking_the_lost_cause():
    # v0 = [p0 lost cause (reports at 0), p1]: p0 is 1800 s late, 1200 s of
    # which it would be even alone. v1 = [p2 (reports 1200), p3]: p2 is 600 s
    # late only because it shares. Saving from removing p0 is about 3.6e7,
    # from p2 or p3 about 2.4e7, so plain R&P takes p0. Beyond its floor
    # (3.009e7), p0 saves only about 6e6, so with the floor v1's pair goes.
    problem = legs_problem([0, math.inf, 1200, math.inf], capacities=[14, 14])
    individual = Individual([[0, 1], [2, 3]])
    floor = unavoidable_costs(problem)

    _, with_floor = worst_removal(
        problem, individual, 1, random.Random(0), floor, NEARLY_ALWAYS_WORST
    )
    _, plain = worst_removal(
        problem, individual, 1, random.Random(0), [0.0] * 4, NEARLY_ALWAYS_WORST
    )

    assert with_floor[0] in (2, 3)
    assert plain == [0]


def test_unavoidable_cost_is_what_a_pickup_costs_even_alone():
    # Alone, every pickup reaches JKIA at 1200 s on v0 and 1500 s on v1
    # (available from 300); the smaller, v0, counts.
    # p0 reports at 20000: on time, outside its buffer. p1 reports at 1500:
    # ideal 600, so 600 s of buffer used. p2 reports at 0: 1200 s late, late
    # crew, whole buffer gone.
    problem = legs_problem([20000, 1500, 0], capacities=[14, 14], available_from=[0, 300])

    floor = unavoidable_costs(problem)

    assert floor == [
        0,
        BUFFER_WEIGHT * 600,
        LATENESS_WEIGHT * 1200 + LATE_CREW_WEIGHT + BUFFER_WEIGHT * 900,
    ]


@pytest.mark.parametrize("seed", range(10))
def test_saving_matches_a_full_re_evaluation(seed):
    rng = random.Random(seed)
    problem = random_problem(rng)
    individual = split(problem, rng.sample(range(12), 12))
    before = fitness(problem, individual)

    for v, route in enumerate(individual.routes):
        savings = _route_excess(problem, v, route, [0.0] * 12, {})
        for i in route:
            after = fitness(problem, take_out(individual, [i]))

            # Costs are around 1e10, so allow for float rounding at that scale.
            assert after - before == pytest.approx(UNASSIGNED_WEIGHT - savings[i], abs=1e-3)


@pytest.mark.parametrize("seed", range(10))
def test_worst_removal_stays_feasible_on_random_instances(seed):
    rng = random.Random(seed)
    problem = random_problem(rng)
    individual = split(problem, rng.sample(range(12), 12))
    routed = sum(len(route) for route in individual.routes)

    result, removed = worst_removal(
        problem, individual, removal_count(routed, rng), rng, unavoidable_costs(problem)
    )

    assert len(removed) == len(set(removed))
    assert_feasible(problem, result)
