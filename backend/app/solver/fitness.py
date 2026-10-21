"""Fitness: one number per Individual, lower is better.

    cost = UNASSIGNED_WEIGHT * U + LATENESS_WEIGHT * L + LATE_CREW_WEIGHT * K_late
           + BUFFER_WEIGHT * B + VEHICLE_WEIGHT * K + TIME_WEIGHT * (T + W)

Computed on the latest-departure schedule, so a vehicle leaves as late as it
can and W measures report-time spread on a route, not an early start.

The weights are tiers. Each higher term outweighs any realistic total of the
terms below it, except vehicles against T + W, which is a deliberate exchange
rate: each vehicle makes one trip, so if saving a vehicle always won, the GA
would put crew reporting hours apart in one van and leave the later ones
waiting at JKIA.

Every term except U belongs to one route, so the cost is U plus a sum over
routes (route_evaluation). Insertion operators re-cost only the route they
change.
"""

import math
from dataclasses import dataclass

from app.solver.individual import REPORT_BUFFER_SEC, Individual, schedule_route
from app.solver.problem import Problem

# Per crew member left without a vehicle. One outweighs about 278 h of total
# lateness (1e10 / 10,000 / 3600).
UNASSIGNED_WEIGHT = 1e10
# Per second past report time, per crew member. One minute late (600,000)
# outweighs about 10 vehicles plus about 150 h of T + W.
LATENESS_WEIGHT = 10_000.0
# Per crew member who is late at all, on top of their seconds late: equal to
# 30 min of lateness. Each late crew member is a separate flight-delay risk, so
# making an on-time crew member late must cost more than adding the same
# seconds to someone already late. At 6,000,000 (10 min), #12's lost-cause
# instance tied exactly between the two (#75); sensitivity run planned (#14).
LATE_CREW_WEIGHT = 18_000_000.0
# Per second of buffer eaten, per crew member. The whole 15 min buffer
# (90,000) costs about 25 vehicles, and still less than a minute late.
BUFFER_WEIGHT = 100.0
# Per vehicle used: worth 1 h of T + W. Sensitivity check at 1,800 and 7,200
# planned for the results chapter.
VEHICLE_WEIGHT = 3_600.0
# Per second of vehicle time (T) or crew waiting beyond the buffer (W).
TIME_WEIGHT = 1.0


@dataclass(frozen=True)
class Evaluation:
    """The terms of the cost, kept apart for tests, logs and the write-up."""

    unassigned: int  # U: pickups in Individual.unassigned
    lateness_sec: float  # L: sum of seconds each crew member arrives late
    late_crew: int  # K_late: crew members who arrive late at all
    buffer_used_sec: float  # B: sum of buffer seconds each crew member loses
    vehicles_used: int  # K: routes that are not empty
    travel_sec: float  # T: sum of route durations, start to destination
    waiting_sec: float  # W: sum of crew waiting at JKIA beyond the buffer

    @property
    def cost(self) -> float:
        return (
            UNASSIGNED_WEIGHT * self.unassigned
            + LATENESS_WEIGHT * self.lateness_sec
            + LATE_CREW_WEIGHT * self.late_crew
            + BUFFER_WEIGHT * self.buffer_used_sec
            + VEHICLE_WEIGHT * self.vehicles_used
            + TIME_WEIGHT * (self.travel_sec + self.waiting_sec)
        )


def route_evaluation(
    problem: Problem,
    vehicle_index: int,
    route: list[int],
    buffer_sec: float = REPORT_BUFFER_SEC,
) -> Evaluation:
    """The terms for one route; unassigned is always 0."""
    scheduled = schedule_route(problem, vehicle_index, route, buffer_sec=buffer_sec)
    if scheduled.start is None:
        return Evaluation(
            unassigned=0,
            lateness_sec=0.0,
            late_crew=0,
            buffer_used_sec=0.0,
            vehicles_used=0,
            travel_sec=0.0,
            waiting_sec=0.0,
        )

    lateness = buffer_used = waiting = 0.0
    late_crew = 0
    end = scheduled.destination_arrival
    for stop in scheduled.stops:
        deadline = problem.pickups[stop.pickup_index].deadline
        # When this crew member would ideally arrive: report time minus buffer.
        ideal = deadline - buffer_sec
        lateness += stop.lateness
        if stop.lateness > 0:
            late_crew += 1
        # Capped at the whole buffer: time past report time is lateness.
        buffer_used += min(buffer_sec, max(0.0, end - ideal))
        # A pickup with no report time (infinite deadline, only in tests)
        # has nothing to wait for.
        if math.isfinite(deadline):
            waiting += max(0.0, ideal - end)

    return Evaluation(
        unassigned=0,
        lateness_sec=lateness,
        late_crew=late_crew,
        buffer_used_sec=buffer_used,
        vehicles_used=1,
        travel_sec=end - scheduled.start,
        waiting_sec=waiting,
    )


# Route cost by (vehicle index, route), so an operator costs each route once
# per call even when it looks at the same route many times.
RouteCostCache = dict[tuple[int, tuple[int, ...]], float]


def cached_route_cost(
    problem: Problem, vehicle_index: int, route: list[int], cache: RouteCostCache
) -> float:
    """route_evaluation(...).cost, remembered in cache."""
    key = (vehicle_index, tuple(route))
    if key not in cache:
        cache[key] = route_evaluation(problem, vehicle_index, route).cost
    return cache[key]


def evaluate(
    problem: Problem, individual: Individual, buffer_sec: float = REPORT_BUFFER_SEC
) -> Evaluation:
    routes = [
        route_evaluation(problem, v, route, buffer_sec) for v, route in enumerate(individual.routes)
    ]
    return Evaluation(
        unassigned=len(individual.unassigned),
        lateness_sec=sum(r.lateness_sec for r in routes),
        late_crew=sum(r.late_crew for r in routes),
        buffer_used_sec=sum(r.buffer_used_sec for r in routes),
        vehicles_used=sum(r.vehicles_used for r in routes),
        travel_sec=sum(r.travel_sec for r in routes),
        waiting_sec=sum(r.waiting_sec for r in routes),
    )


def fitness(problem: Problem, individual: Individual) -> float:
    """Cost of an Individual; lower is better."""
    return evaluate(problem, individual).cost
