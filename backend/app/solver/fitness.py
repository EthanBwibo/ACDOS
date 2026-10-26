"""Fitness: one number per Individual, lower is better.

    cost = UNASSIGNED_WEIGHT * U + LATENESS_WEIGHT * L + LATE_CREW_WEIGHT * K_late
           + BUFFER_WEIGHT * B + RIDE_WEIGHT * R + VEHICLE_WEIGHT * K
           + TIME_WEIGHT * (T + W) + (distance weight) * D

The weights come from the Problem (weights.py, #99). The names above are the
crew profile, CREW; its distance weight is 0, since driving already costs
through T. The Solomon profile (SOLOMON) turns the buffer, ride and time terms
off and charges D, the total distance: the benchmark objective of #13.

For crew, computed on the latest-departure schedule, so a vehicle leaves as late as it
can and W measures report-time spread on a route, not an early start.

The weights are tiers. Each higher term outweighs any realistic total of the
terms below it, except vehicles against T + W, which is a deliberate exchange
rate: each vehicle makes one trip, so if saving a vehicle always won, the GA
would put crew reporting hours apart in one van and leave the later ones
waiting at JKIA.

W charges waiting at JKIA, but time in the van was free, so the GA could build
long zigzag routes that collect crew hours before their report time and
arrive just in time (#89). R charges each crew member's ride beyond
MAX_RIDE_SEC, the soft form of the maximum ride time constraint in
dial-a-ride problems (Cordeau and Laporte, 2003).

With stop windows (Solomon), starting service after a pickup's due time is
lateness too: it adds to L and makes the pickup count in K_late.

Every term except U belongs to one route, so the cost is U plus a sum over
routes (route_evaluation). Insertion operators re-cost only the route they
change.
"""

import math
from dataclasses import dataclass, field

from app.solver.individual import Individual, route_times
from app.solver.problem import Problem

# The crew weights, under the names used before #99. Their values and reasons
# are in weights.py.
from app.solver.weights import (  # noqa: F401 (re-exported)
    BUFFER_WEIGHT,
    CREW,
    LATE_CREW_WEIGHT,
    LATENESS_WEIGHT,
    MAX_RIDE_SEC,
    RIDE_WEIGHT,
    TIME_WEIGHT,
    UNASSIGNED_WEIGHT,
    VEHICLE_WEIGHT,
    FitnessWeights,
)


@dataclass(frozen=True)
class Evaluation:
    """The terms of the cost, kept apart for tests, logs and the write-up."""

    unassigned: int  # U: pickups in Individual.unassigned
    lateness_sec: float  # L: sum of seconds each crew member arrives late
    late_crew: int  # K_late: crew members who arrive late at all
    buffer_used_sec: float  # B: sum of buffer seconds each crew member loses
    ride_excess_sec: float  # R: sum of seconds each crew member rides beyond MAX_RIDE_SEC
    vehicles_used: int  # K: routes that are not empty
    travel_sec: float  # T: sum of route durations, start to destination
    waiting_sec: float  # W: sum of crew waiting at JKIA beyond the buffer
    # D: sum of leg lengths (Problem.distance), not counting waiting or
    # service. Only computed when the weights charge for it, so 0 for crew.
    distance: float = 0.0
    # The weights the cost uses: the Problem's.
    weights: FitnessWeights = field(default=CREW, compare=False, repr=False)

    @property
    def cost(self) -> float:
        w = self.weights
        return (
            w.unassigned * self.unassigned
            + w.lateness * self.lateness_sec
            + w.late_crew * self.late_crew
            + w.buffer * self.buffer_used_sec
            + w.ride * self.ride_excess_sec
            + w.vehicle * self.vehicles_used
            + w.time * (self.travel_sec + self.waiting_sec)
            # Last, so for crew (0 * 0) the sum above is unchanged to the bit.
            + w.distance * self.distance
        )


def route_evaluation(
    problem: Problem,
    vehicle_index: int,
    route: list[int],
    buffer_sec: float | None = None,
) -> Evaluation:
    """The terms for one route; unassigned is always 0.

    Works from the route's times alone, not schedule_route's Stops: the
    operators cost hundreds of thousands of routes per solve (#85).
    buffer_sec defaults to the problem's weights.
    """
    weights = problem.weights
    if not route:
        return Evaluation(
            unassigned=0,
            lateness_sec=0.0,
            late_crew=0,
            buffer_used_sec=0.0,
            ride_excess_sec=0.0,
            vehicles_used=0,
            travel_sec=0.0,
            waiting_sec=0.0,
            weights=weights,
        )

    if buffer_sec is None:
        buffer_sec = weights.report_buffer_sec
    max_ride_sec = weights.max_ride_sec
    stop_windows = problem.stop_windows
    start, arrivals, end = route_times(problem, vehicle_index, route, buffer_sec)
    lateness = buffer_used = waiting = ride_excess = 0.0
    late_crew = 0
    for i, arrival in zip(route, arrivals, strict=True):
        deadline = problem.pickups[i].deadline
        # Everyone on board arrives together, as Stop.lateness counts it.
        late = max(0.0, end - deadline)
        if stop_windows:
            # arrival is when service starts (after any wait), see _drive.
            late += max(0.0, arrival - problem.pickups[i].due)
        # When this crew member would ideally arrive: report time minus buffer.
        ideal = deadline - buffer_sec
        lateness += late
        if late > 0:
            late_crew += 1
        # Capped at the whole buffer: time past report time is lateness.
        buffer_used += min(buffer_sec, max(0.0, end - ideal))
        # A pickup with no report time (infinite deadline, only in tests)
        # has nothing to wait for.
        if math.isfinite(deadline):
            waiting += max(0.0, ideal - end)
        # In the van from the moment it reaches their stop until JKIA.
        ride_excess += max(0.0, end - arrival - max_ride_sec)

    return Evaluation(
        unassigned=0,
        lateness_sec=lateness,
        late_crew=late_crew,
        buffer_used_sec=buffer_used,
        ride_excess_sec=ride_excess,
        vehicles_used=1,
        travel_sec=end - start,
        waiting_sec=waiting,
        distance=_route_distance(problem, vehicle_index, route) if weights.distance > 0 else 0.0,
        weights=weights,
    )


def _route_distance(problem: Problem, vehicle_index: int, route: list[int]) -> float:
    """D for one route: start, each stop in order, then the destination, by
    the leg lengths built when the Problem was (Problem.leg_lengths)."""
    lengths = problem.leg_lengths
    row = lengths.from_start[vehicle_index]
    total = 0.0
    for i in route:
        total += row[i]
        row = lengths.between[i]
    return total + row[lengths.destination]


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
    problem: Problem, individual: Individual, buffer_sec: float | None = None
) -> Evaluation:
    routes = [
        route_evaluation(problem, v, route, buffer_sec) for v, route in enumerate(individual.routes)
    ]
    return Evaluation(
        unassigned=len(individual.unassigned),
        lateness_sec=sum(r.lateness_sec for r in routes),
        late_crew=sum(r.late_crew for r in routes),
        buffer_used_sec=sum(r.buffer_used_sec for r in routes),
        ride_excess_sec=sum(r.ride_excess_sec for r in routes),
        vehicles_used=sum(r.vehicles_used for r in routes),
        travel_sec=sum(r.travel_sec for r in routes),
        waiting_sec=sum(r.waiting_sec for r in routes),
        distance=sum(r.distance for r in routes),
        weights=problem.weights,
    )


def fitness(problem: Problem, individual: Individual) -> float:
    """Cost of an Individual; lower is better."""
    return evaluate(problem, individual).cost
