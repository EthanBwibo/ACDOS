"""Fitness: one number per Individual, lower is better.

    cost = UNASSIGNED_WEIGHT * U + LATENESS_WEIGHT * L + BUFFER_WEIGHT * B
           + VEHICLE_WEIGHT * K + TIME_WEIGHT * (T + W)

Computed on the latest-departure schedule, so a vehicle leaves as late as it
can and W measures report-time spread on a route, not an early start.

The weights are tiers. Each higher term outweighs any realistic total of the
terms below it, except vehicles against T + W, which is a deliberate exchange
rate: each vehicle makes one trip, so if saving a vehicle always won, the GA
would put crew reporting hours apart in one van and leave the later ones
waiting at JKIA.
"""

import math
from dataclasses import dataclass

from app.solver.individual import REPORT_BUFFER_SEC, Individual, schedule
from app.solver.problem import Problem

# Per crew member left without a vehicle. One outweighs about 278 h of total
# lateness (1e10 / 10,000 / 3600).
UNASSIGNED_WEIGHT = 1e10
# Per second past report time, per crew member. One minute late (600,000)
# outweighs about 10 vehicles plus about 150 h of T + W.
LATENESS_WEIGHT = 10_000.0
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
    buffer_used_sec: float  # B: sum of buffer seconds each crew member loses
    vehicles_used: int  # K: routes that are not empty
    travel_sec: float  # T: sum of route durations, start to destination
    waiting_sec: float  # W: sum of crew waiting at JKIA beyond the buffer

    @property
    def cost(self) -> float:
        return (
            UNASSIGNED_WEIGHT * self.unassigned
            + LATENESS_WEIGHT * self.lateness_sec
            + BUFFER_WEIGHT * self.buffer_used_sec
            + VEHICLE_WEIGHT * self.vehicles_used
            + TIME_WEIGHT * (self.travel_sec + self.waiting_sec)
        )


def evaluate(
    problem: Problem, individual: Individual, buffer_sec: float = REPORT_BUFFER_SEC
) -> Evaluation:
    lateness = buffer_used = travel = waiting = 0.0
    vehicles = 0
    for route in schedule(problem, individual, buffer_sec=buffer_sec):
        if route.start is None:
            continue
        vehicles += 1
        end = route.destination_arrival
        travel += end - route.start
        for stop in route.stops:
            deadline = problem.pickups[stop.pickup_index].deadline
            # When this crew member would ideally arrive: report time minus buffer.
            ideal = deadline - buffer_sec
            lateness += stop.lateness
            # Capped at the whole buffer: time past report time is lateness.
            buffer_used += min(buffer_sec, max(0.0, end - ideal))
            # A pickup with no report time (infinite deadline, only in tests)
            # has nothing to wait for.
            if math.isfinite(deadline):
                waiting += max(0.0, ideal - end)

    return Evaluation(
        unassigned=len(individual.unassigned),
        lateness_sec=lateness,
        buffer_used_sec=buffer_used,
        vehicles_used=vehicles,
        travel_sec=travel,
        waiting_sec=waiting,
    )


def fitness(problem: Problem, individual: Individual) -> float:
    """Cost of an Individual; lower is better."""
    return evaluate(problem, individual).cost
