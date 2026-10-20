import math

import pytest

from app.solver.individual import Individual, schedule_route, split
from app.solver.problem import JKIA, Pickup, Point, Problem, Vehicle, haversine_travel_time
from tests.solver_checks import assert_feasible

DEPOT = Point(-1.30, 36.80)


def every_leg_takes(seconds):
    """Travel time function where every drive takes the same time."""
    return lambda origin, dest, depart_sec: seconds


def make_problem(deadlines, capacities, leg_sec=600.0, service_sec=0.0):
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline, service_sec=service_sec)
        for i, deadline in enumerate(deadlines)
    )
    vehicles = tuple(Vehicle(f"v{v}", capacity, DEPOT) for v, capacity in enumerate(capacities))
    return Problem(pickups, vehicles, every_leg_takes(leg_sec))


def test_split_starts_a_new_route_when_the_vehicle_is_full():
    problem = make_problem([math.inf] * 5, capacities=[2, 2, 2])

    individual = split(problem, [0, 1, 2, 3, 4])

    assert individual.routes == [[0, 1], [2, 3], [4]]
    assert individual.unassigned == []
    assert assert_feasible(problem, individual) == {}


def test_split_starts_a_new_route_when_the_next_pickup_would_make_someone_late():
    # Depot -> p0 -> JKIA is 2 legs (1200 s), exactly p0's deadline. Adding p1
    # first would make it 1800 s, so p1 goes to the second vehicle.
    problem = make_problem([1200, math.inf], capacities=[14, 14])

    individual = split(problem, [0, 1])

    assert individual.routes == [[0], [1]]
    assert assert_feasible(problem, individual) == {}


def test_split_reports_pickups_left_over_when_the_fleet_runs_out():
    problem = make_problem([math.inf] * 3, capacities=[1, 1])

    individual = split(problem, [2, 0, 1])

    assert individual.routes == [[2], [0]]
    assert individual.unassigned == [1]
    assert_feasible(problem, individual)


def test_split_sends_pickups_to_unassigned_when_deadlines_use_up_the_fleet():
    # Each pickup is on time only alone (1200 s), so two vehicles take two.
    problem = make_problem([1200] * 3, capacities=[14, 14])

    individual = split(problem, [0, 1, 2])

    assert individual.routes == [[0], [1]]
    assert individual.unassigned == [2]
    assert assert_feasible(problem, individual) == {}


def test_a_pickup_that_cannot_be_on_time_still_gets_a_route_and_is_reported_late():
    problem = make_problem([100], capacities=[14])

    individual = split(problem, [0])

    assert individual.routes == [[0]]
    assert assert_feasible(problem, individual) == {"p0": 1100}


# Lost causes: late even alone on every vehicle. In make_problem, any pickup
# alone reaches JKIA at 1200 s, so deadline 0 is a lost cause.


def test_lost_causes_share_a_vehicle_instead_of_taking_one_each():
    problem = make_problem([0, 0, 0], capacities=[14, 14, 14])

    individual = split(problem, [0, 1, 2])

    assert individual.routes == [[0, 1, 2], [], []]
    assert assert_feasible(problem, individual) == {"p0": 2400, "p1": 2400, "p2": 2400}


def test_a_lost_cause_does_not_block_the_pickups_after_it():
    problem = make_problem([0, math.inf, math.inf], capacities=[14, 14])

    individual = split(problem, [0, 1, 2])

    assert individual.routes == [[0, 1, 2], []]
    assert assert_feasible(problem, individual) == {"p0": 2400}


def test_a_lost_cause_joins_the_route_where_it_adds_least_lateness():
    # v0 holds p0 (no deadline); p1 (deadline 1200) cannot join it and opens
    # v1. Lost cause p2 on v0 adds 1800 s (its own); on v1 it would add 2400 s
    # (its own 1800 plus 600 s for p1), so it goes to v0, an earlier route.
    problem = make_problem([math.inf, 1200, 0], capacities=[2, 14, 14])

    individual = split(problem, [0, 1, 2])

    assert individual.routes == [[0, 2], [1], []]
    assert assert_feasible(problem, individual) == {"p2": 1800}


def test_a_lost_cause_opens_the_next_vehicle_only_when_no_open_route_has_room():
    problem = make_problem([0, 0], capacities=[1, 1])

    individual = split(problem, [0, 1])

    assert individual.routes == [[0], [1]]
    assert assert_feasible(problem, individual) == {"p0": 1200, "p1": 1200}


def test_a_lost_cause_still_finds_room_after_the_fleet_runs_out():
    # p2 (on time alone) finds no vehicle and is unassigned; lost cause p3
    # then fills the free seat on v0 rather than being unassigned too.
    problem = make_problem([math.inf, 1200, 1200, 0], capacities=[2, 1])

    individual = split(problem, [0, 1, 2, 3])

    assert individual.routes == [[0, 3], [1]]
    assert individual.unassigned == [2]
    assert assert_feasible(problem, individual) == {"p3": 1800}


def test_schedule_route_times_each_stop_and_the_shared_arrival():
    problem = make_problem([2000, 1900], capacities=[14], service_sec=60)

    route = schedule_route(problem, 0, [0, 1])

    assert [(s.arrival, s.departure) for s in route.stops] == [(600, 660), (1260, 1320)]
    assert route.destination_arrival == 1920
    assert route.load == 2
    # Both arrive at 1920: p0 (deadline 2000) is on time, p1 (1900) is 20 s late.
    assert [s.lateness for s in route.stops] == [0, 20]


def test_unused_vehicle_has_an_empty_schedule():
    problem = make_problem([math.inf], capacities=[14, 14])

    route = schedule_route(problem, 1, [])

    assert route.stops == ()
    assert route.destination_arrival is None


def test_vehicle_cannot_leave_before_it_is_available():
    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=math.inf)
    vehicle = Vehicle("v0", 14, DEPOT, available_from=300)
    problem = Problem((pickup,), (vehicle,), every_leg_takes(600))

    route = schedule_route(problem, 0, [0])

    assert route.stops[0].arrival == 900
    assert route.destination_arrival == 1500


def test_giant_tour_and_split_round_trip_keeps_order():
    problem = make_problem([math.inf] * 4, capacities=[2, 2])
    individual = Individual(routes=[[3, 1], [0, 2]])

    tour = individual.giant_tour()

    assert tour == [3, 1, 0, 2]
    assert split(problem, tour).routes == individual.routes


def test_giant_tour_puts_unassigned_pickups_last():
    individual = Individual(routes=[[1], []], unassigned=[0])

    assert individual.giant_tour() == [1, 0]


def test_copy_does_not_share_route_lists():
    individual = Individual(routes=[[0, 1]], unassigned=[2])

    clone = individual.copy()
    clone.routes[0].append(2)
    clone.unassigned.clear()

    assert individual.routes == [[0, 1]]
    assert individual.unassigned == [2]


def test_problem_rejects_duplicate_pickup_ids():
    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=0)

    with pytest.raises(ValueError, match="pickup ids"):
        Problem((pickup, pickup), (Vehicle("v0", 14, DEPOT),), every_leg_takes(600))


def test_problem_rejects_zero_capacity():
    with pytest.raises(ValueError, match="capacity"):
        Problem((), (Vehicle("v0", 0, DEPOT),), every_leg_takes(600))


def test_haversine_matches_straight_line_distance_from_pickup_zones():
    # data/pickup_zones.csv: South B is 10.5 km from JKIA in a straight line.
    # At 60 km/h that is 10.5 minutes.
    south_b = Point(-1.310341, 36.833737)

    seconds = haversine_travel_time(speed_kmh=60)(south_b, JKIA, 0)

    assert seconds == pytest.approx(10.5 * 60, rel=0.02)


def test_feasibility_check_catches_a_pickup_visited_twice():
    problem = make_problem([math.inf] * 2, capacities=[14, 14])

    with pytest.raises(AssertionError, match="exactly once"):
        assert_feasible(problem, Individual(routes=[[0, 1], [1]]))


def test_feasibility_check_catches_a_missing_pickup():
    problem = make_problem([math.inf] * 2, capacities=[14])

    with pytest.raises(AssertionError, match="exactly once"):
        assert_feasible(problem, Individual(routes=[[0]]))


def test_feasibility_check_catches_an_overfull_vehicle():
    problem = make_problem([math.inf] * 3, capacities=[2])

    with pytest.raises(AssertionError, match="carries 3 > 2"):
        assert_feasible(problem, Individual(routes=[[0, 1, 2]]))
