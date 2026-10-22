"""Destroy operators for the ALNS (Ropke and Pisinger, 2006), and what they share.

Every destroy operator takes q pickups out of the routes and returns a new
Individual with them appended to unassigned, plus the removed pickups in the
order they were taken. The input is never changed. Shaw removal is in shaw.py.

- Random removal: q routed pickups chosen uniformly. Cheap, and it disrupts
  the solution in ways the targeted operators never would.
- Worst removal: the pickups whose removal saves the most, so badly placed
  crew are put somewhere better.

Departure from Ropke and Pisinger (R&P), for worst removal: each pickup's
saving is reduced by its unavoidable cost, what it would cost even driven
alone (see unavoidable_costs). Without that, a lost cause (late whatever
happens) always looks like the worst pickup, and worst removal would spend
every call taking out crew it cannot help.
"""

import math
import random

from app.solver.fitness import (
    BUFFER_WEIGHT,
    LATE_CREW_WEIGHT,
    LATENESS_WEIGHT,
    RIDE_WEIGHT,
    RouteCostCache,
    cached_route_cost,
    route_evaluation,
)
from app.solver.individual import Individual
from app.solver.problem import Problem

# R&P remove between 4 and xi = 40% of the requests per destroy.
MIN_REMOVED = 4
MAX_REMOVED_FRACTION = 0.4
# R&P's p for worst removal: higher takes the worst pickup more often.
WORST_DETERMINISM = 3


def removal_count(n_routed: int, rng: random.Random) -> int:
    """How many pickups one destroy removes: between 4 and 40% of those routed."""
    low = min(MIN_REMOVED, n_routed)
    high = max(low, math.ceil(MAX_REMOVED_FRACTION * n_routed))
    return rng.randint(low, high)


def take_out(individual: Individual, removed: list[int]) -> Individual:
    """A new Individual without these pickups in its routes, appended to unassigned."""
    taken = set(removed)
    routes = [[i for i in route if i not in taken] for route in individual.routes]
    return Individual(routes, individual.unassigned + list(removed))


def random_removal(
    individual: Individual, q: int, rng: random.Random
) -> tuple[Individual, list[int]]:
    """Remove q routed pickups chosen uniformly at random."""
    routed = [i for route in individual.routes for i in route]
    q = min(q, len(routed))
    if q <= 0:
        return individual.copy(), []
    removed = rng.sample(routed, q)
    return take_out(individual, removed), removed


def unavoidable_costs(problem: Problem) -> list[float]:
    """For each pickup, the crew-level cost it has even driven alone.

    The lateness, late-crew, buffer and ride terms of the pickup alone on a
    vehicle, on the vehicle where they are smallest. With FIFO travel times a
    route with other stops arrives no earlier, and rides no shorter, than the
    pickup alone on the same vehicle, so no placement costs it less than this. 0 for crew who can
    arrive before their buffer starts; positive for lost causes and crew who
    can only arrive inside their buffer. Built once per Problem.
    """
    floor = []
    for i in range(len(problem.pickups)):
        alone = (route_evaluation(problem, w, [i]) for w in range(len(problem.vehicles)))
        floor.append(
            min(
                (
                    LATENESS_WEIGHT * e.lateness_sec
                    + LATE_CREW_WEIGHT * e.late_crew
                    + BUFFER_WEIGHT * e.buffer_used_sec
                    + RIDE_WEIGHT * e.ride_excess_sec
                    for e in alone
                ),
                default=0.0,
            )
        )
    return floor


def worst_removal(
    problem: Problem,
    individual: Individual,
    q: int,
    rng: random.Random,
    floor: list[float],
    determinism: float = WORST_DETERMINISM,
) -> tuple[Individual, list[int]]:
    """Remove q pickups whose removal saves the most beyond their floor.

    Each step: sort routed pickups by saving minus floor, highest first, and
    take the one at index floor(y^p * count) for y uniform in [0, 1), as in
    Shaw removal. Removing a pickup changes the savings on its route, so that
    route is re-costed before the next step.

    floor comes from unavoidable_costs(problem); all zeros gives plain R&P.
    """
    routes = [route.copy() for route in individual.routes]
    q = min(q, sum(len(route) for route in routes))
    if q <= 0:
        return individual.copy(), []

    cache: RouteCostCache = {}
    excess: dict[int, float] = {}
    for v, route in enumerate(routes):
        excess.update(_route_excess(problem, v, route, floor, cache))

    removed: list[int] = []
    while len(removed) < q:
        # Index as tie-break so the order never depends on dict order.
        ranked = sorted(excess, key=lambda i: (-excess[i], i))
        i = ranked[int(rng.random() ** determinism * len(ranked))]
        v = next(v for v, route in enumerate(routes) if i in route)
        routes[v].remove(i)
        del excess[i]
        excess.update(_route_excess(problem, v, routes[v], floor, cache))
        removed.append(i)

    return take_out(individual, removed), removed


def _route_excess(
    problem: Problem, v: int, route: list[int], floor: list[float], cache: RouteCostCache
) -> dict[int, float]:
    """For each pickup on route v: what removing it saves, minus its floor.

    Removing a pickup also adds UNASSIGNED_WEIGHT; that is the same for every
    pickup, so it is left out, as in insertion_cost.
    """
    full = cached_route_cost(problem, v, route, cache)
    return {
        i: full - cached_route_cost(problem, v, [j for j in route if j != i], cache) - floor[i]
        for i in route
    }
