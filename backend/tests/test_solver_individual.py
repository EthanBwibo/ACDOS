import math
import random

import pytest

from app.solver.individual import (
    DEPARTURE_TOLERANCE_SEC,
    REPORT_BUFFER_SEC,
    Individual,
    _drive,
    _latest_start,
    route_times,
    schedule,
    schedule_route,
    split,
)
from app.solver.instances import morning_wave
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


def test_a_lost_cause_avoids_making_an_on_time_pickup_late_even_at_more_total_lateness():
    # v0 holds three pickups with no deadline (JKIA at 2400 s); p3 (deadline
    # 1200) cannot join and opens v1. Lost cause p4 on v1 adds 2400 s (1800 its
    # own, 600 for p3); on v0 it adds 3000 s, all its own. Least total lateness
    # would pick v1 and make p3 late; the rule picks v0.
    problem = make_problem([math.inf, math.inf, math.inf, 1200, 0], capacities=[14, 14])

    individual = split(problem, [0, 1, 2, 3, 4])

    assert individual.routes == [[0, 1, 2, 4], [3]]
    assert assert_feasible(problem, individual) == {"p4": 3000}


def test_a_lost_cause_takes_least_total_lateness_when_every_route_would_make_someone_late():
    # p0 (deadline 1200) on v0, p1 (deadline 1500) on v1. Lost cause p2 makes
    # someone late either way: on v0 it adds 2400 s (600 for p0), on v1 2100 s
    # (300 for p1). It goes to v1 and does not open a new vehicle.
    problem = make_problem([1200, 1500, 0], capacities=[14, 14, 14])

    individual = split(problem, [0, 1, 2])

    assert individual.routes == [[0], [1, 2], []]
    assert assert_feasible(problem, individual) == {"p1": 300, "p2": 1800}


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


# Latest departure. make_problem legs take 600 s, so depot -> pickup -> JKIA
# is 1200 s, and the target is report time minus REPORT_BUFFER_SEC (900 s).


def test_latest_departure_leaves_as_late_as_the_buffer_allows():
    # Target 10000 - 900 = 9100, so the latest start is 7900 s.
    problem = make_problem([10000], capacities=[14])

    route = schedule_route(problem, 0, [0])

    assert 7900 - DEPARTURE_TOLERANCE_SEC < route.start <= 7900
    assert route.destination_arrival <= 9100
    assert assert_feasible(problem, problem_individual(problem, [[0]])) == {}


def test_earliest_departure_leaves_at_available_from():
    problem = make_problem([10000], capacities=[14])

    route = schedule_route(problem, 0, [0], latest_departure=False)

    assert route.start == 0
    assert route.destination_arrival == 1200


def test_latest_departure_uses_the_earliest_report_time_on_board():
    # Three legs (1800 s). p0 reports at 5000, so the target is 4100 and the
    # start at most 2300, though p1 alone could leave much later.
    problem = make_problem([5000, 20000], capacities=[14])

    route = schedule_route(problem, 0, [0, 1])

    assert 2300 - DEPARTURE_TOLERANCE_SEC < route.start <= 2300


def test_latest_departure_takes_a_configured_buffer():
    problem = make_problem([10000], capacities=[14])

    route = schedule_route(problem, 0, [0], buffer_sec=0)

    assert 8800 - DEPARTURE_TOLERANCE_SEC < route.start <= 8800


def test_latest_departure_leaves_at_available_from_when_the_target_is_out_of_reach():
    # On time (1200 <= 1500) but only inside the buffer (target 600).
    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=1500)
    vehicle = Vehicle("v0", 14, DEPOT, available_from=300)
    problem = Problem((pickup,), (vehicle,), every_leg_takes(600))

    route = schedule_route(problem, 0, [0])

    assert route.start == 300
    assert route.destination_arrival == 1500
    assert assert_feasible(problem, problem_individual(problem, [[0]])) == {}


def test_latest_departure_leaves_at_once_with_a_lost_cause_on_board():
    problem = make_problem([0, 20000], capacities=[14])

    route = schedule_route(problem, 0, [0, 1])

    assert route.start == 0
    assert [s.lateness for s in route.stops] == [1800, 0]


def test_latest_departure_leaves_at_available_from_with_no_report_time():
    problem = make_problem([math.inf], capacities=[14])

    assert schedule_route(problem, 0, [0]).start == 0


def test_latest_departure_allows_for_travel_time_that_changes_with_departure():
    # Rush hour from 5000 s: legs leaving then take 1800 s instead of 600 s.
    # Target 6100. Assuming fixed 600 s legs would start at 4900, but the
    # second leg would then leave at 5500 and arrive at 7300, late. Leaving
    # before 4400 keeps both legs out of rush hour.
    def rush_hour(origin, dest, depart_sec):
        return 600.0 if depart_sec < 5000 else 1800.0

    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=7000)
    problem = Problem((pickup,), (Vehicle("v0", 14, DEPOT),), rush_hour)

    route = schedule_route(problem, 0, [0])

    assert 4400 - DEPARTURE_TOLERANCE_SEC < route.start < 4400
    assert route.destination_arrival <= 6100
    assert assert_feasible(problem, problem_individual(problem, [[0]])) == {}


def test_latest_departure_is_still_on_time_when_travel_time_is_not_fifo():
    # Legs leaving after 5000 s take 60 s instead of 3000 s, so leaving later
    # can arrive earlier. On-time starts for target 6100 are [0, 100],
    # [2000, 3040] and [5000, 5980]; any of them will do.
    def not_fifo(origin, dest, depart_sec):
        return 3000.0 if depart_sec < 5000 else 60.0

    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=7000)
    problem = Problem((pickup,), (Vehicle("v0", 14, DEPOT),), not_fifo)

    route = schedule_route(problem, 0, [0])

    assert route.start >= 0
    assert route.destination_arrival <= 6100
    assert assert_feasible(problem, problem_individual(problem, [[0]])) == {}


def counting(travel_time):
    """Wrap a travel time function to count legs driven."""

    def counted(origin, dest, depart_sec):
        counted.calls += 1
        return travel_time(origin, dest, depart_sec)

    counted.calls = 0
    return counted


def test_departure_search_is_exact_in_one_step_when_travel_time_ignores_departure():
    # Two legs of 600 s, report at 10000: the latest start is exactly 7900.
    # One drive from available_from shows 7900 s of slack; the next tries
    # 7900 and lands exactly on target. The schedule reuses that drive
    # (#109): 2 drives.
    travel = counting(every_leg_takes(600))
    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=10000)
    problem = Problem((pickup,), (Vehicle("v0", 14, DEPOT),), travel)

    route = schedule_route(problem, 0, [0])

    assert route.start == 7900
    assert route.destination_arrival == 10000 - REPORT_BUFFER_SEC
    assert travel.calls == 2 * 2


def test_departure_search_stops_at_the_step_cap_still_on_time(monkeypatch):
    # The rush-hour travel time needs several corrections (see
    # test_latest_departure_allows_for_travel_time_that_changes_with_departure).
    # With the cap at 1, the search stops after one, still on time.
    monkeypatch.setattr("app.solver.individual.MAX_DEPARTURE_SEARCH_STEPS", 1)

    def rush_hour(origin, dest, depart_sec):
        return 600.0 if depart_sec < 5000 else 1800.0

    travel = counting(rush_hour)
    pickup = Pickup("p0", Point(-1.28, 36.81), deadline=7000)
    problem = Problem((pickup,), (Vehicle("v0", 14, DEPOT),), travel)

    route = schedule_route(problem, 0, [0])

    # Two legs per drive: the reachability check and 1 step; the schedule
    # reuses the drive that set the start (#109).
    assert travel.calls == 2 * (1 + 1)
    assert route.destination_arrival <= 7000 - REPORT_BUFFER_SEC


def rush_hour(origin, dest, depart_sec):
    return 600.0 if depart_sec < 5000 else 1800.0


def every_branch():
    """Problems that take each branch of _latest_start: no report time on
    board, out of reach from available_from, and a search of several steps
    whose last try was late (so it differs from the start returned)."""
    no_report = make_problem([math.inf], capacities=[14])
    out_of_reach = make_problem([0, 20000], capacities=[14])
    search = Problem(
        (Pickup("p0", Point(-1.28, 36.81), deadline=7000, service_sec=30),),
        (Vehicle("v0", 14, DEPOT, available_from=100),),
        rush_hour,
    )
    return [("no report time", no_report, [0]), ("out of reach", out_of_reach, [0, 1]),
            ("search", search, [0])]  # fmt: skip


@pytest.mark.parametrize("case", range(3))
def test_reusing_the_search_drive_times_routes_as_driving_again(case):
    # #109: route_times and schedule_route reuse the drive the departure
    # search ended on. They must give what driving again from that start
    # gives, to the bit, on every branch of the search.
    name, problem, route = every_branch()[case]
    start = _latest_start(problem, 0, route, REPORT_BUFFER_SEC)[0]
    arrivals, end = _drive(problem, 0, route, start)

    assert route_times(problem, 0, route) == (start, arrivals, end), name
    scheduled = schedule_route(problem, 0, route)
    assert scheduled.start == start
    assert [s.arrival for s in scheduled.stops] == arrivals
    assert scheduled.destination_arrival == end


def test_the_search_returns_the_drive_of_the_start_it_returns():
    # In the search case the last try is late, so the drive returned must be
    # lo's, not the last one tried.
    _, problem, route = every_branch()[2]
    start, arrivals, end = _latest_start(problem, 0, route, REPORT_BUFFER_SEC)
    assert (arrivals, end) == _drive(problem, 0, route, start)
    assert end <= 7000 - REPORT_BUFFER_SEC

    _, no_report, route = every_branch()[0]
    assert _latest_start(no_report, 0, route, REPORT_BUFFER_SEC)[1:] == (None, None)


def test_an_out_of_reach_route_is_driven_once():
    # The reachability drive already is the schedule: leave at once.
    travel = counting(every_leg_takes(600))
    pickups = (Pickup("p0", Point(-1.28, 36.81), 0), Pickup("p1", Point(-1.28, 36.82), 20000))
    problem = Problem(pickups, (Vehicle("v0", 14, DEPOT),), travel)

    assert route_times(problem, 0, [0, 1])[0] == 0
    assert travel.calls == 3  # one drive of three legs


@pytest.mark.parametrize("seed", range(20))
def test_latest_departure_never_changes_who_is_late(seed):
    rng = random.Random(seed)
    pickups = tuple(
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(1800, 4 * 3600),
            service_sec=60,
        )
        for i in range(12)
    )
    vehicles = tuple(
        Vehicle(f"v{v}", 4, DEPOT, available_from=rng.uniform(0, 1800)) for v in range(4)
    )
    problem = Problem(pickups, vehicles, haversine_travel_time(speed_kmh=30))
    individual = split(problem, rng.sample(range(12), 12))

    latest = schedule(problem, individual)
    earliest = schedule(problem, individual, latest_departure=False)

    def lateness(schedules):
        return {s.pickup_index: s.lateness for r in schedules for s in r.stops}

    assert lateness(latest) == lateness(earliest)
    for late_route, early_route in zip(latest, earliest, strict=True):
        if late_route.start is not None:
            assert late_route.start >= early_route.start
    assert_feasible(problem, individual)


def problem_individual(problem, routes):
    """Individual with these routes and an empty route for every other vehicle."""
    return Individual(routes + [[] for _ in range(len(problem.vehicles) - len(routes))])


# Remembering legs for travel time that ignores departure time (#85)


def test_a_problem_remembers_each_leg_of_a_travel_time_that_ignores_departure():
    travel = counting(every_leg_takes(600))
    travel.ignores_departure_time = True
    a, b = Point(-1.28, 36.81), Point(-1.29, 36.82)
    problem = Problem((), (Vehicle("v0", 14, DEPOT),), travel)
    travel.calls = 0  # building the leg table (#88) asked for its own legs

    first = problem.travel_time(a, b, 0)
    second = problem.travel_time(a, b, 5000)

    assert first == second == 600
    assert travel.calls == 1


def test_equal_points_that_are_different_objects_are_not_mixed_up():
    # The memo is keyed on identity and checks it, so it never hands one
    # point's leg to another object, even an equal one.
    travel = counting(every_leg_takes(600))
    travel.ignores_departure_time = True
    problem = Problem((), (Vehicle("v0", 14, DEPOT),), travel)
    travel.calls = 0  # building the leg table (#88) asked for its own legs

    problem.travel_time(Point(-1.28, 36.81), JKIA, 0)
    problem.travel_time(Point(-1.28, 36.81), JKIA, 0)

    assert travel.calls == 2


def test_each_problem_has_its_own_memo():
    # The same leg asked through two problems built from one function is
    # computed once per problem: the memo goes when its Problem does, so it
    # cannot grow across solves.
    travel = counting(every_leg_takes(600))
    travel.ignores_departure_time = True
    first = Problem((), (Vehicle("v0", 14, DEPOT),), travel)
    second = Problem((), (Vehicle("v0", 14, DEPOT),), travel)
    travel.calls = 0  # building the leg tables (#88) asked for their own legs
    a = Point(-1.28, 36.81)  # a leg neither table holds

    first.travel_time(a, JKIA, 0)
    second.travel_time(a, JKIA, 0)
    second.travel_time(a, JKIA, 0)

    assert travel.calls == 2


def test_remembered_haversine_gives_the_same_times():
    rng = random.Random(0)
    points = [Point(rng.uniform(-1.4, -1.1), rng.uniform(36.6, 37.0)) for _ in range(10)]
    plain = haversine_travel_time(speed_kmh=30)
    problem = Problem((), (Vehicle("v0", 14, DEPOT),), plain)

    for _ in range(2):  # second pass comes from the memo
        for a in points:
            for b in points:
                assert problem.travel_time(a, b, 0) == plain(a, b, 0)


def test_travel_time_that_depends_on_departure_is_left_alone():
    def rush_hour(origin, dest, depart_sec):
        return 600.0 if depart_sec < 5000 else 1800.0

    problem = Problem((), (Vehicle("v0", 14, DEPOT),), rush_hour)

    assert problem.travel_time is rush_hour


# Leg table (#88)


def test_the_leg_table_gives_the_same_drive_as_calling_travel_time():
    problem = morning_wave(n_crew=15, n_vans=4, seed=3)
    plain = Problem(problem.pickups, problem.vehicles, haversine_travel_time(speed_kmh=30))
    object.__setattr__(plain, "legs", None)  # force the travel_time path
    rng = random.Random(3)

    for _ in range(50):
        route = rng.sample(range(15), rng.randint(1, 8))
        v = rng.randrange(4)
        start = rng.uniform(0, 3600)
        assert _drive(problem, v, route, start) == _drive(plain, v, route, start)


def test_travel_time_that_depends_on_departure_gets_no_leg_table():
    def rush_hour(origin, dest, depart_sec):
        return 600.0 if depart_sec < 5000 else 1800.0

    problem = Problem((), (Vehicle("v0", 14, DEPOT),), rush_hour)

    assert problem.legs is None
