"""Feasibility check shared by every solver test (CLAUDE.md: every pickup
visited once, capacity respected, every deadline met or explicitly reported).

Stop windows (#99) are checked the same way: a vehicle early at a stop waits
for its ready time, and starting service after its due time counts as late.

Takes only each route's start time from schedule() and recomputes the rest on
its own, so a bug in the solver's timing cannot hide behind the same bug in the
check.
"""

import pytest

from app.solver.individual import Individual, schedule
from app.solver.problem import Problem


def assert_feasible(problem: Problem, individual: Individual) -> dict[str, float]:
    """Fail on a broken solution; return {pickup id: seconds late} for the rest.

    Late pickups are allowed (a deadline can be impossible to meet), but the
    lateness schedule() reports must match the recomputed value.
    """
    assert len(individual.routes) == len(problem.vehicles), "one route per vehicle"

    placed = [i for route in individual.routes for i in route] + individual.unassigned
    assert sorted(placed) == list(range(len(problem.pickups))), (
        "every pickup must appear exactly once, in a route or in unassigned"
    )

    schedules = schedule(problem, individual)
    late: dict[str, float] = {}
    for v, route in enumerate(individual.routes):
        vehicle = problem.vehicles[v]
        load = sum(problem.pickups[i].demand for i in route)
        assert load <= vehicle.capacity, f"vehicle {vehicle.id} carries {load} > {vehicle.capacity}"
        if not route:
            continue

        start = schedules[v].start
        assert start >= vehicle.available_from, (
            f"vehicle {vehicle.id} leaves at {start}, before it is available "
            f"at {vehicle.available_from}"
        )
        if not problem.weights.latest_departure:
            assert start == vehicle.available_from, (
                f"vehicle {vehicle.id} should leave at {vehicle.available_from}, leaves at {start}"
            )
        clock, position = start, vehicle.start
        service_starts = {}
        for i in route:
            pickup = problem.pickups[i]
            clock += problem.travel_time(position, pickup.location, clock)
            # Early: wait for the stop window to open (ready is -inf for crew).
            clock = max(clock, pickup.ready)
            service_starts[i] = clock
            clock += pickup.service_sec
            position = pickup.location
        end = clock + problem.travel_time(position, problem.destination, clock)

        for i in route:
            pickup = problem.pickups[i]
            seconds_late = max(0.0, end - pickup.deadline) + max(
                0.0, service_starts[i] - pickup.due
            )
            if seconds_late > 0:
                late[pickup.id] = seconds_late

    reported = {
        problem.pickups[stop.pickup_index].id: stop.lateness
        for route_schedule in schedules
        for stop in route_schedule.stops
        if stop.lateness > 0
    }
    # approx: the two sums add the same floats in a different order.
    assert reported == pytest.approx(late), f"schedule() reports {reported}, recomputed {late}"
    return late
