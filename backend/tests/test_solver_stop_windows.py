"""Stop time windows and per-problem weights (#99).

Hand-checkable instances on a plane: (x, y) in Point(lat=y, lon=x), straight
lines at one unit of distance per unit of time, the depot at (0, 0) as both
start and destination, as on Solomon's instances (#13).
"""

import math
import random

import pytest

from app.solver import insertion
from app.solver.fitness import route_evaluation
from app.solver.ga import solve
from app.solver.individual import (
    Individual,
    late_even_alone,
    route_times,
    schedule_route,
    split,
)
from app.solver.instances import smoke_30
from app.solver.nearest_neighbour import nearest_neighbour
from app.solver.problem import Pickup, Point, Problem, Vehicle
from app.solver.shaw import relatedness_matrix
from app.solver.weights import CREW, SOLOMON
from tests.solver_checks import assert_feasible

DEPOT = Point(0.0, 0.0)
DEPOT_CLOSES = 1000.0


def euclidean(origin: Point, dest: Point) -> float:
    return math.hypot(origin.lon - dest.lon, origin.lat - dest.lat)


def plane_travel_time(origin: Point, dest: Point, depart: float) -> float:
    return euclidean(origin, dest)


plane_travel_time.ignores_departure_time = True  # type: ignore[attr-defined]


def customer(name, x, y, ready=0.0, due=DEPOT_CLOSES, service=0.0, demand=1):
    return Pickup(
        name,
        Point(lat=y, lon=x),
        deadline=DEPOT_CLOSES,
        demand=demand,
        service_sec=service,
        ready=ready,
        due=due,
    )


def plane_problem(customers, vehicles=1, weights=SOLOMON, capacity=100, leg_table=True):
    """leg_table=False hides that travel time ignores departure, so the solver
    drives leg by leg as it does with the Random Forest."""
    fleet = tuple(Vehicle(f"v{v}", capacity, DEPOT) for v in range(vehicles))
    travel_time = plane_travel_time if leg_table else (lambda o, d, t: euclidean(o, d))
    return Problem(
        tuple(customers),
        fleet,
        travel_time,
        destination=DEPOT,
        weights=weights,
        distance=euclidean,
    )


@pytest.mark.parametrize("leg_table", [True, False])
def test_a_vehicle_that_arrives_early_waits_for_the_ready_time(leg_table):
    # A is 10 away and opens at 50: leave 0, arrive 10, wait to 50, serve
    # 10 units, leave 60, back at the depot at 70.
    problem = plane_problem(
        [customer("A", 0, 10, ready=50, due=100, service=10)], leg_table=leg_table
    )
    assert (problem.legs is not None) == leg_table

    route = schedule_route(problem, 0, [0])

    assert route.start == 0
    assert route.stops[0].arrival == 50  # service starts when the window opens
    assert route.stops[0].departure == 60
    assert route.destination_arrival == 70
    assert route.stops[0].lateness == 0
    assert assert_feasible(problem, Individual([[0]])) == {}


def test_starting_service_after_the_due_time_is_lateness():
    # A is 10 away but due at 5: service starts 5 units late. The depot
    # closes at 1000, so that is the only lateness.
    problem = plane_problem([customer("A", 0, 10, due=5)])

    evaluation = route_evaluation(problem, 0, [0])

    assert evaluation.lateness_sec == 5
    assert evaluation.late_crew == 1
    assert schedule_route(problem, 0, [0]).stops[0].lateness == 5
    assert assert_feasible(problem, Individual([[0]])) == {"A": 5}


def test_solomon_routes_leave_when_the_depot_opens():
    # Solomon: leave at available_from, as VRPTW schedules do, even though A
    # makes the vehicle wait 40 for its window.
    problem = plane_problem([customer("A", 0, 10, ready=50)])

    assert route_times(problem, 0, [0])[0] == 0
    assert schedule_route(problem, 0, [0]).start == 0
    # Crew weights on the same kind of route leave as late as they can: back
    # by 1000 - 900 buffer = 100 after a 20 round trip, so at 80.
    crew_weights = plane_problem([customer("A", 0, 10)], weights=CREW)
    assert route_times(crew_weights, 0, [0])[0] == 80


def test_split_refuses_an_append_past_the_due_time():
    # B alone: arrive 15, due 18, fine. After A (10 away, 10 service), B is
    # reached at 25: past 18, so B goes to the second vehicle.
    problem = plane_problem(
        [customer("A", 0, 10, service=10), customer("B", 0, 15, due=18)], vehicles=2
    )

    individual = split(problem, [0, 1])

    assert individual.routes == [[0], [1]]
    assert assert_feasible(problem, individual) == {}


def test_split_counts_the_wait_for_a_ready_time():
    # A opens at 50, so B (5 further on) is reached at 50 + 10 + 5 = 65,
    # past its due time of 60. Without the wait it would be 25, in time.
    problem = plane_problem(
        [customer("A", 0, 10, ready=50, service=10), customer("B", 0, 15, due=60)],
        vehicles=2,
    )

    assert split(problem, [0, 1]).routes == [[0], [1]]
    # Forced onto one vehicle, B is 5 late: the check counts the wait too.
    assert assert_feasible(problem, Individual([[0, 1], []])) == {"B": 5}


def test_a_pickup_due_before_any_vehicle_can_reach_it_is_a_lost_cause():
    problem = plane_problem([customer("A", 0, 10, due=9), customer("B", 0, 10, due=10)])

    assert late_even_alone(problem, problem.pickups[0])
    assert not late_even_alone(problem, problem.pickups[1])


def test_the_detour_shortlist_is_off_with_stop_windows(monkeypatch):
    # Waiting for a ready time can absorb a detour, so every position is
    # costed (#88's shortlist would cost only 2 of the 5).
    monkeypatch.setattr(insertion, "FULLY_COSTED_POSITIONS", 2)
    problem = plane_problem([customer(f"c{k}", k, 0) for k in range(1, 6)])

    positions = insertion._positions_worth_costing(problem, [0, 1, 2, 3], 0, 4)

    assert positions == [0, 1, 2, 3, 4]


def test_distance_is_the_sum_of_leg_lengths_without_waiting_or_service():
    # Depot -> A (3, 4) is 5, A -> B (3, 0) is 4, B -> depot is 3: D = 12.
    # A opens at 20 and both take 10 to serve, so T is 20 + 10 + 4 + 10 + 3 = 47.
    problem = plane_problem(
        [customer("A", 3, 4, ready=20, service=10), customer("B", 3, 0, service=10)]
    )

    evaluation = route_evaluation(problem, 0, [0, 1])

    assert evaluation.distance == 12
    assert evaluation.travel_sec == 47
    assert evaluation.cost == SOLOMON.vehicle * 1 + SOLOMON.distance * 12


def test_crew_problems_have_no_stop_windows_and_no_distance_term():
    problem = smoke_30()

    assert problem.weights is CREW
    assert not problem.stop_windows
    assert problem.leg_lengths is None
    individual = nearest_neighbour(problem)
    assert route_evaluation(problem, 0, individual.routes[0]).distance == 0


def test_ready_after_due_is_rejected():
    with pytest.raises(ValueError, match="ready"):
        plane_problem([customer("A", 0, 10, ready=20, due=10)])


def test_shaw_relates_pickups_by_due_time_when_they_have_one():
    # Same place, same depot deadline: only the due times differ, so the
    # pickup due at 20 is more related to the one due at 10 than the one due
    # at 100 is.
    problem = plane_problem(
        [customer("A", 0, 10, due=10), customer("B", 0, 10, due=20), customer("C", 0, 10, due=100)]
    )

    relatedness = relatedness_matrix(problem)

    assert relatedness[0][1] < relatedness[0][2]


def test_nearest_neighbour_starts_with_the_earliest_due_time():
    # C is due first, so it seeds the route although it is the farthest.
    problem = plane_problem(
        [customer("A", 0, 1, due=500), customer("B", 0, 2, due=500), customer("C", 0, 3, due=5)]
    )

    assert nearest_neighbour(problem).routes[0][0] == 2


def test_the_ga_returns_a_feasible_solution_with_stop_windows():
    # 20 customers with wide windows and four vehicles: the GA must keep
    # every check in assert_feasible, and on this easy instance be on time.
    rng = random.Random(7)
    customers = []
    for k in range(20):
        x, y = rng.uniform(-30, 30), rng.uniform(-30, 30)
        ready = rng.uniform(0, 300)
        customers.append(customer(f"c{k}", x, y, ready=ready, due=ready + 200, service=10))
    problem = plane_problem(customers, vehicles=4, capacity=10)

    result = solve(problem, random.Random(1), max_generations=5, clock=lambda: 0.0)

    assert assert_feasible(problem, result.best) == {}
    assert result.evaluation.unassigned == 0
    assert result.evaluation.lateness_sec == 0
