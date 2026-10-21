import math

from app.solver.fitness import (
    BUFFER_WEIGHT,
    LATE_CREW_WEIGHT,
    LATENESS_WEIGHT,
    TIME_WEIGHT,
    UNASSIGNED_WEIGHT,
    VEHICLE_WEIGHT,
    Evaluation,
    evaluate,
    fitness,
    route_evaluation,
)
from app.solver.individual import DEPARTURE_TOLERANCE_SEC, Individual
from app.solver.problem import Pickup, Point, Problem, Vehicle
from tests.solver_checks import assert_feasible

DEPOT = Point(-1.30, 36.80)

# Every leg takes 600 s, so a route with n pickups takes (n + 1) * 600 s, and
# the report buffer is 900 s.


def make_problem(deadlines, capacities):
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline)
        for i, deadline in enumerate(deadlines)
    )
    vehicles = tuple(Vehicle(f"v{v}", capacity, DEPOT) for v, capacity in enumerate(capacities))
    return Problem(pickups, vehicles, lambda origin, dest, depart_sec: 600.0)


def cost(problem, routes, unassigned=()):
    individual = Individual(routes, list(unassigned))
    assert_feasible(problem, individual)
    return fitness(problem, individual)


def test_evaluation_breaks_the_cost_into_its_terms():
    # Every start is pinned to available_from (target out of reach), so the
    # numbers are exact.
    # v0 [p0, p1]: JKIA at 1800. p0 reports 2600, so 100 s into its buffer
    # (ideal 1700); p1 reports 4000, ideal 3100, so it waits 1300 s.
    # v1 [p2]: JKIA at 1200, p2 reports 1000: 200 s late, whole buffer gone.
    # p3 is unassigned.
    problem = make_problem([2600, 4000, 1000, 10000], capacities=[14, 14])
    individual = Individual([[0, 1], [2]], unassigned=[3])

    evaluation = evaluate(problem, individual)

    assert evaluation == Evaluation(
        unassigned=1,
        lateness_sec=200,
        late_crew=1,
        buffer_used_sec=100 + 900,
        vehicles_used=2,
        travel_sec=1800 + 1200,
        waiting_sec=1300,
    )
    assert evaluation.cost == (
        UNASSIGNED_WEIGHT * 1
        + LATENESS_WEIGHT * 200
        + LATE_CREW_WEIGHT * 1
        + BUFFER_WEIGHT * 1000
        + VEHICLE_WEIGHT * 2
        + TIME_WEIGHT * (3000 + 1300)
    )
    assert assert_feasible(problem, individual) == {"p2": 200}


def test_waiting_counts_only_time_beyond_the_buffer():
    # Alone and leaving as late as it can, p0 arrives at about report time
    # minus the buffer: no buffer used, waiting only the search tolerance.
    problem = make_problem([20000], capacities=[14])

    evaluation = evaluate(problem, Individual([[0]]))

    assert evaluation.buffer_used_sec == 0
    assert 0 <= evaluation.waiting_sec < DEPARTURE_TOLERANCE_SEC
    assert evaluation.travel_sec == 1200


def test_evaluate_is_unassigned_plus_the_sum_of_route_evaluations():
    problem = make_problem([2600, 4000, 1000, 10000, 1200], capacities=[14, 14, 14])
    individual = Individual([[0, 1], [2], [4]], unassigned=[3])

    routes = [route_evaluation(problem, v, r) for v, r in enumerate(individual.routes)]

    assert evaluate(problem, individual).cost == (
        UNASSIGNED_WEIGHT * 1 + sum(route.cost for route in routes)
    )


def test_an_unused_vehicle_costs_nothing():
    problem = make_problem([1000], capacities=[14, 14])

    assert route_evaluation(problem, 1, []).cost == 0


def test_an_empty_problem_costs_nothing():
    problem = make_problem([], capacities=[14])

    assert fitness(problem, Individual([[]])) == 0


# Tiers: each test compares two solutions to the same problem.


def test_an_unassigned_pickup_costs_more_than_a_lot_of_lateness():
    # Sharing the one vehicle makes both 600 s late; leaving p1 unassigned
    # keeps p0 on time.
    problem = make_problem([1200, 1200], capacities=[14])

    shared = cost(problem, [[0, 1]])
    one_left_behind = cost(problem, [[0]], unassigned=[1])

    assert shared < one_left_behind


def test_a_minute_late_costs_more_than_an_extra_vehicle():
    # Together JKIA is at 1800 s, 60 s past p0's 1740 report time. p1 reports
    # at 2700 (ideal 1800), so it neither waits nor eats its buffer either way.
    problem = make_problem([1740, 2700], capacities=[14, 14])

    shared = cost(problem, [[0, 1], []])
    separate = cost(problem, [[0], [1]])

    assert separate < shared


def test_arriving_ten_minutes_into_the_buffer_costs_more_than_an_extra_vehicle():
    # p0 reports at 2100, ideal arrival 1200. Together JKIA is at 1800,
    # 600 s into its buffer; alone p0 arrives at 1200. p1 reports at 2700
    # (ideal 1800), so only the buffer term separates the two: without it,
    # sharing would win on vehicles and driving time.
    problem = make_problem([2100, 2700], capacities=[14, 14])

    shared = cost(problem, [[0, 1], []])
    separate = cost(problem, [[0], [1]])

    assert separate < shared


def test_a_minute_late_costs_more_than_losing_the_whole_buffer():
    # Compared term by term: a crew member who is late has lost the buffer
    # too, so this is the weight ratio a swap between two crew members tests.
    # late_crew is left at 0 to compare the two per-second weights alone.
    terms = {
        "unassigned": 0,
        "late_crew": 0,
        "vehicles_used": 1,
        "travel_sec": 1200,
        "waiting_sec": 0,
    }
    late = Evaluation(lateness_sec=60, buffer_used_sec=0, **terms)
    whole_buffer_gone = Evaluation(lateness_sec=0, buffer_used_sec=900, **terms)

    assert late.cost > whole_buffer_gone.cost


def test_crew_reporting_30_minutes_apart_share_a_vehicle():
    # Shared: one vehicle, 1800 s of driving, p1 waits about 1800 s.
    # Separate: two vehicles, 2400 s of driving, nobody waits.
    problem = make_problem([20000, 21800], capacities=[14, 14])

    shared = cost(problem, [[0, 1], []])
    separate = cost(problem, [[0], [1]])

    assert shared < separate


def test_crew_reporting_90_minutes_apart_get_a_vehicle_each():
    # Shared, p1 waits about 5400 s: more than the vehicle saves.
    problem = make_problem([20000, 25400], capacities=[14, 14])

    shared = cost(problem, [[0, 1], []])
    separate = cost(problem, [[0], [1]])

    assert separate < shared


def test_making_an_on_time_crew_member_late_costs_more_than_the_same_seconds_on_someone_late():
    # Lost cause p3 (deadline 0) joins v0 or v1. On v0, behind p0 and p1 (no
    # report time), it is 2400 s late. On v1, behind p2 (reports 1200), it is
    # 1800 s late and makes p2 600 s late: the same 2400 s in total, the same
    # buffer and driving, but two late crew instead of one.
    problem = make_problem([math.inf, math.inf, 1200, 0], capacities=[14, 14])

    behind_crew_without_a_deadline = cost(problem, [[0, 1, 3], [2]])
    making_p2_late = cost(problem, [[0, 1], [2, 3]])

    assert making_p2_late - behind_crew_without_a_deadline == LATE_CREW_WEIGHT


def test_a_lost_cause_placement_that_keeps_others_on_time_now_costs_less():
    # #12's instance: on v0 the lost cause p4 is 3000 s late; on v1 it is
    # 1800 s late but makes p3 600 s late. Without K_late, v1 was cheaper by
    # 600 s of lateness; at 6,000,000 per late crew member it tied (#75).
    problem = make_problem([math.inf, math.inf, math.inf, 1200, 0], capacities=[14, 14])

    on_v0 = cost(problem, [[0, 1, 2, 4], [3]])
    on_v1 = cost(problem, [[0, 1, 2], [3, 4]])

    assert on_v1 - on_v0 == LATE_CREW_WEIGHT - 600 * LATENESS_WEIGHT  # 12,000,000
